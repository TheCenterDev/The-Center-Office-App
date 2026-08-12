/*
 * One-time correction script: sets every account in staff-list.json to
 * the shared password below, and force-updates their Firestore role to
 * match staff-list.json (unlike create_logins.js, which never touches
 * an account that already exists -- this one deliberately overwrites
 * both, since that's exactly what was asked for).
 *
 * Needs the same scripts/service-account.json as create_logins.js.
 * Run with:
 *   node scripts/set_password_and_roles.js
 */

const fs = require("fs");
const path = require("path");

const SHARED_PASSWORD = "Center123";

const SERVICE_ACCOUNT_PATH = path.join(__dirname, "service-account.json");
const STAFF_LIST_PATH = path.join(__dirname, "staff-list.json");

if (!fs.existsSync(SERVICE_ACCOUNT_PATH)) {
  console.error("\nCouldn't find scripts/service-account.json. See create_logins.js for how to get it.\n");
  process.exit(1);
}

const admin = require("firebase-admin");
const staffList = JSON.parse(fs.readFileSync(STAFF_LIST_PATH, "utf8"));

admin.initializeApp({
  credential: admin.credential.cert(require(SERVICE_ACCOUNT_PATH)),
});

const auth = admin.auth();
const db = admin.firestore();

async function main() {
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

    await auth.updateUser(user.uid, { password: SHARED_PASSWORD });
    await db.collection("users").doc(email).set({ role }, { merge: true });
    console.log(`Set password + role "${role}" for ${person.name} <${email}>`);
  }
  console.log(`\nDone. Everyone above can now sign in with the password: ${SHARED_PASSWORD}`);
}

main().catch((err) => {
  console.error("\nSomething went wrong:", err.message || err);
  process.exit(1);
});
