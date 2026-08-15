#!/usr/bin/env python3
"""
The Center — Office Tools
==========================

A simple desktop app for new office members. It opens to a Home page
explaining what the app is for. A sidebar on the left (collapsible via
the ⟨/⟩ arrow at its top) lists the HTML guides kept in the `html/`
folder next to this program; clicking one shows it in the main pane
on the right, right inside the app:

- Plain guides open in a lightweight built-in viewer (tkinterweb).
- Interactive HTML "programs" (anything with real JavaScript logic,
  like a calculator or reconciliation tool) show a small card with an
  "Open Tool" button. Clicking it opens the tool in its own native
  window powered by pywebview, which uses the OS's real web engine
  (WebKit on Mac, WebView2 on Windows) — full JavaScript, file
  uploads, and downloads all work, still without leaving a browser
  tab behind. The launcher window stays open the whole time.
- If pywebview isn't installed, those documents fall back to opening
  in your default web browser instead.

Built with CustomTkinter for the interface, tkinterweb for the
lightweight in-app viewer, and pywebview for interactive tools.
Install all three once with:

    pip install customtkinter tkinterweb pywebview

HOW TO ADD OR UPDATE DOCUMENTS
-------------------------------
1. Drop an .html file into the `html` folder next to this program
   (or next to the packaged app, see README.md).
2. Optional: start the filename with a number to control the order
   it appears in the sidebar, e.g. "01_Welcome.html", "02_FAQ.html".
   The number and underscore are stripped from the on-screen name.
3. Optional: give the file a <title>Some Title</title> in its <head>
   — the launcher will display that instead of the filename.
4. Click the "Refresh" button in the app (or just restart it) to
   pick up new or changed files. No code changes needed.

HOW TO ADD A REAL LOGO
------------------------
Drop an image (PNG/JPG, transparent background recommended) at
`assets/logo.png` next to this program. It replaces the round
placeholder mark automatically — no code changes needed. The logo
is drawn at a fixed height with its real aspect ratio preserved, so
it doesn't need to be square.

HOW IN-APP VIEWING WORKS
--------------------------
Plain guides open in the built-in viewer, embedded in the main pane.
Documents containing a <script> tag (interactive tools) show an
"Open Tool" card instead — clicking it opens a pywebview-powered
window with a real web engine, so JavaScript, file uploads, and
downloads all work normally.

RUNNING THIS PROGRAM
---------------------
    pip install customtkinter tkinterweb pywebview
    python3 launcher.py

See README.md for full instructions, including how to package this
as a standalone Windows .exe or Mac .app that colleagues can run
without installing Python.
"""

import base64
import datetime
import hashlib
import os
import html
import html.parser
import json
import re
import shutil
import ssl
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import StringVar, filedialog, messagebox

try:
    import customtkinter as ctk
except ImportError:
    print(
        "This launcher requires the 'customtkinter' package.\n\n"
        "Install it with:\n"
        "    pip install customtkinter\n"
    )
    sys.exit(1)

# ---- patch a real CustomTkinter bug: scrolling over a guide page crashes.
# The sidebar's scrollable list (nav_scroll) registers its mouse-wheel
# listener globally (bind_all), which is how CustomTkinter makes "scroll
# anywhere over this list" work -- but that means it also fires when the
# mouse is over completely unrelated widgets, like the guide viewer (which
# uses the separate tkinterweb library to render HTML, not CustomTkinter).
# CustomTkinter's handler then walks up the widget tree to check whether
# what's under the mouse belongs to it, assuming every step is a normal
# Tkinter widget -- but tkinterweb's internal widgets don't fit that
# assumption, so partway up the walk it hits something that isn't a
# widget at all and crashes with "AttributeError: 'str' object has no
# attribute 'master'". This is confirmed via the app's own error_log.txt
# and reproduces every time by scrolling on a guide page (e.g. "How the
# Office Works"), independent of themes or rebuilds. Since this is a bug
# in CustomTkinter's own code and not something we can fix by changing
# our layout, patch the one unsafe line so it treats an unrecognized
# widget as "not part of this scrollable list" instead of crashing.
try:
    _original_check_if_valid_scroll = ctk.CTkScrollableFrame._check_if_valid_scroll

    def _safe_check_if_valid_scroll(self, widget):
        try:
            return _original_check_if_valid_scroll(self, widget)
        except AttributeError:
            return False

    ctk.CTkScrollableFrame._check_if_valid_scroll = _safe_check_if_valid_scroll
except Exception:
    pass

# ---- patch mouse-wheel scrolling to feel smooth instead of "clicky".
# CustomTkinter's own _mouse_wheel_all scrolls by calling
# canvas.yview("scroll", N, "units"), which always snaps the view to a
# multiple of a fixed pixel increment (8px per notch on Mac, 30px on
# Linux, 1px on Windows -- see _set_scroll_increments) in one instant
# jump per event. A trackpad swipe fires many of these events in quick
# succession, so each one independently teleporting to its own grid line
# is what reads as a series of hard little hops rather than one glide.
#
# A first attempt just replaced the grid-snapped jump with an equal-size
# instant jump computed as a continuous fraction -- same math, still one
# instant teleport per event, so it didn't fix the feel (and a mismatch
# between the live-recomputed bbox("all") and the canvas's actual
# scrollregion could occasionally overshoot on top of that).
#
# This version instead treats every incoming wheel event as a nudge to a
# running target position, and animates the visible position toward that
# target in short, quick, eased steps (each step covers 55% of the
# remaining distance, ticking every 8ms) rather than snapping straight
# there. Multiple rapid events just extend the same in-flight animation
# toward a new target instead of stacking separate jumps, which is what
# turns a fast trackpad swipe into one continuous-looking glide instead
# of repeated teleports. Reads the canvas's actual scrollregion (rather
# than recomputing bbox live) so the distance-per-notch matches
# CustomTkinter's own increments exactly, with no overshoot.
try:
    _SCROLL_EASE = 0.55       # fraction of remaining distance covered per tick
    _SCROLL_TICK_MS = 8       # time between animation ticks
    _SCROLL_SNAP_EPS = 0.0008  # close enough to the target to stop animating

    def _ctk_scroll_axis_size(canvas, scroll_x):
        try:
            x1, y1, x2, y2 = (float(v) for v in str(canvas.cget("scrollregion")).split())
            return (x2 - x1) if scroll_x else (y2 - y1)
        except Exception:
            pass
        bbox = canvas.bbox("all")
        if not bbox:
            return 0
        return (bbox[2] - bbox[0]) if scroll_x else (bbox[3] - bbox[1])

    def _ctk_scroll_animate_step(self, axis_attr, job_attr):
        canvas = self._parent_canvas
        if not self.winfo_exists() or not canvas.winfo_exists():
            setattr(self, job_attr, None)
            return
        scroll_x = axis_attr.endswith("_x")
        target = getattr(self, axis_attr, None)
        if target is None:
            setattr(self, job_attr, None)
            return
        current = (canvas.xview() if scroll_x else canvas.yview())[0]
        remaining = target - current
        if abs(remaining) < _SCROLL_SNAP_EPS:
            (canvas.xview_moveto if scroll_x else canvas.yview_moveto)(target)
            setattr(self, axis_attr, None)
            setattr(self, job_attr, None)
            return
        (canvas.xview_moveto if scroll_x else canvas.yview_moveto)(current + remaining * _SCROLL_EASE)
        job = self.after(_SCROLL_TICK_MS, lambda: _ctk_scroll_animate_step(self, axis_attr, job_attr))
        setattr(self, job_attr, job)

    def _smooth_mouse_wheel_all(self, event):
        if not self._check_if_valid_scroll(event.widget):
            return

        scroll_x = self._shift_pressed
        canvas = self._parent_canvas
        view = canvas.xview() if scroll_x else canvas.yview()
        if view == (0.0, 1.0):
            return

        if sys.platform.startswith("win"):
            units = -int(event.delta / 6)
            increment = 1
        elif sys.platform == "darwin":
            units = -event.delta
            increment = 4 if scroll_x else 8
        else:
            units = -1 if getattr(event, "num", 5) == 4 else 1
            increment = 30

        content_size = _ctk_scroll_axis_size(canvas, scroll_x)
        if content_size <= 0:
            return

        axis_attr = "_smooth_scroll_target_x" if scroll_x else "_smooth_scroll_target_y"
        job_attr = "_smooth_scroll_job_x" if scroll_x else "_smooth_scroll_job_y"

        base = getattr(self, axis_attr, None)
        if base is None:
            base = view[0]
        new_target = max(0.0, min(1.0, base + (units * increment) / content_size))
        setattr(self, axis_attr, new_target)

        if getattr(self, job_attr, None) is None:
            _ctk_scroll_animate_step(self, axis_attr, job_attr)

    ctk.CTkScrollableFrame._mouse_wheel_all = _smooth_mouse_wheel_all
except Exception:
    pass

# ---- patch every scrollbar app-wide to auto-hide when it isn't needed,
# and to fade out when idle at the top otherwise.
# CustomTkinter's CTkScrollbar always draws a full-length thumb the
# moment a CTkScrollableFrame is created, even when the content already
# fits with nothing to scroll -- there's no built-in "hide if unneeded"
# behavior the way a classic Tk scrollbar can have. That's the
# always-visible-but-never-usable scrollbar on shorter pages.
#
# This patches CTkScrollbar.set() (called every time the scroll
# position/range changes) to:
#   - hide the scrollbar entirely whenever the visible range already
#     covers the whole content (nothing to scroll, ever, regardless of
#     activity)
#   - otherwise show it immediately (scrolling just happened, or the
#     page just loaded) and, once idle for a moment, fade it back out
#     -- but only once the view is back at the very top; if you've
#     scrolled down, it stays put as a position indicator rather than
#     disappearing while you're mid-page
#   - hovering directly over the scrollbar keeps it visible and pauses
#     the idle timer, so it doesn't vanish out from under the cursor
try:
    _SCROLLBAR_IDLE_HIDE_MS = 900

    _original_scrollbar_init = ctk.CTkScrollbar.__init__

    def _patched_scrollbar_init(self, *args, **kwargs):
        _original_scrollbar_init(self, *args, **kwargs)
        self._auto_hide_job = None
        self._auto_hide_hovering = False
        self._auto_hide_visible = True
        self._auto_hide_at_top = True
        try:
            self._canvas.bind("<Enter>", lambda e: self._scrollbar_auto_hide_enter(), add=True)
            self._canvas.bind("<Leave>", lambda e: self._scrollbar_auto_hide_leave(), add=True)
        except Exception:
            pass

    def _scrollbar_auto_hide_reveal(self):
        if not self.winfo_exists():
            return
        if self._auto_hide_job is not None:
            try:
                self.after_cancel(self._auto_hide_job)
            except Exception:
                pass
            self._auto_hide_job = None
        if not self._auto_hide_visible:
            try:
                self.grid()
            except Exception:
                pass
            self._auto_hide_visible = True

    def _scrollbar_auto_hide_conceal(self):
        if not self.winfo_exists():
            return
        self._auto_hide_job = None
        if self._auto_hide_hovering:
            return
        if self._auto_hide_visible:
            try:
                self.grid_remove()
            except Exception:
                pass
            self._auto_hide_visible = False

    def _scrollbar_auto_hide_schedule(self):
        if not self.winfo_exists():
            return
        if self._auto_hide_job is not None:
            try:
                self.after_cancel(self._auto_hide_job)
            except Exception:
                pass
        self._auto_hide_job = self.after(_SCROLLBAR_IDLE_HIDE_MS, lambda: self._scrollbar_auto_hide_conceal())

    def _scrollbar_auto_hide_enter(self):
        self._auto_hide_hovering = True
        self._scrollbar_auto_hide_reveal()

    def _scrollbar_auto_hide_leave(self):
        self._auto_hide_hovering = False
        if self._auto_hide_at_top:
            self._scrollbar_auto_hide_schedule()

    _original_scrollbar_set = ctk.CTkScrollbar.set

    def _patched_scrollbar_set(self, start_value, end_value):
        _original_scrollbar_set(self, start_value, end_value)
        try:
            start_f, end_f = float(start_value), float(end_value)
        except (TypeError, ValueError):
            start_f, end_f = 0.0, 1.0

        if end_f - start_f >= 0.999:
            # Nothing to scroll, ever -- always hidden, no timers.
            self._auto_hide_at_top = True
            if self._auto_hide_job is not None:
                try:
                    self.after_cancel(self._auto_hide_job)
                except Exception:
                    pass
                self._auto_hide_job = None
            if self._auto_hide_visible:
                try:
                    self.grid_remove()
                except Exception:
                    pass
                self._auto_hide_visible = False
            return

        self._auto_hide_at_top = start_f <= 0.001

        # Reveal only when the view has actually MOVED, not on every
        # set() call.
        #
        # set() fires on any re-layout, not just on scrolling -- and
        # hiding the scrollbar is itself a re-layout: the column it
        # occupied disappears, the content area gets wider, text rewraps,
        # and Tk calls set() again. Revealing unconditionally there meant
        # concealing instantly un-concealed, then the 900ms timer hid it
        # again, forever. That is the once-a-second flicker, and it took
        # the surrounding widgets with it because the width change
        # rewrapped every text block on the page.
        #
        # Comparing the start fraction distinguishes the two cases: real
        # scrolling changes where you are, a re-layout doesn't. Sitting
        # at the top, start stays 0.0 through any number of re-layouts,
        # so the loop can't start.
        previous_start = getattr(self, "_auto_hide_last_start", None)
        self._auto_hide_last_start = start_f
        if previous_start is None or abs(start_f - previous_start) > 0.0005:
            self._scrollbar_auto_hide_reveal()

        if self._auto_hide_at_top and not self._auto_hide_hovering:
            self._scrollbar_auto_hide_schedule()

    ctk.CTkScrollbar.__init__ = _patched_scrollbar_init
    ctk.CTkScrollbar._scrollbar_auto_hide_reveal = _scrollbar_auto_hide_reveal
    ctk.CTkScrollbar._scrollbar_auto_hide_conceal = _scrollbar_auto_hide_conceal
    ctk.CTkScrollbar._scrollbar_auto_hide_schedule = _scrollbar_auto_hide_schedule
    ctk.CTkScrollbar._scrollbar_auto_hide_enter = _scrollbar_auto_hide_enter
    ctk.CTkScrollbar._scrollbar_auto_hide_leave = _scrollbar_auto_hide_leave
    ctk.CTkScrollbar.set = _patched_scrollbar_set
except Exception:
    pass

try:
    from PIL import Image, ImageDraw, ImageFont
    _pil_import_error = None
except ImportError as _e:
    # Pillow is a real dependency (logo + drawn search/team icons), not an
    # optional extra -- it's listed explicitly in the build workflow. This
    # fallback only exists so a broken install degrades to "no images"
    # instead of refusing to start; see log_pil_missing_once() below, which
    # makes that state visible in error_log.txt instead of silent.
    Image = None
    ImageDraw = None
    ImageFont = None
    _pil_import_error = str(_e)

try:
    from tkinterweb import HtmlFrame
except ImportError:
    HtmlFrame = None  # falls back to opening static guides in the browser

try:
    import webview
except ImportError:
    webview = None  # falls back to opening interactive tools in the browser

APP_NAME = "The Center"
APP_TAGLINE = "Office Tools"
WINDOW_TITLE = f"{APP_NAME} — {APP_TAGLINE}"
WINDOW_SIZE = "1040x640"

# ---- palette: real Center brand colors — extracted directly from
# assets/logo.png. Navy sidebar, white content pane, cyan accents. ------
#
# The sidebar (navy, white text) stays the same in every theme below —
# it's already a "dark" panel by brand design, so it isn't part of the
# light/dark/eye-comfort switch. Only the main content pane's colors
# (BODY_BG, CARD_BG, BORDER, TEXT_DARK, TEXT_MUTED, ACCENT_SOFT) change
# with the theme — see THEMES and apply_theme() below. They start out
# as plain module globals (the "light" values) and get reassigned by
# apply_theme(); every place that uses them (e.g. fg_color=BODY_BG)
# looks the name up fresh each time a widget is built, so re-running
# the page-building methods after a theme change is enough to reskin
# the whole app — no per-widget color tuples needed.
BODY_BG = "#ffffff"
CARD_BG = "#ffffff"
BORDER = "#dde1ee"
ACCENT = "#00C0F3"  # Center cyan — constant across all themes
ACCENT_SOFT = "#e3f8ff"
TEXT_DARK = "#1D2071"  # primary text color — navy in the light theme,
                       # despite the name, this becomes off-white in dark
TEXT_MUTED = "#6b7280"

# Always white, regardless of theme — used for the login/loading screens
# (explicitly meant to stay a blank white gate) and anywhere the real
# logo is drawn, since its navy ink needs a light backdrop to read at
# all and there's no separate light-mode logo asset.
WHITE_BACKDROP = "#ffffff"

THEMES = {
    "light": dict(
        BODY_BG="#ffffff", CARD_BG="#ffffff", BORDER="#dde1ee",
        TEXT_DARK="#1D2071", TEXT_MUTED="#6b7280", ACCENT_SOFT="#e3f8ff",
    ),
    "dark": dict(
        BODY_BG="#14161f", CARD_BG="#1c1f2b", BORDER="#2b2f3d",
        TEXT_DARK="#f2f4fa", TEXT_MUTED="#9aa0b4", ACCENT_SOFT="#0f2f3d",
    ),
    "eye_comfort": dict(
        # Warm, low-glare "paper" palette (like an e-reader's sepia mode)
        # for people sensitive to bright white screens.
        BODY_BG="#f4ecd8", CARD_BG="#faf3e3", BORDER="#e3d5b8",
        TEXT_DARK="#4a3b23", TEXT_MUTED="#8a7a5c", ACCENT_SOFT="#e9dcc0",
    ),
}
THEME_LABELS = {"light": "Light", "dark": "Dark", "eye_comfort": "Eye Comfort", "system": "System"}


def resolve_theme(theme_name: str) -> str:
    """"system" follows the OS's light/dark preference (via darkdetect,
    which customtkinter already depends on); falls back to "light" if
    that can't be detected. Any other theme name is already concrete."""
    if theme_name != "system":
        return theme_name if theme_name in THEMES else "light"
    try:
        import darkdetect
        return "dark" if darkdetect.isDark() else "light"
    except Exception:
        return "light"


def apply_theme(theme_name: str):
    """Reassigns the module-level color globals to the chosen theme's
    values. Because every widget builder reads these as bare globals
    (not values captured at import time), simply rebuilding the visible
    pages after calling this is enough to reskin the whole app."""
    globals().update(THEMES[resolve_theme(theme_name)])


def is_dark_hex(hex_color: str) -> bool:
    """True if a #rrggbb color reads as "dark" (perceptual luminance),
    used to decide whether the sidebar header needs the white-silhouette
    logo (see load_logo_image) instead of the real navy-and-cyan one."""
    hex_color = hex_color.lstrip("#")
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return False
    return (0.299 * r + 0.587 * g + 0.114 * b) < 128


FONT_SCALES = {"small": 0.9, "normal": 1.0, "large": 1.15, "xlarge": 1.3}
FONT_SCALE_LABELS = {"small": "Small", "normal": "Normal", "large": "Large", "xlarge": "Extra Large"}
FONT_SCALE = 1.0


def apply_font_scale(scale_name: str):
    global FONT_SCALE
    FONT_SCALE = FONT_SCALES.get(scale_name, 1.0)


def F(size, weight=None):
    """Build a (family, size, [weight]) font tuple scaled by the current
    FONT_SCALE, so changing the Text Size setting scales every label,
    button, and entry in the app consistently instead of needing a
    separate size chosen per widget."""
    scaled = max(1, round(size * FONT_SCALE))
    return (FONT_FAMILY, scaled, weight) if weight else (FONT_FAMILY, scaled)


SIDEBAR_BG = TEXT_DARK
SIDEBAR_HOVER = "#2b2f8c"  # lighter navy — used as the *idle* fill for
                           # input-like controls (search box, its buttons)
SIDEBAR_BUTTON_HOVER = "#14164f"  # darker navy — the hover state for
                                  # every clickable sidebar button
SIDEBAR_ACTIVE = "#363bab"
SIDEBAR_DIVIDER = "#33377a"
SIDEBAR_TEXT = "#ffffff"
SIDEBAR_TEXT_MUTED = "#9fd6f0"
SIDEBAR_WIDTH = 220
SIDEBAR_COLLAPSED_WIDTH = 40
SIDEBAR_ANIMATION_MS = 220  # total duration of the collapse/expand animation
SIDEBAR_ANIMATION_STEPS = 16  # more steps = smoother, at the cost of more .after() calls

FONT_FAMILY = "Segoe UI"
CODE_FONT_FAMILY = "Courier New"  # widely available on both macOS and Windows

TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
ORDER_PREFIX_RE = re.compile(r"^\d+[\s_.\-]+")
SCRIPT_TAG_RE = re.compile(r"<script\b", re.IGNORECASE)
SCRIPT_STYLE_BLOCK_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
HTML_TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")
SEARCH_SNIPPET_RADIUS = 70  # chars of context shown before/after a match

LOGO_SIZE = 44  # px, square — used only for the placeholder mark when no
                # real logo file is present
LOGO_HEIGHT = 40  # px tall in the sidebar header — real logo.png is drawn
                  # at this height, with width scaled to its aspect ratio
WELCOME_LOGO_HEIGHT = 72  # px tall on the welcome screen (bigger, roomier)

# Guides that duplicate content already covered by a pinned sidebar page
# (Home covers the welcome/onboarding content) — kept as real files so
# they still exist and can be opened directly, just not listed a second
# time in the general document list.
SIDEBAR_HIDDEN_FILES = {"01_welcome.html"}

# The Claude Skills built for this office, shown on the sidebar's pinned
# "Skills" page (mirrors how "Apps" lists every interactive tool). These
# aren't files in html/ -- there's nothing to open in the launcher for a
# Skill -- so they're just a small hand-maintained list here rather than
# something discover_documents() scans for. Each "file" is packaged
# under assets/skills/ (see _show_skills / _download_skill_file).
SKILLS = [
    {
        "name": "Center Context",
        "description": (
            "Gives Claude the background it would otherwise ask for every time — "
            "our sites and programs, who does what, what JDAI and ASC mean, which "
            "grants are active, and how this app works. Install it once and stop "
            "explaining. Anyone can keep it current: tell Claude what changed."
        ),
        "prompts": [
            "What's due for JDAI this month?",
            "Who should I ask about a payroll question?",
            "What does ASC/SERVE mean?",
            "Update the Center context skill — Isaiah moved to the Busco site.",
        ],
        "file": "center-context.skill",
    },
    {
        "name": "Apricot Birthdays",
        "description": (
            "Turns an Apricot birthday or roster export into a file the Calendar's "
            "bulk upload accepts, so a year of birthdays goes in once instead of "
            "being typed one at a time. Hand Claude the PDF and it does the rest."
        ),
        "prompts": [
            "Format these birthdays for the calendar upload.",
            "Here's the Apricot birthday export — turn it into the upload template.",
            "Mass-upload these birthdays to the Office App calendar.",
        ],
        "file": "apricot-birthdays.skill",
    },
    {
        "name": "Deposit Reconciliation",
        "description": "Pulls all deposits and compares them side by side to catch any mismatches.",
        "prompts": [
            "Reconcile this deposit against QuickBooks.",
            "Here's the donor export and the QuickBooks deposit — do they match?",
            "Put together the deposit detail PDF for this batch.",
        ],
        "file": "deposit-reconciliation.skill",
    },
    {
        "name": "Financial Summary Email",
        "description": "Prepares a templated financial summary email for any given period.",
        "prompts": [
            "Draft this month's financials email.",
            "Compile the budget vs actual email with these QuickBooks numbers.",
            "Write the monthly financial summary for the board.",
        ],
        "file": "financial-summary-email.skill",
    },
]

