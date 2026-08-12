/*
 * Bulk-create mobile site logins for everyone in scripts/staff-list.json.
 *
 * What it does, for each person in the list:
 *   1. Creates their Firebase Authentication account (email + a random
 *      password nobody ever sees), if one doesn't already exist.
 *   2. Creates their app profile in Firestore (users/{email}: name,
 *      role, default preferences), if one doesn't already exist. Never
 *      overwrites an existing profile, so re-running this is always
 *      safe -- e.g. next time someone new is hired, just add them to
 *      staff-list.json and run this again; everyone else is skipped.
 *   3. Generates a one-time "set your password" link for each newly
 *      created account and writes all of them to a
 *      scripts/login-links-<timestamp>.txt file. Send each person their
 *      own link (text or email); they click it, choose a password, and
 *      can then sign in at the mobile site with their email + that
 *      password.
 *
 * Everyone is created with role "staff". If someone needs Admin or
 * Director access (so they can manage the Team list themselves), sign
 * into the mobile site yourself and promote them from Settings -> Team.
 *
 * One-time setup before running this:
 *   1. Firebase console -> gear icon (top left) -> Project settings ->
 *      Service accounts tab -> "Generate new private key" -> Generate
 *      key. This downloads a JSON file.
 *   2. Rename it to service-account.json and put it in this same
 *      scripts/ folder. (It's already in .gitignore -- it will never
 *      be committed. Never share this file; it's a master key to the
 *      whole project.)
 *   3. In Terminal: cd into the project folder, then run once:
 *        npm install firebase-admin
 *
 * Then run it with:
 *   node scripts/create_logins.js
 *
 * When you're done, it's fine to delete scripts/service-account.json
 * (you can always generate a new one later) -- keeping it around just
 * means you won't have to repeat step 1 next time you hire someone.
 */

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

const SERVICE_ACCOUNT_PATH = path.join(__dirname, "service-account.json");
const STAFF_LIST_PATH = path.join(__dirname, "staff-list.json");

if (!fs.existsSync(SERVICE_ACCOUNT_PATH)) {
  console.error(
    "\nCouldn't find scripts/service-account.json.\n" +
      "Download it from the Firebase console first -- see the instructions\n" +
      "at the top of this file (scripts/create_logins.js) -- then try again.\n"
  );
  process.exit(1);
}

let admin;
try {
  admin = require("firebase-admin");
} catch (e) {
  console.error(
    '\nMissing dependency. Run "npm install firebase-admin" in this folder first.\n'
  );
  process.exit(1);
}

const staffList = JSON.parse(fs.readFileSync(STAFF_LIST_PATH, "utf8"));

admin.initializeApp({
  credential: admin.credential.cert(require(SERVICE_ACCOUNT_PATH)),
});

const auth = admin.auth();
const db = admin.firestore();

const DEFAULT_PREFERENCES = {
  theme: "light",
  font_scale: "normal",
  default_page: "home",
  sidebar_expanded: true,
};

function randomPassword() {
  // Nobody needs to know this -- each new account gets a password reset
  // link instead, so the person picks their own password on first use.
  return crypto.randomBytes(18).toString("base64");
}

async function ensureAuthUser(name, email) {
  try {
    const existing = await auth.getUserByEmail(email);
    return { user: existing, created: false };
  } catch (e) {
    if (e.code !== "auth/user-not-found") throw e;
  }
  const created = await auth.createUser({
    email,
    password: randomPassword(),
    displayName: name,
  });
  return { user: created, created: true };
}

async function ensureProfile(name, email, role) {
  const key = email.trim().toLowerCase();
  const ref = db.collection("users").doc(key);
  const snap = await ref.get();
  if (snap.exists) return false;
  await ref.set({
    name,
    role: role || "staff",
    preferences: DEFAULT_PREFERENCES,
  });
  return true;
}

async function main() {
  const links = [];
  let createdCount = 0;
  let skippedCount = 0;

  for (const person of staffList) {
    const name = person.name;
    const email = String(person.email).trim().toLowerCase();
    if (!name || !email) {
      console.warn("Skipping entry with missing name/email:", person);
      continue;
    }

    const { created } = await ensureAuthUser(name, email);
    const profileCreated = await ensureProfile(name, email, person.role);

    if (created) {
      const link = await auth.generatePasswordResetLink(email);
      links.push({ name, email, link });
      createdCount++;
      console.log(`Created login for ${name} <${email}>`);
    } else {
      skippedCount++;
      console.log(`Already had a login, left alone: ${name} <${email}>`);
    }

    if (created && !profileCreated) {
      // Shouldn't normally happen (a brand-new auth user with an
      // already-existing profile), but if it does, nothing's broken --
      // they just won't need re-adding on the Team page.
    }
  }

  if (links.length > 0) {
    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    const outPath = path.join(__dirname, `login-links-${stamp}.txt`);
    const body = links
      .map((l) => `${l.name} <${l.email}>\n${l.link}\n`)
      .join("\n");
    fs.writeFileSync(outPath, body, "utf8");
    console.log(`\nWrote ${links.length} personal sign-in link(s) to:\n  ${outPath}`);
    console.log(
      "Send each person their own link (text or email). They'll click it,\n" +
        "set a password, then can sign into the mobile site with their email\n" +
        "and that password."
    );
  }

  console.log(`\nDone. ${createdCount} created, ${skippedCount} already existed.`);
}

main().catch((err) => {
  console.error("\nSomething went wrong:", err.message || err);
  process.exit(1);
});
