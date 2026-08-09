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

import re
import subprocess
import sys
import webbrowser
from pathlib import Path
from tkinter import StringVar, messagebox

try:
    import customtkinter as ctk
except ImportError:
    print(
        "This launcher requires the 'customtkinter' package.\n\n"
        "Install it with:\n"
        "    pip install customtkinter\n"
    )
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    Image = None  # CustomTkinter installs Pillow automatically; this is a fallback.

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
BODY_BG = "#ffffff"
CARD_BG = "#ffffff"
BORDER = "#dde1ee"
ACCENT = "#00C0F3"  # Center cyan
ACCENT_SOFT = "#e3f8ff"
TEXT_DARK = "#1D2071"  # Center navy
TEXT_MUTED = "#6b7280"

SIDEBAR_BG = TEXT_DARK
SIDEBAR_HOVER = "#2b2f8c"
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

LOGIN_LOGO_HEIGHT = 80  # px tall on the login screen
# Logo and card are stacked in one column (logo on top, card below) and
# that whole stack is centered as a unit, so the two never overlap.
LOGIN_FIELD_WIDTH = 300  # width of the username field, and of the
                          # password field + arrow button combined
LOGIN_BUTTON_WIDTH = 46
LOGIN_FIELD_HEIGHT = 38

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


class LauncherApp:
    def __init__(self, root: ctk.CTk):
        self.root = root
        self.documents = []  # list of (sort_key, title, path, is_program)
        self.filtered = []
        self._nav_buttons = {}  # path -> CTkButton, for highlighting the active row
        self._selected_path = None  # None = Home, "apps" = Apps, else a document Path
        self._sidebar_expanded = True
        self.home_button = None
        self.apps_button = None
        self.user_role = None  # "admin" or "staff" once logged in
        self._sidebar_logo = load_logo_image(LOGO_HEIGHT)
        self._welcome_logo = load_logo_image(WELCOME_LOGO_HEIGHT)
        self._login_logo = load_logo_image(LOGIN_LOGO_HEIGHT)

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        root.title(WINDOW_TITLE)
        root.geometry(WINDOW_SIZE)
        root.minsize(860, 520)
        root.configure(fg_color=BODY_BG)

        self._show_login_screen()

    # ------------------------------------------------------------ login --
    def _show_login_screen(self):
        """Blank white gate shown on launch, before any app content builds.
        The logo and the login card are stacked in a single column (logo
        on top, card directly below) and that whole stack is centered as
        one unit in the window, so the two never overlap regardless of
        the card's size."""
        self.login_screen = ctk.CTkFrame(self.root, fg_color=BODY_BG, corner_radius=0)
        self.login_screen.pack(fill="both", expand=True)

        stack = ctk.CTkFrame(self.login_screen, fg_color=BODY_BG)
        stack.place(relx=0.5, rely=0.5, anchor="center")

        logo_holder = ctk.CTkFrame(stack, fg_color=BODY_BG)
        logo_holder.pack(pady=(0, 22))
        self._render_logo(logo_holder, self._login_logo, LOGIN_LOGO_HEIGHT, anchor="center")

        card = ctk.CTkFrame(
            stack, fg_color=CARD_BG, corner_radius=16, border_width=1, border_color=BORDER
        )
        card.pack()

        inner = ctk.CTkFrame(card, fg_color=CARD_BG)
        inner.pack(padx=24, pady=20)

        ctk.CTkLabel(
            inner, text="Sign In", font=(FONT_FAMILY, 15, "bold"), text_color=TEXT_DARK, fg_color=CARD_BG
        ).pack(anchor="w", pady=(0, 12))

        username_var = StringVar()
        password_var = StringVar()
        error_var = StringVar()

        username_entry = ctk.CTkEntry(
            inner,
            textvariable=username_var,
            placeholder_text="Username",
            font=(FONT_FAMILY, 12),
            height=LOGIN_FIELD_HEIGHT,
            corner_radius=8,
            width=LOGIN_FIELD_WIDTH,
        )
        username_entry.pack(pady=(0, 8))

        # Password field + submit arrow sit flush against each other in
        # one row, sized so together they match the username field's
        # width above — reads as one seamless control instead of two.
        password_row = ctk.CTkFrame(inner, fg_color=CARD_BG)
        password_row.pack()

        password_entry = ctk.CTkEntry(
            password_row,
            textvariable=password_var,
            placeholder_text="Password",
            show="•",
            font=(FONT_FAMILY, 12),
            height=LOGIN_FIELD_HEIGHT,
            corner_radius=8,
            width=LOGIN_FIELD_WIDTH - LOGIN_BUTTON_WIDTH,
        )
        password_entry.pack(side="left")

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
            self.root.unbind("<Return>")
            self.login_screen.destroy()
            self._build_layout()
            self.refresh_documents()

        ctk.CTkButton(
            password_row,
            text="→",
            font=(FONT_FAMILY, 16, "bold"),
            fg_color=ACCENT,
            hover_color=TEXT_DARK,
            text_color="white",
            corner_radius=8,
            height=LOGIN_FIELD_HEIGHT,
            width=LOGIN_BUTTON_WIDTH,
            command=attempt_login,
        ).pack(side="left")

        ctk.CTkLabel(
            inner, textvariable=error_var, font=(FONT_FAMILY, 11), text_color="#c0392b", fg_color=CARD_BG
        ).pack(pady=(8, 0))

        self.root.bind("<Return>", attempt_login)
        username_entry.focus_set()

    # ----------------------------------------------------------- layout --
    def _build_layout(self):
        container = ctk.CTkFrame(self.root, fg_color=BODY_BG, corner_radius=0)
        container.pack(fill="both", expand=True)

        self._build_sidebar(container)

        self.content_frame = ctk.CTkFrame(container, fg_color=BODY_BG, corner_radius=0)
        self.content_frame.pack(side="left", fill="both", expand=True)
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
            hover_color=SIDEBAR_HOVER,
            text_color=SIDEBAR_TEXT_MUTED,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._toggle_sidebar,
        )
        self.toggle_button.pack(anchor="e", padx=6, pady=6)

        # Everything else lives in one sub-frame so it can be hidden as a
        # unit when the sidebar collapses to a thin strip.
        self.sidebar_content = ctk.CTkFrame(self.sidebar, fg_color=SIDEBAR_BG, corner_radius=0)
        self.sidebar_content.pack(fill="both", expand=True)

        # Header stays white so the real (navy-and-cyan) logo is readable
        # — it would disappear if drawn directly on the navy sidebar.
        header = ctk.CTkFrame(self.sidebar_content, fg_color=BODY_BG, corner_radius=0)
        header.pack(fill="x")
        header_inner = ctk.CTkFrame(header, fg_color=BODY_BG)
        header_inner.pack(padx=18, pady=18)
        self._render_logo(header_inner, self._sidebar_logo, LOGO_SIZE, anchor="center")
        ctk.CTkLabel(
            header_inner, text=APP_NAME, font=(FONT_FAMILY, 14, "bold"), text_color=TEXT_DARK, fg_color=BODY_BG
        ).pack(anchor="center", pady=(8, 0))
        ctk.CTkLabel(
            header_inner, text=APP_TAGLINE, font=(FONT_FAMILY, 10), text_color=ACCENT, fg_color=BODY_BG
        ).pack(anchor="center")

        ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_DIVIDER, height=1, corner_radius=0).pack(fill="x")

        home_row = ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_BG)
        home_row.pack(fill="x", padx=6, pady=(10, 4))
        self.home_button = ctk.CTkButton(
            home_row,
            text="Home",
            anchor="w",
            font=(FONT_FAMILY, 12, "bold"),
            fg_color=SIDEBAR_BG,
            hover_color=SIDEBAR_HOVER,
            text_color=SIDEBAR_TEXT,
            corner_radius=8,
            height=36,
            command=self._show_home,
        )
        self.home_button.pack(fill="x")

        ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_DIVIDER, height=1, corner_radius=0).pack(
            fill="x", padx=6, pady=(6, 0)
        )

        search_row = ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_BG)
        search_row.pack(fill="x", padx=12, pady=12)
        self.search_var = StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        ctk.CTkEntry(
            search_row,
            textvariable=self.search_var,
            placeholder_text="Search…",
            font=(FONT_FAMILY, 12),
            height=32,
            corner_radius=8,
            fg_color=SIDEBAR_HOVER,
            border_color=SIDEBAR_DIVIDER,
            text_color=SIDEBAR_TEXT,
            placeholder_text_color=SIDEBAR_TEXT_MUTED,
        ).pack(fill="x")

        apps_row = ctk.CTkFrame(self.sidebar_content, fg_color=SIDEBAR_BG)
        apps_row.pack(fill="x", padx=6, pady=(0, 4))
        self.apps_button = ctk.CTkButton(
            apps_row,
            text="Apps",
            anchor="w",
            font=(FONT_FAMILY, 12, "bold"),
            fg_color=SIDEBAR_BG,
            hover_color=SIDEBAR_HOVER,
            text_color=SIDEBAR_TEXT,
            corner_radius=8,
            height=36,
            command=self._show_apps,
        )
        self.apps_button.pack(fill="x")

        self.nav_scroll = ctk.CTkScrollableFrame(self.sidebar_content, fg_color=SIDEBAR_BG, corner_radius=0)
        self.nav_scroll.pack(fill="both", expand=True, padx=6)

        self._build_sidebar_footer(self.sidebar_content)

    def _toggle_sidebar(self):
        self._sidebar_expanded = not self._sidebar_expanded
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
                font=(FONT_FAMILY, 11),
                fg_color="transparent",
                hover_color=SIDEBAR_HOVER,
                text_color=SIDEBAR_TEXT_MUTED,
                corner_radius=8,
                height=30,
                command=command,
            )

        footer_button("Refresh", self.refresh_documents).pack(fill="x", pady=1)
        footer_button("How to Use This Launcher", self.show_help).pack(fill="x", pady=1)
        footer_button("Quit", self.root.destroy).pack(fill="x", pady=1)

    def _render_logo(self, parent, logo_image, placeholder_size, anchor="w"):
        """Show a real logo if assets/logo.* exists, otherwise a clean
        rounded placeholder mark so the app still looks finished today.
        Always drawn on a white background — see load_logo_image.
        `anchor` controls horizontal alignment within `parent`: "w" for
        the left-aligned Home-page usage, "center" for the sidebar header
        and login screen, where the logo should sit dead-center."""
        if logo_image is not None:
            ctk.CTkLabel(parent, image=logo_image, text="", fg_color=BODY_BG).pack(anchor=anchor)
            return

        ctk.CTkLabel(
            parent,
            text=APP_NAME[0],
            width=placeholder_size,
            height=placeholder_size,
            corner_radius=placeholder_size // 2,
            fg_color=ACCENT,
            text_color="white",
            font=(FONT_FAMILY, int(placeholder_size * 0.4), "bold"),
        ).pack(anchor=anchor)

    # --------------------------------------------------------- behavior --
    def refresh_documents(self):
        self.documents = discover_documents()
        self._apply_filter()
        if self._selected_path == "apps":
            self._show_apps()

    def _apply_filter(self):
        # Interactive tools have their own dedicated "Apps" page, and some
        # guides (currently just the welcome guide) are superseded by the
        # pinned "Home" page — both are left out of this general list so
        # they aren't shown twice, though the files themselves still exist
        # and Apps still pulls tools straight from self.documents.
        nav_docs = [
            d for d in self.documents
            if not d[3] and d[2].name.lower() not in SIDEBAR_HIDDEN_FILES
        ]

        query = self.search_var.get().strip().lower()
        self.filtered = [d for d in nav_docs if query in d[1].lower()] if query else nav_docs

        for widget in self.nav_scroll.winfo_children():
            widget.destroy()
        self._nav_buttons = {}

        if not self.filtered:
            message = (
                "No documents match your search."
                if query
                else f"No documents found yet.\nAdd .html files to:\n{HTML_DIR}"
            )
            ctk.CTkLabel(
                self.nav_scroll,
                text=message,
                font=(FONT_FAMILY, 11),
                text_color=SIDEBAR_TEXT_MUTED,
                fg_color=SIDEBAR_BG,
                justify="left",
                wraplength=SIDEBAR_WIDTH - 40,
            ).pack(anchor="w", padx=6, pady=12)
            return

        for _key, title, path, is_program in self.filtered:
            label = f"{title}  ↗" if is_program else title
            btn = ctk.CTkButton(
                self.nav_scroll,
                text=label,
                anchor="w",
                font=(FONT_FAMILY, 12),
                fg_color=SIDEBAR_BG,
                hover_color=SIDEBAR_HOVER,
                text_color=SIDEBAR_TEXT,
                corner_radius=8,
                height=36,
                command=lambda p=path, t=title, prog=is_program: self._select_document(p, t, prog),
            )
            btn.pack(fill="x", pady=2)
            self._nav_buttons[path] = btn

        self._highlight_nav(self._selected_path)

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
    def _clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def _content_header(self, title: str, extra_button=None):
        """Shared header row (icon + title, optional right-side button)
        used at the top of every non-welcome content view."""
        header = ctk.CTkFrame(self.content_frame, fg_color=BODY_BG)
        header.pack(fill="x", padx=24, pady=(20, 12))

        ctk.CTkLabel(
            header,
            text=(title[:1] or "?").upper(),
            width=34,
            height=34,
            corner_radius=10,
            fg_color=TEXT_DARK,
            text_color="white",
            font=(FONT_FAMILY, 15, "bold"),
        ).pack(side="left")

        ctk.CTkLabel(
            header,
            text=title,
            font=(FONT_FAMILY, 16, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
            wraplength=420,
            justify="left",
        ).pack(side="left", padx=(12, 0))

        if extra_button is not None:
            text, command = extra_button
            ctk.CTkButton(
                header,
                text=text,
                font=(FONT_FAMILY, 11),
                fg_color="transparent",
                hover_color=ACCENT_SOFT,
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

        scroll = ctk.CTkScrollableFrame(self.content_frame, fg_color=BODY_BG, corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=32, pady=28)

        logo_holder = ctk.CTkFrame(scroll, fg_color=BODY_BG)
        logo_holder.pack(anchor="w", pady=(0, 16))
        self._render_logo(logo_holder, self._welcome_logo, 64)

        ctk.CTkLabel(
            scroll,
            text="Welcome to The Center Office Application",
            font=(FONT_FAMILY, 19, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
            wraplength=560,
            justify="left",
        ).pack(anchor="w", pady=(0, 16))

        def section(heading: str, body: str):
            ctk.CTkLabel(
                scroll,
                text=heading,
                font=(FONT_FAMILY, 13, "bold"),
                text_color=TEXT_DARK,
                fg_color=BODY_BG,
            ).pack(anchor="w", pady=(14, 4))
            ctk.CTkLabel(
                scroll,
                text=body,
                font=(FONT_FAMILY, 12),
                text_color=TEXT_MUTED,
                fg_color=BODY_BG,
                wraplength=560,
                justify="left",
            ).pack(anchor="w")

        section(
            "What this app is for",
            "This app is home base for the resources that automate day-to-day "
            "office work at The Center. Instead of digging through email "
            "threads or asking around, everything you need — reference "
            "guides and small tools that do part of the work for you — "
            "lives in the sidebar on the left.",
        )
        section(
            "Using the guides and tools",
            "Click any item in the sidebar to open it. Plain guides (like "
            "this one) display right here in the main pane. Items marked "
            "with ↗ are interactive HTML tools — they need a real browser "
            "to run, so they open an \"Open Tool\" card with a button that "
            "launches them in their own window, without closing this app. "
            "Click Apps (also pinned at the top of the sidebar) for a "
            "dedicated list of every interactive tool currently available.",
        )
        section(
            "Using Claude Skills",
            "Some repetitive office work is automated with Claude Skills — "
            "reusable instructions Claude can follow for a specific task, "
            "such as reconciling a bank deposit against QuickBooks or "
            "drafting the monthly budget-vs-actual financial summary email. "
            "You don't run these from this app — just describe what you "
            "need to Claude in plain language (for example, \"reconcile "
            "this deposit\" or \"draft the financials email\") and it runs "
            "the right skill automatically.",
        )
        section(
            "Getting started",
            "New to the office? Start with the Welcome guide in the "
            "sidebar, then browse the rest as you need them. Use Search to "
            "find something quickly, or the ⟨ arrow at the top of the "
            "sidebar to collapse it out of the way. Questions? Contact your "
            "office administrator.",
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

        scroll = ctk.CTkScrollableFrame(self.content_frame, fg_color=BODY_BG, corner_radius=0)
        scroll.pack(fill="both", expand=True, padx=32, pady=28)

        ctk.CTkLabel(
            scroll,
            text="Apps",
            font=(FONT_FAMILY, 19, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
        ).pack(anchor="w")
        ctk.CTkLabel(
            scroll,
            text="Interactive tools that open in their own window, with full JavaScript support.",
            font=(FONT_FAMILY, 12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).pack(anchor="w", pady=(2, 18))

        programs = [(title, path) for _key, title, path, is_program in self.documents if is_program]

        if not programs:
            ctk.CTkLabel(
                scroll,
                text="No interactive tools yet. Drop an .html file with a <script> tag into the html folder and click Refresh.",
                font=(FONT_FAMILY, 12),
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
                font=(FONT_FAMILY, 15, "bold"),
            ).pack(side="left")

            text_holder = ctk.CTkFrame(row, fg_color=CARD_BG)
            text_holder.pack(side="left", padx=(14, 0), fill="x", expand=True)
            ctk.CTkLabel(
                text_holder,
                text=title,
                font=(FONT_FAMILY, 14, "bold"),
                text_color=TEXT_DARK,
                fg_color=CARD_BG,
                anchor="w",
            ).pack(fill="x")
            ctk.CTkLabel(
                text_holder,
                text="Interactive tool — opens in its own window.",
                font=(FONT_FAMILY, 11),
                text_color=TEXT_MUTED,
                fg_color=CARD_BG,
                anchor="w",
            ).pack(fill="x")

            ctk.CTkButton(
                row,
                text="Open Tool" if webview is not None else "Open in Browser",
                font=(FONT_FAMILY, 12, "bold"),
                fg_color=ACCENT,
                hover_color=TEXT_DARK,
                text_color="white",
                corner_radius=10,
                height=36,
                width=120,
                command=lambda p=path, t=title: self._open_program(p, t),
            ).pack(side="right")

    def _show_guide(self, title: str, path: Path):
        self._clear_content()
        self._content_header(title, extra_button=("Open in Browser ↗", lambda: webbrowser.open(path.resolve().as_uri())))

        viewer_card = ctk.CTkFrame(
            self.content_frame, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=BORDER
        )
        viewer_card.pack(fill="both", expand=True, padx=24, pady=(0, 20))

        try:
            html_view = HtmlFrame(viewer_card, messages_enabled=False)
            html_view.pack(fill="both", expand=True, padx=1, pady=1)
            html_view.load_file(str(path))
        except Exception:
            ctk.CTkLabel(
                viewer_card,
                text="This document couldn't be displayed in the app.\nUse \"Open in Browser\" above instead.",
                font=(FONT_FAMILY, 12),
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
            font=(FONT_FAMILY, 12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).pack()
        ctk.CTkButton(
            wrap,
            text="Open Again",
            font=(FONT_FAMILY, 12, "bold"),
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
            font=(FONT_FAMILY, 16, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
        ).pack()
        button_word = "tool window" if webview is not None else "your browser"
        ctk.CTkLabel(
            wrap,
            text=f"This is an interactive tool that needs a real browser\nengine to run — it opens in its own {button_word}.",
            font=(FONT_FAMILY, 12),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
            justify="center",
        ).pack(pady=(6, 16))
        ctk.CTkButton(
            wrap,
            text="Open Tool" if webview is not None else "Open in Browser",
            font=(FONT_FAMILY, 13, "bold"),
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
            "4. Use Search to quickly find an item by name, or the ⟨ arrow "
            "at the top of the sidebar to collapse it out of the way.\n"
            "5. If you don't see a document you expect, ask an admin to add it "
            "to the html folder, then click Refresh.\n\n"
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
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