LOGIN_LOGO_HEIGHT = 80  # px tall on the login screen
# Logo and card are stacked in one column (logo on top, card below) and
# that whole stack is centered as a unit, so the two never overlap.
LOGIN_FIELD_WIDTH = 300  # width of the username field, and of the
                          # password field + arrow button + gap combined
LOGIN_BUTTON_WIDTH = 46
LOGIN_FIELD_GAP = 10  # space between the password field and the arrow button
LOGIN_FIELD_HEIGHT = 38
LOGIN_LOADING_DURATION_MS = 700  # how long the post-login loading animation shows

# Fixed colors (not the theme-variable BODY_BG/CARD_BG/TEXT_DARK/
# ACCENT_SOFT globals) for the handful of surfaces that intentionally
# always look the same no matter which Settings theme is active: the
# login/loading screens, and the sidebar header (which stays white so
# the logo's navy ink stays legible even in Dark or Eye Comfort mode).
LOGIN_TEXT = "#1D2071"
LOGIN_BORDER = "#dde1ee"
LOGIN_ACCENT_SOFT = "#e3f8ff"

# Accounts live in the shared Firebase database, the same one the mobile
# site uses -- see the "shared database" section further down. There is
# no password stored anywhere in this file, this app, or this repository.
#
# There used to be three shared logins here (director/admin/staff, with
# their passwords written in plain text) as a fallback for a missing
# users.json. They're gone: this repository is public, it publishes the
# staff Contacts page, and a password committed next to the matching
# email addresses is simply a published password. Everyone now signs in
# as themselves, and recovers access with "Forgot password?" on the
# login screen, which emails them a link.

# Valid roles, lowest to highest. Used to build the role-choice
# dropdown on the Team page and to validate profiles from the database.
ROLES = ("staff", "admin", "director")
ROLE_LABELS = {"staff": "Staff", "admin": "Admin", "director": "Director"}

# Extra layer of protection on top of users.json itself: even if an
# email/password pair somehow matched a stored record, or someone tried
# to log in with an outside address, only this domain is accepted.
# Checked in both attempt_login (below) and the Team page's Add Person
# form, so a wrong-domain address is rejected before it's ever compared
# against a real password, and can't even be added to the roster.
ALLOWED_EMAIL_DOMAIN = "thecentercc.com"


# Name of the per-user data folder on Mac, under ~/Library/Application
# Support/. Only used for the packaged Mac app -- see get_base_dir.
MAC_DATA_FOLDER_NAME = "The Center Office App"


def get_bundled_dir() -> Path:
    """Where the read-only copies of html/ and assets/ that ship *inside*
    the app live. Used only to seed a fresh install (see
    seed_data_dir_from_bundle) -- never written to, and never read from
    once real copies exist in BASE_DIR, so someone editing a guide page
    isn't silently overwritten on the next update."""
    if getattr(sys, "frozen", False):
        # PyInstaller unpacks bundled data here (a temp folder for a
        # onefile .exe, Contents/Frameworks for a Mac .app).
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def get_legacy_mac_dir():
    """The old Mac location for editable data: the folder *containing*
    TheCenterOfficeLauncher.app, which in practice means /Applications
    itself. Everything used to live there -- html/, assets/, users.json,
    settings.json -- which worked, but scattered six items across the
    user's Applications folder, which is not how Mac apps behave.
    Returns None when that doesn't apply. Kept solely so
    migrate_legacy_mac_data() can move an existing install's files to
    the new home; nothing else should read from here."""
    if getattr(sys, "frozen", False) and sys.platform == "darwin":
        exe_path = Path(sys.executable).resolve()
        for parent in exe_path.parents:
            if parent.suffix == ".app":
                return parent.parent
    return None


def get_base_dir() -> Path:
    """Folder holding the editable, per-machine data: html/, assets/,
    settings.json, users.json, and the error log — kept out of any
    PyInstaller temp-extraction folder so they stay normal folders on
    disk that can be edited or added to without rebuilding the app.

    - Running from source: the folder containing this script.
    - Packaged on Windows (--onefile .exe): the folder containing the
      .exe, so the whole thing stays one portable folder you can move
      around or run off a shared drive.
    - Packaged on Mac (.app bundle): ~/Library/Application Support/The
      Center Office App — the standard place Mac apps keep this kind of
      thing. It deliberately is NOT the folder next to the .app (i.e.
      /Applications), which is what earlier versions used; that left
      html/, assets/, and four loose files sitting in the user's
      Applications folder alongside their real applications. Existing
      installs are moved over automatically on first launch, see
      migrate_legacy_mac_data().
    """
    if getattr(sys, "frozen", False):
        if sys.platform == "darwin":
            return Path.home() / "Library" / "Application Support" / MAC_DATA_FOLDER_NAME
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


# Everything the app keeps on disk, by name. Order matters only for the
# progress of migration -- the folders are the slow ones.
DATA_ITEM_NAMES = (
    "html",
    "assets",
    "users.json",
    "settings.json",
    "shared_preferences.json",
    "error_log.txt",
)


def migrate_legacy_mac_data(base_dir: Path):
    """One-time move of an existing Mac install's data out of
    /Applications and into ~/Library/Application Support/. Runs on every
    launch but does nothing once there's nothing left to move, and never
    overwrites anything already in the new location, so it's safe to
    re-run and safe if someone half-moved things by hand.

    Deliberately best-effort per item: /Applications is normally
    writable by an admin user, but if a move fails (permissions, or the
    file being open), the app falls back to copying it, and failing
    that just skips it rather than refusing to start. Returns the list
    of item names it actually brought over, for logging."""
    legacy = get_legacy_mac_dir()
    if legacy is None:
        return []
    try:
        if legacy.resolve() == base_dir.resolve():
            return []
    except OSError:
        return []

    moved = []
    for name in DATA_ITEM_NAMES:
        src = legacy / name
        dst = base_dir / name
        if not src.exists() or dst.exists():
            continue
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(name)
        except Exception:
            try:
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
                moved.append(name)
            except Exception:
                pass
    return moved


# A copy of exactly what was last laid down from the app bundle. It's
# what makes it possible to tell "this file is just the shipped version"
# apart from "somebody edited this page in the app", which decides
# whether an update may overwrite it.
SNAPSHOT_DIR_NAME = ".bundled-snapshot"


def _file_digest(path: Path):
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def seed_data_dir_from_bundle(base_dir: Path):
    """Keeps html/ and assets/ up to date with the copies shipped inside
    the app, without throwing away pages edited through "Edit This Page".

    The first version of this only ever filled in what was *missing*,
    which quietly broke updates: once the folder existed, a newer app
    could never deliver a corrected guide or a fixed tool again. The
    updated Onboarding Tracker shipped inside the app and simply never
    appeared, because an older copy already sat in the data folder.

    So for each file: if it's identical to what was last laid down, it's
    untouched and gets updated. If it differs, someone edited it, and it
    is left exactly as it is. New files arrive; files deleted on purpose
    stay deleted.

    On the very first run there's no snapshot to compare against, so
    nothing can be classified. Rather than guess, the existing folder is
    set aside as html-backup-<timestamp>/ and a clean copy is laid down.
    Nothing is lost, and from then on edit detection works properly."""
    bundled = get_bundled_dir()
    snapshot_root = base_dir / SNAPSHOT_DIR_NAME
    changed = []

    for name in ("html", "assets"):
        src_root = bundled / name
        dst_root = base_dir / name
        snap_root = snapshot_root / name
        if not src_root.exists():
            continue

        try:
            if not dst_root.exists():
                shutil.copytree(src_root, dst_root)
                shutil.rmtree(snap_root, ignore_errors=True)
                shutil.copytree(src_root, snap_root)
                changed.append(f"{name} (first install)")
                continue

            if not snap_root.exists():
                # Upgrading from a build that didn't keep a snapshot.
                backup = base_dir / f"{name}-backup-{time.strftime('%Y%m%d-%H%M%S')}"
                shutil.copytree(dst_root, backup)
                for item in src_root.iterdir():
                    target = dst_root / item.name
                    if item.is_dir():
                        shutil.rmtree(target, ignore_errors=True)
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)
                shutil.copytree(src_root, snap_root)
                changed.append(f"{name} (refreshed; previous copy kept in {backup.name})")
                continue

            for item in src_root.rglob("*"):
                if not item.is_file():
                    continue
                relative = item.relative_to(src_root)
                local = dst_root / relative
                snapshot = snap_root / relative

                if local.exists():
                    local_digest = _file_digest(local)
                    snapshot_digest = _file_digest(snapshot)
                    if snapshot_digest is not None and local_digest != snapshot_digest:
                        continue  # edited here on purpose -- leave it alone
                    if local_digest == _file_digest(item):
                        continue  # already current

                local.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, local)
                snapshot.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, snapshot)
                changed.append(str(Path(name) / relative))
        except Exception:
            # A problem updating content must never stop the app opening.
            pass

    return changed


BASE_DIR = get_base_dir()
try:
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    _migrated_items = migrate_legacy_mac_data(BASE_DIR)
    _seeded_items = seed_data_dir_from_bundle(BASE_DIR)
except Exception:
    # Never let a storage-location problem stop the app from opening --
    # a missing html/ already degrades gracefully (see _show_home's
    # fallback), and write_error_log below can't be called yet anyway
    # since ERROR_LOG_FILE depends on BASE_DIR.
    _migrated_items = []
    _seeded_items = []
HTML_DIR = BASE_DIR / "html"
ASSETS_DIR = BASE_DIR / "assets"
SETTINGS_FILE = BASE_DIR / "settings.json"
ERROR_LOG_FILE = BASE_DIR / "error_log.txt"
# Real people, with real emails and passwords — deliberately kept out
# of git (see .gitignore) the same way settings.json and error_log.txt
# already are, just next to the app on this machine instead of baked
# into the source code that gets pushed to GitHub.
USERS_FILE = BASE_DIR / "users.json"


def write_error_log(details: str):
    """Best-effort append to error_log.txt next to html/ and assets/."""
    try:
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n---- {time.strftime('%Y-%m-%d %H:%M:%S')} ----\n{details}")
    except OSError:
        pass


# Deferred until write_error_log exists (ERROR_LOG_FILE needs BASE_DIR,
# which is what the migration above was setting up). Moving someone's
# data between folders is exactly the kind of thing worth having a
# record of if a page or login later seems to have gone missing.
if _migrated_items:
    write_error_log(
        "(moved app data out of the Applications folder into "
        f"{BASE_DIR})\nItems: {', '.join(_migrated_items)}\n"
    )
if _seeded_items:
    write_error_log(
        f"(first run -- copied starter {', '.join(_seeded_items)} into {BASE_DIR})\n"
    )


_pil_missing_logged = False


def log_pil_missing_once():
    """Pillow failing to import is normally silent by design (see the
    try/except around `from PIL import Image, ImageDraw` above) so a
    packaged build missing it degrades to no logo/icons instead of
    crashing outright -- but silent also means undiagnosable, which is
    exactly what happened when a Mac build shipped without Pillow's
    compiled bits bundled (fixed in launcher.spec's collect_all list).
    This writes it to error_log.txt the first time anything actually
    needed an image, without spamming the log on every sidebar rebuild
    that calls load_logo_image() again."""
    global _pil_missing_logged
    if _pil_missing_logged:
        return
    _pil_missing_logged = True
    write_error_log(
        "(Pillow/PIL unavailable -- logo and drawn icons will be missing)\n"
        f"ImportError: {_pil_import_error}\n"
    )


def log_and_show_error(exc_type, exc_value, exc_tb):
    """Installed as root.report_callback_exception (see main()). Tkinter
    normally just prints exceptions raised inside event callbacks —
    button commands, after()-scheduled calls, etc. — to stderr and
    otherwise silently keeps going, which is invisible in a packaged
    windowed app with no console attached. This instead writes the full
    traceback to error_log.txt next to html/ and assets/, and shows a
    one-time popup pointing at it, so a bug like 'the page went blank
    after clicking X' produces an actual diagnosable error instead of
    just a support request with no evidence."""
    write_error_log("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
    try:
        messagebox.showerror(
            WINDOW_TITLE,
            "Something went wrong and part of the app may not have updated "
            "correctly.\n\nDetails were saved to error_log.txt next to this "
            "app. Please share that file if you report the problem.\n\n"
            f"{exc_type.__name__}: {exc_value}",
        )
    except Exception:
        pass


DEFAULT_SETTINGS = {
    "theme": "light",  # "light" | "dark" | "eye_comfort" | "system"
    "font_scale": "normal",  # key into FONT_SCALES
    "default_page": "home",  # "home" | "apps" — which page shows right after login
    "sidebar_expanded": True,
    "remember_username": True,  # prefill the last-used login email
    "last_username": "",
}

# Which of the keys above are "my settings" -- stored on the person's
# own row in the shared database, so they follow them to any computer or
# to the mobile site, rather than living on one device.
# remember_username/last_username stay device-level: they only matter
# before anyone's identity is known yet, since they drive what's
# prefilled on the login screen itself.
PERSONAL_SETTING_KEYS = ("theme", "font_scale", "default_page", "sidebar_expanded")


def load_settings() -> dict:
    """Reads settings.json next to html/ and assets/, filling in any
    missing keys with defaults (so adding a new setting later doesn't
    break existing installs) and tolerating a missing or corrupt file
    by falling back to defaults entirely."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            settings.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict):
    """Best-effort write — if the folder isn't writable for some reason,
    the app just falls back to defaults next launch instead of crashing."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


# NOTE: users.json, shared_preferences.json, and their load/save helpers
# used to live here. They're gone -- accounts, roles, and personal
# display settings are read from and written to the shared Firebase
# database instead (see the section below), so every computer and phone
# sees the same thing rather than each keeping its own divergent copy.
# Any old users.json still sitting next to the app is simply ignored.


# ---------------------------------------------------------------------
# The shared database (Firebase)
# ---------------------------------------------------------------------
# Logins, roles, and personal display settings live in the same Firebase
# project the mobile site uses, so one account works everywhere and a
# change made on a phone shows up on every desktop. There used to be a
# users.json file next to the app holding names, roles, and plaintext
# passwords -- per machine, so each computer had its own divergent copy
# and someone added on one was invisible on the others.
#
# Deliberately talks to Firebase's REST API with nothing but the
# standard library rather than pulling in the firebase-admin SDK:
#   - the SDK is a large dependency to bundle into a PyInstaller build,
#     and it exists to hold a *service account* key, which is a master
#     credential that must never ship inside an app people install;
#   - the REST endpoints below take the same public web API key the
#     mobile site already exposes, and every read/write is checked
#     against firestore.rules using the signed-in person's own token.
#     A staff member's copy of this app therefore has exactly the
#     permissions their account has, no more.
FIREBASE_API_KEY = "AIzaSyB2rLNc8NaBcWzk_kCyhulEIseXeMbNZEg"
FIREBASE_PROJECT_ID = "the-center-office-app"

IDENTITY_URL = "https://identitytoolkit.googleapis.com/v1/accounts"
FIRESTORE_URL = (
    f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}"
    "/databases/(default)/documents"
)

NETWORK_TIMEOUT = 20  # seconds; generous, since a slow office link shouldn't fail a login


def _build_ssl_context():
    """HTTPS needs a list of trusted certificate authorities to verify
    Google's certificate against. Python does not use the operating
    system's own trust store on macOS -- it expects its own CA bundle,
    normally supplied by the `certifi` package.

    A PyInstaller build that doesn't include certifi therefore has no CA
    bundle at all, and every HTTPS request fails certificate
    verification. That surfaces as urllib.error.URLError, which looks
    exactly like "no internet" from the outside, which is precisely how
    it was first reported: the app said it couldn't reach the internet
    on a machine whose internet was fine.

    So: use certifi's bundle when it's available, otherwise fall back to
    Python's default. Never fall back to an unverified context -- that
    would "fix" the error by disabling the check that stops someone
    impersonating the login server."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


SSL_CONTEXT = _build_ssl_context()


class FirebaseError(Exception):
    """Any failure talking to Firebase. .friendly is a message safe to
    show a non-technical person; str() keeps the raw detail for the log."""

    def __init__(self, friendly, detail=""):
        super().__init__(detail or friendly)
        self.friendly = friendly


def _http_json(url, payload=None, token=None, method=None):
    """Small JSON-in/JSON-out helper over urllib. Raises FirebaseError
    with a readable message rather than letting urllib's exceptions
    surface, since these end up in front of end users."""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(
            request, timeout=NETWORK_TIMEOUT, context=SSL_CONTEXT
        ) as response:
            body = response.read().decode("utf-8")
        return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8")
            message = json.loads(raw).get("error", {}).get("message", "")
        except Exception:
            message = ""
        raise FirebaseError(_friendly_firebase_message(e.code, message), f"HTTP {e.code}: {raw}")
    except urllib.error.URLError as e:
        # A certificate failure is NOT a connectivity failure, and saying
        # "check your internet" when the internet is fine sends people
        # off debugging the wrong thing entirely. Distinguish them.
        if isinstance(getattr(e, "reason", None), ssl.SSLError):
            raise FirebaseError(
                "Couldn't securely verify the connection to the login server. "
                "This is a problem with this copy of the app, not your "
                "internet — details are in error_log.txt.",
                f"SSL failure: {e.reason}",
            )
        raise FirebaseError(
            "Can't reach the internet. This app needs a connection to sign in.",
            f"URLError: {e.reason}",
        )
    except (TimeoutError, OSError) as e:
        raise FirebaseError(
            "The connection timed out. Check your internet and try again.", str(e)
        )


def _friendly_firebase_message(status_code, message):
    """Firebase's own error strings are SHOUTY_SNAKE_CASE and unhelpful
    to the person reading them, so they're translated here."""
    mapping = {
        "EMAIL_NOT_FOUND": "Incorrect email or password.",
        "INVALID_PASSWORD": "Incorrect email or password.",
        "INVALID_LOGIN_CREDENTIALS": "Incorrect email or password.",
        "INVALID_EMAIL": "That doesn't look like a valid email address.",
        "USER_DISABLED": "That account has been disabled. Ask a Director.",
        "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Wait a few minutes and try again.",
        "WEAK_PASSWORD : Password should be at least 6 characters":
            "That password is too short — use at least 6 characters.",
        "MISSING_PASSWORD": "Enter your password.",
    }
    for key, friendly in mapping.items():
        if message.startswith(key):
            return friendly
    if status_code == 403:
        return "Your account doesn't have permission to do that."
    if status_code == 404:
        return "That wasn't found in the database."
    return "Something went wrong talking to the database. Details in error_log.txt."


# --- Firestore's REST format stores every value tagged with its type, ---
# --- e.g. {"stringValue": "Jeff"}. These convert to and from that.    ---

def _from_firestore_value(value: dict):
    if "stringValue" in value:
        return value["stringValue"]
    if "booleanValue" in value:
        return value["booleanValue"]
    if "integerValue" in value:
        return int(value["integerValue"])
    if "doubleValue" in value:
        return value["doubleValue"]
    if "nullValue" in value:
        return None
    if "mapValue" in value:
        return _from_firestore_fields(value["mapValue"].get("fields", {}))
    if "arrayValue" in value:
        return [_from_firestore_value(v) for v in value["arrayValue"].get("values", [])]
    return None


def _from_firestore_fields(fields: dict) -> dict:
    return {key: _from_firestore_value(value) for key, value in (fields or {}).items()}


def _to_firestore_value(value):
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {k: _to_firestore_value(v) for k, v in value.items()}}}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_to_firestore_value(v) for v in value]}}
    if value is None:
        return {"nullValue": None}
    return {"stringValue": str(value)}


def _to_firestore_fields(data: dict) -> dict:
    return {key: _to_firestore_value(value) for key, value in data.items()}


def firebase_sign_in(email: str, password: str) -> dict:
    """Verifies an email/password against Firebase Authentication.
    Returns {"idToken", "refreshToken", "email"}. Raises FirebaseError
    with a friendly message on bad credentials or no connection."""
    result = _http_json(
        f"{IDENTITY_URL}:signInWithPassword?key={FIREBASE_API_KEY}",
        {"email": email, "password": password, "returnSecureToken": True},
    )
    return {
        "idToken": result.get("idToken", ""),
        "refreshToken": result.get("refreshToken", ""),
        "email": result.get("email", email).strip().lower(),
    }


def firebase_send_password_reset(email: str):
    """Asks Firebase to email a "choose a new password" link. This is how
    everyone gets in the first time -- no password is ever handed out or
    stored anywhere."""
    _http_json(
        f"{IDENTITY_URL}:sendOobCode?key={FIREBASE_API_KEY}",
        {"requestType": "PASSWORD_RESET", "email": email},
    )


def firebase_change_own_password(id_token: str, new_password: str) -> str:
    """Changes the signed-in person's own password. Firebase issues a
    fresh token afterwards, which is returned so the session keeps
    working."""
    result = _http_json(
        f"{IDENTITY_URL}:update?key={FIREBASE_API_KEY}",
        {"idToken": id_token, "password": new_password, "returnSecureToken": True},
    )
    return result.get("idToken", id_token)


def firestore_get_profile(id_token: str, email: str):
    """That person's row in the shared users collection: name, role, and
    their display preferences. Returns None if they can sign in but
    nobody has given them a profile yet."""
    key = urllib.parse.quote(email.strip().lower(), safe="")
    try:
        document = _http_json(f"{FIRESTORE_URL}/users/{key}", token=id_token)
    except FirebaseError as e:
        if "HTTP 404" in str(e):
            return None
        raise
    fields = _from_firestore_fields(document.get("fields", {}))
    raw_prefs = fields.get("preferences") or {}
    return {
        "email": email.strip().lower(),
        "name": fields.get("name") or email,
        "role": fields.get("role") if fields.get("role") in ROLES else "staff",
        "preferences": {k: v for k, v in raw_prefs.items() if k in PERSONAL_SETTING_KEYS},
    }


