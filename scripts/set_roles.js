/*
 * Syncs each person's role (staff / admin / director) from
 * scripts/staff-list.json into their Firestore profile.
 *
 * It cannot change anyone's password. There is no shared password
 * anywhere in this system: people set their own by opening the mobile
 * site, entering their email, and tapping "Forgot password?", which has
 * Firebase email them a link. Nothing here reads, writes, prints, or
 * transmits a password.
 *
 * Easiest way to run it: GitHub -> Actions tab -> "Set staff roles" ->
 * Run workflow. No Terminal, no local setup; it uses the repository
 * secret.
 *
 * To run it locally instead:
 *   export FIREBASE_SERVICE_ACCOUNT="$(cat path/to/service-account.json)"
 *   node scripts/set_roles.js
 */

const fs = require("fs");
const path = require("path");

// Prefer the environment (GitHub Actions secret); fall back to a local
// service-account.json for hand-runs.
const SERVICE_ACCOUNT_RAW = process.env.FIREBASE_SERVICE_ACCOUNT;
const SERVICE_ACCOUNT_PATH = path.join(__dirname, "service-account.json");
const STAFF_LIST_PATH = path.join(__dirname, "staff-list.json");

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

admin.initializeApp({ credential: admin.credential.cert(serviceAccount) });

const auth = admin.auth();
const db = admin.firestore();

const VALID_ROLES = ["staff", "admin", "director"];

async function main() {
  console.log("Syncing roles from staff-list.json. No password is touched.\n");

  let updated = 0;
  let skipped = 0;

  for (const person of staffList) {
    const email = String(person.email || "").trim().toLowerCase();
    const role = person.role || "staff";

    if (!email) {
      console.warn("Entry with no email, skipping:", JSON.stringify(person));
      skipped++;
      continue;
    }
    if (!VALID_ROLES.includes(role)) {
      console.warn(`"${role}" isn't a valid role for ${email}, skipping. Use one of: ${VALID_ROLES.join(", ")}`);
      skipped++;
      continue;
    }

    try {
      await auth.getUserByEmail(email);
    } catch (e) {
      console.warn(`No login exists yet for ${email}, skipping.`);
      skipped++;
      continue;
    }

    await db.collection("users").doc(email).set(
      { name: person.name || email, role },
      { merge: true }
    );
    updated++;
    console.log(`${role.padEnd(8)} ${person.name} <${email}>`);
  }

  console.log(`\nDone. ${updated} updated, ${skipped} skipped.`);
}

main().catch((err) => {
  console.error("\nSomething went wrong:", err.message || err);
  process.exit(1);
});
