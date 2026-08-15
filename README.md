# The Center — Office Tools

A small desktop app for new office members. It opens to a Home page
explaining what the app is for and how to use it. A sidebar on the left
(collapsible via the arrow at its top) lists every HTML guide in the
`html/` folder; clicking one shows it in the main pane on the right,
right inside the app:

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
and publishes them to this repo's **Releases** page — ready to run right
out of the zip, no Python or command line needed.

1. On GitHub, click **Releases** (right-hand sidebar of the repo page,
   or go directly to the repo's `/releases/latest` URL).
2. Under **Assets**, download the zip for your OS:
   - `TheCenterOfficeLauncher-Windows.zip`
   - `TheCenterOfficeLauncher-Mac.zip`
3. Unzip it.
4. Run it:
   - **Windows**: double-click `TheCenterOfficeLauncher.exe`. Windows
     SmartScreen may warn about an unrecognized app the first time —
     click **More info** → **Run anyway**. The unzipped folder has the
     `.exe` plus `html/` and `assets/` next to it; keep them together
     and the whole folder stays portable (a USB stick, a shared drive).
   - **Mac**: the zip contains just `TheCenterOfficeLauncher.app`.
     Drag it into `/Applications`, then **right-click** it and choose
     **Open** the first time (don't just double-click) — macOS blocks
     unsigned apps by default. If it still refuses, open **System
     Settings → Privacy & Security** and click **Open Anyway** next to
     its name.

That's it — no `pip install`, no PyInstaller, no manual folder assembly.
Anyone updating the documents just needs to edit files in `html/` and
push to `main`; the next release will include the changes automatically.

### Where the Mac app keeps its files

The Mac app stores its data in `~/Library/Application Support/The Center
Office App/` — the standard place Mac apps put this sort of thing. That
folder holds `html/`, `assets/`, `settings.json`, and
`error_log.txt`. (Earlier versions also kept `users.json` and
`shared_preferences.json` here; accounts and preferences both live in
Firebase now, so those files are no longer created or read.)

To open it in Finder: **Go** menu → **Go to Folder…** → paste
`~/Library/Application Support/The Center Office App`.

Earlier versions kept all of that in `/Applications`, right next to the
app icon, which left six stray items sitting among the user's real
applications. The app now moves them automatically the first time a
newer build runs — nothing is lost, and anything already edited wins
over the copies bundled in the app, so guide pages edited via **Edit
This Page** survive updates. Fresh installs get starter copies from
inside the app bundle instead.

Windows is unchanged and still fully portable: the `.exe` reads `html/`
and `assets/` from its own folder.

### Updating an already-installed Mac app without using a browser

`scripts/update_app.command` does steps 1–4 above in one go: double-click
it in Finder (or run it in Terminal) any time after pushing a code change,
and it downloads the latest Mac build, quits the app if it's open, and
replaces the one in `/Applications` — no manual zip download or dragging
files around. It only ever touches the app itself, never the data folder
described above.

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

Edit the `html/` folder **in this repository**, then push. That single
change reaches the desktop app and the mobile site together.

1. Add or edit an `.html` file in `html/`.
2. Optional: prefix the filename with a number to control its order in the
   list, e.g. `01_Welcome.html`, `02_FAQ.html`. The number is stripped from
   the on-screen name.
3. Optional: set `<title>Your Title</title>` in the file's `<head>` — the
   launcher shows that instead of the filename.
4. Push to `main`. The mobile site rebuilds automatically; the desktop app
   picks the change up next time `scripts/update_app.command` is run.

To remove a document, delete its file from `html/` and push.

**Don't edit the installed copy by hand.** A packaged Mac app reads
`~/Library/Application Support/The Center Office App/html/`, and editing
a file there changes that one machine only — every other computer and the
phone site stay on the old text. That is exactly how the two drifted
apart once already. The repo is the source of truth.

## Mobile / web access

There's also a phone-friendly web version of this same content — install
it to an iPhone or Android home screen and it opens full-screen like a
real app, no App Store or Play Store needed.

- Source lives in `web/` (the site shell) and `scripts/build_site.py`
  (which mirrors `html/` alongside it and generates the sidebar list).
- **One-time setup**: in this repo's **Settings → Pages**, set **Source**
  to **GitHub Actions**. After that, every push to `main` that touches
  `html/`, `web/`, or the logo automatically rebuilds and republishes the
  site via the "Build and deploy mobile site" workflow
  (`.github/workflows/pages.yml`) — usually live within a couple of
  minutes of the push.
- Once Pages is turned on, the site is reachable at
  `https://thecenterdev.github.io/The-Center-Office-App/` (GitHub shows
  the exact URL under Settings → Pages once it's enabled).
- To install it: open that URL on a phone, then use the browser's
  **Add to Home Screen** option (Safari: Share → Add to Home Screen;
  Chrome on Android: menu → Add to Home screen / Install app).
- Editing documents works exactly the same as above — the mobile site
  reads the same `html/` files, so there's nothing extra to maintain.
- The site requires signing in — see "Mobile login and accounts" below.

## One account, everywhere

The desktop app and the mobile site now share a single set of accounts,
roles, and personal display settings, stored in the same free Firebase
project. Sign in with the same email and password in either place.

What that changes, compared to how the desktop app used to work:

- **No more `users.json`.** Accounts used to live in a file next to the
  app, so every computer had its own separate copy — someone added on
  one machine simply didn't exist on another, and a password changed in
  one place didn't change anywhere else. That file is now ignored; if
  one is still lying around it does nothing.
- **No more shared `director` / `admin` / `staff` logins.** Those had
  their passwords written in plain text in `launcher.py`, which is in a
  public repository that also publishes the staff Contacts page — the
  email addresses and the passwords were both published. Everyone signs
  in as themselves now.
- **Nobody can look up anyone's password, including a Director.**
  Firebase stores passwords hashed and won't return them to the app, to
  the console, or to anyone. The Team page's old "Show password" and
  "Change Password" controls are replaced with **Send Reset Email**,
  which mails that person a link to set their own.
- **Your theme and text size follow you.** Change them on one computer
  and they apply on every other one, and on the mobile site.
- **The app needs an internet connection to sign in.** It talks to
  Firebase at the login screen. Once you're in, reading guides works
  normally; sign-in itself won't work offline.

**Everyone must reset their password once.** The desktop passwords that
used to live in `users.json` were never the same as the Firebase ones,
and can't be transferred (they were plain text on one side, hashed on
the other). So the first time anyone opens the updated desktop app:
enter your email, click **Forgot password?**, and follow the link
Firebase emails you. That same password then works on the mobile site
too. Check spam the first time — it comes from a firebaseapp.com
address.

## Mobile login and accounts

The mobile site is backed by a free Firebase project (Authentication +
Firestore) for login and per-person settings sync — see `web/auth.js`
and `firestore.rules`. It's a separate system from the desktop app's
`users.json`; the two don't share a live connection, so someone needs
an account in both places to use both apps.

**One-time backend setup** (already done for this project, listed here
in case it's ever needed again — e.g. a new Firebase project):

1. Create a Firebase project at [console.firebase.google.com](https://console.firebase.google.com),
   enable **Authentication → Email/Password**, and create a **Firestore
   Database**.
2. Register a **Web app** under Project settings → Your apps, and paste
   its `firebaseConfig` values into `web/firebase-config.js`.
3. Paste the contents of `firestore.rules` (repo root) into **Firestore
   Database → Rules** in the console and publish it.
4. **Bootstrap the first account**: the security rules only let an
   existing Admin/Director create other people's profiles, so the very
   first one has to be added by hand once. In the console, go to
   **Firestore Database → Data → Start collection** → collection ID
   `users` → document ID: your email, all lowercase (e.g.
   `dev@thecentercc.com`) → add fields `name` (string), `role` (string,
   set to `director`), and `preferences` (map, can be left empty `{}`).
   Also add that same email under **Authentication → Add user** with a
   password. After that, everyone else can be added through the app's
   Team page instead of the console.

**How people get their first password.** There isn't a shared one, and
nobody hands out passwords. Each person opens the mobile site, types
their email address, and taps **Forgot password?** — Firebase emails
them a link to choose their own. (Worth telling people to check their
spam folder the first time; the mail comes from a firebaseapp.com
address.) After that they can change it any time in **Settings →
Security**.

**Adding a new staff member** (the normal, ongoing way — no console
work beyond step 1):

1. Firebase console → **Authentication → Add user** → enter their email
   and any throwaway password. This just creates the account; they'll
   replace the password themselves via Forgot password?.
2. In the mobile site, **Settings → Team** (Admin/Director only) → enter
   their email, name, and role, → **Save**. This is what tells the app
   who they are and what they're allowed to see.
3. Point them at the site and tell them to use **Forgot password?**.

**Fixing everyone's roles at once.** If the roles in Firestore drift out
of step with `scripts/staff-list.json`, run the **Set staff roles**
workflow from the Actions tab. It only writes roles — passwords are left
alone unless a `STAFF_SHARED_PASSWORD` secret exists, which normally it
shouldn't.

There's no self-service sign-up anywhere in the app on purpose — both
steps above are deliberately manual and Admin/Director-only.

**Changing passwords:** everyone can change their own from Settings →
Security, once signed in. Admin/Director can also do it for someone
else from the Team page — a **Reset password** button next to each
person sends them Firebase's standard password-reset email. (There's
no button that directly *sets* someone else's password to a chosen
value — that would need a real backend function, i.e. Firebase Cloud
Functions, which unlike everything else this project uses isn't
available on the no-cost Spark plan. The reset-email approach stays
entirely free.)

## Bulk-creating logins (script)

Doing the two steps above one person at a time is fine for a single new
hire, but tedious for a whole staff list. `scripts/create_logins.js`
does both steps for everyone in `scripts/staff-list.json` in one go —
safe to re-run any time (it skips anyone who already has a login).

Everyone it creates gets the `staff` role by default; promote anyone
who needs Admin or Director access afterward from **Settings → Team**.

**One-time setup:**

1. Firebase console → gear icon (top left, next to "Project Overview")
   → **Project settings** → **Service accounts** tab → **Generate new
   private key** → **Generate key**. This downloads a JSON file — it's
   a master key to the whole project, so don't share it or post it
   anywhere.
2. Rename the downloaded file to `service-account.json` and put it in
   this project's `scripts/` folder. (It's already excluded from Git,
   so it can never accidentally get uploaded to GitHub.)
3. Install [Node.js](https://nodejs.org) if it isn't already on your
   computer, then in Terminal, `cd` into this project folder and run
   once: `npm install firebase-admin`

**To create the logins:**

1. Open `scripts/staff-list.json` and check the name/email list is
   current — add a `{ "name": "...", "email": "..." }` entry for anyone
   new, or remove someone who's left.
2. In Terminal, from this project folder, run: `node scripts/create_logins.js`
3. It prints what it did, and writes a `scripts/login-links-<date>.txt`
   file with one personal "set your password" link per new person.
   Send each person their own link (text or email) — they click it,
   choose a password, and can then sign into the mobile site with their
   email and that password.

You can delete `scripts/service-account.json` when done, or leave it —
just never commit it. Generate a fresh one from the console any time.

## Shared data in the interactive tools

The interactive tools save to the same Firebase project as login,
instead of each device's own browser storage:

- **Building Maintenance Log** → `maintenance_log`
- **New Hire Onboarding Tracker** → `onboarding_hires` (each hire's
  progress) and `onboarding_template` (the checklist itself)
- **Calendar** → `calendar_events`
- **Notes** → `notes`
- **Count Log** → `count_log`
- **Reporting Calendar** → `reporting_calendar`

**Program Timer** is the exception and deliberately so: no sign-in, no
database, nothing saved beyond the station list in that browser. It has
to work in a room with no internet.

### Editing the onboarding checklist

The checklist used to be fixed in the page's code, so changing it meant
editing a file and shipping a new build. It now lives in the database
and is edited in the app: open the New Hire Onboarding Tracker and click
**Edit Checklist**. You can add, rename, and delete both sections and
individual items, plus an optional note under any item. Nothing saves
until you click **Save Checklist**, and **Cancel** discards cleanly.

Edits apply everywhere at once — every computer, the mobile site, and
every hire's checklist, current and future.

Two details worth knowing:

- **Rewording an item keeps whoever already ticked it ticked.** Each
  item has a hidden id that stays the same when you change its wording,
  which is what preserves progress. Deleting an item and adding a
  replacement instead creates a genuinely new item, unticked for
  everyone.
- **Deleting an item doesn't disturb past hires' records.** Their old
  ticks are simply no longer shown.

**Only Admin and Director can edit it** — the button is hidden from
everyone else, and `firestore.rules` enforces it on the server, so it
holds even for someone who works around the page itself. Everyone can
still tick boxes and add per-hire "Additional Items", which apply to
that one person only.

Any signed-in person with a profile can read, add, edit, or delete in
the maintenance log and the onboarding tracker — the same flat
permissions the old single-device versions had,
just shared live across everyone now instead of stuck on one browser.
See `firestore.rules` for the exact rule (unchanged from the login
rules otherwise; just two new collections added at the bottom).

### Maintenance requests go to Todoist automatically

New Building Maintenance Log entries are turned into tasks in the
Todoist **Facilities - TCWCY** project, roughly every 5 minutes, by
`.github/workflows/todoist-sync.yml` running `scripts/sync_todoist.js`.

Each task gets the location and issue as its title, and location,
urgency, reporter, and date in the description. Urgency maps to Todoist
priority, so Urgent items land at P1 and sort to the top.

**Why it's a scheduled job and not instant.** A Todoist *personal* API
token grants full access to the entire account — Todoist's add-only
permission (`task:add`) exists for OAuth apps only, not personal tokens.
The Maintenance Log is a public web page, so a token placed in it could
be read by anyone who opens the site. Running the sync in GitHub Actions
keeps the token in encrypted secrets, where no browser ever sees it.

**Duplicates can't happen.** Once an entry is sent, its Firestore
document gets a `todoistTaskId` field written back, and anything with
that field is skipped from then on. The workflow also uses a
concurrency group so two runs can't overlap.

**One-time setup** — in the repo, go to **Settings → Secrets and
variables → Actions → New repository secret**, and add two:

| Secret name | Value |
| --- | --- |
| `TODOIST_API_TOKEN` | Todoist → Settings → Integrations → Developer → your API token |
| `FIREBASE_SERVICE_ACCOUNT` | The entire contents of a Firebase service account JSON key (Firebase console → Project settings → Service accounts → Generate new private key) |

Then go to the **Actions** tab → **Send maintenance requests to
Todoist** → **Run workflow** to test it without waiting for the
schedule. The run log lists exactly what it sent.

To point it at a different Todoist project, either edit
`DEFAULT_PROJECT_ID` in `scripts/sync_todoist.js` or add a
`TODOIST_PROJECT_ID` secret. The ID is the last part of the project's
URL — for `.../project/facilities-tcwcy-td-6CrfG2HXhxfV58Qw` it's
`6CrfG2HXhxfV58Qw`.

**Photos aren't synced.** The Maintenance Log's photo field was removed
rather than half-supported — Firestore documents cap out around 1 MB,
and a synced-photo feature really wants Firebase Storage instead, which
(as of this writing) requires linking a billing account to enable, even
though usage would stay within the free allowance. Since staying
entirely card-free was the point, photos are left out for now; email
one separately if a maintenance issue needs one.

**One sign-in on the desktop, too.** These tools open in their own
pywebview window, and for a while that meant signing in twice: once into
the launcher and again into each tool. The launcher now hands its
session to the tool it opens, passed through the process environment and
into the page as a URL fragment (fragments are never sent to a server),
so a tool opened from the launcher is already signed in as you. Opened
directly in a browser, the same page still shows its own sign-in. See
`html/center-session.js`.

## Firestore security rules

`firestore.rules` is the live rule set, not a copy of it. Pushing a
change to that file on `main` publishes it to the database, via
`.github/workflows/firestore-rules.yml`.

It used to say "paste this into the Firebase console", and the
predictable happened: a new tool would ship with its collection but
without its permissions, and the tool would answer *"Missing or
insufficient permissions"* until someone remembered the second step. The
security model shouldn't depend on remembering.

- Changing the rules in the console still works, but the next push that
  touches `firestore.rules` overwrites it. Change the file.
- The workflow reuses the `FIREBASE_SERVICE_ACCOUNT` secret the Todoist
  sync already uses. The key is written to the runner's temp directory,
  never echoed, never inside the checkout, and deleted afterwards.
- **If the deploy fails with a permissions error**, that service account
  needs the **Firebase Rules Admin** role: Google Cloud console → IAM →
  find the service account → Edit → Add role. The Admin SDK key doesn't
  always come with it.
- To publish without changing anything: Actions → **Publish Firestore
  rules** → Run workflow.

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

Both Windows and Mac now build from the same `launcher.spec` file (it
branches on the OS internally), so the command is identical on either
platform:

```
pyinstaller launcher.spec --noconfirm
```

This produces `dist/TheCenterOfficeLauncher.exe` on Windows and
`dist/TheCenterOfficeLauncher.app` on Mac.

Why a `.spec` file instead of a plain `pyinstaller launcher.py ...`
command with flags: PyInstaller's CLI has no flag for setting custom
`Info.plist` keys, and this app needs one — `NSHighResolutionCapable` —
so macOS renders it at full Retina resolution. Without it, macOS silently
upscales the whole app (the Tkinter UI, the tkinterweb guide viewer, and
the pywebview tool windows, since they're all part of the same process)
into a blurry, low-resolution image. `launcher.spec` also handles what
the old flags used to do — `--collect-all customtkinter`/`tkinterweb`/
`tkinterweb_tkhtml` (needed because those packages ship theme, font, and
compiled-engine files PyInstaller won't find automatically; `pywebview`
ships its own PyInstaller hook and doesn't need this) and `--icon=` to
set the Dock/Finder/Launchpad/taskbar icon to the real logo — so all of
that configuration now lives in one place and stays in sync between local
builds and CI. Any of the three collected packages can be missing without
the app crashing: guides and tools just fall back to opening in the
browser instead of rendering in-app / their own window.

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

1. Click **Home** at the top of the sidebar any time to return to the
   welcome overview of what the app is for, or **Apps** for a dedicated
   list of every interactive tool.
2. Click any other item in the sidebar to open it in the main pane.
3. Items marked with **↗** are interactive tools that need real JavaScript
   to run — they show an **Open Tool** button (or **Open in Browser**, if
   pywebview isn't installed) instead of rendering in the built-in viewer.
4. Use **Search** to filter the list by name, or the arrow at the top of
   the sidebar to collapse it out of the way.
5. If an expected document is missing, ask an admin to add it to `html/`,
   then click **Refresh** at the bottom of the sidebar.
