# The Center — Office Tools

A small desktop app for new office members. The home page shows a grid of
tiles (a "waffle") — one per HTML guide in the `html/` folder — and clicking
a tile opens it right inside the app:

- Plain guides open in a lightweight built-in viewer
  ([tkinterweb](https://github.com/Andereoo/TkinterWeb)).
- Interactive HTML tools (anything with real JavaScript, like a calculator
  or reconciliation tool) open in their own native window powered by
  [pywebview](https://pywebview.flowrl.com/), which uses the OS's real web
  engine (WebKit on Mac, WebView2 on Windows) — full JavaScript, file
  uploads, and downloads all work. The launcher window stays open the
  whole time; the tool just opens alongside it in its own window. If
  pywebview isn't installed, those tools fall back to opening in the
  default web browser instead.

Built with [CustomTkinter](https://customtkinter.tomschimansky.com/) for
the interface.

The window opens with a white banner showing the real logo, the "The
Center" wordmark in navy, and an "Office Tools" tagline in cyan underneath.

## Download and run (easiest way — no setup required)

Every push to `main` automatically builds fresh Windows and Mac versions
and publishes them to this repo's **Releases** page, bundled together
with the `html/` and `assets/` folders — ready to run right out of the
zip, no Python or command line needed.

1. On GitHub, click **Releases** (right-hand sidebar of the repo page,
   or go directly to the repo's `/releases/latest` URL).
2. Under **Assets**, download the zip for your OS:
   - `TheCenterOfficeLauncher-Windows.zip`
   - `TheCenterOfficeLauncher-Mac.zip`
3. Unzip it. You'll get a folder containing the app plus its `html/` and
   `assets/` folders, already sitting together correctly.
4. Run it:
   - **Windows**: double-click `TheCenterOfficeLauncher.exe`. Windows
     SmartScreen may warn about an unrecognized app the first time —
     click **More info** → **Run anyway**.
   - **Mac**: **right-click** `TheCenterOfficeLauncher.app` and choose
     **Open** (don't just double-click the first time) — macOS blocks
     unsigned apps by default; this one-time right-click bypasses that.
     Then optionally drag it into `/Applications` along with the
     `html/` and `assets/` folders from the same unzipped download.

That's it — no `pip install`, no PyInstaller, no manual folder assembly.
Anyone updating the documents just needs to edit files in `html/` and
push to `main`; the next release will include the changes automatically.

## Folder contents

```
TheCenterOfficeLauncher/
├── launcher.py       # the app
├── html/             # documents shown in the launcher (edit/add freely)
│   ├── 01_welcome.html
│   ├── 02_how_it_works.html
│   ├── 03_faq.html
│   └── 04_contacts.html
├── assets/           # optional: drop a real logo.png here (see below)
└── README.md          # this file
```

## Running it (from source)

Requires Python 3.8+. Install the three dependencies once (this also pulls
in Pillow, which CustomTkinter needs for images):

```
pip install customtkinter tkinterweb pywebview
```

Then run:

```
python3 launcher.py
```

If `customtkinter` isn't installed, the app prints the install command
above and exits cleanly instead of crashing. If `tkinterweb` isn't
installed, guides just open in the browser instead of the in-app viewer.
If `pywebview` isn't installed, interactive tools open in the browser
instead of their own window. Nothing ever crashes over a missing optional
dependency — it just falls back to the browser.

## Adding or updating documents

No code changes needed:

1. Drop an `.html` file into the `html/` folder.
2. Optional: prefix the filename with a number to control its order in the
   list, e.g. `01_Welcome.html`, `02_FAQ.html`. The number is stripped from
   the on-screen name.
3. Optional: set `<title>Your Title</title>` in the file's `<head>` — the
   launcher shows that instead of the filename.
4. Click **Refresh** in the app (or restart it) to see the change.

To remove a document, delete its file from `html/`.

## Adding a real logo

Right now the banner shows a simple round placeholder mark (a colored
circle with "T"). To replace it:

1. Save a square image (PNG or JPG), ideally around 120×120px with a
   transparent background, as `assets/logo.png` (or `logo.jpg`).
2. Restart the launcher. It's picked up automatically — no code changes.

If no logo file is found, the placeholder mark is shown instead, so the
app always looks finished.

## Building manually (for developers — most people won't need this)

The Releases page above already gives you a working build. This section
is only for building a copy yourself — e.g. testing a change before
pushing, or if GitHub Actions isn't available to you.

Use [PyInstaller](https://pyinstaller.org/) to build a single executable
that colleagues can double-click without installing Python.

```
pip install pyinstaller customtkinter tkinterweb pywebview
```

**Windows** — produces `dist/TheCenterOfficeLauncher.exe`:

```
pyinstaller --onefile --windowed --collect-all customtkinter --collect-all tkinterweb --collect-all tkinterweb_tkhtml --name "TheCenterOfficeLauncher" launcher.py
```

**Mac** — produces `dist/TheCenterOfficeLauncher.app`:

```
pyinstaller --windowed --collect-all customtkinter --collect-all tkinterweb --collect-all tkinterweb_tkhtml --name "TheCenterOfficeLauncher" launcher.py
```

The `--collect-all customtkinter` flag is required — CustomTkinter ships
its own theme and font files that PyInstaller won't find automatically.
Likewise, `--collect-all tkinterweb --collect-all tkinterweb_tkhtml` is
required for the in-app document viewer — tkinterweb ships a compiled
Tkhtml engine per platform that PyInstaller won't find automatically.
`pywebview` doesn't need a `--collect-all` flag — it ships its own
PyInstaller hook that's picked up automatically. Any of these three can be
missing without the app crashing: guides and tools just fall back to
opening in the browser instead of rendering in-app / their own window.

Add `--icon=youricon.ico` (Windows) or `--icon=youricon.icns` (Mac) if you
have a custom icon.

### Important: keep the html/ folder next to the built app

The packaged app looks for an `html` folder in the **same directory as the
executable** — not bundled inside it — so it stays editable after packaging.
After building, copy your `html/` folder next to the executable:

```
dist/
├── TheCenterOfficeLauncher.exe   (or .app on Mac)
├── html/
│   ├── 01_welcome.html
│   ├── 02_how_it_works.html
│   └── ...
└── assets/
    └── logo.png
```

Ship the whole `dist/` folder (executable + `html/` + `assets/` folders
together) to new office members. They can add or edit `.html` files, or
drop in a real `logo.png`, at any time without needing you to rebuild
anything.

### Installing the Mac .app in your Applications folder

You can move `TheCenterOfficeLauncher.app` into `/Applications` (or your
personal `~/Applications` folder) like any other Mac app. The `html/` and
`assets/` folders need to move there too, sitting right next to the
`.app` icon — the app looks for them next to itself, not inside its own
bundle:

```
/Applications/
├── TheCenterOfficeLauncher.app
├── html/
│   ├── 01_welcome.html
│   └── ...
└── assets/
    └── logo.png
```

So after building: drag `dist/TheCenterOfficeLauncher.app` and copy
`dist/html/` and `dist/assets/` all into `/Applications` together. From
there it opens like any other Mac app — Launchpad, Spotlight, or a dock
icon all work normally.

## Using the app (for end users)

This is also built into the app via the **"How to Use This Launcher"**
button, so new hires can self-serve:

1. Click any tile on the home page to open it right in the app.
2. Tiles marked **"Opens in a tool window"** are interactive tools that need
   real JavaScript to run — clicking them opens a separate window for that
   tool (or your default browser, if pywebview isn't installed).
3. Use **← Back to Home** (top left of a document) to return to the tiles.
4. Use **Search** to filter the tiles by name.
5. If an expected document is missing, ask an admin to add it to `html/`,
   then click **Refresh**.