def firestore_save_preferences(id_token: str, email: str, preferences: dict):
    """Writes just the preferences field, leaving name and role alone --
    which is also all firestore.rules permits a non-admin to change on
    their own row, so this matches what the server will actually allow."""
    key = urllib.parse.quote(email.strip().lower(), safe="")
    clean = {k: v for k, v in preferences.items() if k in PERSONAL_SETTING_KEYS}
    _http_json(
        f"{FIRESTORE_URL}/users/{key}?updateMask.fieldPaths=preferences",
        {"fields": _to_firestore_fields({"preferences": clean})},
        token=id_token,
        method="PATCH",
    )


def firestore_list_profiles(id_token: str) -> list:
    """Everyone with a profile, for the Team page. firestore.rules only
    allows this for Admin/Director accounts."""
    people = []
    page_token = ""
    while True:
        url = f"{FIRESTORE_URL}/users?pageSize=300"
        if page_token:
            url += "&pageToken=" + urllib.parse.quote(page_token)
        result = _http_json(url, token=id_token)
        for document in result.get("documents", []):
            fields = _from_firestore_fields(document.get("fields", {}))
            email = document.get("name", "").rsplit("/", 1)[-1]
            people.append({
                "email": email,
                "name": fields.get("name") or email,
                "role": fields.get("role") if fields.get("role") in ROLES else "staff",
            })
        page_token = result.get("nextPageToken", "")
        if not page_token:
            break
    people.sort(key=lambda p: p["name"].lower())
    return people


def firestore_save_profile(id_token: str, email: str, name: str, role: str):
    """Creates or updates someone's name and role. Admin/Director only,
    enforced by firestore.rules rather than trusted from the UI."""
    key = urllib.parse.quote(email.strip().lower(), safe="")
    _http_json(
        f"{FIRESTORE_URL}/users/{key}"
        "?updateMask.fieldPaths=name&updateMask.fieldPaths=role",
        {"fields": _to_firestore_fields({"name": name, "role": role})},
        token=id_token,
        method="PATCH",
    )


def firestore_delete_profile(id_token: str, email: str):
    """Removes someone's profile, which takes away their access to
    everything in the app. Their Firebase sign-in itself still exists
    until it's deleted in the Firebase console -- but with no profile,
    the app won't let them past the login screen."""
    key = urllib.parse.quote(email.strip().lower(), safe="")
    _http_json(f"{FIRESTORE_URL}/users/{key}", token=id_token, method="DELETE")


def firestore_due_reminders(id_token: str, email: str) -> list:
    """Calendar dates whose reminder window has opened, for the banner
    at the top of the app (html/Calendar.html writes these).

    Three separate queries rather than one listing, because
    firestore.rules is a permission check and not a filter: asking for
    every event would be refused outright, since most of them belong to
    other people. So we ask only the questions we're allowed to ask --
    mine, team-wide, addressed to me -- and merge the answers.

    Never raises. A reminder banner failing to appear is a small loss;
    it taking the whole launcher down with it on a flaky connection
    would not be."""
    me = email.strip().lower()
    today = datetime.date.today()
    conditions = [
        ("author", "EQUAL", {"stringValue": me}),
        ("visibility", "EQUAL", {"stringValue": "team"}),
        ("recipients", "ARRAY_CONTAINS", {"stringValue": me}),
    ]
    found = {}
    for field, op, value in conditions:
        body = {
            "structuredQuery": {
                "from": [{"collectionId": "calendar_events"}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": field},
                        "op": op,
                        "value": value,
                    }
                },
                "limit": 200,
            }
        }
        try:
            rows = _http_json(f"{FIRESTORE_URL}:runQuery", body, token=id_token)
        except FirebaseError:
            continue
        for row in rows or []:
            document = row.get("document")
            if not document:
                continue
            found[document.get("name", "")] = _from_firestore_fields(
                document.get("fields", {})
            )

    due = []
    for event in found.values():
        try:
            when = datetime.date.fromisoformat(str(event.get("date", "")))
        except ValueError:
            continue
        away = (when - today).days
        lead = event.get("remindDays") or 0
        try:
            lead = int(lead)
        except (TypeError, ValueError):
            lead = 0
        if 0 <= away <= lead:
            due.append({"title": str(event.get("title", "")), "away": away})
    due.sort(key=lambda item: item["away"])
    return due


def display_name_from_filename(filename: str) -> str:
    name = Path(filename).stem
    name = ORDER_PREFIX_RE.sub("", name)
    name = name.replace("_", " ").replace("-", " ")
    return name.strip().title() or filename


def read_title(path: Path) -> str:
    """Best-effort <title> extraction; falls back to the filename."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        match = TITLE_TAG_RE.search(text)
        if match:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            if title:
                return title
    except OSError:
        pass
    return display_name_from_filename(path.name)


def extract_plain_text(path: Path) -> str:
    """Best-effort plain-text extraction from an HTML document, used for
    full-text search. Strips <script>/<style> blocks first (so JS/CSS
    source code doesn't show up in search results or match a query by
    accident), then every remaining tag, then unescapes HTML entities
    and collapses whitespace down to single spaces."""
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    raw = SCRIPT_STYLE_BLOCK_RE.sub(" ", raw)
    text = HTML_TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    return WHITESPACE_RE.sub(" ", text).strip()


class _GuideHTMLParser(html.parser.HTMLParser):
    """Turns the small, hand-authored subset of HTML our guides actually
    use into a plain list of block dicts that native CTk widgets can
    render directly, instead of handing the raw file to tkinterweb.

    tkinterweb's Tkhtml rendering engine isn't Retina-aware the way
    CustomTkinter's own widgets are (see _show_guide), so guide pages
    rendered through it look visibly softer than Home/Apps, which are
    built entirely out of native CTk widgets. Since every guide we ship
    is simple, hand-written HTML (headings, paragraphs, lists,
    definition lists, one small table, and a handful of inline links),
    parsing that ourselves and drawing it with the same native widgets
    Home uses gets guides to the same visual quality, with the side
    benefit of finally respecting the Light/Dark/Eye Comfort theme
    (tkinterweb only ever used the guide's own hardcoded CSS colors).

    Only understands the tags our guides use. Anything else it doesn't
    recognize is simply ignored at the tag level (its text content still
    comes through via handle_data) rather than raising, so an unexpected
    tag degrades gracefully instead of breaking the whole page."""

    _INLINE_STYLE_TAGS = {"strong": "bold", "b": "bold", "em": "italic", "i": "italic", "code": "code"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks = []
        self._tag_stack = []       # list of (tag, attrs) currently open
        self._runs = None          # list of (text, styleset, href) while inside a run-collecting element
        self._heading_tag = None
        self._list_items = None    # list of run-lists while inside <ul>
        self._dl_items = None      # list of [term_runs, desc_runs] while inside <dl>
        self._dl_current = None    # the in-progress [term_runs, desc_runs] pair
        self._table_rows = None    # list of (is_header, [cell_runs, ...]) while inside <table>
        self._table_current_row = None
        self._table_row_is_header = False
        self._in_note = False

    # -- helpers ------------------------------------------------------
    def _current_style_and_href(self):
        style = set()
        href = None
        for tag, attrs in self._tag_stack:
            mapped = self._INLINE_STYLE_TAGS.get(tag)
            if mapped:
                style.add(mapped)
            if tag == "span" and "fill" in (attrs.get("class") or ""):
                style.add("fill")
            if tag == "a" and attrs.get("href"):
                href = attrs["href"]
        return frozenset(style), href

    def _start_runs(self):
        self._runs = []

    def _p_is_nested(self):
        """True if a <p> is nested inside something that already owns
        its own runs list -- a note div, or a table cell/list item/
        definition term/description. Real, hand-authored guide content
        routinely wraps cell/item text in <p> (it's what Cocoa's HTML
        export always does), and without this check that <p>'s own
        open/close handling hijacks the container's runs entirely: its
        text leaks out as a spurious extra top-level paragraph block,
        and the actual container (table cell, list item, ...) ends up
        empty. See handle_starttag/handle_endtag's "p" branches."""
        if self._in_note:
            return True
        return any(t in ("td", "th", "li", "dt", "dd") for t, _attrs in self._tag_stack)

    # -- HTMLParser overrides ------------------------------------------
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("h1", "h2", "h3"):
            self._heading_tag = tag
            self._runs = []
        elif tag == "p":
            if not self._p_is_nested():
                self._start_runs()
        elif tag == "ul":
            self._list_items = []
        elif tag == "li":
            self._start_runs()
        elif tag == "dl":
            self._dl_items = []
        elif tag == "dt":
            self._start_runs()
        elif tag == "dd":
            self._start_runs()
        elif tag == "table":
            self._table_rows = []
        elif tag == "tr":
            self._table_current_row = []
            self._table_row_is_header = False
        elif tag in ("td", "th"):
            self._start_runs()
            if tag == "th":
                self._table_row_is_header = True
        elif tag == "div" and "note" in (attrs.get("class") or ""):
            self._in_note = True
            self._start_runs()
        elif tag == "br" and self._runs is not None:
            self._runs.append(("\n", frozenset(), None))
        self._tag_stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self._tag_stack) - 1, -1, -1):
            if self._tag_stack[i][0] == tag:
                del self._tag_stack[i:]
                break

        if tag in ("h1", "h2", "h3") and self._heading_tag:
            text = "".join(t for t, _s, _h in (self._runs or [])).strip()
            if text:
                self.blocks.append({"type": self._heading_tag, "text": text})
            self._heading_tag = None
            self._runs = None
        elif tag == "p" and self._runs is not None and not self._p_is_nested():
            if any(t.strip() for t, _s, _h in self._runs):
                self.blocks.append({"type": "p", "runs": self._runs})
            self._runs = None
        elif tag == "li" and self._runs is not None:
            if self._list_items is not None:
                self._list_items.append(self._runs)
            self._runs = None
        elif tag == "ul" and self._list_items is not None:
            self.blocks.append({"type": "ul", "items": self._list_items})
            self._list_items = None
        elif tag == "dt" and self._runs is not None:
            self._dl_current = [self._runs, []]
            self._runs = None
        elif tag == "dd" and self._runs is not None:
            if self._dl_current is not None:
                self._dl_current[1] = self._runs
                if self._dl_items is not None:
                    self._dl_items.append(self._dl_current)
                self._dl_current = None
            self._runs = None
        elif tag == "dl" and self._dl_items is not None:
            self.blocks.append({"type": "dl", "items": self._dl_items})
            self._dl_items = None
        elif tag in ("td", "th") and self._runs is not None:
            if self._table_current_row is not None:
                self._table_current_row.append(self._runs)
            self._runs = None
        elif tag == "tr" and self._table_current_row is not None:
            if self._table_rows is not None:
                self._table_rows.append((self._table_row_is_header, self._table_current_row))
            self._table_current_row = None
        elif tag == "table" and self._table_rows is not None:
            self.blocks.append({"type": "table", "rows": self._table_rows})
            self._table_rows = None
        elif tag == "div" and self._in_note:
            if self._runs is not None and any(t.strip() for t, _s, _h in self._runs):
                self.blocks.append({"type": "note", "runs": self._runs})
            self._runs = None
            self._in_note = False

    def handle_data(self, data):
        if self._runs is None:
            return
        collapsed = WHITESPACE_RE.sub(" ", data)
        if collapsed == "":
            return
        style, href = self._current_style_and_href()
        self._runs.append((collapsed, style, href))

    @classmethod
    def parse(cls, source: str) -> list:
        parser = cls()
        try:
            parser.feed(source)
            parser.close()
        except Exception:
            pass
        return parser.blocks


def is_interactive_program(path: Path) -> bool:
    """True if the document has any <script> tag — real JavaScript logic,
    like a calculator or reconciliation tool, rather than a static guide.
    The in-app viewer (tkinterweb) doesn't run JavaScript, so anything
    interactive opens via pywebview (or the browser) instead."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return bool(SCRIPT_TAG_RE.search(text))


def discover_documents():
    """Return a sorted list of (sort_key, display_title, path, is_program)
    tuples. is_program is True for interactive HTML tools (see
    is_interactive_program)."""
    if not HTML_DIR.exists():
        return []
    docs = []
    for path in HTML_DIR.glob("*.htm*"):
        if path.is_file():
            docs.append((path.name.lower(), read_title(path), path, is_interactive_program(path)))
    docs.sort(key=lambda d: d[0])
    return docs


def load_logo_image(height, white=False):
    """Load a real logo from assets/ if one has been dropped in there.

    Sized by height, with width derived from the image's own aspect
    ratio — so a non-square logo (like The Center's wordmark-style
    mark) isn't squashed or stretched into a square. Normally drawn in
    its real navy-and-cyan ink, meant for a light-ish background (the
    welcome screen, or the sidebar header when a light-ish theme is
    active) — the navy would disappear against a dark background.

    white=True instead recolors every visible pixel to solid white,
    keeping the original alpha channel as a silhouette — used for the
    sidebar header when a dark theme is active, so the logo actually
    changes instead of sitting frozen while everything around it
    re-themes (see _build_sidebar)."""
    if Image is None:
        log_pil_missing_once()
        return None
    for candidate in (ASSETS_DIR / "logo.png", ASSETS_DIR / "logo.jpg", ASSETS_DIR / "logo.jpeg"):
        if candidate.exists():
            try:
                img = Image.open(candidate).convert("RGBA")
                width_px, height_px = img.size
                width = max(1, round(height * (width_px / height_px)))
                if white:
                    silhouette = Image.new("RGBA", img.size, (255, 255, 255, 0))
                    silhouette.putalpha(img.getchannel("A"))
                    img = silhouette
                return ctk.CTkImage(light_image=img, dark_image=img, size=(width, height))
            except Exception:
                write_error_log(f"(load_logo_image failed on {candidate})\n{traceback.format_exc()}")
    return None


def build_search_icon(size=16, color="#ffffff"):
    """Draws a plain magnifying-glass silhouette (a lens circle + handle
    line) instead of using the 🔍 emoji character. Emoji glyphs render as
    small full-color pictures on macOS/Windows -- that's the "image" look
    the sidebar's search button had -- rather than a flat icon that matches
    the rest of the app's white-on-navy sidebar style. Drawn at 4x the
    target size and downsampled with LANCZOS so the circle and line come
    out smooth instead of jagged."""
    if Image is None or ImageDraw is None:
        log_pil_missing_once()
        return None
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    line_w = max(1, round(big * 0.11))
    lens_d = round(big * 0.62)
    draw.ellipse((line_w, line_w, lens_d, lens_d), outline=color, width=line_w)
    handle_start = (round(lens_d * 0.82), round(lens_d * 0.82))
    handle_end = (big - line_w, big - line_w)
    draw.line([handle_start, handle_end], fill=color, width=line_w)
    img = img.resize((size, size), Image.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def build_team_icon(size=16, color="#ffffff"):
    """Two overlapping circle 'heads', for the Team button in Settings --
    same reasoning as build_search_icon: a flat silhouette that matches
    the button's own color instead of a colored emoji picture. The
    smaller overlap (vs. two heavily-overlapping circles) is what keeps
    it reading as two people rather than one blob."""
    if Image is None or ImageDraw is None:
        log_pil_missing_once()
        return None
    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = round(big * 0.28)
    cy = round(big * 0.52)
    left_cx = round(big * 0.34)
    right_cx = round(big * 0.66)
    draw.ellipse((right_cx - r, cy - r, right_cx + r, cy + r), fill=color)
    draw.ellipse((left_cx - r, cy - r, left_cx + r, cy + r), fill=color)
    img = img.resize((size, size), Image.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def build_app_icon(title, size=36):
    """An icon for one interactive tool, drawn to echo the logo: the
    Center's broken ring in cyan and navy, with a simple glyph inside
    saying what the tool is.

    The Apps page used to show a navy square with the tool's first
    letter, which meant every tool looked identical apart from one
    character -- "Count Log" and "Credit Card Reconciliation" were both
    a "C". These are drawn rather than shipped as image files so they
    stay sharp at any text size and there's nothing to keep in sync;
    same approach as build_search_icon and build_team_icon above.

    Falls back to the first letter if Pillow isn't available, so the
    page still renders something sensible."""
    if Image is None or ImageDraw is None:
        log_pil_missing_once()
        return None

    scale = 4
    big = size * scale
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cyan = ACCENT          # #00C0F3, sampled from the logo
    navy = "#1D2071"       # the logo's navy, fixed rather than themed

    # --- the ring: two arcs with gaps, as in the logo's mark ---
    ring_w = max(2, round(big * 0.075))
    inset = round(ring_w * 0.6)
    box = (inset, inset, big - inset, big - inset)
    draw.arc(box, start=118, end=332, fill=cyan, width=ring_w)
    draw.arc(box, start=342, end=104, fill=navy, width=ring_w)

    # --- the glyph, sized to sit inside the ring ---
    c = big / 2.0
    r = big * 0.30                     # usable radius inside the ring
    lw = max(2, round(big * 0.055))    # glyph stroke width
    name = (title or "").lower()

    def mentions(*words):
        """Whole-word match. Plain substring matching bit here: "Whitley
        County Resource Directory" contains "count", so the directory
        was drawn with the Count Log's tally marks."""
        return any(re.search(r"\b" + w, name) for w in words)

    def rrect(x0, y0, x1, y1, radius, fill=None, outline=None, width=1):
        draw.rounded_rectangle([x0, y0, x1, y1], radius=radius,
                               fill=fill, outline=outline, width=width)

    if mentions("maintenance", "repair", "facilit"):
        # Wrench: a thick diagonal shaft with an open head.
        # A gear. A wrench is the more obvious symbol for maintenance,
        # but at 36 pixels its handle-and-jaw silhouette read as a key
        # or a map pin; a gear stays unmistakable when small.
        import math
        outer, inner = r * 0.86, r * 0.60
        teeth = 8
        pts = []
        for i in range(teeth * 2):
            ang = math.pi * i / teeth - math.pi / 2
            rad = outer if i % 2 == 0 else inner
            pts.append((c + rad * math.cos(ang), c + rad * math.sin(ang)))
        draw.polygon(pts, fill=navy)
        hole = r * 0.30
        draw.ellipse([c - hole, c - hole, c + hole, c + hole], fill=(0, 0, 0, 0))
        draw.ellipse([c - hole, c - hole, c + hole, c + hole], fill=cyan)

    elif mentions("onboard", "hire"):
        # Clipboard with a tick.
        rrect(c - r * 0.62, c - r * 0.78, c + r * 0.62, c + r * 0.82,
              radius=lw, outline=navy, width=lw)
        rrect(c - r * 0.26, c - r * 0.98, c + r * 0.26, c - r * 0.66,
              radius=lw * 0.6, fill=navy)
        draw.line([(c - r * 0.32, c + r * 0.12), (c - r * 0.06, c + r * 0.38),
                   (c + r * 0.38, c - r * 0.30)], fill=cyan, width=lw, joint="curve")
    elif mentions("resource", "directory", "guide"):
        # An open book.
        draw.line([(c, c - r * 0.52), (c, c + r * 0.62)], fill=navy, width=lw)
        for side in (-1, 1):
            draw.line([(c + side * r * 0.06, c - r * 0.52),
                       (c + side * r * 0.78, c - r * 0.34)], fill=navy, width=lw)
            draw.line([(c + side * r * 0.78, c - r * 0.34),
                       (c + side * r * 0.78, c + r * 0.52)], fill=cyan, width=lw)
            draw.line([(c + side * r * 0.78, c + r * 0.52),
                       (c + side * r * 0.06, c + r * 0.62)], fill=navy, width=lw)
    elif mentions("count", "tally"):
        # Four tally strokes and the diagonal across them.
        for i in range(4):
            x = c - r * 0.62 + i * (r * 0.38)
            draw.line([(x, c - r * 0.55), (x, c + r * 0.55)], fill=navy, width=lw)
        draw.line([(c - r * 0.80, c + r * 0.62), (c + r * 0.78, c - r * 0.62)],
                  fill=cyan, width=lw)
    elif mentions("note"):
        # A page with lines.
        rrect(c - r * 0.66, c - r * 0.80, c + r * 0.66, c + r * 0.80,
              radius=lw, outline=navy, width=lw)
        for i, w in enumerate((0.78, 0.78, 0.44)):
            y = c - r * 0.34 + i * (r * 0.40)
            draw.line([(c - r * 0.36, y), (c - r * 0.36 + r * w * 0.92, y)],
                      fill=cyan, width=max(2, lw - scale))
    elif mentions("timer", "clock", "stopwatch"):
        # Clock face with hands.
        draw.ellipse([c - r * 0.78, c - r * 0.70, c + r * 0.78, c + r * 0.86],
                     outline=navy, width=lw)
        draw.line([(c, c + r * 0.08), (c, c - r * 0.34)], fill=navy, width=lw)
        draw.line([(c, c + r * 0.08), (c + r * 0.40, c + r * 0.30)], fill=cyan, width=lw)
        draw.line([(c - r * 0.22, c - r * 0.92), (c + r * 0.22, c - r * 0.92)],
                  fill=navy, width=lw)  # the winder on top
    elif mentions("calendar", "reporting", "schedule", "deadline"):
        # Calendar: header bar and a grid of days.
        rrect(c - r * 0.76, c - r * 0.62, c + r * 0.76, c + r * 0.80,
              radius=lw, outline=navy, width=lw)
        draw.line([(c - r * 0.76, c - r * 0.24), (c + r * 0.76, c - r * 0.24)],
                  fill=navy, width=lw)
        for dx in (-0.34, 0.34):
            draw.line([(c + r * dx, c - r * 0.88), (c + r * dx, c - r * 0.50)],
                      fill=navy, width=lw)
        dot = max(2, round(lw * 0.85))
        for row in range(2):
            for col in range(3):
                x = c - r * 0.42 + col * (r * 0.42)
                y = c + r * 0.06 + row * (r * 0.36)
                draw.ellipse([x - dot, y - dot, x + dot, y + dot], fill=cyan)
    elif mentions("credit", "card", "reconcil", "expense"):
        # Payment card with a magnetic stripe.
        rrect(c - r * 0.86, c - r * 0.56, c + r * 0.86, c + r * 0.58,
              radius=lw * 1.2, outline=navy, width=lw)
        draw.line([(c - r * 0.86, c - r * 0.18), (c + r * 0.86, c - r * 0.18)],
                  fill=cyan, width=lw)
        draw.line([(c - r * 0.54, c + r * 0.28), (c - r * 0.04, c + r * 0.28)],
                  fill=navy, width=max(2, lw - scale))
    else:
        # Anything we don't recognise keeps the initial, but inside the
        # ring so it still looks like part of the set.
        letter = (title[:1] or "?").upper()
        try:
            font = ImageFont.truetype("Helvetica", int(big * 0.40))
        except Exception:
            font = ImageFont.load_default()
        box_ = draw.textbbox((0, 0), letter, font=font)
        draw.text((c - (box_[2] - box_[0]) / 2 - box_[0],
                   c - (box_[3] - box_[1]) / 2 - box_[1]),
                  letter, font=font, fill=navy)

    img = img.resize((size, size), Image.LANCZOS)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def make_text_readonly(widget):
    """Blocks typing/pasting in a tkinter Text widget while leaving mouse
    drag-selection and Ctrl/Cmd+C copy fully working.

    The obvious approach, widget.configure(state="disabled"), was what
    every guide/paragraph/note widget used before -- but a disabled Text
    widget can't be selected with the mouse at all, which is exactly why
    none of that content could be copied. This instead renames the
    widget's own underlying Tcl command and intercepts just the "insert"
    and "delete" sub-commands (what typing and pasting call); everything
    else -- "tag", "get", "see", "yview", "compare", etc., which is what
    mouse selection and the built-in <<Copy>> binding actually use --
    passes straight through untouched."""
    original_cmd = widget._w + "_orig"
    widget.tk.call("rename", widget._w, original_cmd)

    def proxy(command, *args):
        if command in ("insert", "delete"):
            return ""
        try:
            return widget.tk.call((original_cmd, command) + args)
        except tk.TclError:
            return ""

    widget.tk.createcommand(widget._w, proxy)
    widget.configure(insertwidth=0)  # hide the blinking caret -- still "normal" state underneath


class LauncherApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.documents = []  # list of (sort_key, title, path, is_program)
        self.filtered = []
        self._nav_buttons = {}  # path -> CTkButton, for highlighting the active row
        self._selected_path = None  # None = Home, "apps" = Apps, "settings" = Settings,
                                     # "search" = search results, else a document Path
        self._last_search_query = ""
        self.home_button = None
        self.apps_button = None
        self.skills_button = None
        self.settings_button = None
        self.user_role = None  # "director", "admin", or "staff" once logged in --
                                # this is the *effective* role every permission
                                # check in the app looks at, and "View As" (see
                                # _show_settings) is allowed to temporarily lower it
        self.true_role = None  # the role actually logged in as, set once at login
                                # and never touched by View As -- used only to
                                # decide whether the View As control itself shows
        self.current_user = None  # the matched users.json record, or None if

        self.settings = load_settings()
        # Set at sign-in: the Firebase tokens authorising every read and
        # write this session makes against the shared database. The
        # refresh token is additionally handed to interactive tools so
        # they don't ask for a second login (see _open_program).
        self.id_token = ""
        self.refresh_token = ""
        self._sidebar_expanded = bool(self.settings.get("sidebar_expanded", True))
        apply_theme(self.settings.get("theme", "light"))
        apply_font_scale(self.settings.get("font_scale", "normal"))

        self._sidebar_logo = load_logo_image(LOGO_HEIGHT)
        self._sidebar_logo_white = load_logo_image(LOGO_HEIGHT, white=True)
        self._welcome_logo = load_logo_image(WELCOME_LOGO_HEIGHT)
        self._login_logo = load_logo_image(LOGIN_LOGO_HEIGHT)
        self._search_icon = build_search_icon(16, SIDEBAR_TEXT)
        self._team_icon = build_team_icon(16, "#ffffff")

        # Deliberately always "light" here, regardless of the chosen theme.
        # Every color in this app is one of our own plain hex strings
        # (BODY_BG, CARD_BG, TEXT_DARK, ...), and CTk only re-maps colors
        # given as a (light, dark) tuple when this global mode changes —
        # a plain string is returned as-is either way. Actually flipping
        # this to "dark" only affects CustomTkinter's own un-overridden
        # internals (e.g. default scrollbar colors), which caused a real
        # bug: switching to Dark mode made scrollbars/entries fall back to
        # CTk's built-in dark theme colors we don't control, blacking out
        # and hiding parts of the UI. Our own apply_theme() already does
        # 100% of the real re-theming work safely.
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        root.title(WINDOW_TITLE)
        root.geometry(WINDOW_SIZE)
        root.minsize(860, 520)
        root.configure(fg_color=WHITE_BACKDROP)

        self._show_login_screen()

    # ------------------------------------------------------------ login --
    def _show_login_screen(self):
        """Blank white gate shown on launch, before any app content builds.
        The logo and the login card are stacked in a single column (logo
        on top, card directly below) and that whole stack is centered as
        one unit in the window, so the two never overlap regardless of
        the card's size."""
        self.login_screen = ctk.CTkFrame(self.root, fg_color=WHITE_BACKDROP, corner_radius=0)
        self.login_screen.pack(fill="both", expand=True)

        stack = ctk.CTkFrame(self.login_screen, fg_color=WHITE_BACKDROP)
        stack.place(relx=0.5, rely=0.5, anchor="center")

        logo_holder = ctk.CTkFrame(stack, fg_color=WHITE_BACKDROP)
        logo_holder.pack(pady=(0, 22))
        self._render_logo(logo_holder, self._login_logo, LOGIN_LOGO_HEIGHT, anchor="center")

        card = ctk.CTkFrame(
            stack, fg_color=WHITE_BACKDROP, corner_radius=16, border_width=1, border_color=LOGIN_BORDER
        )
        card.pack()

        inner = ctk.CTkFrame(card, fg_color=WHITE_BACKDROP)
        inner.pack(padx=24, pady=20)

        ctk.CTkLabel(
            inner, text="Sign In", font=F(15, "bold"), text_color=LOGIN_TEXT, fg_color=WHITE_BACKDROP
        ).pack(anchor="w", pady=(0, 12))

        remembered_username = self.settings.get("last_username", "") if self.settings.get("remember_username", True) else ""
        username_var = StringVar(value=remembered_username)
        password_var = StringVar()
        error_var = StringVar()

        username_entry = ctk.CTkEntry(
            inner,
            textvariable=username_var,
            placeholder_text=f"you@{ALLOWED_EMAIL_DOMAIN}",
            font=F(12),
            height=LOGIN_FIELD_HEIGHT,
            corner_radius=8,
            width=LOGIN_FIELD_WIDTH,
            fg_color=WHITE_BACKDROP,
            border_color=LOGIN_BORDER,
            text_color=LOGIN_TEXT,
        )
        username_entry.pack(pady=(0, 8))

        # Password field and submit arrow sit in one row, with a gap
        # between them, sized so together (field + gap + button) they
        # still match the username field's width above.
        password_row = ctk.CTkFrame(inner, fg_color=WHITE_BACKDROP)
        password_row.pack()

        password_entry = ctk.CTkEntry(
            password_row,
            textvariable=password_var,
            placeholder_text="Password",
            show="•",
            font=F(12),
            height=LOGIN_FIELD_HEIGHT,
            corner_radius=8,
            width=LOGIN_FIELD_WIDTH - LOGIN_BUTTON_WIDTH - LOGIN_FIELD_GAP,
            fg_color=WHITE_BACKDROP,
            border_color=LOGIN_BORDER,
            text_color=LOGIN_TEXT,
        )
        password_entry.pack(side="left", padx=(0, LOGIN_FIELD_GAP))

        # Set while a sign-in is in flight, so hammering Return or the
        # arrow button doesn't fire off several overlapping requests.
        signing_in = {"busy": False}

        def finish_login(profile, id_token, refresh_token):
            """Back on the UI thread, with a verified account and its
            profile from the shared database."""
            self.user_role = profile["role"]
            self.true_role = profile["role"]
            self.current_user = profile
            self.id_token = id_token
            # Kept so tools opened from here can be handed this session
            # instead of asking for the password all over again.
            self.refresh_token = refresh_token

            # Personal settings (theme, text size, startup page, sidebar
            # state) live on the account in the database, so they follow
            # the person to any computer or phone. Applied before the
            # rest of the UI builds so it comes up in their theme rather
            # than whoever last used this machine.
            prefs = profile.get("preferences", {})
            for key in PERSONAL_SETTING_KEYS:
                if key in prefs:
                    self.settings[key] = prefs[key]
            apply_theme(self.settings.get("theme", "light"))
            apply_font_scale(self.settings.get("font_scale", "normal"))
            self._sidebar_expanded = bool(self.settings.get("sidebar_expanded", True))

            if self.settings.get("remember_username", True):
                self.settings["last_username"] = profile["email"]
            save_settings(self.settings)

            self.root.unbind("<Return>")
            self.login_screen.destroy()
            self._show_loading_screen()

        def login_failed(message, password_was_wrong=True):
            signing_in["busy"] = False
            submit_button.configure(state="normal", text="→")
            error_var.set(message)
            if password_was_wrong:
                password_var.set("")

        def attempt_login(*_event):
            if signing_in["busy"]:
                return
            username = username_var.get().strip().lower()
            password = password_var.get()

            if not username.endswith("@" + ALLOWED_EMAIL_DOMAIN):
                error_var.set(f"Use your @{ALLOWED_EMAIL_DOMAIN} email address.")
                password_var.set("")
                return
            if not password:
                error_var.set("Enter your password.")
                return

            signing_in["busy"] = True
            error_var.set("")
            submit_button.configure(state="disabled", text="…")

            def work():
                """Runs off the UI thread: a sign-in involves two network
                round trips, and on a slow connection doing that inline
                would freeze the window (and on Windows, grey it out and
                show "Not Responding") for as long as it took."""
                try:
                    session = firebase_sign_in(username, password)
                    profile = firestore_get_profile(session["idToken"], session["email"])
                except FirebaseError as e:
                    write_error_log(f"(sign-in failed for {username})\n{e}\n")
                    # Bound to a plain local first: Python deletes `e`
                    # when the except block ends, so a lambda that runs
                    # later (which is the whole point of root.after)
                    # would raise NameError instead of showing the
                    # message. Same pattern everywhere below.
                    message = e.friendly
                    self.root.after(0, lambda: login_failed(message))
                    return
                except Exception:
                    write_error_log(f"(unexpected sign-in error)\n{traceback.format_exc()}")
                    self.root.after(0, lambda: login_failed(
                        "Something went wrong signing in. Details in error_log.txt."
                    ))
                    return

                if profile is None:
                    # Their password is right, but nobody has given them
                    # a profile yet -- so the app has no idea who they
                    # are or what they should see. Deliberately a
                    # different message from a wrong password, since the
                    # fix is completely different.
                    self.root.after(0, lambda: login_failed(
                        "Your password works, but you don't have access yet. "
                        "Ask a Director to add you on the Team page.",
                        password_was_wrong=False,
                    ))
                    return

                self.root.after(0, lambda: finish_login(
                    profile, session["idToken"], session.get("refreshToken", "")
                ))

            threading.Thread(target=work, daemon=True).start()

        def forgot_password():
            username = username_var.get().strip().lower()
            if not username:
                error_var.set("Type your email address first, then click this.")
                return

            def work():
                try:
                    firebase_send_password_reset(username)
                except FirebaseError as e:
                    write_error_log(f"(password reset failed for {username})\n{e}\n")
                    message = e.friendly
                    self.root.after(0, lambda: error_var.set(message))
                    return
                self.root.after(0, lambda: error_var.set(
                    "Sent. Check your email (and your spam folder) for the link."
                ))

            error_var.set("Sending…")
            threading.Thread(target=work, daemon=True).start()

        submit_button = ctk.CTkButton(
            password_row,
            text="→",
            font=F(16, "bold"),
            fg_color=ACCENT,
            hover_color=LOGIN_TEXT,
            text_color="white",
            corner_radius=8,
            height=LOGIN_FIELD_HEIGHT,
            width=LOGIN_BUTTON_WIDTH,
            # Deferred (see the fix/comment on _show_settings's
            # apply_and_rebuild) since a successful login destroys
            # login_screen, this button's own ancestor. The <Return>
            # binding below calls attempt_login directly since a root-
            # level key binding doesn't have this hazard.
            command=lambda: self.root.after(1, attempt_login),
        )
        submit_button.pack(side="left")

        ctk.CTkLabel(
            inner,
            textvariable=error_var,
            font=F(11),
            text_color="#c0392b",
            fg_color=WHITE_BACKDROP,
            wraplength=LOGIN_FIELD_WIDTH,
            justify="left",
        ).pack(pady=(8, 0))

        # No password is ever handed out -- this is how everyone gets in
        # the first time, and how they recover a forgotten one.
        ctk.CTkButton(
            inner,
            text="Forgot password?",
            font=F(11),
            fg_color="transparent",
            hover_color=LOGIN_ACCENT_SOFT,
            text_color=ACCENT,
            border_width=0,
            corner_radius=6,
            height=24,
            command=forgot_password,
        ).pack(pady=(6, 0))

        self.root.bind("<Return>", attempt_login)
        (password_entry if remembered_username else username_entry).focus_set()

    def _show_loading_screen(self):
        """Brief animated screen shown right after a successful login,
        before the sidebar/Home layout builds — same blank-white style
        as the login screen, with an indeterminate progress bar."""
        self.loading_screen = ctk.CTkFrame(self.root, fg_color=WHITE_BACKDROP, corner_radius=0)
        self.loading_screen.pack(fill="both", expand=True)

        stack = ctk.CTkFrame(self.loading_screen, fg_color=WHITE_BACKDROP)
        stack.place(relx=0.5, rely=0.5, anchor="center")

        logo_holder = ctk.CTkFrame(stack, fg_color=WHITE_BACKDROP)
        logo_holder.pack(pady=(0, 18))
        self._render_logo(logo_holder, self._login_logo, LOGIN_LOGO_HEIGHT, anchor="center")

        progress = ctk.CTkProgressBar(
            stack, mode="indeterminate", width=180, progress_color=ACCENT, fg_color=LOGIN_ACCENT_SOFT
        )
        progress.pack()
        progress.start()

        def finish():
            progress.stop()
            self.loading_screen.destroy()
            self._build_layout()
            self.refresh_documents()

        self.root.after(LOGIN_LOADING_DURATION_MS, finish)

    # ----------------------------------------------------------- layout --
    def _build_layout(self, open_default_page=True):
        container = ctk.CTkFrame(self.root, fg_color=BODY_BG, corner_radius=0)
        container.pack(fill="both", expand=True)

        self._build_sidebar(container)

        # Sidebar sits to the left; everything else stacks vertically to
        # its right, so the reminder strip can sit above the content
        # without every page having to know about it. Page renderers
        # clear content_frame's children, which would wipe out a banner
        # placed inside it the moment anyone navigated.
        right_side = ctk.CTkFrame(container, fg_color=BODY_BG, corner_radius=0)
        right_side.pack(side="left", fill="both", expand=True)

        self.reminder_bar = ctk.CTkFrame(right_side, fg_color=ACCENT_SOFT, corner_radius=0)
        # Deliberately not packed yet -- it appears only if something is
        # actually due, so an empty strip never eats vertical space.

        self.content_frame = ctk.CTkFrame(right_side, fg_color=BODY_BG, corner_radius=0)
        self.content_frame.pack(fill="both", expand=True)
        # open_default_page=False during _rebuild_ui — it immediately
        # re-opens whatever page was actually showing (which could well
        # be a different one, e.g. Settings) via _restore_view, so
        # rendering Home/Apps here first would just be an extra,
        # unnecessary render that gets thrown away a moment later.
        if open_default_page:
            if self.settings.get("default_page") == "apps":
                self._show_apps()
            else:
                self._show_home()

        self._load_reminders()

    # -------------------------------------------------------- reminders --
    def _load_reminders(self):
        """Fetches anything due from the Calendar in the background and,
        if there is any, draws a strip above the content area.

        Deliberately a banner rather than a system notification: a
        notification needs per-machine permission and silently does
        nothing when it isn't granted, whereas this cannot fail
        invisibly. Runs off the UI thread because it's a network call,
        and never blocks startup -- the app is fully usable whether or
        not this ever comes back."""
        if self.current_user is None or not getattr(self, "id_token", ""):
            return
        email = self.current_user.get("email", "")
        if not email:
            return

        def work():
            try:
                due = firestore_due_reminders(self.id_token, email)
            except Exception:
                return
            if due:
                self.root.after(0, lambda: self._show_reminders(due))

        threading.Thread(target=work, daemon=True).start()

    def _dismiss_reminders(self, bar):
        """Hides the strip and remembers that, so it doesn't reappear on
        the next launch the same day. The mobile site already behaved
        this way; the desktop app didn't, which made the documented
        behaviour true in one place and not the other."""
        bar.pack_forget()
        self.settings["reminders_dismissed_on"] = datetime.date.today().isoformat()
        save_settings(self.settings)

    def _show_reminders(self, due):
        bar = getattr(self, "reminder_bar", None)
        if bar is None or not bar.winfo_exists():
            return
        if self.settings.get("reminders_dismissed_on") == datetime.date.today().isoformat():
            return
        for widget in bar.winfo_children():
            widget.destroy()

        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=18, pady=(8, 8))

        for item in due[:4]:
            if item["away"] == 0:
                lead = "Today: "
            elif item["away"] == 1:
                lead = "Tomorrow: "
            else:
                lead = f"In {item['away']} days: "
            ctk.CTkLabel(
                inner,
                text=lead + item["title"],
                font=ctk.CTkFont(size=F(13)),
                text_color=TEXT_DARK,
                anchor="w",
                justify="left",
            ).pack(fill="x", anchor="w")

        if len(due) > 4:
            ctk.CTkLabel(
                inner,
                text=f"…and {len(due) - 4} more.",
                font=ctk.CTkFont(size=F(12)),
                text_color=TEXT_MUTED,
                anchor="w",
            ).pack(fill="x", anchor="w")

        dismiss = ctk.CTkButton(
            bar,
            text="✕",
            width=28,
            fg_color="transparent",
            hover_color=ACCENT_SOFT,
            text_color=TEXT_MUTED,
            font=ctk.CTkFont(size=F(14)),
            command=lambda: self._dismiss_reminders(bar),
        )
        dismiss.place(relx=1.0, x=-10, y=8, anchor="ne")

        bar.pack(fill="x", before=self.content_frame)

    def _rebuild_ui(self):
        """Tears down and rebuilds the whole sidebar + content pane, then
        reopens whatever page was showing. Needed after a Settings change
        (theme, font size, ...) because CustomTkinter widgets don't
        re-read the color/font globals on their own once built — the
        only way to reskin what's already on screen is to rebuild it."""
        current_path = self._selected_path
        current_query = self._last_search_query
        for widget in self.root.winfo_children():
            widget.destroy()
        # Both the sidebar list and the page content were just destroyed
        # above, along with every CTkScrollableFrame binding they'd
        # accumulated — nothing is still alive to re-arm, so rearm_nav is
        # False. See _reset_stale_scroll_bindings for the full story: this
        # is what fixes the "'str' object has no attribute 'master'" crash
        # after a scroll. The fresh sidebar + content built a few lines
        # down register their own clean bindings in their own __init__.
        self._reset_stale_scroll_bindings(rearm_nav=False)
        self.root.configure(fg_color=WHITE_BACKDROP)
        self._build_layout(open_default_page=False)
        self.refresh_documents()
        try:
            self._restore_view(current_path, current_query)
        except Exception:
            # Caught here (rather than left to report_callback_exception)
            # so the app can fall back to a working Home page instead of
            # leaving a blank content pane — still logged and surfaced,
            # just with a recovery instead of just an error popup.
            write_error_log(
                f"(recovered in _rebuild_ui, restoring {current_path!r})\n{traceback.format_exc()}"
            )
            try:
                messagebox.showwarning(
                    WINDOW_TITLE,
                    "That change applied, but reopening the page you were on "
                    "ran into a problem, so you've been returned to Home. "
                    "Details were saved to error_log.txt next to this app.",
                )
            except Exception:
                pass
            self._show_home()

    def _restore_view(self, selected_path, last_search_query):
        if selected_path is None:
            self._show_home()
        elif selected_path == "apps":
            self._show_apps()
        elif selected_path == "skills":
            self._show_skills()
        elif selected_path == "settings":
            self._show_settings()
        elif selected_path == "team":
            if self.user_role in ("admin", "director"):
                self._show_team()
            else:
                self._show_home()
        elif selected_path == "search":
            if last_search_query:
                self._show_search_results(last_search_query)
            else:
                self._show_home()
        elif isinstance(selected_path, Path):
            match = next((d for d in self.documents if d[2] == selected_path), None)
            if match:
                _, title, path, is_program = match
                self._select_document(path, title, is_program)
            else:
                self._show_home()
        else:
            self._show_home()

    # ---------------------------------------------------------- sidebar --
    def _build_sidebar(self, parent):
        self.sidebar = ctk.CTkFrame(parent, fg_color=SIDEBAR_BG, corner_radius=0, width=SIDEBAR_WIDTH)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        # A collapse/expand toggle sits at the very top and is always
        # visible, whichever state the sidebar is in.
        toggle_row = ctk.CTkFrame(self.sidebar, fg_color=SIDEBAR_BG)
        toggle_row.pack(fill="x")
        self.toggle_button = ctk.CTkButton(
            toggle_row,
            text="⟨",
            width=26,
            height=26,
            corner_radius=6,
            fg_color="transparent",
            hover_color=SIDEBAR_BUTTON_HOVER,
            text_color=SIDEBAR_TEXT_MUTED,
            font=F(12, "bold"),
            command=self._toggle_sidebar,
        )
        self.toggle_button.pack(anchor="e", padx=6, pady=6)

        # Everything else lives in one sub-frame so it can be hidden as a
        # unit when the sidebar collapses to a thin strip.
        self.sidebar_content = ctk.CTkFrame(self.sidebar, fg_color=SIDEBAR_BG, corner_radius=0)
        self.sidebar_content.pack(fill="both", expand=True)

        # The header band follows BODY_BG (the theme-variable global) so
        # it actually re-themes along with the rest of the app, instead
        # of sitting frozen white forever. The logo itself switches
        # between its real navy-and-cyan ink (light-ish themes) and a
        # white silhouette (see load_logo_image) on dark ones, since the
        # navy ink alone would otherwise vanish against a dark header.
        header_bg = BODY_BG
        sidebar_logo = self._sidebar_logo_white if is_dark_hex(header_bg) else self._sidebar_logo
        header = ctk.CTkFrame(self.sidebar_content, fg_color=header_bg, corner_radius=0)
        header.pack(fill="x")
        header_inner = ctk.CTkFrame(header, fg_color=header_bg)
        header_inner.pack(padx=18, pady=18)
        self._render_logo(header_inner, sidebar_logo, LOGO_SIZE, anchor="center", bg_color=header_bg)
        ctk.CTkLabel(
            header_inner, text=APP_NAME, font=F(14, "bold"), text_color=TEXT_DARK, fg_color=header_bg
        ).pack(anchor="center", pady=(8, 0))
        ctk.CTkLabel(
            header_inner, text=APP_TAGLINE, font=F(10), text_color=ACCENT, fg_color=header_bg
        ).pack(anchor="center")

        ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_DIVIDER, height=1, corner_radius=0).pack(fill="x")

        home_row = ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_BG)
        home_row.pack(fill="x", padx=6, pady=(10, 4))
        self.home_button = ctk.CTkButton(
            home_row,
            text="Home",
            anchor="w",
            font=F(12, "bold"),
            fg_color=SIDEBAR_BG,
            hover_color=SIDEBAR_BUTTON_HOVER,
            text_color=SIDEBAR_TEXT,
            corner_radius=8,
            height=36,
            command=self._show_home,
        )
        self.home_button.pack(fill="x")

        ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_DIVIDER, height=1, corner_radius=0).pack(
            fill="x", padx=6, pady=(6, 0)
        )

        # Search doesn't filter this sidebar list live — it jumps to a
        # dedicated Search Results page (Enter or the 🔍 button) that
        # looks everywhere: page names, document titles, and the full
        # text inside every guide and app, not just what's listed here.
        search_row = ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_BG)
        search_row.pack(fill="x", padx=12, pady=12)

        # The bordered container itself IS the search box; the entry and
        # the × both live inside it as ordinary, normally-packed children
        # with their own reserved space. An earlier version tried to
        # overlay the × on top of the entry's own text via place(), with
        # a same-color background standing in for a "fade" -- that never
        # actually worked, because CTkEntry's inner text field is a real
        # native text control that always draws its own contents
        # regardless of sibling stacking order, so the overlay had no
        # visible effect. Giving the × its own permanent slot means text
        # can't ever reach it in the first place; the entry's native
        # behavior already scrolls long text leftward as you type, the
        # same way any OS or browser search box handles overflow, so
        # there's nothing left to visually collide with the ×.
        box = ctk.CTkFrame(
            search_row,
            fg_color=SIDEBAR_HOVER,
            corner_radius=8,
            border_width=1,
            border_color=SIDEBAR_TEXT_MUTED,
        )
        box.pack(side="left", fill="x", expand=True)

        self.search_var = StringVar()
        self.search_entry = ctk.CTkEntry(
            box,
            textvariable=self.search_var,
            placeholder_text="Search…",
            font=F(12),
            # CTkEntry defaults to width=140 when not given -- combined
            # with the sidebar's fixed 220px width, box's border, the
            # ×'s permanently reserved slot, and the 🔍 button next to
            # it, that default alone was already wider than the space
            # available, which is why the box kept overflowing and
            # shoving the 🔍 button out. width=1 here isn't literal --
            # it just drops the entry's own oversized minimum so
            # fill="x"/expand=True (below) are what actually size it,
            # based on whatever room box really has.
            width=1,
            height=30,
            corner_radius=0,
            fg_color="transparent",
            border_width=0,
            text_color=SIDEBAR_TEXT,
            placeholder_text_color=SIDEBAR_TEXT_MUTED,
        )
        self.search_entry.pack(side="left", fill="both", expand=True, padx=(10, 2), pady=1)
        self.search_entry.bind("<Return>", lambda _e: self._perform_search())

        # Packed once, permanently, so its slot is always reserved --
        # this button used to be pack()'d in only once there was text
        # and pack_forget()'d otherwise, which changed box's own required
        # width each time and squeezed the 🔍 button beside it (even
        # pushing it out of the sidebar entirely). Now "showing" and
        # "hiding" the × is just a color change (text/hover color match
        # the box's own background when hidden, so it's blended away
        # rather than removed), and the layout never reflows.
        self.search_clear_button = ctk.CTkButton(
            box,
            text="×",
            width=20,
            height=20,
            corner_radius=6,
            fg_color="transparent",
            hover_color=SIDEBAR_HOVER,
            text_color=SIDEBAR_HOVER,
            font=F(13, "bold"),
            command=self._clear_search,
        )
        self.search_clear_button.pack(side="right", padx=(0, 6))

        def _update_search_clear_visibility(*_args):
            has_text = bool(self.search_var.get())
            self.search_clear_button.configure(
                text_color=(SIDEBAR_TEXT_MUTED if has_text else SIDEBAR_HOVER),
                hover_color=(SIDEBAR_BUTTON_HOVER if has_text else SIDEBAR_HOVER),
            )

        self.search_var.trace_add("write", _update_search_clear_visibility)
        _update_search_clear_visibility()

        # A drawn white silhouette (see build_search_icon) instead of the
        # 🔍 emoji, which renders as a small full-color picture rather
        # than a flat icon matching the rest of the sidebar. Falls back
        # to the emoji only if Pillow isn't available at all.
        search_button_kwargs = dict(
            width=32,
            height=32,
            corner_radius=8,
            fg_color=SIDEBAR_HOVER,
            hover_color=SIDEBAR_BUTTON_HOVER,
            command=self._perform_search,
        )
        if self._search_icon is not None:
            search_button_kwargs["image"] = self._search_icon
            search_button_kwargs["text"] = ""
        else:
            search_button_kwargs["text"] = "🔍"
            search_button_kwargs["text_color"] = SIDEBAR_TEXT
            search_button_kwargs["font"] = F(12)
        ctk.CTkButton(search_row, **search_button_kwargs).pack(side="left", padx=(6, 0))

        apps_row = ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_BG)
        apps_row.pack(fill="x", padx=6, pady=(0, 4))
        self.apps_button = ctk.CTkButton(
            apps_row,
            text="Apps",
            anchor="w",
            font=F(12, "bold"),
            fg_color=SIDEBAR_BG,
            hover_color=SIDEBAR_BUTTON_HOVER,
            text_color=SIDEBAR_TEXT,
            corner_radius=8,
            height=36,
            command=self._show_apps,
        )
        self.apps_button.pack(fill="x")

        skills_row = ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_BG)
        skills_row.pack(fill="x", padx=6, pady=(0, 4))
        self.skills_button = ctk.CTkButton(
            skills_row,
            text="Skills",
            anchor="w",
            font=F(12, "bold"),
            fg_color=SIDEBAR_BG,
            hover_color=SIDEBAR_BUTTON_HOVER,
            text_color=SIDEBAR_TEXT,
            corner_radius=8,
            height=36,
            command=self._show_skills,
        )
        self.skills_button.pack(fill="x")

        # Team is no longer a pinned sidebar row -- it's reached via a
        # button inside Settings instead (see _show_settings), since it's
        # an Admin/Director-only management page rather than something
        # everyone navigates to often.

        self.nav_scroll = ctk.CTkScrollableFrame(
            self.sidebar_content, fg_color=SIDEBAR_BG, corner_radius=0,
            scrollbar_fg_color=SIDEBAR_BG, scrollbar_button_color=SIDEBAR_HOVER,
            scrollbar_button_hover_color=SIDEBAR_BUTTON_HOVER,
        )
        self.nav_scroll.pack(fill="both", expand=True, padx=6)

        # The document-list buttons live in their own inner frame (instead
        # of directly in nav_scroll) so _render_nav_list can safely clear
        # and rebuild just that list on every refresh without touching the
        # footer below it, which is built once and needs to survive.
        self.nav_list_container = ctk.CTkFrame(self.nav_scroll, fg_color=SIDEBAR_BG)
        self.nav_list_container.pack(fill="x")

        # The footer (Refresh/Settings/Help/Quit) is packed inside the
        # same scrollable nav_scroll, right after the document list --
        # not as a separate fixed-height sibling below it. It used to
        # sit outside the scroll area entirely, with a fixed minimum
        # height; on a short/minimized window there wasn't enough room
        # for the header, nav rows, search box, document list, AND the
        # footer to all fit, so the footer's last items ("How to Use
        # This Launcher", "Quit") got clipped off below the visible
        # window with no way to reach them. Making it part of the single
        # scrollable region means the whole sidebar scrolls as one unit
        # when things don't fit, and the auto-hide scrollbar (see the
        # CTkScrollbar patch above) only appears when that's actually
        # needed.
        self._build_sidebar_footer(self.nav_scroll)

        # _build_sidebar always constructs the expanded layout above;
        # apply a previously-saved collapsed state now that everything
        # exists, without toggling self._sidebar_expanded itself.
        self._apply_sidebar_state()

    def _sync_shared_preferences(self):
        """Pushes the signed-in person's display preferences up to their
        own row in the shared database, so a change made on this
        computer shows up on every other one -- and on the mobile site --
        the next time they sign in.

        Done on a background thread and deliberately silent about
        failures: this is a preference, not data anyone typed. If the
        network is briefly down, the setting still applies locally for
        this session and simply doesn't travel; nobody should get an
        error popup for changing their text size."""
        if self.current_user is None or not getattr(self, "id_token", ""):
            return
        email = self.current_user["email"]
        preferences = {
            key: self.settings.get(key) for key in PERSONAL_SETTING_KEYS
        }
        self.current_user["preferences"] = preferences
        token = self.id_token

        def work():
            try:
                firestore_save_preferences(token, email, preferences)
            except Exception:
                write_error_log(
                    f"(couldn't sync preferences for {email})\n{traceback.format_exc()}"
                )

        threading.Thread(target=work, daemon=True).start()

    def _toggle_sidebar(self):
        self._sidebar_expanded = not self._sidebar_expanded
        self._animate_sidebar(self._sidebar_expanded)
        self.settings["sidebar_expanded"] = self._sidebar_expanded
        save_settings(self.settings)
        self._sync_shared_preferences()

    def _apply_sidebar_state(self):
        """Instantly applies self._sidebar_expanded to the already-built
        sidebar widgets, without flipping it or animating -- used right
        after _build_sidebar constructs everything in its default
        (expanded) layout, so a collapsed state saved from a previous
        launch (or restored via Settings) takes effect immediately on
        load. _toggle_sidebar (an actual user click) uses the animated
        _animate_sidebar instead — see there for why."""
        if self._sidebar_expanded:
            self.sidebar.configure(width=SIDEBAR_WIDTH)
            self.sidebar_content.pack(fill="both", expand=True)
            self.toggle_button.configure(text="⟨")
        else:
            self.sidebar_content.pack_forget()
            self.sidebar.configure(width=SIDEBAR_COLLAPSED_WIDTH)
            self.toggle_button.configure(text="⟩")

    def _animate_sidebar(self, expanding: bool):
        """Eases the sidebar open/closed instead of snapping instantly --
        fast at the start, slowing to a stop at the end (ease-out cubic),
        like a soft-close door or drawer. sidebar_content (the nav list,
        search box, footer) is hidden immediately when collapsing and
        shown only once the expand animation finishes, rather than
        somewhere mid-resize -- squeezing real text/buttons into a
        shrinking frame looks far worse than just letting the frame
        resize around empty space. Guarded against a second click
        interrupting an animation already in flight, and against the
        sidebar being torn down (rebuild/sign-out) mid-animation."""
        if getattr(self, "_sidebar_animating", False):
            return
        self._sidebar_animating = True
        self.toggle_button.configure(text="⟨" if expanding else "⟩")
        start_width = SIDEBAR_COLLAPSED_WIDTH if expanding else SIDEBAR_WIDTH
        end_width = SIDEBAR_WIDTH if expanding else SIDEBAR_COLLAPSED_WIDTH
        if not expanding:
            self.sidebar_content.pack_forget()

        steps = SIDEBAR_ANIMATION_STEPS
        interval = max(1, SIDEBAR_ANIMATION_MS // steps)

        def step(i=0):
            try:
                if i >= steps:
                    self.sidebar.configure(width=end_width)
                    if expanding:
                        self.sidebar_content.pack(fill="both", expand=True)
                    self._sidebar_animating = False
                    return
                t = (i + 1) / steps
                eased = 1 - (1 - t) ** 3  # ease-out cubic: fast start, slow finish
                width = round(start_width + (end_width - start_width) * eased)
                self.sidebar.configure(width=width)
                self.root.after(interval, lambda: step(i + 1))
            except Exception:
                self._sidebar_animating = False

        step()

    def _build_sidebar_footer(self, sidebar):
        ctk.CTkFrame(sidebar, fg_color=SIDEBAR_DIVIDER, height=1, corner_radius=0).pack(fill="x")
        footer = ctk.CTkFrame(sidebar, fg_color=SIDEBAR_BG)
        footer.pack(fill="x", padx=8, pady=8)

        def footer_button(text, command):
            return ctk.CTkButton(
                footer,
                text=text,
                anchor="w",
                font=F(11),
                fg_color="transparent",
                hover_color=SIDEBAR_BUTTON_HOVER,
                text_color=SIDEBAR_TEXT_MUTED,
                corner_radius=8,
                height=30,
                command=command,
            )

        self._refresh_button = footer_button("Refresh", self._refresh_with_feedback)
        self._refresh_button.pack(fill="x", pady=1)
        self.settings_button = footer_button("Settings", self._show_settings)
        self.settings_button.pack(fill="x", pady=1)
        # Deferred to the next idle tick -- same fix as apply_and_rebuild
        # in _show_settings and attempt_login on the login screen.
        # _sign_out() destroys the entire sidebar + content pane,
        # including this very button; tearing that down synchronously
        # from inside the button's own click handler is the classic Tk
        # hazard where CTkButton still has post-click bookkeeping to do
        # on itself once this callback returns, and that throws "invalid
        # command name ...!ctkbutton" once everything around it is
        # already gone. This is exactly the TCL error logged to
        # error_log.txt after Sign Out → Sign back in.
        footer_button("Sign Out", lambda: self.root.after(1, self._sign_out)).pack(fill="x", pady=1)
        footer_button("Quit", self.root.destroy).pack(fill="x", pady=1)

    def _render_logo(self, parent, logo_image, placeholder_size, anchor="w", bg_color=None):
        """Show a real logo if assets/logo.* exists, otherwise a clean
        rounded placeholder mark so the app still looks finished today.
        Drawn on bg_color, defaulting to WHITE_BACKDROP (fixed white, not
        the theme-variable BODY_BG) — see load_logo_image — since the
        real navy-and-cyan logo needs a light background to read. The
        sidebar header is the one caller that passes its own bg_color
        (BODY_BG) instead, since it also switches to the white-silhouette
        logo variant on dark themes rather than forcing a fixed-white
        chip — see _build_sidebar. Every other caller just wraps this in
        a WHITE_BACKDROP-colored holder frame to match the default.
        `anchor` controls horizontal alignment within `parent`: "w" for
        the left-aligned Home-page usage, "center" for the sidebar
        header and login/loading screens, where it should sit dead-center."""
        bg_color = bg_color or WHITE_BACKDROP
        if logo_image is not None:
            ctk.CTkLabel(parent, image=logo_image, text="", fg_color=bg_color).pack(anchor=anchor)
            return

        ctk.CTkLabel(
            parent,
            text=APP_NAME[0],
            width=placeholder_size,
            height=placeholder_size,
            corner_radius=placeholder_size // 2,
            fg_color=ACCENT,
            text_color="white",
            font=F(int(placeholder_size * 0.4), "bold"),
        ).pack(anchor=anchor)

    # --------------------------------------------------------- behavior --
    def refresh_documents(self):
        """Rescans html/ for new/removed/renamed files and re-renders
        whatever's actually on screen right now -- not just the nav list
        and Apps. Previously this only refreshed the list itself, which
        is why picking up an edit made via "Edit This Page" (or dropping
        in a new file) meant clicking away to another page and back
        before the change actually showed up."""
        self.documents = discover_documents()
        self._render_nav_list()
        if self._selected_path == "apps":
            self._show_apps()
        elif self._selected_path is None:
            self._show_home()
        elif isinstance(self._selected_path, Path):
            match = next((d for d in self.documents if d[2] == self._selected_path), None)
            if match:
                _, title, path, is_program = match
                self._select_document(path, title, is_program)
            else:
                # The file that was open got removed/renamed out from
                # under it -- fall back rather than show a stale page.
                self._show_home()

    def _refresh_with_feedback(self):
        """Wraps refresh_documents() with a brief, visible button-state
        animation -- Refresh -> Refreshing... -> checkmark -> back to
        Refresh -- so clicking it actually feels like it did something,
        instead of the button just sitting there with no acknowledgment
        while the page silently updates behind it."""
        btn = getattr(self, "_refresh_button", None)
        if btn is None:
            self.refresh_documents()
            return

        def revert():
            try:
                btn.configure(text="Refresh", state="normal")
            except Exception:
                pass  # sidebar was rebuilt/torn down before this fired

        def finish():
            self.refresh_documents()
            try:
                btn.configure(text="✓ Refreshed", state="normal")
                self.root.after(900, revert)
            except Exception:
                pass

        try:
            btn.configure(text="Refreshing…", state="disabled")
        except Exception:
            pass
        # Tiny delay so "Refreshing..." actually has a moment to be seen
        # even when the rescan+re-render itself is instant.
        self.root.after(150, finish)

    def _render_nav_list(self):
        """Populates the sidebar's document list. Always shows every
        guide/app (minus the ones superseded by a pinned page — see
        SIDEBAR_HIDDEN_FILES); no longer affected by the search box,
        which now jumps to a dedicated Search Results page instead of
        filtering this list — see _perform_search."""
        self.filtered = [
            d for d in self.documents
            if not d[3] and d[2].name.lower() not in SIDEBAR_HIDDEN_FILES
        ]

        for widget in self.nav_list_container.winfo_children():
            widget.destroy()
        self._nav_buttons = {}

        if not self.filtered:
            ctk.CTkLabel(
                self.nav_list_container,
                text=f"No documents found yet.\nAdd .html files to:\n{HTML_DIR}",
                font=F(11),
                text_color=SIDEBAR_TEXT_MUTED,
                fg_color=SIDEBAR_BG,
                justify="left",
                wraplength=SIDEBAR_WIDTH - 40,
            ).pack(anchor="w", padx=6, pady=12)
            return

        for _key, title, path, is_program in self.filtered:
            label = f"{title}  ↗" if is_program else title
            btn = ctk.CTkButton(
                self.nav_list_container,
                text=label,
                anchor="w",
                font=F(12),
                fg_color=SIDEBAR_BG,
                hover_color=SIDEBAR_BUTTON_HOVER,
                text_color=SIDEBAR_TEXT,
                corner_radius=8,
                height=36,
                command=lambda p=path, t=title, prog=is_program: self._select_document(p, t, prog),
            )
            btn.pack(fill="x", pady=2)
            self._nav_buttons[path] = btn

        self._highlight_nav(self._selected_path)

    # ---------------------------------------------------------- search --
    def _perform_search(self):
        query = self.search_var.get().strip()
        if query:
            self._show_search_results(query)

    def _clear_search(self):
        self.search_var.set("")
        self.search_entry.focus_set()

    def _search_pages(self, query_l: str):
        """Matches against the pinned Home/Apps pages by name, so
        searching "apps" finds the Apps page itself, not just documents
        that happen to have "apps" in their title or text."""
        pages = [
            ("Home", "Welcome overview — what this app is for, using guides and apps, and Claude Skills.", self._show_home),
            ("Apps", "Dedicated list of every interactive tool in this app.", self._show_apps),
        ]
        return [(title, snippet, action) for title, snippet, action in pages if query_l in title.lower()]

    def _search_documents(self, query_l: str):
        """Matches against every known document — including ones hidden
        from the general sidebar list (SIDEBAR_HIDDEN_FILES) or shown
        only on the Apps page — checking both the title and the full
        text inside the file, not just what's visible in the sidebar."""
        results = []
        for _key, title, path, is_program in self.documents:
            snippet = None
            if query_l in title.lower():
                snippet = "Match in the title."

            text = extract_plain_text(path)
            idx = text.lower().find(query_l)
            if idx != -1:
                start = max(0, idx - SEARCH_SNIPPET_RADIUS)
                end = min(len(text), idx + len(query_l) + SEARCH_SNIPPET_RADIUS)
                snippet = ("…" if start > 0 else "") + text[start:end].strip() + ("…" if end < len(text) else "")

            if snippet is not None:
                results.append((title, path, is_program, snippet))
        return results

    def _show_search_results(self, query: str):
        """Dedicated Search Results page — looks everywhere (pinned page
        names, every document's title, and every document's full text),
        not just the currently-visible sidebar list."""
        self._selected_path = "search"
        self._last_search_query = query
        self._clear_content()
        self._highlight_nav("search")

        query_l = query.lower()
        page_matches = self._search_pages(query_l)
        doc_matches = self._search_documents(query_l)
        total = len(page_matches) + len(doc_matches)

        scroll = ctk.CTkScrollableFrame(
            self.content_frame, fg_color=BODY_BG, corner_radius=0,
            scrollbar_fg_color=BODY_BG, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=TEXT_MUTED,
        )
        scroll.pack(fill="both", expand=True, padx=32, pady=28)

        ctk.CTkLabel(
            scroll,
            text=f'Search results for "{query}"',
            font=F(19, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
            wraplength=560,
            justify="left",
        ).pack(anchor="w")
        ctk.CTkLabel(
            scroll,
            text=f"{total} match{'es' if total != 1 else ''} found across pages, guides, and apps.",
            font=F(12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).pack(anchor="w", pady=(2, 18))

        if total == 0:
            ctk.CTkLabel(
                scroll,
                text="No matches. Try a different word.",
                font=F(12),
                text_color=TEXT_MUTED,
                fg_color=BODY_BG,
            ).pack(anchor="w")
            return

        def result_card(title, kind_label, snippet, on_click):
            card = ctk.CTkFrame(scroll, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=BORDER)
            card.pack(fill="x", pady=6)
            row = ctk.CTkFrame(card, fg_color=CARD_BG)
            row.pack(fill="x", padx=18, pady=14)

            top = ctk.CTkFrame(row, fg_color=CARD_BG)
            top.pack(fill="x")
            ctk.CTkLabel(
                top, text=title, font=F(14, "bold"), text_color=TEXT_DARK, fg_color=CARD_BG, anchor="w"
            ).pack(side="left")
            badge = ctk.CTkFrame(top, fg_color=ACCENT_SOFT, corner_radius=6)
            badge.pack(side="right")
            ctk.CTkLabel(
                badge, text=kind_label, font=F(10, "bold"), text_color=ACCENT, fg_color=ACCENT_SOFT
            ).pack(padx=8, pady=2)

            if snippet:
                ctk.CTkLabel(
                    row,
                    text=snippet,
                    font=F(11),
                    text_color=TEXT_MUTED,
                    fg_color=CARD_BG,
                    anchor="w",
                    justify="left",
                    wraplength=560,
                ).pack(fill="x", pady=(6, 10))

            # Deferred via after() rather than calling on_click directly:
            # it clears content_frame, which is this button's own
            # ancestor. Destroying a widget tree synchronously from
            # inside one of its own buttons' click handlers is a classic
            # Tk hazard (the button still has post-click bookkeeping to
            # do on itself once this callback returns) -- see the same
            # fix/comment in _show_settings's apply_and_rebuild.
            ctk.CTkButton(
                row,
                text="Open",
                font=F(11, "bold"),
                fg_color=ACCENT,
                hover_color=TEXT_DARK,
                text_color="white",
                corner_radius=8,
                height=30,
                width=90,
                command=lambda cb=on_click: self.root.after(1, cb),
            ).pack(anchor="e")

        for title, snippet, action in page_matches:
            result_card(title, "PAGE", snippet, action)

        for title, path, is_program, snippet in doc_matches:
            result_card(
                title,
                "APP" if is_program else "GUIDE",
                snippet,
                lambda p=path, t=title, prog=is_program: self._select_document(p, t, prog),
            )

    def _highlight_nav(self, active_path):
        # Every .configure() below goes through this instead of being
        # called directly, because these are all long-lived references
        # (self.home_button, self._nav_buttons, ...) held across a full
        # Sign Out -> Sign In cycle. _sign_out() now clears them up
        # front, but this is a second, unconditional safety net: if any
        # reference here ever does end up pointing at an already-
        # destroyed widget again (from this or some future change), a
        # bare .configure() call throws _tkinter.TclError: invalid
        # command name "...!ctkbutton" and takes the whole callback down
        # with it -- which is exactly the crash reported after Sign Out
        # -> Sign In (error_log.txt, _highlight_nav, TclError on a
        # button living inside the sidebar's scrollable nav list).
        def safe_configure(widget, **kwargs):
            if widget is None:
                return
            try:
                widget.configure(**kwargs)
            except Exception:
                pass

        safe_configure(
            self.home_button,
            fg_color=(SIDEBAR_ACTIVE if active_path is None else SIDEBAR_BG),
            text_color=(ACCENT if active_path is None else SIDEBAR_TEXT),
        )
        safe_configure(
            self.apps_button,
            fg_color=(SIDEBAR_ACTIVE if active_path == "apps" else SIDEBAR_BG),
            text_color=(ACCENT if active_path == "apps" else SIDEBAR_TEXT),
        )
        safe_configure(
            self.skills_button,
            fg_color=(SIDEBAR_ACTIVE if active_path == "skills" else SIDEBAR_BG),
            text_color=(ACCENT if active_path == "skills" else SIDEBAR_TEXT),
        )
        safe_configure(
            self.settings_button,
            fg_color=(SIDEBAR_ACTIVE if active_path == "settings" else "transparent"),
            text_color=(ACCENT if active_path == "settings" else SIDEBAR_TEXT_MUTED),
        )
        for path, btn in list(self._nav_buttons.items()):
            safe_configure(
                btn,
                fg_color=(SIDEBAR_ACTIVE if path == active_path else SIDEBAR_BG),
                text_color=(ACCENT if path == active_path else SIDEBAR_TEXT),
            )

    def _select_document(self, path: Path, title: str, is_program: bool):
        if not path.exists():
            messagebox.showerror(WINDOW_TITLE, f"File not found:\n{path}\n\nClick Refresh and try again.")
            return
        self._selected_path = path
        self._highlight_nav(path)
        if is_program:
            self._show_program_card(title, path)
        elif HtmlFrame is None:
            webbrowser.open(path.resolve().as_uri())
            self._show_browser_fallback_card(title, path)
        else:
            self._show_guide(title, path)

    def _open_guides_page(self):
        """Used by the Skills tab's 'See example prompts in Guides' link
        to jump straight to the Guides document -- looked up by filename
        rather than hardcoding a title, so renaming/re-ordering Guides
        doesn't silently break this link."""
        match = next((d for d in self.documents if d[2].name == "02_guides.html"), None)
        if match:
            _, title, path, is_program = match
            self._select_document(path, title, is_program)
        else:
            self._show_home()

    def _open_program(self, path: Path, title: str):
        """Launch an interactive tool in its own pywebview window, spawned
        as a separate process. pywebview needs to run its own event loop
        on the main thread, same as Tkinter does — so rather than fight
        over one thread, the tool runs as a fresh invocation of this same
        program with a hidden `--webview` flag (see run_webview_window /
        main() below), which never touches Tkinter at all.

        The launcher window stays open the whole time — the tool just
        opens alongside it in its own window."""
        # Hand this session to the tool so it doesn't ask for a password
        # again -- signing into the launcher is meant to be the only
        # login. Passed through the child process's environment rather
        # than its command line: command lines are visible to anything
        # that can list processes, environments are not.
        environment = dict(os.environ)
        environment.pop("CENTER_SESSION", None)
        if getattr(self, "refresh_token", "") and self.current_user:
            environment["CENTER_SESSION"] = json.dumps({
                "refreshToken": self.refresh_token,
                "email": self.current_user.get("email", ""),
                "name": self.current_user.get("name", ""),
                "role": self.current_user.get("role", "staff"),
            })

        if webview is not None:
            try:
                args = [sys.executable]
                if not getattr(sys, "frozen", False):
                    args.append(str(Path(__file__).resolve()))
                args += ["--webview", str(path.resolve()), title or APP_NAME]
                subprocess.Popen(args, env=environment)
                return
            except Exception:
                pass
        # Browser fallback: no way to hand the session over, so the tool
        # will ask for a sign-in of its own.
        webbrowser.open(path.resolve().as_uri())

    # ---------------------------------------------------- content pane --
    def _reset_stale_scroll_bindings(self, rearm_nav=True):
        """CustomTkinter's CTkScrollableFrame registers a handful of
        application-wide bind_all() handlers in its own __init__ (mouse
        wheel scrolling, plus shift-key tracking for horizontal scroll)
        but its destroy() never removes them. Every page render creates
        and destroys one of these (the content pane's scrollable area),
        and Settings changes additionally destroy/recreate the sidebar's
        (self.nav_scroll) -- each one left behind a stale binding
        pointing at a dead widget. The next scroll anywhere in the app
        then fires every stale handler too, and CustomTkinter's own
        scroll code crashes trying to read a live widget off the event
        ("AttributeError: 'str' object has no attribute 'master'").

        Call this right after destroying a CTkScrollableFrame to wipe
        all accumulated bindings. If self.nav_scroll is still alive
        (i.e. it wasn't itself just destroyed -- the normal case for
        plain page navigation), pass rearm_nav=True (the default) to
        immediately re-register its bindings, since the blanket clear
        above would otherwise silence sidebar scrolling until the next
        full rebuild. Any freshly-created CTkScrollableFrame (e.g. the
        new page's content) re-adds its own clean bindings in its own
        __init__ right after this runs, so nothing else is needed."""
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>",
                         "<KeyPress-Shift_L>", "<KeyPress-Shift_R>",
                         "<KeyRelease-Shift_L>", "<KeyRelease-Shift_R>"):
            try:
                self.root.unbind_all(sequence)
            except Exception:
                pass
        if rearm_nav and getattr(self, "nav_scroll", None) is not None:
            try:
                if self.nav_scroll.winfo_exists():
                    if "linux" in sys.platform:
                        self.nav_scroll.bind_all("<Button-4>", self.nav_scroll._mouse_wheel_all, add=True)
                        self.nav_scroll.bind_all("<Button-5>", self.nav_scroll._mouse_wheel_all, add=True)
                    else:
                        self.nav_scroll.bind_all("<MouseWheel>", self.nav_scroll._mouse_wheel_all, add=True)
                    self.nav_scroll.bind_all("<KeyPress-Shift_L>", self.nav_scroll._keyboard_shift_press_all, add=True)
                    self.nav_scroll.bind_all("<KeyPress-Shift_R>", self.nav_scroll._keyboard_shift_press_all, add=True)
                    self.nav_scroll.bind_all("<KeyRelease-Shift_L>", self.nav_scroll._keyboard_shift_release_all, add=True)
                    self.nav_scroll.bind_all("<KeyRelease-Shift_R>", self.nav_scroll._keyboard_shift_release_all, add=True)
            except Exception:
                pass

    def _clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        self._reset_stale_scroll_bindings(rearm_nav=True)

    def _content_header(self, title: str, extra_button=None, extra_buttons=None):
        """Shared header row (title, optional right-side button(s)) used
        at the top of every non-welcome content view. Used to also show a
        colored square with the title's first letter next to the title,
        as a stand-in for a real icon — dropped since it read as a bare
        "logo" rather than anything meaningful.

        extra_button is a single (text, command) tuple, kept for existing
        callers; extra_buttons is a list of the same, for when more than
        one is needed (e.g. "Open in Browser" + an admin-only "Edit This
        Page"). Buttons are packed right-to-left, so list order reads
        left-to-right in the header."""
        header = ctk.CTkFrame(self.content_frame, fg_color=BODY_BG)
        header.pack(fill="x", padx=24, pady=(20, 12))

        ctk.CTkLabel(
            header,
            text=title,
            font=F(16, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
            wraplength=420,
            justify="left",
        ).pack(side="left")

        buttons = list(extra_buttons) if extra_buttons else []
        if extra_button is not None:
            buttons.append(extra_button)
        for text, command in reversed(buttons):
            ctk.CTkButton(
                header,
                text=text,
                font=F(11),
                fg_color="transparent",
                hover_color=TEXT_DARK,
                text_color=ACCENT,
                border_width=0,
                corner_radius=8,
                height=32,
                command=command,
            ).pack(side="right")

    def _show_home(self):
        """The initial page and the sidebar's pinned 'Home' entry — an
        overview of what this app is for, aimed at someone brand new to
        the office. The welcome heading, intro, and the two info
        sections below are rendered from html/01_welcome.html (the same
        native guide-block renderer Guides use), instead of being
        hardcoded here, so Admin/Owner can edit that wording with the
        same "Edit This Page" mechanism as any other guide (see
        _edit_page_file). The logo and the Employee Portal callout stay
        as fixed, Python-built chrome around it."""
        self._selected_path = None
        self._clear_content()
        self._highlight_nav(None)

        scroll = ctk.CTkScrollableFrame(
            self.content_frame, fg_color=BODY_BG, corner_radius=0,
            scrollbar_fg_color=BODY_BG, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=TEXT_MUTED,
        )
        scroll.pack(fill="both", expand=True, padx=32, pady=28)

        # Wrapped in its own small white tile (WHITE_BACKDROP, corner_radius)
        # rather than sitting directly on BODY_BG, so the logo stays legible
        # in Dark/Eye Comfort mode too — in the Light theme it's white on
        # white and looks identical to before.
        logo_holder = ctk.CTkFrame(scroll, fg_color=WHITE_BACKDROP, corner_radius=12)
        logo_holder.pack(anchor="w", pady=(0, 16))
        logo_inner = ctk.CTkFrame(logo_holder, fg_color=WHITE_BACKDROP)
        logo_inner.pack(padx=14, pady=14)
        self._render_logo(logo_inner, self._welcome_logo, 64)

        home_page_path = HTML_DIR / "01_welcome.html"
        if self.user_role in ("admin", "director"):
            edit_row = ctk.CTkFrame(scroll, fg_color=BODY_BG)
            edit_row.pack(fill="x", pady=(0, 4))
            ctk.CTkButton(
                edit_row,
                text="Edit This Page ✎",
                font=F(11),
                fg_color="transparent",
                hover_color=TEXT_DARK,
                text_color=ACCENT,
                border_width=0,
                corner_radius=8,
                height=28,
                command=lambda: self._edit_page_file(home_page_path),
            ).pack(anchor="e")

        try:
            source = home_page_path.read_text(encoding="utf-8", errors="ignore")
            blocks = _GuideHTMLParser.parse(source)
            if not blocks:
                raise ValueError("no renderable content found")
            self._render_guide_blocks(scroll, blocks, HTML_DIR)
        except Exception:
            # Same defensive fallback pattern as _show_guide -- Home
            # should never show fully blank just because the underlying
            # file went missing or got mangled by a manual edit.
            write_error_log(f"(home native-render fallback for {home_page_path})\n{traceback.format_exc()}")
            ctk.CTkLabel(
                scroll,
                text="Welcome to the Office App",
                font=F(19, "bold"),
                text_color=TEXT_DARK,
                fg_color=BODY_BG,
                wraplength=560,
                justify="left",
            ).pack(anchor="w", pady=(0, 6))
            ctk.CTkLabel(
                scroll,
                text="This is your toolbox for office work — guides, small tools, "
                     "and Claude Skills, all in one place.",
                font=F(13),
                text_color=TEXT_MUTED,
                fg_color=BODY_BG,
                wraplength=560,
                justify="left",
            ).pack(anchor="w", pady=(0, 18))

        # Callout linking out to the full employee onboarding site — this
        # app deliberately only covers tools/Skills, so anything else new
        # hires need (policies, other links, general instructions) points
        # here instead of trying to duplicate it in-app. Fixed chrome,
        # not part of the editable file above.
        portal_card = ctk.CTkFrame(scroll, fg_color=ACCENT_SOFT, corner_radius=12)
        portal_card.pack(fill="x", pady=(18, 0))
        portal_inner = ctk.CTkFrame(portal_card, fg_color=ACCENT_SOFT)
        portal_inner.pack(fill="x", padx=18, pady=16)
        ctk.CTkLabel(
            portal_inner,
            text="New here, or need something beyond tools and Skills?",
            font=F(13, "bold"),
            text_color=TEXT_DARK,
            fg_color=ACCENT_SOFT,
            wraplength=500,
            justify="left",
        ).pack(anchor="w")
        ctk.CTkLabel(
            portal_inner,
            text="The Employee Portal has the rest — onboarding info, "
                 "policies, and other helpful links.",
            font=F(12),
            text_color=TEXT_MUTED,
            fg_color=ACCENT_SOFT,
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))
        ctk.CTkButton(
            portal_inner,
            text="Open Employee Portal ↗",
            font=F(12, "bold"),
            fg_color=ACCENT,
            hover_color=TEXT_DARK,
            text_color="white",
            corner_radius=8,
            height=34,
            command=lambda: webbrowser.open("https://thecenterwcy.com/employee-portal/"),
        ).pack(anchor="w")

    def _show_apps(self):
        """The sidebar's pinned 'Apps' entry — a dedicated list of every
        interactive HTML tool (anything with a <script> tag), pulled
        straight from self.documents so a new tool shows up here
        automatically, with no separate registration step. Unaffected
        by the sidebar search box, same as Home."""
        self._selected_path = "apps"
        self._clear_content()
        self._highlight_nav("apps")

        scroll = ctk.CTkScrollableFrame(
            self.content_frame, fg_color=BODY_BG, corner_radius=0,
            scrollbar_fg_color=BODY_BG, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=TEXT_MUTED,
        )
        scroll.pack(fill="both", expand=True, padx=32, pady=28)

        ctk.CTkLabel(
            scroll,
            text="Apps",
            font=F(19, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
        ).pack(anchor="w")
        ctk.CTkLabel(
            scroll,
            text="Interactive tools that open in their own window, with full JavaScript support.",
            font=F(12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).pack(anchor="w", pady=(2, 18))

        programs = [(title, path) for _key, title, path, is_program in self.documents if is_program]

        if not programs:
            ctk.CTkLabel(
                scroll,
                text="No interactive tools yet. Drop an .html file with a <script> tag into the html folder and click Refresh.",
                font=F(12),
                text_color=TEXT_MUTED,
                fg_color=BODY_BG,
                wraplength=520,
                justify="left",
            ).pack(anchor="w")
            return

        for title, path in programs:
            card = ctk.CTkFrame(scroll, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=BORDER)
            card.pack(fill="x", pady=8)

            row = ctk.CTkFrame(card, fg_color=CARD_BG)
            row.pack(fill="x", padx=18, pady=16)

            # Icon drawn to match the logo (see build_app_icon). Kept on
            # the card so it isn't garbage-collected -- CTkImage doesn't
            # hold its own reference and the image vanishes if the only
            # one goes out of scope when this loop moves on.
            icon = build_app_icon(title, 36)
            if icon is not None:
                card._app_icon = icon
                ctk.CTkLabel(row, image=icon, text="", width=36, height=36,
                             fg_color=CARD_BG).pack(side="left")
            else:
                ctk.CTkLabel(
                    row,
                    text=(title[:1] or "?").upper(),
                    width=36,
                    height=36,
                    corner_radius=10,
                    fg_color=TEXT_DARK,
                    text_color="white",
                    font=F(15, "bold"),
                ).pack(side="left")

            text_holder = ctk.CTkFrame(row, fg_color=CARD_BG)
            text_holder.pack(side="left", padx=(14, 0), fill="x", expand=True)
            ctk.CTkLabel(
                text_holder,
                text=title,
                font=F(14, "bold"),
                text_color=TEXT_DARK,
                fg_color=CARD_BG,
                anchor="w",
            ).pack(fill="x")
            ctk.CTkLabel(
                text_holder,
                text="Interactive tool — opens in its own window.",
                font=F(11),
                text_color=TEXT_MUTED,
                fg_color=CARD_BG,
                anchor="w",
            ).pack(fill="x")

            ctk.CTkButton(
                row,
                text="Open Tool" if webview is not None else "Open in Browser",
                font=F(12, "bold"),
                fg_color=ACCENT,
                hover_color=TEXT_DARK,
                text_color="white",
                corner_radius=10,
                height=36,
                width=120,
                command=lambda p=path, t=title: self._open_program(p, t),
            ).pack(side="right")

    def _show_skills(self):
        """The sidebar's pinned 'Skills' entry — a dedicated list of the
        Claude Skills built for this office, mirroring how Apps lists
        every interactive tool. There's nothing to open in the launcher
        for a Skill (you just ask Claude in plain language), so this
        reads from the small SKILLS registry above instead of
        self.documents, and offers a download of the packaged .skill
        file for anyone who wants to add it to their own Claude/Cowork
        chat."""
        self._selected_path = "skills"
        self._clear_content()
        self._highlight_nav("skills")

        scroll = ctk.CTkScrollableFrame(
            self.content_frame, fg_color=BODY_BG, corner_radius=0,
            scrollbar_fg_color=BODY_BG, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=TEXT_MUTED,
        )
        scroll.pack(fill="both", expand=True, padx=32, pady=28)

        ctk.CTkLabel(
            scroll,
            text="Skills",
            font=F(19, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
        ).pack(anchor="w")
        ctk.CTkLabel(
            scroll,
            text="Things Claude already knows how to do for this office — just ask, no app to open.",
            font=F(12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).pack(anchor="w", pady=(2, 18))

        if not SKILLS:
            ctk.CTkLabel(
                scroll,
                text="No Skills added yet.",
                font=F(12),
                text_color=TEXT_MUTED,
                fg_color=BODY_BG,
            ).pack(anchor="w")
            return

        for skill in SKILLS:
            card = ctk.CTkFrame(scroll, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=BORDER)
            card.pack(fill="x", pady=8)

            inner = ctk.CTkFrame(card, fg_color=CARD_BG)
            inner.pack(fill="x", padx=18, pady=16)

            header_row = ctk.CTkFrame(inner, fg_color=CARD_BG)
            header_row.pack(fill="x")
            ctk.CTkLabel(
                header_row,
                text=skill["name"],
                font=F(14, "bold"),
                text_color=TEXT_DARK,
                fg_color=CARD_BG,
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

            skill_path = ASSETS_DIR / "skills" / skill["file"]
            ctk.CTkButton(
                header_row,
                text="Download",
                font=F(11, "bold"),
                fg_color=ACCENT,
                hover_color=TEXT_DARK,
                text_color="white",
                corner_radius=8,
                width=80,
                height=28,
                command=lambda p=skill_path: self._download_skill_file(p),
            ).pack(side="right")

            ctk.CTkLabel(
                inner,
                text=skill["description"],
                font=F(12),
                text_color=TEXT_MUTED,
                fg_color=CARD_BG,
                wraplength=560,
                justify="left",
            ).pack(anchor="w", pady=(10, 8))

            ctk.CTkButton(
                inner,
                text="See example prompts in Guides →",
                font=F(11, "bold"),
                fg_color="transparent",
                hover_color=TEXT_DARK,
                text_color=ACCENT,
                border_width=0,
                corner_radius=6,
                height=22,
                anchor="w",
                command=self._open_guides_page,
            ).pack(anchor="w")

    def _show_team(self):
        """Admin/Director only — reached from a button in Settings. The
        roster of everyone with access, read live from the shared
        database, so it's the same list on every computer and on the
        mobile site.

        Notably absent compared to the old file-backed version: showing
        or setting someone else's password. Passwords now live in
        Firebase Authentication, which stores them hashed and will not
        hand them back to anybody -- not to this app, not to a Director,
        not to Firebase's own console. That's the point of hashing. So
        instead of a Show/Change control that couldn't work, each person
        has "Send Reset Email", which mails them a link to set their
        own.

        Anything that changes data redraws via
        self.root.after(1, self._show_team) — deferred for the same
        reason documented on _sign_out/apply_and_rebuild: these buttons
        sit on cards a redraw would otherwise destroy synchronously out
        from under their own click handler."""
        self._selected_path = "team"
        self._clear_content()
        self._highlight_nav("team")

        scroll = ctk.CTkScrollableFrame(
            self.content_frame, fg_color=BODY_BG, corner_radius=0,
            scrollbar_fg_color=BODY_BG, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=TEXT_MUTED,
        )
        scroll.pack(fill="both", expand=True, padx=32, pady=28)

        # Team is only ever reached from Settings now (see _show_settings),
        # so "back" always means Settings specifically -- no need for a
        # general navigation history for just one page. Deferred for the
        # usual reason: this button's own click destroys the page it's on.
        ctk.CTkButton(
            scroll,
            text="← Back to Settings",
            font=F(11, "bold"),
            fg_color="transparent",
            hover_color=BORDER,
            text_color=ACCENT,
            border_width=0,
            corner_radius=6,
            height=26,
            anchor="w",
            command=lambda: self.root.after(1, self._show_settings),
        ).pack(anchor="w", pady=(0, 10))

        ctk.CTkLabel(
            scroll, text="Team", font=F(19, "bold"), text_color=TEXT_DARK, fg_color=BODY_BG
        ).pack(anchor="w")
        ctk.CTkLabel(
            scroll,
            text=(
                "Everyone with access, shared across every computer and the "
                "mobile site. Visible to Admin and Director."
            ),
            font=F(12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).pack(anchor="w", pady=(2, 18))

        # -------------------------------------------------- add person --
        add_card = ctk.CTkFrame(scroll, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=BORDER)
        add_card.pack(fill="x", pady=(0, 16))
        add_inner = ctk.CTkFrame(add_card, fg_color=CARD_BG)
        add_inner.pack(fill="x", padx=18, pady=16)

        ctk.CTkLabel(
            add_inner, text="Add or Update Person", font=F(13, "bold"), text_color=TEXT_DARK, fg_color=CARD_BG
        ).pack(anchor="w", pady=(0, 4))
        ctk.CTkLabel(
            add_inner,
            text=(
                "Sets someone's name and role. Their sign-in itself is created "
                "once in the Firebase console (Authentication → Add user); after "
                "that they use “Forgot password?” to choose their own password."
            ),
            font=F(11),
            text_color=TEXT_MUTED,
            fg_color=CARD_BG,
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        add_row = ctk.CTkFrame(add_inner, fg_color=CARD_BG)
        add_row.pack(fill="x")

        add_name_var = StringVar()
        add_email_var = StringVar()
        role_by_label = {v: k for k, v in ROLE_LABELS.items()}
        add_role_var = StringVar(value=ROLE_LABELS["staff"])
        add_status_var = StringVar()

        def field_group(label_text):
            group = ctk.CTkFrame(add_row, fg_color=CARD_BG)
            group.pack(side="left", padx=(0, 10))
            ctk.CTkLabel(
                group, text=label_text, font=F(10, "bold"), text_color=TEXT_MUTED, fg_color=CARD_BG, anchor="w"
            ).pack(anchor="w", pady=(0, 3))
            return group

        def add_field(label_text, var, placeholder, width):
            group = field_group(label_text)
            ctk.CTkEntry(
                group, textvariable=var, placeholder_text=placeholder, font=F(12),
                height=32, corner_radius=8, width=width, fg_color=BODY_BG,
                border_color=BORDER, text_color=TEXT_DARK, placeholder_text_color=TEXT_MUTED,
            ).pack()

        add_field("Name", add_name_var, "Full name", 170)
        add_field("Email", add_email_var, f"name@{ALLOWED_EMAIL_DOMAIN}", 210)

        role_group = field_group("Role")
        # CTkOptionMenu has no border_width/border_color of its own (unlike
        # CTkEntry), so it's wrapped in a thin bordered frame instead --
        # otherwise it's the one field in this row without an outline,
        # which is what looked inconsistent next to the entries beside it.
        role_wrap = ctk.CTkFrame(role_group, fg_color=BODY_BG, corner_radius=8, border_width=1, border_color=BORDER)
        role_wrap.pack()
        ctk.CTkOptionMenu(
            role_wrap,
            variable=add_role_var,
            values=[ROLE_LABELS[r] for r in ROLES],
            width=108,
            height=30,
            corner_radius=6,
            fg_color=BODY_BG,
            button_color=ACCENT,
            button_hover_color=TEXT_DARK,
            text_color=TEXT_DARK,
            dropdown_fg_color=CARD_BG,
            dropdown_text_color=TEXT_DARK,
            dropdown_hover_color=ACCENT_SOFT,
        ).pack(padx=1, pady=1)

        add_status_label = ctk.CTkLabel(
            add_inner, textvariable=add_status_var, font=F(11), text_color=TEXT_MUTED, fg_color=CARD_BG
        )

        def add_person():
            name = add_name_var.get().strip()
            email = add_email_var.get().strip().lower()
            role = role_by_label.get(add_role_var.get(), "staff")
            if not name or not email:
                add_status_var.set("Fill in both a name and an email.")
                add_status_label.configure(text_color="#c0392b")
                return
            if not email.endswith("@" + ALLOWED_EMAIL_DOMAIN):
                add_status_var.set(f"Email must be a @{ALLOWED_EMAIL_DOMAIN} address.")
                add_status_label.configure(text_color="#c0392b")
                return

            add_status_var.set("Saving…")
            add_status_label.configure(text_color=TEXT_MUTED)
            self._run_team_write(
                lambda token: firestore_save_profile(token, email, name, role),
                on_error=lambda message: (
                    add_status_var.set(message),
                    add_status_label.configure(text_color="#c0392b"),
                ),
            )

        ctk.CTkButton(
            add_inner,
            text="Save",
            font=F(12, "bold"),
            fg_color=ACCENT,
            hover_color=TEXT_DARK,
            text_color="white",
            corner_radius=8,
            height=32,
            command=add_person,
        ).pack(anchor="w", pady=(10, 4))
        add_status_label.pack(anchor="w")

        # ------------------------------------------------------ roster --
        # Fetched on a background thread so a slow connection doesn't
        # freeze the window; the placeholder is replaced once it lands.
        roster_holder = ctk.CTkFrame(scroll, fg_color=BODY_BG)
        roster_holder.pack(fill="x")
        loading_label = ctk.CTkLabel(
            roster_holder, text="Loading the team…", font=F(12), text_color=TEXT_MUTED, fg_color=BODY_BG
        )
        loading_label.pack(anchor="w")

        def render_roster(people):
            if not roster_holder.winfo_exists():
                return  # navigated away while the request was in flight
            loading_label.destroy()
            if not people:
                ctk.CTkLabel(
                    roster_holder,
                    text="Nobody has a profile yet — use Add or Update Person above.",
                    font=F(12),
                    text_color=TEXT_MUTED,
                    fg_color=BODY_BG,
                ).pack(anchor="w")
                return

            for person in people:
                card = ctk.CTkFrame(
                    roster_holder, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=BORDER
                )
                card.pack(fill="x", pady=8)
                inner = ctk.CTkFrame(card, fg_color=CARD_BG)
                inner.pack(fill="x", padx=18, pady=16)

                top_row = ctk.CTkFrame(inner, fg_color=CARD_BG)
                top_row.pack(fill="x")
                ctk.CTkLabel(
                    top_row, text=person["name"], font=F(14, "bold"),
                    text_color=TEXT_DARK, fg_color=CARD_BG, anchor="w",
                ).pack(side="left")
                badge = ctk.CTkFrame(top_row, fg_color=ACCENT_SOFT, corner_radius=6)
                badge.pack(side="left", padx=(10, 0))
                ctk.CTkLabel(
                    badge, text=ROLE_LABELS[person["role"]], font=F(10, "bold"),
                    text_color=ACCENT, fg_color=ACCENT_SOFT,
                ).pack(padx=8, pady=2)

                # Director rows stay non-removable, as before -- managing
                # peers wasn't asked for, and it prevents the last
                # Director accidentally removing their own access and
                # leaving nobody able to manage the team at all.
                if person["role"] != "director":
                    def remove_person(email=person["email"], name=person["name"]):
                        if not messagebox.askyesno(
                            WINDOW_TITLE,
                            f"Remove {name}'s access? They won't be able to sign in "
                            "on any computer or on the mobile site.",
                        ):
                            return
                        self._run_team_write(lambda token: firestore_delete_profile(token, email))

                    ctk.CTkButton(
                        top_row,
                        text="Remove Access",
                        font=F(11),
                        fg_color="transparent",
                        hover_color=BORDER,
                        text_color="#c0392b",
                        border_width=1,
                        border_color=BORDER,
                        corner_radius=8,
                        height=26,
                        command=remove_person,
                    ).pack(side="right")

                ctk.CTkLabel(
                    inner, text=person["email"], font=F(12), text_color=TEXT_MUTED, fg_color=CARD_BG
                ).pack(anchor="w", pady=(4, 10))

                actions = ctk.CTkFrame(inner, fg_color=CARD_BG)
                actions.pack(fill="x")

                # ---- password reset (no reveal -- see the docstring) --
                reset_status_var = StringVar()

                def send_reset(email=person["email"], status_var=reset_status_var):
                    status_var.set("Sending…")

                    def work():
                        try:
                            firebase_send_password_reset(email)
                        except FirebaseError as e:
                            write_error_log(f"(reset email failed for {email})\n{e}\n")
                            message = e.friendly
                            self.root.after(0, lambda: status_var.set(message))
                            return
                        self.root.after(0, lambda: status_var.set("Sent — they'll get an email."))

                    threading.Thread(target=work, daemon=True).start()

                ctk.CTkButton(
                    actions,
                    text="Send Reset Email",
                    font=F(11),
                    fg_color="transparent",
                    hover_color=BORDER,
                    text_color=ACCENT,
                    border_width=1,
                    border_color=BORDER,
                    corner_radius=6,
                    height=26,
                    command=send_reset,
                ).pack(side="left")

                ctk.CTkLabel(
                    actions, textvariable=reset_status_var, font=F(11),
                    text_color=TEXT_MUTED, fg_color=CARD_BG,
                ).pack(side="left", padx=(10, 0))

                # ---- promote / demote (staff <-> admin only) --
                if person["role"] in ("staff", "admin"):
                    def toggle_role(email=person["email"], name=person["name"], current_role=person["role"]):
                        new_role = "admin" if current_role == "staff" else "staff"
                        self._run_team_write(
                            lambda token: firestore_save_profile(token, email, name, new_role)
                        )

                    ctk.CTkButton(
                        inner,
                        text=("Promote to Admin" if person["role"] == "staff" else "Demote to Staff"),
                        font=F(11, "bold"),
                        fg_color="transparent",
                        hover_color=TEXT_DARK,
                        text_color=ACCENT,
                        border_width=0,
                        corner_radius=6,
                        height=24,
                        anchor="w",
                        command=toggle_role,
                    ).pack(anchor="w", pady=(10, 0))

        def load_roster():
            try:
                people = firestore_list_profiles(self.id_token)
            except FirebaseError as e:
                write_error_log(f"(couldn't load the team roster)\n{e}\n")
                message = e.friendly
                self.root.after(0, lambda: (
                    loading_label.winfo_exists()
                    and loading_label.configure(text=message, text_color="#c0392b")
                ))
                return
            self.root.after(0, lambda: render_roster(people))

        threading.Thread(target=load_roster, daemon=True).start()

    def _run_team_write(self, action, on_error=None):
        """Runs a Team-page write (add/update/remove) against the shared
        database off the UI thread, then redraws the page so everyone
        sees the result. firestore.rules enforces Admin/Director on the
        server side too, so a permissions error here is reported rather
        than assumed impossible."""
        token = getattr(self, "id_token", "")
        if not token:
            return

        def work():
            try:
                action(token)
            except FirebaseError as e:
                write_error_log(f"(team change failed)\n{e}\n")
                message = e.friendly
                if on_error is not None:
                    self.root.after(0, lambda: on_error(message))
                else:
                    self.root.after(0, lambda: messagebox.showerror(WINDOW_TITLE, message))
                return
            except Exception:
                write_error_log(f"(unexpected team change error)\n{traceback.format_exc()}")
                self.root.after(0, lambda: messagebox.showerror(
                    WINDOW_TITLE, "Something went wrong. Details in error_log.txt."
                ))
                return
            self.root.after(1, self._show_team)

        threading.Thread(target=work, daemon=True).start()

    def _show_settings(self):
        """Personal display preferences. If you're logged in as a real
        person, these are saved
        to your own account in users.json, so they follow you to any
        computer running this app instead of staying behind on this one
        — see PERSONAL_SETTING_KEYS and attempt_login. Emergency shared
        logins still fall back to settings.json next to html/ and
        assets/. Every change here applies immediately (no Save button)
        and triggers a full UI rebuild — see _rebuild_ui — since
        CustomTkinter widgets don't pick up new colors/fonts on their
        own once built."""
        self._selected_path = "settings"
        self._clear_content()
        self._highlight_nav("settings")

        scroll = ctk.CTkScrollableFrame(
            self.content_frame, fg_color=BODY_BG, corner_radius=0,
            scrollbar_fg_color=BODY_BG, scrollbar_button_color=BORDER,
            scrollbar_button_hover_color=TEXT_MUTED,
        )
        scroll.pack(fill="both", expand=True, padx=32, pady=28)

        ctk.CTkLabel(
            scroll, text="Settings", font=F(19, "bold"), text_color=TEXT_DARK, fg_color=BODY_BG
        ).pack(anchor="w")
        ctk.CTkLabel(
            scroll,
            text=(
                "Saved to your account — follows you wherever you log in."
                if self.current_user is not None
                else "Personal display preferences, saved on this computer."
            ),
            font=F(12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).pack(anchor="w", pady=(2, 22))

        def section(heading, subtext=None):
            ctk.CTkLabel(
                scroll, text=heading, font=F(13, "bold"), text_color=TEXT_DARK, fg_color=BODY_BG
            ).pack(anchor="w", pady=(18, 2))
            if subtext:
                ctk.CTkLabel(
                    scroll,
                    text=subtext,
                    font=F(11),
                    text_color=TEXT_MUTED,
                    fg_color=BODY_BG,
                    wraplength=560,
                    justify="left",
                ).pack(anchor="w")

        def apply_and_rebuild(key, value):
            self.settings[key] = value
            save_settings(self.settings)
            if key in PERSONAL_SETTING_KEYS:
                # This choice belongs to the person, not the computer,
                # so it goes up to their row in the shared database and
                # follows them to any other machine or the mobile site.
                self._sync_shared_preferences()
            if key == "theme":
                apply_theme(value)
            elif key == "font_scale":
                apply_font_scale(value)
            elif key == "remember_username" and not value:
                self.settings["last_username"] = ""
                save_settings(self.settings)
            # Deferred to the next idle tick rather than called directly:
            # _rebuild_ui() destroys the entire sidebar + content pane,
            # including the very button whose click got us here. Tearing
            # that down synchronously from inside the button's own click
            # handler is a classic Tk hazard -- CTkButton still has
            # post-click bookkeeping to do on itself once this callback
            # returns, and that blows up if it (and everything around it)
            # is already gone, which was exactly what made Eye Comfort
            # (and presumably Dark too) look like a frozen black screen.
            self.root.after(1, self._rebuild_ui)

        section(
            "Appearance",
            "Choose a color theme, or follow your system's setting. The sidebar "
            "stays navy in every theme — only the main pages change.",
        )
        self._settings_choice_row(
            scroll,
            [(k, THEME_LABELS[k]) for k in ("light", "dark", "eye_comfort", "system")],
            self.settings.get("theme", "light"),
            lambda v: apply_and_rebuild("theme", v),
        )

        section("Text Size", "Scales text and buttons throughout the app.")
        self._settings_choice_row(
            scroll,
            [(k, FONT_SCALE_LABELS[k]) for k in ("small", "normal", "large", "xlarge")],
            self.settings.get("font_scale", "normal"),
            lambda v: apply_and_rebuild("font_scale", v),
        )

        section("Startup Page", "Which page shows right after you log in.")
        self._settings_choice_row(
            scroll,
            [("home", "Home"), ("apps", "Apps")],
            self.settings.get("default_page", "home"),
            lambda v: apply_and_rebuild("default_page", v),
        )

        section("Login", "Whether your username is remembered for next time — never your password.")
        self._settings_choice_row(
            scroll,
            [(True, "Remember my username"), (False, "Don't remember")],
            self.settings.get("remember_username", True),
            lambda v: apply_and_rebuild("remember_username", v),
        )

        if self.current_user is not None:
            # Self-service password change, available to every real
            # named account regardless of role — Staff included, not
            # just Admin/Director. Previously the only way to change a
            # password was Admin/Director doing it for you from the Team
            # page; this lets anyone handle their own. Deliberately not
            # (self.current_user is None for those) — those shared
            # passwords are only touched via "Reset to Defaults" or by
            # editing settings.json directly.
            section(
                "Password",
                "Change your own sign-in password. The new one works "
                "everywhere immediately -- this app, the phone site, and "
                "every tool inside them.",
            )
            pw_card = ctk.CTkFrame(scroll, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=BORDER)
            pw_card.pack(fill="x", pady=(6, 0))
            pw_inner = ctk.CTkFrame(pw_card, fg_color=CARD_BG)
            pw_inner.pack(fill="x", padx=18, pady=16)

            pw_row = ctk.CTkFrame(pw_inner, fg_color=CARD_BG)
            pw_row.pack(fill="x")

            current_pw_var = StringVar()
            new_pw_var = StringVar()
            confirm_pw_var = StringVar()
            pw_status_var = StringVar()

            def pw_field(label_text, var, placeholder):
                group = ctk.CTkFrame(pw_row, fg_color=CARD_BG)
                group.pack(side="left", padx=(0, 10))
                ctk.CTkLabel(
                    group, text=label_text, font=F(10, "bold"), text_color=TEXT_MUTED,
                    fg_color=CARD_BG, anchor="w",
                ).pack(anchor="w", pady=(0, 3))
                ctk.CTkEntry(
                    group, textvariable=var, placeholder_text=placeholder, font=F(12),
                    height=32, corner_radius=8, width=150, fg_color=BODY_BG,
                    border_color=BORDER, text_color=TEXT_DARK, placeholder_text_color=TEXT_MUTED,
                    show="•",
                ).pack()

            pw_field("Current Password", current_pw_var, "Current password")
            pw_field("New Password", new_pw_var, "New password")
            pw_field("Confirm New Password", confirm_pw_var, "Confirm new password")

            pw_status_label = ctk.CTkLabel(
                pw_inner, textvariable=pw_status_var, font=F(11), text_color=TEXT_MUTED, fg_color=CARD_BG
            )

            def change_own_password():
                current_pw = current_pw_var.get()
                new_pw = new_pw_var.get()
                confirm_pw = confirm_pw_var.get()

                if not current_pw:
                    pw_status_var.set("Enter your current password.")
                    pw_status_label.configure(text_color="#c0392b")
                    return
                if len(new_pw) < 6:
                    pw_status_var.set("New password must be at least 6 characters.")
                    pw_status_label.configure(text_color="#c0392b")
                    return
                if new_pw != confirm_pw:
                    pw_status_var.set("New password and confirmation don't match.")
                    pw_status_label.configure(text_color="#c0392b")
                    return

                pw_status_var.set("Changing…")
                pw_status_label.configure(text_color=TEXT_MUTED)

                def work():
                    """Re-signs in with the current password first. That's
                    what verifies the person typing actually knows it --
                    the app can't compare it to a stored copy, because
                    passwords live hashed in Firebase and nothing here
                    ever holds one. It also refreshes the token, since
                    Firebase requires a recent sign-in before allowing a
                    password change."""
                    try:
                        session = firebase_sign_in(self.current_user["email"], current_pw)
                    except FirebaseError:
                        self.root.after(0, lambda: (
                            pw_status_var.set("Current password is incorrect."),
                            pw_status_label.configure(text_color="#c0392b"),
                        ))
                        return
                    try:
                        new_token = firebase_change_own_password(session["idToken"], new_pw)
                    except FirebaseError as e:
                        write_error_log(f"(password change failed)\n{e}\n")
                        message = e.friendly
                        self.root.after(0, lambda: (
                            pw_status_var.set(message),
                            pw_status_label.configure(text_color="#c0392b"),
                        ))
                        return

                    def done():
                        self.id_token = new_token
                        current_pw_var.set("")
                        new_pw_var.set("")
                        confirm_pw_var.set("")
                        pw_status_var.set("Password changed. Use it everywhere, including the mobile site.")
                        pw_status_label.configure(text_color=TEXT_MUTED)

                    self.root.after(0, done)

                threading.Thread(target=work, daemon=True).start()

            ctk.CTkButton(
                pw_inner,
                text="Change Password",
                font=F(12, "bold"),
                fg_color=ACCENT,
                hover_color=TEXT_DARK,
                text_color="white",
                corner_radius=8,
                height=32,
                command=change_own_password,
            ).pack(anchor="w", pady=(10, 4))
            pw_status_label.pack(anchor="w")

        if self.true_role in ("admin", "director"):
            # Gated on true_role, not user_role -- this section has to
            # stay visible even after switching to a lower view, or
            # there'd be no way back to your own role short of signing
            # out and back in.
            section(
                "View As",
                "Preview the app the way a lower-access role sees it — "
                "nothing about your own access changes, and this resets "
                "automatically when you sign out.",
            )
            view_as_options = [(self.true_role, f"{ROLE_LABELS[self.true_role]} (Me)")]
            if self.true_role == "director":
                view_as_options.append(("admin", "Admin"))
            view_as_options.append(("staff", "Staff"))

            def set_view_as(role):
                self.user_role = role
                # Same deferral as apply_and_rebuild above -- _rebuild_ui
                # tears down this very button's ancestors.
                self.root.after(1, self._rebuild_ui)

            self._settings_choice_row(scroll, view_as_options, self.user_role, set_view_as)

        if self.user_role in ("admin", "director"):
            section(
                "Team",
                "See everyone with access, reveal or change anyone's "
                "password, promote/demote, or remove access.",
            )
            team_button_kwargs = dict(
                text="Open Team",
                font=F(12, "bold"),
                fg_color=ACCENT,
                hover_color=TEXT_DARK,
                text_color="white",
                corner_radius=8,
                height=36,
                # Deferred to the next idle tick -- same fix as
                # apply_and_rebuild above and _sign_out: _show_team()
                # destroys this whole page, including the very button
                # whose click got us here.
                command=lambda: self.root.after(1, self._show_team),
            )
            if self._team_icon is not None:
                team_button_kwargs["image"] = self._team_icon
                team_button_kwargs["compound"] = "left"
            ctk.CTkButton(scroll, **team_button_kwargs).pack(anchor="w", pady=(6, 0))

        reset_row = ctk.CTkFrame(scroll, fg_color=BODY_BG)
        reset_row.pack(anchor="w", pady=(30, 0))
        ctk.CTkButton(
            reset_row,
            text="Reset to Defaults",
            font=F(12, "bold"),
            fg_color="transparent",
            hover_color=BORDER,
            text_color=TEXT_MUTED,
            border_width=1,
            border_color=BORDER,
            corner_radius=8,
            height=34,
            command=self._reset_settings,
        ).pack(anchor="w")

    def _settings_choice_row(self, parent, options, current_value, on_select):
        """One row of segmented-style buttons for a single setting — the
        option matching current_value is filled in accent color, the
        rest are outlined. `options` is a list of (value, label) pairs;
        `on_select(value)` runs when a non-active option is clicked."""
        row = ctk.CTkFrame(parent, fg_color=BODY_BG)
        row.pack(anchor="w", pady=(6, 0))
        for value, label in options:
            active = value == current_value
            ctk.CTkButton(
                row,
                text=label,
                font=F(12, "bold" if active else None),
                fg_color=ACCENT if active else CARD_BG,
                hover_color=TEXT_DARK if active else BORDER,
                text_color="white" if active else TEXT_DARK,
                border_width=0 if active else 1,
                border_color=BORDER,
                corner_radius=8,
                height=34,
                command=lambda v=value: on_select(v),
            ).pack(side="left", padx=(0, 8), pady=(0, 8))

    def _reset_settings(self):
        """Restores every display preference to its default — except the
        remembered username, which isn't really a "display" preference
        and shouldn't quietly disappear just because someone reset the
        theme back to Light.

        Login passwords are handled the same way, but simpler: "Reset to
        Defaults" is for display preferences only and is visible to
        everyone (including Staff), so it never touches the emergency
        shared admin/staff/director passwords, no matter who clicks it.
        Real people's individual passwords live in users.json, which
        this doesn't touch at all — that's managed entirely from the
        Team page."""
        keep_username = self.settings.get("last_username", "")
        self.settings = dict(DEFAULT_SETTINGS)
        self.settings["last_username"] = keep_username
        save_settings(self.settings)
        # Push the restored defaults up to this person's row in the
        # shared database too, rather than the reset appearing to work
        # here and then silently reverting the next time they sign in
        # on this or any other computer.
        self._sync_shared_preferences()
        apply_theme(self.settings["theme"])
        apply_font_scale(self.settings["font_scale"])
        self._sidebar_expanded = self.settings["sidebar_expanded"]
        # See the comment in _show_settings's apply_and_rebuild — deferred
        # for the same reason: this button (and everything around it) is
        # about to be destroyed by _rebuild_ui, which must not happen
        # synchronously inside its own click handler.
        self.root.after(1, self._rebuild_ui)

    def _resolve_local_download_path(self, url: str, base_dir: Path):
        """If a clicked link inside a guide points at a local, downloadable
        file (currently: anything under assets/skills/), resolve it to a
        real filesystem Path. Returns None for ordinary page links (http,
        https, or any other local file), which should navigate normally."""
        try:
            parsed = urllib.parse.urlparse(url)
        except Exception:
            return None
        if parsed.scheme not in ("", "file"):
            return None

        raw_path = urllib.parse.unquote(parsed.path or url)
        candidate = Path(raw_path)
        if not candidate.is_absolute():
            candidate = (base_dir / candidate).resolve()

        if candidate.suffix.lower() in (".skill",) and candidate.exists():
            return candidate
        return None

    def _download_skill_file(self, source_path: Path):
        """Saves a packaged .skill file to a location the user picks, with
        a brief animated "Downloading..." popup for feedback. Used instead
        of a plain HTML download link: tkinterweb has no real download
        mechanism, so clicking a link straight to the file just rendered
        its raw zip bytes as garbled text instead of saving anything."""
        dest = filedialog.asksaveasfilename(
            title="Save Skill",
            initialfile=source_path.name,
            defaultextension=".skill",
            filetypes=[("Claude Skill", "*.skill"), ("All files", "*.*")],
        )
        if not dest:
            return

        popup = ctk.CTkToplevel(self.root)
        popup.title("Downloading")
        popup.geometry("280x120")
        popup.resizable(False, False)
        popup.configure(fg_color=WHITE_BACKDROP)
        popup.transient(self.root)
        popup.grab_set()

        ctk.CTkLabel(
            popup,
            text=f"Downloading {source_path.name}…",
            font=F(12, "bold"),
            text_color=LOGIN_TEXT,
            fg_color=WHITE_BACKDROP,
            wraplength=240,
            justify="center",
        ).pack(pady=(26, 14))
        bar = ctk.CTkProgressBar(
            popup, mode="indeterminate", width=200, progress_color=ACCENT, fg_color=LOGIN_ACCENT_SOFT
        )
        bar.pack()
        bar.start()

        def finish():
            bar.stop()
            try:
                shutil.copyfile(source_path, dest)
            except Exception as exc:
                popup.destroy()
                messagebox.showerror(WINDOW_TITLE, f"Couldn't save the file:\n{exc}")
                return
            popup.destroy()
            messagebox.showinfo(WINDOW_TITLE, f"Saved to:\n{dest}")

        popup.after(650, finish)

    # ------------------------------------------------ native guide render --
    def _guide_open_link(self, href: str, base_dir: Path):
        """Shared link-click handler for natively-rendered guide content.
        Mirrors what tkinterweb's on_link_click used to do: local .skill
        files get the native Save-As + download animation treatment (see
        _download_skill_file), http(s) links open normally, and any other
        relative link is resolved against the guide's own folder and
        opened externally if it exists. mailto: links are special-cased
        to open a Gmail compose window in the browser instead of
        webbrowser.open()'s normal behavior of handing off to whatever
        the OS's default mail app is -- every address in this app is a
        real @thecentercc.com Google Workspace account, so Gmail is
        almost always what's actually wanted."""
        if not href:
            return
        if href.startswith("mailto:"):
            address = href[len("mailto:"):].split("?", 1)[0].strip()
            if address:
                webbrowser.open(
                    "https://mail.google.com/mail/?view=cm&fs=1&to=" + urllib.parse.quote(address)
                )
            return
        if href.startswith("http://") or href.startswith("https://"):
            webbrowser.open(href)
            return
        skill_path = self._resolve_local_download_path(href, base_dir)
        if skill_path is not None:
            self._download_skill_file(skill_path)
            return
        try:
            parsed = urllib.parse.urlparse(href)
            raw_path = urllib.parse.unquote(parsed.path or href)
            candidate = Path(raw_path)
            if not candidate.is_absolute():
                candidate = (base_dir / candidate).resolve()
            if candidate.exists():
                webbrowser.open(candidate.as_uri())
        except Exception:
            pass

    def _build_rich_text(self, parent, runs, base_dir: Path, font_size=12, base_color=None, bg_color=None, width_chars=None):
        """Renders a list of (text, styleset, href) runs as one flowing,
        read-only paragraph able to mix bold/link/placeholder styling
        inline -- e.g. "...guessing. Download Skill" or "Brad Boyles —
        Brad@thecentercc.com" -- which a plain CTkLabel can't do, since a
        label only ever draws one font/color for its whole text. Backed
        by a bare tkinter.Text widget (CTk has no rich-text widget of its
        own), styled to sit invisibly among the CTk widgets around it and
        auto-sized to its wrapped line count so it behaves like a normal
        paragraph rather than a fixed-size box.

        width_chars is left unset (None) for normal paragraph flow --
        those are packed with fill="x", which stretches/shrinks a Text
        widget to its parent's actual width regardless of the widget's
        own naturally-requested size. Table cells (see
        _render_guide_table) pass an explicit width_chars instead, since
        those live in a grid layout, where an unset width lets a Text
        widget's ~80-character default request blow the column out far
        wider than intended."""
        bg_color = bg_color or BODY_BG
        base_color = base_color or TEXT_MUTED

        text_kwargs = dict(
            wrap="word", background=bg_color, foreground=base_color,
            borderwidth=0, highlightthickness=0, font=F(font_size), padx=0, pady=0,
            # "xterm" is Tk's cross-platform I-beam cursor -- signals this
            # text can be selected/copied, the same way it would on a
            # webpage. Individual links override this to a hand cursor
            # on hover (see the tag_bind calls below).
            cursor="xterm", takefocus=0, height=1,
        )
        if width_chars is not None:
            text_kwargs["width"] = width_chars
        widget = tk.Text(parent, **text_kwargs)
        widget.tag_configure("bold", font=F(font_size, "bold"), foreground=TEXT_DARK)
        widget.tag_configure("italic", font=(FONT_FAMILY, F(font_size)[1], "italic"))
        widget.tag_configure(
            "code", font=(CODE_FONT_FAMILY, F(font_size)[1]), foreground=TEXT_DARK,
            background=BORDER,
        )
        widget.tag_configure("fill", foreground="#b45309")
        widget.tag_configure("link", foreground=ACCENT, underline=True)

        has_link = False
        for text, styleset, href in runs:
            tags = [s for s in ("bold", "italic", "code", "fill") if s in styleset]
            if href:
                tags.append("link")
                tags.append(f"href::{href}")
                has_link = True
            widget.insert("end", text, tuple(tags))

        if has_link:
            def on_click(event):
                index = widget.index(f"@{event.x},{event.y}")
                for name in widget.tag_names(index):
                    if name.startswith("href::"):
                        self._guide_open_link(name[len("href::"):], base_dir)
                        return

            hand_cursor = "pointinghand" if sys.platform == "darwin" else "hand2"
            widget.tag_bind("link", "<Button-1>", on_click)
            widget.tag_bind("link", "<Enter>", lambda e: widget.configure(cursor=hand_cursor))
            widget.tag_bind("link", "<Leave>", lambda e: widget.configure(cursor="xterm"))

        make_text_readonly(widget)
        widget.pack(fill="x", anchor="w")

        def resize(event=None):
            # Bound to <Configure> and then changes the widget's height,
            # which raises <Configure> again -- so this re-enters unless
            # it stops itself. Writing the same height back still counts
            # as a change to Tk on Windows, which turned every reflow
            # into a burst of redraws and made the text blocks visibly
            # jitter. Only touch the widget when the answer differs.
            try:
                counted = widget.count("1.0", "end", "displaylines")
                lines = max(1, counted[0] if counted else 1)
                if getattr(widget, "_last_line_count", None) == lines:
                    return
                widget._last_line_count = lines
                widget.configure(height=lines)
            except Exception:
                pass

        widget.bind("<Configure>", resize)
        widget.after(30, resize)
        return widget

    def _render_guide_table(self, parent, rows, base_dir: Path):
        """Renders each cell through _build_rich_text instead of a plain
        CTkLabel, so a link inside a table cell (e.g. a Contacts email)
        is actually clickable, selectable, and copyable -- the same as
        link/body text anywhere else in a guide. Plain CTkLabel discarded
        the href entirely, which is why table links never worked."""
        if not rows:
            return
        col_count = max((len(cells) for _is_header, cells in rows), default=0)
        if col_count == 0:
            return

        table_card = ctk.CTkFrame(parent, fg_color=CARD_BG, corner_radius=10, border_width=1, border_color=BORDER)
        table_card.pack(fill="x", pady=(8, 12))
        for col in range(col_count):
            table_card.grid_columnconfigure(col, weight=1, uniform="guide_table_col")

        for row_idx, (is_header, cells) in enumerate(rows):
            row_bg = ACCENT_SOFT if is_header else CARD_BG
            for col_idx in range(col_count):
                cell_runs = cells[col_idx] if col_idx < len(cells) else []
                cell_frame = ctk.CTkFrame(table_card, fg_color=row_bg)
                cell_frame.grid(row=row_idx, column=col_idx, sticky="nsew", padx=12, pady=8)
                if any(t.strip() for t, _s, _h in cell_runs):
                    if is_header:
                        # Header rows read as headers regardless of
                        # whether the source table actually wrapped them
                        # in <b> -- _build_rich_text's "bold" tag is
                        # otherwise only driven by the source markup.
                        cell_runs = [(t, s | {"bold"}, h) for t, s, h in cell_runs]
                    self._build_rich_text(
                        cell_frame, cell_runs, base_dir, font_size=12,
                        base_color=(TEXT_DARK if is_header else TEXT_MUTED), bg_color=row_bg,
                        # Explicit narrow width -- see _build_rich_text's
                        # docstring on why this matters inside a grid
                        # layout specifically. Roughly matches the old
                        # wraplength=200 (in px) this replaced.
                        width_chars=24,
                    )
                else:
                    ctk.CTkLabel(
                        cell_frame, text="—", font=F(12), text_color=TEXT_MUTED,
                        fg_color=row_bg, anchor="w",
                    ).pack(anchor="w")

    def _render_guide_blocks(self, parent, blocks: list, base_dir: Path):
        """Draws parsed guide blocks (see _GuideHTMLParser) using the same
        native CTk widgets and theme-variable colors Home/Apps use, so
        guide pages get identical rendering quality and, as a bonus,
        finally follow the Light/Dark/Eye Comfort theme instead of a
        guide's own hardcoded CSS colors."""
        for block in blocks:
            kind = block["type"]
            if kind == "h1":
                ctk.CTkLabel(
                    parent, text=block["text"], font=F(19, "bold"), text_color=TEXT_DARK,
                    fg_color=BODY_BG, wraplength=640, justify="left",
                ).pack(anchor="w", pady=(0, 16))
            elif kind == "h2":
                wrap = ctk.CTkFrame(parent, fg_color=BODY_BG)
                wrap.pack(fill="x", anchor="w", pady=(24, 8))
                ctk.CTkLabel(
                    wrap, text=block["text"], font=F(14, "bold"), text_color=TEXT_DARK, fg_color=BODY_BG,
                ).pack(anchor="w")
                ctk.CTkFrame(wrap, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x", pady=(6, 0))
            elif kind == "h3":
                ctk.CTkLabel(
                    parent, text=block["text"], font=F(12, "bold"), text_color=TEXT_DARK, fg_color=BODY_BG,
                    wraplength=640, justify="left",
                ).pack(anchor="w", pady=(14, 4))
            elif kind == "p":
                self._build_rich_text(parent, block["runs"], base_dir, font_size=12, base_color=TEXT_MUTED, bg_color=BODY_BG)
            elif kind == "ul":
                for item_runs in block["items"]:
                    row = ctk.CTkFrame(parent, fg_color=BODY_BG)
                    row.pack(fill="x", anchor="w")
                    ctk.CTkLabel(
                        row, text="•", font=F(12), text_color=TEXT_MUTED, fg_color=BODY_BG, width=16,
                    ).pack(side="left", anchor="n")
                    bullet_body = ctk.CTkFrame(row, fg_color=BODY_BG)
                    bullet_body.pack(side="left", fill="x", expand=True)
                    self._build_rich_text(bullet_body, item_runs, base_dir, font_size=12, base_color=TEXT_MUTED, bg_color=BODY_BG)
            elif kind == "dl":
                for term_runs, desc_runs in block["items"]:
                    term_text = "".join(t for t, _s, _h in term_runs).strip()
                    ctk.CTkLabel(
                        parent, text=term_text, font=F(12, "bold"), text_color=TEXT_DARK, fg_color=BODY_BG,
                        wraplength=640, justify="left",
                    ).pack(anchor="w", pady=(14, 2))
                    desc_wrap = ctk.CTkFrame(parent, fg_color=BODY_BG)
                    desc_wrap.pack(fill="x", anchor="w")
                    self._build_rich_text(desc_wrap, desc_runs, base_dir, font_size=12, base_color=TEXT_MUTED, bg_color=BODY_BG)
            elif kind == "table":
                self._render_guide_table(parent, block["rows"], base_dir)
            elif kind == "note":
                note_card = ctk.CTkFrame(parent, fg_color=ACCENT_SOFT, corner_radius=10)
                note_card.pack(fill="x", pady=(16, 4))
                note_inner = ctk.CTkFrame(note_card, fg_color=ACCENT_SOFT)
                note_inner.pack(fill="x", padx=14, pady=12)
                self._build_rich_text(note_inner, block["runs"], base_dir, font_size=11, base_color=TEXT_DARK, bg_color=ACCENT_SOFT)

    def _edit_page_file(self, path: Path):
        """Admin-only: opens a guide's underlying .html file in a plain
        text editor, so wording can be tweaked without needing git or
        Terminal. This deliberately doesn't try to be a rich in-app
        editor -- it just hands the real file to a real text editor.
        Guide content is read from disk fresh every time a page opens,
        so saved changes show up as soon as the page is reopened or
        Refresh is clicked."""
        if not path.exists():
            messagebox.showerror(
                WINDOW_TITLE,
                f"Couldn't find this page's file on disk:\n{path}\n\n"
                "It may have been moved or renamed. Click Refresh (bottom "
                "of the sidebar) and try again.",
            )
            return
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-a", "TextEdit", str(path)])
            elif sys.platform.startswith("win"):
                subprocess.Popen(["notepad.exe", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            messagebox.showinfo(
                WINDOW_TITLE,
                f"Opened {path.name} in a text editor.\n\n"
                "Save your changes there, then come back and click "
                "Refresh (bottom of the sidebar) to see them.",
            )
        except Exception:
            messagebox.showerror(
                WINDOW_TITLE,
                f"Couldn't open a text editor for this file.\n\nYou can edit it directly at:\n{path}",
            )

    def _show_guide(self, title: str, path: Path):
        self._clear_content()
        header_buttons = [("Open in Browser ↗", lambda: webbrowser.open(path.resolve().as_uri()))]
        if self.user_role in ("admin", "director"):
            header_buttons.append(("Edit This Page ✎", lambda: self._edit_page_file(path)))
        self._content_header(title, extra_buttons=header_buttons)

        # Guides render natively (same CTk widgets/theme colors as
        # Home/Apps) instead of through tkinterweb, which isn't
        # Retina-aware the way CustomTkinter's own widgets are -- that
        # mismatch is what made guide pages look visibly softer than
        # Home/Apps. Falls back to the old tkinterweb viewer (or a plain
        # message) only if native parsing/rendering hits something it
        # can't handle, so an unexpected guide still displays somehow.
        scroll = None
        try:
            source = path.read_text(encoding="utf-8", errors="ignore")
            blocks = _GuideHTMLParser.parse(source)
            if not blocks:
                raise ValueError("no renderable content found")
            scroll = ctk.CTkScrollableFrame(
                self.content_frame, fg_color=BODY_BG, corner_radius=0,
                scrollbar_fg_color=BODY_BG, scrollbar_button_color=BORDER,
                scrollbar_button_hover_color=TEXT_MUTED,
            )
            scroll.pack(fill="both", expand=True, padx=32, pady=(0, 20))
            self._render_guide_blocks(scroll, blocks, path.parent)
            return
        except Exception:
            write_error_log(f"(guide native-render fallback for {path})\n{traceback.format_exc()}")
            if scroll is not None:
                try:
                    scroll.destroy()
                except Exception:
                    pass

        viewer_card = ctk.CTkFrame(self.content_frame, fg_color=CARD_BG, corner_radius=14)
        viewer_card.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        try:
            html_view = None

            def handle_link_click(url):
                skill_path = self._resolve_local_download_path(url, path.parent)
                if skill_path is not None:
                    self._download_skill_file(skill_path)
                    return
                html_view.load_url(url)

            html_view = HtmlFrame(viewer_card, messages_enabled=False, on_link_click=handle_link_click)
            html_view.pack(fill="both", expand=True, padx=1, pady=1)
            html_view.load_file(str(path))
        except Exception:
            ctk.CTkLabel(
                viewer_card,
                text="This document couldn't be displayed in the app.\nUse \"Open in Browser\" above instead.",
                font=F(12),
                text_color=TEXT_MUTED,
                fg_color=CARD_BG,
                justify="center",
            ).pack(expand=True)

    def _show_browser_fallback_card(self, title: str, path: Path):
        """Used when tkinterweb isn't installed at all — the document has
        already been opened in the browser; this just confirms that in
        the content pane instead of leaving it blank."""
        self._clear_content()
        self._content_header(title)
        wrap = ctk.CTkFrame(self.content_frame, fg_color=BODY_BG)
        wrap.place(relx=0.5, rely=0.42, anchor="center")
        ctk.CTkLabel(
            wrap,
            text="Opened in your default browser.",
            font=F(12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).pack()
        ctk.CTkButton(
            wrap,
            text="Open Again",
            font=F(12, "bold"),
            fg_color=ACCENT,
            hover_color=TEXT_DARK,
            text_color="white",
            corner_radius=10,
            height=38,
            command=lambda: webbrowser.open(path.resolve().as_uri()),
        ).pack(pady=(12, 0))

    def _show_program_card(self, title: str, path: Path):
        self._clear_content()
        self._content_header(title)

        wrap = ctk.CTkFrame(self.content_frame, fg_color=BODY_BG)
        wrap.place(relx=0.5, rely=0.42, anchor="center")

        ctk.CTkLabel(
            wrap,
            text=title,
            font=F(16, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
        ).pack()
        button_word = "tool window" if webview is not None else "your browser"
        ctk.CTkLabel(
            wrap,
            text=f"This is an interactive tool that needs a real browser\nengine to run — it opens in its own {button_word}.",
            font=F(12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
            justify="center",
        ).pack(pady=(6, 16))
        ctk.CTkButton(
            wrap,
            text="Open Tool" if webview is not None else "Open in Browser",
            font=F(13, "bold"),
            fg_color=ACCENT,
            hover_color=TEXT_DARK,
            text_color="white",
            corner_radius=10,
            height=40,
            width=160,
            command=lambda: self._open_program(path, title),
        ).pack()

    def _sign_out(self):
        """Tears down the whole app UI and drops back to the login screen
        -- the same teardown _rebuild_ui uses after a Settings change
        (destroy everything under root, clean up the scroll bindings that
        would otherwise leak, reset the white backdrop), just landing on
        the login screen instead of rebuilding the signed-in layout.
        Replaces the old 'How to Use This Launcher' button, which just
        popped up a plain text messagebox of navigation tips."""
        self.user_role = None
        self.true_role = None
        self.current_user = None
        # Drop the session tokens too, so a tool opened after signing out
        # (or after someone else signs in) can't still be handed the
        # previous person's access. Tool windows already open keep
        # working until they're closed -- they're separate programs with
        # their own copy -- which is the same as any other app leaving an
        # already-open window alone.
        self.id_token = ""
        self.refresh_token = ""
        self._selected_path = None
        self._last_search_query = ""
        # These are all long-lived references to this session's sidebar
        # widgets (self.home_button etc., and every entry in
        # self._nav_buttons). Destroying the widgets below doesn't clear
        # the Python attributes still pointing at them -- without this,
        # _highlight_nav() ran on the next Sign In using these stale
        # references before the freshly-rebuilt sidebar's real buttons
        # were assigned, and .configure() on an already-destroyed widget
        # raises _tkinter.TclError: invalid command name "...!ctkbutton"
        # (see error_log.txt). _highlight_nav() now also guards against
        # this defensively, but clearing the references here is the
        # actual fix -- there's nothing stale left to hit.
        self.home_button = None
        self.apps_button = None
        self.skills_button = None
        self.settings_button = None
        self._nav_buttons = {}
        for widget in self.root.winfo_children():
            widget.destroy()
        self._reset_stale_scroll_bindings(rearm_nav=False)
        self.root.configure(fg_color=WHITE_BACKDROP)
        self._show_login_screen()


def run_webview_window(file_path: str, title: str):
    """Runs a single interactive tool in its own pywebview window.

    This is invoked as a fresh, separate process (see
    LauncherApp._open_program) rather than from inside the main Tkinter
    app, because pywebview needs to run its own event loop on the main
    thread — the same requirement Tkinter's root.mainloop() has. Two
    GUI toolkits can't share one main thread, so instead of fighting
    over it, the tool gets a whole process to itself.
    """
    if webview is None:
        print("pywebview is required to open this tool but isn't installed.")
        sys.exit(1)

    url = Path(file_path).resolve().as_uri()
    # The launcher passed its signed-in session in the environment (see
    # _open_program). Hand it to the page in the URL fragment, which the
    # page reads and immediately wipes. A fragment never leaves the
    # machine -- it isn't sent to any server, and this is a local file
    # in any case.
    session = os.environ.get("CENTER_SESSION", "")
    if session:
        encoded = base64.urlsafe_b64encode(session.encode("utf-8")).decode("ascii")
        url += "#session=" + encoded

    webview.create_window(title, url=url)
    webview.start()


def main():
    # Hidden mode used internally to open one interactive tool in its own
    # window — see run_webview_window's docstring for why this is a
    # separate process instead of a function call.
    if len(sys.argv) >= 3 and sys.argv[1] == "--webview":
        title = sys.argv[3] if len(sys.argv) > 3 else APP_NAME
        run_webview_window(sys.argv[2], title)
        return

    HTML_DIR.mkdir(exist_ok=True)
    ASSETS_DIR.mkdir(exist_ok=True)
    root = ctk.CTk()
    # Surface exceptions raised inside button clicks / after() callbacks
    # instead of letting Tkinter silently swallow them to a stderr that
    # doesn't exist in a packaged windowed app — see log_and_show_error.
    root.report_callback_exception = log_and_show_error
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
