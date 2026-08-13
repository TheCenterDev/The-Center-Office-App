# PyInstaller spec file for TheCenterOfficeLauncher.
#
# Why a .spec file instead of a plain `pyinstaller launcher.py ...` command:
# the CLI has no flag for custom Info.plist keys, and this app needs one --
# NSHighResolutionCapable -- to render at full Retina resolution on Mac.
# Without it, macOS silently upscales the whole app (Tkinter UI, the
# tkinterweb guide viewer, and the pywebview tool windows, since they're
# all part of the same process) into a blurry, low-resolution image.
#
# Build with:
#   pyinstaller launcher.spec --noconfirm
#
# This replaces the old `pyinstaller --windowed --icon=... --collect-all ...`
# commands -- all of that configuration now lives here instead, so local
# builds and CI stay in sync automatically.

import sys

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []
for pkg in ("customtkinter", "tkinterweb", "tkinterweb_tkhtml", "PIL"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports
    # pywebview ships its own PyInstaller hook (auto-discovered), so it
    # doesn't need collect_all here.
    #
    # PIL (Pillow) needs to be here too: launcher.py does a plain
    # `from PIL import Image, ImageDraw` wrapped in try/except ImportError
    # (see load_logo_image and friends), so a build missing Pillow's
    # compiled _imaging extension or its plugin modules doesn't crash --
    # it just silently disables the logo and every drawn icon (search,
    # team) with nothing in error_log.txt to explain why, since that's
    # exactly the failure mode the try/except was written to survive.
    # PyInstaller's static analysis can miss Pillow's dynamically-loaded
    # plugins without this explicit collect_all, which is what happened
    # to the build that shipped without a visible logo.

# Ship read-only copies of html/ and assets/ *inside* the app. These are
# never read directly at runtime -- they're only used to seed a fresh
# install's real data folder the first time it opens (see
# seed_data_dir_from_bundle in launcher.py), which is what lets the Mac
# app keep its data in ~/Library/Application Support instead of
# scattering html/, assets/, and four loose files across /Applications.
# An existing data folder is never overwritten, so guide pages edited
# in-app survive every update.
datas += [("html", "html"), ("assets", "assets")]

a = Analysis(
    ["launcher.py"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
)
pyz = PYZ(a.pure)

is_mac = sys.platform == "darwin"
icon_file = "assets/icon.icns" if is_mac else "assets/icon.ico"

if is_mac:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="TheCenterOfficeLauncher",
        debug=False,
        console=False,
        icon=icon_file,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        name="TheCenterOfficeLauncher",
    )
    app = BUNDLE(
        coll,
        name="TheCenterOfficeLauncher.app",
        icon=icon_file,
        bundle_identifier="com.thecentercc.officetools",
        info_plist={
            # The actual fix: without this, macOS renders the whole app
            # (Tkinter UI, in-app viewer, and pywebview tool windows --
            # all one process) at half resolution and upscales it, which
            # looks blurry/low quality on any Retina display.
            "NSHighResolutionCapable": True,
            "NSPrincipalClass": "NSApplication",
            "CFBundleShortVersionString": "1.0.0",
        },
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="TheCenterOfficeLauncher",
        debug=False,
        console=False,
        icon=icon_file,
    )
