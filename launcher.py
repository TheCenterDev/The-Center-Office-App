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

import html
import html.parser
import json
import re
import shutil
import subprocess
import sys
import time
import tkinter as tk
import traceback
import urllib.parse
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
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # CustomTkinter installs Pillow automatically; this is a fallback.
    ImageDraw = None

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

FONT_FAMILY = "Segoe UI"

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

# No real email/accounts system yet — these two hardcoded logins are a
# placeholder gate until The Center wants real per-person accounts.
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "TH3Center1"
STAFF_USERNAME = "staff"
STAFF_PASSWORD = "Center123"


def get_base_dir() -> Path:
    """Folder used to find html/ and assets/ — kept separate from any
    PyInstaller temp-extraction folder so they stay normal, editable
    folders on disk that can be added to or replaced without rebuilding.

    - Running from source: the folder containing this script.
    - Packaged on Windows (--onefile .exe): the folder containing the
      .exe, so the whole thing stays one portable folder.
    - Packaged on Mac (--windowed .app bundle): the real executable is
      buried inside TheCenterOfficeLauncher.app/Contents/MacOS/, which
      isn't where you'd want to keep editable html/ and assets/ folders
      — especially once the .app is moved into /Applications. So on Mac
      we walk up from the executable to find the enclosing ".app"
      bundle and use the folder that *contains* it instead, meaning
      html/ and assets/ sit right next to the visible app icon.
    """
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        if sys.platform == "darwin":
            for parent in exe_path.parents:
                if parent.suffix == ".app":
                    return parent.parent
        return exe_path.parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
HTML_DIR = BASE_DIR / "html"
ASSETS_DIR = BASE_DIR / "assets"
SETTINGS_FILE = BASE_DIR / "settings.json"
ERROR_LOG_FILE = BASE_DIR / "error_log.txt"


def write_error_log(details: str):
    """Best-effort append to error_log.txt next to html/ and assets/."""
    try:
        with open(ERROR_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n---- {time.strftime('%Y-%m-%d %H:%M:%S')} ----\n{details}")
    except OSError:
        pass


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
    "remember_username": True,  # prefill the last-used login username
    "last_username": "",
}


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

    # -- HTMLParser overrides ------------------------------------------
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("h1", "h2", "h3"):
            self._heading_tag = tag
            self._runs = []
        elif tag == "p":
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
        elif tag == "p" and self._runs is not None and not self._in_note:
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


