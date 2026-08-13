#!/bin/bash
# Double-click this file in Finder (or run it in Terminal) any time to grab
# the newest build of TheCenterOfficeLauncher and install it in /Applications
# -- no browser, no manual zip download needed.
#
# What it does:
#   1. Downloads the latest Mac build from this repo's GitHub Releases.
#   2. Quits the app if it's currently open.
#   3. Replaces /Applications/TheCenterOfficeLauncher.app with the new one.
#
# What it deliberately does NOT touch: html/, assets/, users.json,
# settings.json, or any other files sitting next to the app in
# /Applications. Those are managed separately (edited directly, or synced
# by hand from this repo) -- this script only ever replaces the app itself.

set -e

REPO="TheCenterDev/The-Center-Office-App"
ASSET_NAME="TheCenterOfficeLauncher-Mac.zip"
APP_NAME="TheCenterOfficeLauncher.app"
DEST_DIR="/Applications"

echo "Downloading the latest build..."
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

curl -L --fail -o "$TMP_DIR/$ASSET_NAME" \
  "https://github.com/$REPO/releases/latest/download/$ASSET_NAME"

echo "Unzipping..."
unzip -o -q "$TMP_DIR/$ASSET_NAME" -d "$TMP_DIR/unzipped"

NEW_APP=$(find "$TMP_DIR/unzipped" -maxdepth 3 -iname "*.app" | head -n 1)
if [ -z "$NEW_APP" ]; then
  echo "Couldn't find $APP_NAME inside the downloaded zip -- stopping without changing anything."
  exit 1
fi

echo "Closing the app if it's open..."
osascript -e "quit app \"TheCenterOfficeLauncher\"" >/dev/null 2>&1 || true
sleep 1

echo "Installing the new version..."
rm -rf "$DEST_DIR/$APP_NAME"
cp -R "$NEW_APP" "$DEST_DIR/"

echo ""
echo "Done. $APP_NAME has been updated in $DEST_DIR."
echo "If macOS still shows an 'Apple could not verify' warning the first"
echo "time you open it, see System Settings -> Privacy & Security for an"
echo "'Open Anyway' button next to its name."
read -p "Press Return to close this window..."
