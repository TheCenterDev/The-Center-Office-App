# The Center — Office Tools

A small desktop app for new office members. A sidebar on the left lists
every HTML guide in the `html/` folder; clicking one shows it in the main
pane on the right, right inside the app:

- Plain guides open in a lightweight built-in viewer
  ([tkinterweb](https://github.com/Andereoo/TkinterWeb)).
- Interactive HTML tools (anything with real JavaScript, like a calculator
  or reconciliation tool) show an "Open Tool" card instead. Clicking it
  opens the tool in its own native window powered by
  [pywebview](https://pywebview.flowrl.com/), which uses the OS's real web
  engine (WebKit on Mac, WebView2 on Windows) — full JavaScript, file
  uploads, and downloads all work. The launcher window stays open the
  whole time; the tool just opens alongside it in its own window. If
  pywebview isn't installed, those tools fall back to opening in the
  default web browser instead.

Built with [CustomTkinter](https://customtkinter.tomschimansky.com/) for
the interface.

The sidebar is navy with a white header showing the real logo, the "The
Center" wordmark, and an "Office Tools" tagline in cyan. The main pane is
white; the currently open item is highlighted in the sidebar.

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

## Adding or replacing the logo

The sidebar header and welcome screen show the real Center logo from
`assets/logo.png`. To replace it:

1. Save an image (PNG or JPG, transparent background recommended) as
   `assets/logo.png` (or `logo.jpg`). It doesn't need to be square — it's
   drawn at a fixed height with its real aspect ratio preserved.
2. Restart the launcher. It's picked up automatically — no code changes.

If no logo file is found, a plain placeholder mark (a colored circle with
"T") is shown instead, so the app always looks finished either way.

## The app icon (Dock / Finder / taskbar)

`assets/icon.icns` (Mac) and `assets/icon.ico` (Windows) are the app's
icon files, built from the real logo — this is what shows up in the Dock,
Finder, Launchpad, and the Windows taskbar, as opposed to `assets/logo.png`
which is what's drawn inside the app's own banner. Both are already wired
into the GitHub Actions workflow and the manual PyInstaller commands below
via the `--icon` flag, so every build already uses them.

To replace it with a different image, regenerate both files from a square
source PNG (ideally 1024×1024) and rebuild:

```
pip install pillow icnsutil
python3 -c "
from PIL import Image
src = Image.open('your_square_logo.png')
src.save('assets/icon.ico', sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
"
python3 -c "
from PIL import Image
import icnsutil, tempfile, os
src = Image.open('your_square_logo.png')
sizes = {'icon_16x16.png': 16, 'icon_16x16@2x.png': 32, 'icon_32x32.png': 32,
         'icon_32x32@2x.png': 64, 'icon_128x128.png': 128, 'icon_128x128@2x.png': 256,
         'icon_256x256.png': 256, 'icon_256x256@2x.png': 512, 'icon_512x512.png': 512,
         'icon_512x512@2x.png': 1024}
tmp = tempfile.mkdtemp()
icns = icnsutil.IcnsFile()
for name, size in sizes.items():
    p = os.path.join(tmp, name)
    src.resize((size, size), Image.LANCZOS).save(p)
    icns.add_media(file=p)
icns.write('assets/icon.icns')
"
```

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
pyinstaller --onefile --windowed --icon=assets/icon.ico --collect-all customtkinter --collect-all tkinterweb --collect-all tkinterweb_tkhtml --name "TheCenterOfficeLauncher" launcher.py
```

**Mac** — produces `dist/TheCenterOfficeLauncher.app`:

```
pyinstaller --windowed --icon=assets/icon.icns --collect-all customtkinter --collect-all tkinterweb --collect-all tkinterweb_tkhtml --name "TheCenterOfficeLauncher" launcher.py
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

`--icon=assets/icon.ico` / `--icon=assets/icon.icns` set the app's Dock,
Finder, Launchpad, and taskbar icon to the real logo (see "The app icon"
above) — leave these off if you'd rather use PyInstaller's generic default.

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

1. Click any item in the sidebar to open it in the main pane.
2. Items marked with **↗** are interactive tools that need real JavaScript
   to run — they show an **Open Tool** button (or **Open in Browser**, if
   pywebview isn't installed) instead of rendering in the built-in viewer.
3. Use **Search** at the top of the sidebar to filter the list by name.
4. If an expected document is missing, ask an admin to add it to `html/`,
   then click **Refresh** at the bottom of the sidebar.
