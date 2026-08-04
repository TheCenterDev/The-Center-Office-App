#!/usr/bin/env python3
"""
The Center — Office Tools
==========================

A simple desktop app for new office members. It lists the HTML guides
kept in the `html/` folder next to this program and opens whichever
one they pick in their default web browser.

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

# ---- palette: real Center brand colors (navy banner, cyan accent, white
# body) — extracted directly from assets/logo.png -----------------------
BANNER_BG = "#1D2071"  # Center navy
BODY_BG = "#ffffff"
CARD_BG = "#ffffff"
BORDER = "#dde1ee"
ACCENT = "#00C0F3"  # Center cyan
ACCENT_HOVER = "#00A3D1"
ACCENT_SOFT = "#e3f8ff"
TEXT_DARK = "#1D2071"
TEXT_MUTED = "#6b7280"
TEXT_ON_DARK = "#ffffff"
TEXT_ON_DARK_MUTED = "#9fd6f0"

FONT_FAMILY = "Segoe UI"

TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
ORDER_PREFIX_RE = re.compile(r"^\d+[\s_.\-]+")

LOGO_SIZE = 56  # px, square — used only for the placeholder mark when no
                # real logo file is present
LOGO_HEIGHT = 64  # px tall — real logo.png is drawn at this height, with
                  # its width scaled to match its actual aspect ratio


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
        self._selected_path = None
        self._row_buttons = {}  # path -> CTkButton, for highlighting the active row
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

        logo_holder = ctk.CTkFrame(banner, fg_color=BANNER_BG)
        logo_holder.pack(side="left", padx=(28, 16), pady=22)
        self._render_logo(logo_holder)

        text_holder = ctk.CTkFrame(banner, fg_color=BANNER_BG)
        text_holder.pack(side="left", fill="y", pady=22)
        ctk.CTkLabel(
            text_holder,
            text=APP_NAME,
            font=(FONT_FAMILY, 26, "bold"),
            text_color=TEXT_ON_DARK,
            fg_color=BANNER_BG,
        ).pack(anchor="w")
        ctk.CTkLabel(
            text_holder,
            text=APP_TAGLINE,
            font=(FONT_FAMILY, 13),
            text_color=TEXT_ON_DARK_MUTED,
            fg_color=BANNER_BG,
        ).pack(anchor="w", pady=(2, 0))

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
        body = ctk.CTkFrame(self.root, fg_color=BODY_BG, corner_radius=0)
        body.pack(fill="both", expand=True, padx=28, pady=(20, 22))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            body,
            text="Office Guides & Documents",
            font=(FONT_FAMILY, 13, "bold"),
            text_color=TEXT_DARK,
            fg_color=BODY_BG,
        ).grid(row=0, column=0, columnspan=2, sticky="w")
        ctk.CTkLabel(
            body,
            text="Pick a guide below and open it — everything a new team member needs, in one place.",
            font=(FONT_FAMILY, 11),
            text_color=TEXT_MUTED,
            fg_color=BODY_BG,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 14))

        self._build_list_card(body)
        self._build_detail_card(body)
        self._build_toolbar(body)

    def _build_list_card(self, body):
        card = ctk.CTkFrame(body, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=BORDER)
        card.grid(row=2, column=0, sticky="nsew", padx=(0, 16))
        card.grid_rowconfigure(1, weight=1)
        card.grid_columnconfigure(0, weight=1)

        search_row = ctk.CTkFrame(card, fg_color=CARD_BG)
        search_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 10))
        search_row.grid_columnconfigure(0, weight=1)

        self.search_var = StringVar()
        self.search_var.trace_add("write", lambda *_: self._apply_filter())
        search_entry = ctk.CTkEntry(
            search_row,
            textvariable=self.search_var,
            placeholder_text="Search documents…",
            font=(FONT_FAMILY, 12),
            height=36,
            corner_radius=8,
            border_color=BORDER,
        )
        search_entry.grid(row=0, column=0, sticky="ew")

        self.list_scroll = ctk.CTkScrollableFrame(card, fg_color=CARD_BG, corner_radius=0)
        self.list_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 12))
        self.list_scroll.grid_columnconfigure(0, weight=1)

        self.empty_label = ctk.CTkLabel(
            self.list_scroll,
            text="No documents found yet.",
            font=(FONT_FAMILY, 11),
            text_color=TEXT_MUTED,
            fg_color=CARD_BG,
        )

    def _build_detail_card(self, body):
        card = ctk.CTkFrame(body, fg_color=CARD_BG, corner_radius=14, border_width=1, border_color=BORDER)
        card.grid(row=2, column=1, sticky="nsew")

        inner = ctk.CTkFrame(card, fg_color=CARD_BG)
        inner.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            inner, text="DETAILS", font=(FONT_FAMILY, 11, "bold"), text_color=TEXT_MUTED, fg_color=CARD_BG
        ).pack(anchor="w")
        self.detail_title = ctk.CTkLabel(
            inner,
            text="Select a document",
            font=(FONT_FAMILY, 18, "bold"),
            text_color=TEXT_DARK,
            fg_color=CARD_BG,
            wraplength=300,
            justify="left",
        )
        self.detail_title.pack(anchor="w", pady=(6, 4))

        self.detail_path = ctk.CTkLabel(
            inner,
            text="",
            font=(FONT_FAMILY, 11),
            text_color=TEXT_MUTED,
            fg_color=CARD_BG,
            wraplength=300,
            justify="left",
        )
        self.detail_path.pack(anchor="w", pady=(0, 20))

        self.open_button = ctk.CTkButton(
            inner,
            text="Open in Browser",
            font=(FONT_FAMILY, 13, "bold"),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            text_color="white",
            corner_radius=10,
            height=42,
            state="disabled",
            command=self.open_selected,
        )
        self.open_button.pack(anchor="w")

    def _build_toolbar(self, body):
        toolbar = ctk.CTkFrame(body, fg_color=BODY_BG)
        toolbar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        def ghost_button(text, command):
            return ctk.CTkButton(
                toolbar,
                text=text,
                font=(FONT_FAMILY, 11),
                fg_color="transparent",
                hover_color="#e9ebf3",
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

        for widget in self.list_scroll.winfo_children():
            widget.pack_forget()
        self._row_buttons = {}

        if not self.filtered:
            message = "No documents match your search." if query else f"No documents found yet.\nAdd .html files to:\n{HTML_DIR}"
            self.empty_label.configure(text=message)
            self.empty_label.pack(anchor="w", padx=8, pady=12)
            self.detail_title.configure(text="Select a document")
            self.detail_path.configure(text="")
            self.open_button.configure(state="disabled")
            self._selected_path = None
            return

        for _key, title, path in self.filtered:
            btn = ctk.CTkButton(
                self.list_scroll,
                text=f"📄   {title}",
                anchor="w",
                font=(FONT_FAMILY, 13),
                fg_color=CARD_BG,
                hover_color=ACCENT_SOFT,
                text_color=TEXT_DARK,
                corner_radius=8,
                height=40,
                command=lambda p=path, t=title: self._select_document(p, t),
            )
            btn.pack(fill="x", padx=4, pady=2)
            self._row_buttons[path] = btn

        # keep the previous selection highlighted if it's still in the list
        if self._selected_path in self._row_buttons:
            self._highlight_row(self._selected_path)

    def _select_document(self, path: Path, title: str):
        self._selected_path = path
        self._highlight_row(path)
        self.detail_title.configure(text=title)
        self.detail_path.configure(text=str(path))
        self.open_button.configure(state="normal")

    def _highlight_row(self, active_path):
        for path, btn in self._row_buttons.items():
            if path == active_path:
                btn.configure(fg_color=ACCENT_SOFT, text_color=ACCENT)
            else:
                btn.configure(fg_color=CARD_BG, text_color=TEXT_DARK)

    def open_selected(self):
        path = self._selected_path
        if not path:
            messagebox.showinfo(WINDOW_TITLE, "Select a document from the list first.")
            return
        if not path.exists():
            messagebox.showerror(WINDOW_TITLE, f"File not found:\n{path}\n\nClick Refresh and try again.")
            return
        webbrowser.open(path.resolve().as_uri())

    def show_help(self):
        messagebox.showinfo(
            "How to Use This Launcher",
            "1. Pick a document from the list on the left.\n"
            "2. Click 'Open in Browser' (or click the document again) to view it.\n"
            "3. Use Search to quickly find a document by name.\n"
            "4. If you don't see a document you expect, ask an admin to add it "
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
