#!/usr/bin/env python3
"""
The Center — Office Tools
==========================

A simple desktop app for new office members. The home page shows a
grid of tiles ("waffle") — one per HTML guide kept in the `html/`
folder next to this program — and opens whichever one they click in
their default web browser.

Built with CustomTkinter for a modern look. Install it once with:

    pip install customtkinter

HOW TO ADD OR UPDATE DOCUMENTS
-------------------------------
1. Drop an .html file into the `html` folder next to this program
   (or next to the packaged app, see README.md).
2. Optional: start the filename with a number to control the order
   it appears in the list, e.g. "01_Welcome.html", "02_FAQ.html".
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

RUNNING THIS PROGRAM
---------------------
    pip install customtkinter
    python3 launcher.py

See README.md for full instructions, including how to package this
as a standalone Windows .exe or Mac .app that colleagues can run
without installing Python.
"""

import re
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

APP_NAME = "The Center"
APP_TAGLINE = "Office Tools"
WINDOW_TITLE = f"{APP_NAME} — {APP_TAGLINE}"
WINDOW_SIZE = "980x640"

# ---- palette: real Center brand colors — extracted directly from
# assets/logo.png. White banner + body, with navy (dark blue) and cyan
# (light blue) used for text, accents, and interactive elements. --------
BANNER_BG = "#ffffff"
BODY_BG = "#ffffff"
CARD_BG = "#ffffff"
BORDER = "#dde1ee"
ACCENT = "#00C0F3"  # Center cyan
ACCENT_SOFT = "#e3f8ff"
TEXT_DARK = "#1D2071"  # Center navy
TEXT_MUTED = "#6b7280"

FONT_FAMILY = "Segoe UI"

TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
ORDER_PREFIX_RE = re.compile(r"^\d+[\s_.\-]+")

LOGO_SIZE = 64  # px, square — used only for the placeholder mark when no
                # real logo file is present
LOGO_HEIGHT = 84  # px tall — real logo.png is drawn at this height, with
                  # its width scaled to match its actual aspect ratio

GRID_COLUMNS = 4  # tiles per row on the home page "waffle"
TILE_WIDTH = 150
TILE_HEIGHT = 120
TILE_ICON_SIZE = 48


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


def discover_documents():
    """Return a sorted list of (sort_key, display_title, path) tuples."""
    if not HTML_DIR.exists():
        return []
    docs = []
    for path in HTML_DIR.glob("*.htm*"):
        if path.is_file():
            docs.append((path.name.lower(), read_title(path), path))
    docs.sort(key=lambda d: d[0])
    return docs