def load_logo_image(height):
    """Load a real logo from assets/ if one has been dropped in there.

    Sized by height, with width derived from the image's own aspect
    ratio — so a non-square logo (like The Center's wordmark-style
    mark) isn't squashed or stretched into a square. Always drawn on a
    white background (sidebar header and welcome screen are both
    white), since the logo's navy ink would disappear against navy.
    """
    if Image is None:
        return None
    for candidate in (ASSETS_DIR / "logo.png", ASSETS_DIR / "logo.jpg", ASSETS_DIR / "logo.jpeg"):
        if candidate.exists():
            try:
                img = Image.open(candidate)
                width_px, height_px = img.size
                width = max(1, round(height * (width_px / height_px)))
                return ctk.CTkImage(light_image=img, dark_image=img, size=(width, height))
            except Exception:
                pass
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
        self.user_role = None  # "admin" or "staff" once logged in

        self.settings = load_settings()
        self._sidebar_expanded = bool(self.settings.get("sidebar_expanded", True))
        apply_theme(self.settings.get("theme", "light"))
        apply_font_scale(self.settings.get("font_scale", "normal"))

        self._sidebar_logo = load_logo_image(LOGO_HEIGHT)
        self._welcome_logo = load_logo_image(WELCOME_LOGO_HEIGHT)
        self._login_logo = load_logo_image(LOGIN_LOGO_HEIGHT)
        self._search_icon = build_search_icon(16, SIDEBAR_TEXT)

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
            placeholder_text="Username",
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

        def attempt_login(*_event):
            username = username_var.get().strip().lower()
            password = password_var.get()
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                role = "admin"
            elif username == STAFF_USERNAME and password == STAFF_PASSWORD:
                role = "staff"
            else:
                error_var.set("Incorrect username or password.")
                password_var.set("")
                return
            self.user_role = role
            if self.settings.get("remember_username", True):
                self.settings["last_username"] = username
                save_settings(self.settings)
            self.root.unbind("<Return>")
            self.login_screen.destroy()
            self._show_loading_screen()

        ctk.CTkButton(
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
            # apply_and_rebuild) since attempt_login destroys
            # login_screen, this button's own ancestor. The <Return>
            # binding below calls attempt_login directly since a root-
            # level key binding doesn't have this hazard.
            command=lambda: self.root.after(1, attempt_login),
        ).pack(side="left")

        ctk.CTkLabel(
            inner, textvariable=error_var, font=F(11), text_color="#c0392b", fg_color=WHITE_BACKDROP
        ).pack(pady=(8, 0))

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

        self.content_frame = ctk.CTkFrame(container, fg_color=BODY_BG, corner_radius=0)
        self.content_frame.pack(side="left", fill="both", expand=True)
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

        # Header always stays white (WHITE_BACKDROP, not the theme-variable
        # BODY_BG) so the real navy-and-cyan logo stays readable regardless
        # of theme — it would disappear if drawn directly on the navy
        # sidebar, or wash out against a dark-mode background.
        header = ctk.CTkFrame(self.sidebar_content, fg_color=WHITE_BACKDROP, corner_radius=0)
        header.pack(fill="x")
        header_inner = ctk.CTkFrame(header, fg_color=WHITE_BACKDROP)
        header_inner.pack(padx=18, pady=18)
        self._render_logo(header_inner, self._sidebar_logo, LOGO_SIZE, anchor="center")
        ctk.CTkLabel(
            header_inner, text=APP_NAME, font=F(14, "bold"), text_color=LOGIN_TEXT, fg_color=WHITE_BACKDROP
        ).pack(anchor="center", pady=(8, 0))
        ctk.CTkLabel(
            header_inner, text=APP_TAGLINE, font=F(10), text_color=ACCENT, fg_color=WHITE_BACKDROP
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

    def _toggle_sidebar(self):
        self._sidebar_expanded = not self._sidebar_expanded
        self._apply_sidebar_state()
        self.settings["sidebar_expanded"] = self._sidebar_expanded
        save_settings(self.settings)

    def _apply_sidebar_state(self):
        """Applies self._sidebar_expanded to the already-built sidebar
        widgets, without flipping it — used both by _toggle_sidebar and
        right after _build_sidebar constructs everything in its default
        (expanded) layout, so a collapsed state saved from a previous
        launch (or restored via Settings) actually takes effect."""
        if self._sidebar_expanded:
            self.sidebar.configure(width=SIDEBAR_WIDTH)
            self.sidebar_content.pack(fill="both", expand=True)
            self.toggle_button.configure(text="⟨")
        else:
            self.sidebar_content.pack_forget()
            self.sidebar.configure(width=SIDEBAR_COLLAPSED_WIDTH)
            self.toggle_button.configure(text="⟩")

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

        footer_button("Refresh", self.refresh_documents).pack(fill="x", pady=1)
        self.settings_button = footer_button("Settings", self._show_settings)
        self.settings_button.pack(fill="x", pady=1)
        footer_button("How to Use This Launcher", self.show_help).pack(fill="x", pady=1)
        footer_button("Quit", self.root.destroy).pack(fill="x", pady=1)

    def _render_logo(self, parent, logo_image, placeholder_size, anchor="w"):
        """Show a real logo if assets/logo.* exists, otherwise a clean
        rounded placeholder mark so the app still looks finished today.
        Always drawn on WHITE_BACKDROP (fixed white, not the theme-variable
        BODY_BG) — see load_logo_image — since the logo's navy ink needs a
        light background to read regardless of the active theme, and every
        caller now wraps this in a WHITE_BACKDROP-colored holder frame to
        match. `anchor` controls horizontal alignment within `parent`: "w"
        for the left-aligned Home-page usage, "center" for the sidebar
        header and login/loading screens, where it should sit dead-center."""
        if logo_image is not None:
            ctk.CTkLabel(parent, image=logo_image, text="", fg_color=WHITE_BACKDROP).pack(anchor=anchor)
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
        self.documents = discover_documents()
        self._render_nav_list()
        if self._selected_path == "apps":
            self._show_apps()

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
        if self.home_button is not None:
            if active_path is None:
                self.home_button.configure(fg_color=SIDEBAR_ACTIVE, text_color=ACCENT)
            else:
                self.home_button.configure(fg_color=SIDEBAR_BG, text_color=SIDEBAR_TEXT)
        if self.apps_button is not None:
            if active_path == "apps":
                self.apps_button.configure(fg_color=SIDEBAR_ACTIVE, text_color=ACCENT)
            else:
                self.apps_button.configure(fg_color=SIDEBAR_BG, text_color=SIDEBAR_TEXT)
        if self.skills_button is not None:
            if active_path == "skills":
                self.skills_button.configure(fg_color=SIDEBAR_ACTIVE, text_color=ACCENT)
            else:
                self.skills_button.configure(fg_color=SIDEBAR_BG, text_color=SIDEBAR_TEXT)
        if self.settings_button is not None:
            if active_path == "settings":
                self.settings_button.configure(fg_color=SIDEBAR_ACTIVE, text_color=ACCENT)
            else:
                self.settings_button.configure(fg_color="transparent", text_color=SIDEBAR_TEXT_MUTED)
        for path, btn in self._nav_buttons.items():
            if path == active_path:
                btn.configure(fg_color=SIDEBAR_ACTIVE, text_color=ACCENT)
            else:
                btn.configure(fg_color=SIDEBAR_BG, text_color=SIDEBAR_TEXT)

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
        if webview is not None:
            try:
                args = [sys.executable]
                if not getattr(sys, "frozen", False):
                    args.append(str(Path(__file__).resolve()))
                args += ["--webview", str(path.resolve()), title or APP_NAME]
                subprocess.Popen(args)
                return
            except Exception:
                pass
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

    def _content_header(self, title: str, extra_button=None):
        """Shared header row (title, optional right-side button) used at
        the top of every non-welcome content view. Used to also show a
        colored square with the title's first letter next to the title,
        as a stand-in for a real icon — dropped since it read as a bare
        "logo" rather than anything meaningful."""
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

        if extra_button is not None:
            text, command = extra_button
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
        the office."""
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
                 "and Claude Skills, all in one place. Just click around in "
                 "the sidebar to see what's here.",
            font=F(13),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(0, 18))

        # Callout linking out to the full employee onboarding site — this
        # app deliberately only covers tools/Skills, so anything else new
        # hires need (policies, other links, general instructions) points
        # here instead of trying to duplicate it in-app.
        portal_card = ctk.CTkFrame(scroll, fg_color=ACCENT_SOFT, corner_radius=12)
        portal_card.pack(fill="x", pady=(0, 18))
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

        def section(heading: str, body: str):
            ctk.CTkLabel(
                scroll,
                text=heading,
                font=F(13, "bold"),
                text_color=TEXT_DARK,
                fg_color=BODY_BG,
            ).pack(anchor="w", pady=(14, 4))
            ctk.CTkLabel(
                scroll,
                text=body,
                font=F(12),
                text_color=TEXT_MUTED,
                fg_color=BODY_BG,
                wraplength=560,
                justify="left",
            ).pack(anchor="w")

        section(
            "Using Claude Skills",
            "For some tasks, just tell Claude what you need in plain "
            "English — like \"reconcile this deposit\" or \"draft the "
            "financials email\" — and it handles it for you. No need to "
            "come find a button for it.",
        )
        section(
            "A couple of quick tips",
            "Anything marked ↗ opens in its own window since it needs a "
            "real browser. Use Search to find something by name, or even "
            "by a word inside it. And Settings (bottom of the sidebar) is "
            "where you can switch to dark mode or make the text bigger.",
        )

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

    def _show_settings(self):
        """Personal display preferences, saved to settings.json next to
        html/ and assets/ so they persist between launches. Every change
        here applies immediately (no Save button) and triggers a full
        UI rebuild — see _rebuild_ui — since CustomTkinter widgets don't
        pick up new colors/fonts on their own once built."""
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
            text="Personal display preferences, saved on this computer.",
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
        theme back to Light."""
        keep_username = self.settings.get("last_username", "")
        self.settings = dict(DEFAULT_SETTINGS)
        self.settings["last_username"] = keep_username
        save_settings(self.settings)
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
        _download_skill_file), mailto/http(s) links open normally, and
        any other relative link is resolved against the guide's own
        folder and opened externally if it exists."""
        if not href:
            return
        if href.startswith("mailto:") or href.startswith("http://") or href.startswith("https://"):
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

    def _build_rich_text(self, parent, runs, base_dir: Path, font_size=12, base_color=None, bg_color=None):
        """Renders a list of (text, styleset, href) runs as one flowing,
        read-only paragraph able to mix bold/link/placeholder styling
        inline -- e.g. "...guessing. Download Skill" or "Brad Boyles —
        Brad@thecentercc.com" -- which a plain CTkLabel can't do, since a
        label only ever draws one font/color for its whole text. Backed
        by a bare tkinter.Text widget (CTk has no rich-text widget of its
        own), styled to sit invisibly among the CTk widgets around it and
        auto-sized to its wrapped line count so it behaves like a normal
        paragraph rather than a fixed-size box."""
        bg_color = bg_color or BODY_BG
        base_color = base_color or TEXT_MUTED

        widget = tk.Text(
            parent, wrap="word", background=bg_color, foreground=base_color,
            borderwidth=0, highlightthickness=0, font=F(font_size), padx=0, pady=0,
            cursor="arrow", takefocus=0, height=1,
        )
        widget.tag_configure("bold", font=F(font_size, "bold"), foreground=TEXT_DARK)
        widget.tag_configure("fill", foreground="#b45309")
        widget.tag_configure("link", foreground=ACCENT, underline=True)

        has_link = False
        for text, styleset, href in runs:
            tags = [s for s in ("bold", "fill") if s in styleset]
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
            widget.tag_bind("link", "<Leave>", lambda e: widget.configure(cursor="arrow"))

        widget.configure(state="disabled")
        widget.pack(fill="x", anchor="w")

        def resize(event=None):
            try:
                counted = widget.count("1.0", "end", "displaylines")
                lines = counted[0] if counted else 1
                widget.configure(height=max(1, lines))
            except Exception:
                pass

        widget.bind("<Configure>", resize)
        widget.after(30, resize)
        return widget

    def _render_guide_table(self, parent, rows):
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
                cell_text = "".join(t for t, _s, _h in cell_runs).strip()
                is_fill = any("fill" in s for _t, s, _h in cell_runs)
                cell_color = "#b45309" if is_fill else (TEXT_DARK if is_header else TEXT_MUTED)
                ctk.CTkLabel(
                    table_card,
                    text=cell_text or "—",
                    font=F(12, "bold" if is_header else None),
                    text_color=cell_color,
                    fg_color=row_bg,
                    anchor="w",
                    justify="left",
                    wraplength=200,
                ).grid(row=row_idx, column=col_idx, sticky="nsew", padx=12, pady=8)

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
                self._render_guide_table(parent, block["rows"])
            elif kind == "note":
                note_card = ctk.CTkFrame(parent, fg_color=ACCENT_SOFT, corner_radius=10)
                note_card.pack(fill="x", pady=(16, 4))
                note_inner = ctk.CTkFrame(note_card, fg_color=ACCENT_SOFT)
                note_inner.pack(fill="x", padx=14, pady=12)
                self._build_rich_text(note_inner, block["runs"], base_dir, font_size=11, base_color=TEXT_DARK, bg_color=ACCENT_SOFT)

    def _show_guide(self, title: str, path: Path):
        self._clear_content()
        self._content_header(title, extra_button=("Open in Browser ↗", lambda: webbrowser.open(path.resolve().as_uri())))

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

    def show_help(self):
        messagebox.showinfo(
            "How to Use This Launcher",
            "1. Click Home (top of the sidebar) any time to return to the "
            "welcome overview, or Apps for a dedicated list of every "
            "interactive tool.\n"
            "2. Click any other item in the sidebar to open it right here "
            "in the app.\n"
            "3. Items marked with ↗ are interactive tools that need real "
            "JavaScript to run — they show an \"Open Tool\" button that opens "
            "a separate window for that tool.\n"
            "4. Press Enter in Search (or click 🔍) to see every match for "
            "a word anywhere in the app — not just the sidebar list — or "
            "use the ⟨ arrow at the top of the sidebar to collapse it out "
            "of the way.\n"
            "5. If you don't see a document you expect, ask an admin to add it "
            "to the html folder, then click Refresh.\n"
            "6. Click Settings (bottom of the sidebar) to change the color "
            "theme, text size, startup page, or whether your username is "
            "remembered on this computer.\n\n"
            "Having trouble? Contact your office administrator.",
        )


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
    webview.create_window(title, url=Path(file_path).resolve().as_uri())
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
