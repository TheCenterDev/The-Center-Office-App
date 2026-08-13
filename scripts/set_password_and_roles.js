/*
 * Sets every account in staff-list.json to one shared password, and
 * force-updates their Firestore role to match staff-list.json (unlike
 * create_logins.js, which never touches an account that already
 * exists -- this one deliberately overwrites both).
 *
 * Easiest way to run it: GitHub -> Actions tab -> "Set staff passwords
 * and roles" -> Run workflow. No Terminal, no local setup; it uses the
 * repository secrets.
 *
 * To run it locally instead, you need the Firebase service account key
 * and the password in the environment -- neither is stored in this
 * repo:
 *   export STAFF_SHARED_PASSWORD="..."
 *   export FIREBASE_SERVICE_ACCOUNT="$(cat scripts/service-account.json)"
 *   node scripts/set_password_and_roles.js
 *
 * The password is read from the environment rather than written here
 * on purpose. This repo is what publishes the public mobile site, and
 * the staff email addresses are on the site's own Contacts page -- a
 * shared password committed alongside them would be everything an
 * outsider needs to sign in.
 */

const fs = require("fs");
const path = require("path");

const SHARED_PASSWORD = process.env.STAFF_SHARED_PASSWORD;

// Prefer the environment (GitHub Actions secret); fall back to a local
// service-account.json file for hand-runs.
const SERVICE_ACCOUNT_RAW = process.env.FIREBASE_SERVICE_ACCOUNT;
const SERVICE_ACCOUNT_PATH = path.join(__dirname, "service-account.json");
const STAFF_LIST_PATH = path.join(__dirname, "staff-list.json");

// No password set = roles-only mode, which is the normal case. Nobody's
// password is touched; people set their own via "Forgot password?" on
// the mobile site's sign-in screen, which has Firebase email them a
// link. Setting STAFF_SHARED_PASSWORD is the opt-in escape hatch for
// handing everyone the same temporary password instead.
const ROLES_ONLY = !SHARED_PASSWORD;

if (!ROLES_ONLY && SHARED_PASSWORD.length < 6) {
  console.error("\nFirebase requires passwords of at least 6 characters.\n");
  process.exit(1);
}

let serviceAccount;
if (SERVICE_ACCOUNT_RAW) {
  try {
    serviceAccount = JSON.parse(SERVICE_ACCOUNT_RAW);
  } catch (e) {
    console.error("\nFIREBASE_SERVICE_ACCOUNT isn't valid JSON:", e.message, "\n");
    process.exit(1);
  }
} else if (fs.existsSync(SERVICE_ACCOUNT_PATH)) {
  serviceAccount = require(SERVICE_ACCOUNT_PATH);
} else {
  console.error(
    "\nNo Firebase credentials. Either set the FIREBASE_SERVICE_ACCOUNT\n" +
      "environment variable (this is what the GitHub Actions run uses), or\n" +
      "put a service-account.json in the scripts/ folder -- see the\n" +
      "instructions at the top of create_logins.js.\n"
  );
  process.exit(1);
}

const admin = require("firebase-admin");
const staffList = JSON.parse(fs.readFileSync(STAFF_LIST_PATH, "utf8"));

admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
});

const auth = admin.auth();
const db = admin.firestore();

async function main() {
  console.log(
    ROLES_ONLY
      ? "Roles-only mode: nobody's password will be changed.\n"
      : "Applying the shared password and roles.\n"
  );

  for (const person of staffList) {
    const email = String(person.email).trim().toLowerCase();
    const role = person.role || "staff";

    let user;
    try {
      user = await auth.getUserByEmail(email);
    } catch (e) {
      console.warn(`No login exists yet for ${email}, skipping.`);
      continue;
    }

    if (!ROLES_ONLY) {
      await auth.updateUser(user.uid, { password: SHARED_PASSWORD });
    }
    await db.collection("users").doc(email).set({ role }, { merge: true });
    console.log(
      ROLES_ONLY
        ? `Set role "${role}" for ${person.name} <${email}>`
        : `Set password + role "${role}" for ${person.name} <${email}>`
    );
  }

  if (ROLES_ONLY) {
    console.log(
      "\nDone. To get in the first time, each person opens the mobile site,\n" +
        "types their email, and taps \"Forgot password?\" -- Firebase emails\n" +
        "them a link to choose their own password."
    );
  } else {
    // Deliberately not echoing the password itself -- this runs in
    // GitHub Actions, whose logs are readable by anyone who can see
    // the repository.
    console.log("\nDone. Everyone above can now sign in with the shared password.");
  }
}

main().catch((err) => {
  console.error("\nSomething went wrong:", err.message || err);
  process.exit(1);
});