def load_logo_image(height=LOGO_HEIGHT):
    """Load a real logo from assets/ if one has been dropped in there.

    Sized by height, with width derived from the image's own aspect
    ratio — so a non-square logo (like The Center's wordmark-style
    mark) isn't squashed or stretched into a square.
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
        self.documents = []  # list of (sort_key, title, path)
        self.filtered = []
        self._logo_image = load_logo_image()

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        root.title(WINDOW_TITLE)
        root.geometry(WINDOW_SIZE)
        root.minsize(800, 520)
        root.configure(fg_color=BODY_BG)

        self._build_banner()
        self._build_body()
        self.refresh_documents()

    # ----------------------------------------------------------- banner --
    def _build_banner(self):
        banner = ctk.CTkFrame(self.root, fg_color=BANNER_BG, corner_radius=0)
        banner.pack(fill="x")

        # Everything centered: logo on top, title + tagline stacked below it.
        content = ctk.CTkFrame(banner, fg_color=BANNER_BG)
        content.pack(pady=(30, 22))

        logo_holder = ctk.CTkFrame(content, fg_color=BANNER_BG)
        logo_holder.pack()
        self._render_logo(logo_holder)

        ctk.CTkLabel(
            content,
            text=APP_NAME,
            font=(FONT_FAMILY, 26, "bold"),
            text_color=TEXT_DARK,
            fg_color=BANNER_BG,
        ).pack(pady=(12, 0))
        ctk.CTkLabel(
            content,
            text=APP_TAGLINE,
            font=(FONT_FAMILY, 13),
            text_color=ACCENT,
            fg_color=BANNER_BG,
        ).pack(pady=(2, 0))

        # Thin divider so the white banner still reads as a distinct
        # section from the white body underneath it.
        ctk.CTkFrame(self.root, fg_color=BORDER, height=1, corner_radius=0).pack(fill="x")

    def _render_logo(self, parent):
        """Show a real logo if assets/logo.* exists, otherwise a clean
        rounded placeholder mark so the app still looks finished today."""
        if self._logo_image is not None:
            ctk.CTkLabel(parent, image=self._logo_image, text="", fg_color=BANNER_BG).pack()
            return

        ctk.CTkLabel(
            parent,
            text=APP_NAME[0],
            width=LOGO_SIZE,
            height=LOGO_SIZE,
            corner_radius=LOGO_SIZE // 2,
            fg_color=ACCENT,
            text_color="white",
            font=(FONT_FAMILY, int(LOGO_SIZE * 0.4), "bold"),
        ).pack()

    # ------------------------------------------------------------- body --
    def _build_body(self):
        """Home page: a search box up top, then a grid of clickable tiles
        (a 'waffle') — one per document — that open straight to the
        browser when clicked. Replaces the old list + details layout."""
        body = ctk.CTkFrame(self.root, fg_color=BODY_BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=28, pady=(20, 22))

        ctk.CTkLabel(
            body,
            text="Office Guides & Documents",
            font=(FONT_FAMILY, 13, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
        ).pack(anchor="w")
        ctk.CTkLabel(
            body,
            text="Pick a tile below to open a guide or tool in your browser.",
            font=(FONT_FAMILY, 11),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).pack(anchor="w", pady=(2, 14))

        search_row = ctk.CTkFrame(body, fg_color=BODY_BG)
        search_row.pack(fill="x", pady=(0, 14))

        self.search_var = StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        ctk.CTkEntry(
            search_row,
            textvariable=self.search_var,
            placeholder_text="Search documents…",
            font=(FONT_FAMILY, 12),
            height=36,
            corner_radius=8,
            border_color=BORDER,
        ).pack(fill="x")

        self.grid_scroll = ctk.CTkScrollableFrame(body, fg_color=BODY_BG, corner_radius=0)
        self.grid_scroll.pack(fill="both", expand=True)
        for col in range(GRID_COLUMNS):
            self.grid_scroll.grid_columnconfigure(col, weight=1)

        self.empty_label = ctk.CTkLabel(
            self.grid_scroll,
            text="No documents found yet.",
            font=(FONT_FAMILY, 11),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
            justify="left",
        )

        self._build_toolbar(body)

    def _build_tile(self, parent, index, title, path):
        """One waffle tile: a colored icon badge (alternating navy/cyan,
        the brand colors) with the document's first letter, and its
        title underneath. The whole tile is clickable and opens the
        document directly — no intermediate page."""
        badge_bg = TEXT_DARK if index % 2 == 0 else ACCENT  # navy / cyan, alternating

        tile = ctk.CTkFrame(
            parent,
            fg_color=CARD_BG,
            border_width=1,
            border_color=BORDER,
            corner_radius=14,
            width=TILE_WIDTH,
            height=TILE_HEIGHT,
        )
        tile.grid_propagate(False)

        icon = ctk.CTkLabel(
            tile,
            text=(title[:1] or "?").upper(),
            width=TILE_ICON_SIZE,
            height=TILE_ICON_SIZE,
            corner_radius=12,
            fg_color=badge_bg,
            text_color="white",
            font=(FONT_FAMILY, int(TILE_ICON_SIZE * 0.42), "bold"),
        )
        icon.pack(pady=(18, 8))

        label = ctk.CTkLabel(
            tile,
            text=title,
            font=(FONT_FAMILY, 12, "bold"),
            text_color=TEXT_DARK,
            fg_color="transparent",
            wraplength=TILE_WIDTH - 20,
            justify="center",
        )
        label.pack(padx=10, pady=(0, 14))

        def on_click(_event=None):
            self.open_document(path)

        def on_enter(_event=None):
            tile.configure(fg_color=ACCENT_SOFT)

        def on_leave(_event=None):
            tile.configure(fg_color=CARD_BG)

        for widget in (tile, icon, label):
            widget.bind("<Button-1>", on_click)
            widget.bind("<Enter>", on_enter)
            widget.bind("<Leave>", on_leave)
            widget.configure(cursor="pointinghand" if sys.platform == "darwin" else "hand2")

        return tile

    def _build_toolbar(self, body):
        toolbar = ctk.CTkFrame(body, fg_color=BODY_BG)
        toolbar.pack(fill="x", pady=(16, 0))

        def ghost_button(text, command):
            return ctk.CTkButton(
                toolbar,
                text=text,
                font=(FONT_FAMILY, 11),
                fg_color="transparent",
                hover_color=ACCENT_SOFT,
                text_color=TEXT_DARK,
                border_width=1,
                border_color=BORDER,
                corner_radius=8,
                height=34,
                command=command,
            )

        ghost_button("Refresh", self.refresh_documents).pack(side="left")
        ghost_button("How to Use This Launcher", self.show_help).pack(side="left", padx=(8, 0))
        ghost_button("Quit", self.root.destroy).pack(side="right")

    # --------------------------------------------------------- behavior --
    def refresh_documents(self):
        self.documents = discover_documents()
        self._apply_filter()

    def _apply_filter(self):
        query = self.search_var.get().strip().lower()
        self.filtered = [d for d in self.documents if query in d[1].lower()] if query else list(self.documents)

        for widget in self.grid_scroll.winfo_children():
            widget.destroy()

        if not self.filtered:
            message = (
                "No documents match your search."
                if query
                else f"No documents found yet.\nAdd .html files to:\n{HTML_DIR}"
            )
            self.empty_label = ctk.CTkLabel(
                self.grid_scroll,
                text=message,
                font=(FONT_FAMILY, 11),
                text_color=TEXT_MUTED,
                fg_color=BODY_BG,
                justify="left",
            )
            self.empty_label.grid(row=0, column=0, columnspan=GRID_COLUMNS, sticky="w", padx=8, pady=12)
            return

        for index, (_key, title, path) in enumerate(self.filtered):
            row, col = divmod(index, GRID_COLUMNS)
            tile = self._build_tile(self.grid_scroll, index, title, path)
            tile.grid(row=row, column=col, padx=10, pady=10, sticky="n")

    def open_document(self, path: Path):
        if not path.exists():
            messagebox.showerror(WINDOW_TITLE, f"File not found:\n{path}\n\nClick Refresh and try again.")
            return
        webbrowser.open(path.resolve().as_uri())

    def show_help(self):
        messagebox.showinfo(
            "How to Use This Launcher",
            "1. Click any tile to open that guide or tool in your browser.\n"
            "2. Use Search to quickly find a tile by name.\n"
            "3. If you don't see a document you expect, ask an admin to add it "
            "to the html folder, then click Refresh.\n\n"
            "Having trouble? Contact your office administrator.",
        )


def main():
    HTML_DIR.mkdir(exist_ok=True)
    ASSETS_DIR.mkdir(exist_ok=True)
    root = ctk.CTk()
    LauncherApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
