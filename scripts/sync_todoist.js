/*
 * Sends new Building Maintenance Log entries to the Todoist "Facilities"
 * project as tasks. Run automatically by
 * .github/workflows/todoist-sync.yml every few minutes; can also be run
 * by hand (see below).
 *
 * Why this runs on a server instead of inside the Maintenance Log page:
 * a Todoist *personal* API token grants full access to the whole
 * account -- Todoist's add-only permission (task:add) is available to
 * OAuth apps only, not personal tokens. The Maintenance Log is served
 * as a public web page, so a token placed in it could be read by anyone
 * who opens the site. Here the token lives only in GitHub's encrypted
 * secrets and never reaches a browser.
 *
 * How it avoids duplicates: after creating a task, the Firestore
 * document gets a todoistTaskId field written back to it. Anything that
 * already has one is skipped forever after, so running this twice (or
 * the schedule overlapping itself) can't post the same request twice.
 *
 * Environment variables (set as GitHub Actions secrets):
 *   TODOIST_API_TOKEN          -- Todoist personal API token
 *   TODOIST_PROJECT_ID         -- optional; defaults to the Facilities
 *                                 project ID below
 *   FIREBASE_SERVICE_ACCOUNT   -- the full contents of a Firebase
 *                                 service account JSON key
 *
 * To run it by hand instead:
 *   export TODOIST_API_TOKEN="..."
 *   export FIREBASE_SERVICE_ACCOUNT="$(cat scripts/service-account.json)"
 *   node scripts/sync_todoist.js
 */

const admin = require("firebase-admin");

// The Facilities - TCWCY project. Taken from the project's URL:
// https://app.todoist.com/app/project/facilities-tcwcy-td-6CrfG2HXhxfV58Qw
const DEFAULT_PROJECT_ID = "6CrfG2HXhxfV58Qw";

const TODOIST_TOKEN = process.env.TODOIST_API_TOKEN;
const PROJECT_ID = process.env.TODOIST_PROJECT_ID || DEFAULT_PROJECT_ID;
const SERVICE_ACCOUNT_RAW = process.env.FIREBASE_SERVICE_ACCOUNT;

if (!TODOIST_TOKEN) {
  console.error("TODOIST_API_TOKEN is not set. Nothing to do.");
  process.exit(1);
}
if (!SERVICE_ACCOUNT_RAW) {
  console.error("FIREBASE_SERVICE_ACCOUNT is not set. Nothing to do.");
  process.exit(1);
}

let serviceAccount;
try {
  serviceAccount = JSON.parse(SERVICE_ACCOUNT_RAW);
} catch (e) {
  console.error("FIREBASE_SERVICE_ACCOUNT isn't valid JSON:", e.message);
  process.exit(1);
}

admin.initializeApp({ credential: admin.credential.cert(serviceAccount) });
const db = admin.firestore();

// Todoist priority is inverted from what you'd guess: 4 is the highest
// (shown as P1 in the app), 1 is the lowest/default.
const PRIORITY_MAP = { Urgent: 4, High: 3, Med: 2, Low: 1 };

function buildTitle(entry) {
  const location = (entry.location || "").trim();
  const description = (entry.description || "").trim() || "Maintenance request";
  // Todoist task titles are one line; keep them scannable and put the
  // rest in the description body.
  const firstLine = description.split("\n")[0].trim();
  const short = firstLine.length > 120 ? firstLine.slice(0, 117) + "..." : firstLine;
  return location ? `${location}: ${short}` : short;
}

function buildDescription(entry, docId) {
  const lines = [];
  const description = (entry.description || "").trim();
  const firstLine = description.split("\n")[0].trim();
  // Only repeat the full text when the title had to truncate it or
  // there's more than one line -- otherwise it's just noise.
  if (description && description !== firstLine) {
    lines.push(description, "");
  } else if (firstLine.length > 120) {
    lines.push(description, "");
  }
  if (entry.location) lines.push(`Location: ${entry.location}`);
  if (entry.priority) lines.push(`Urgency: ${entry.priority}`);
  if (entry.reporter) lines.push(`Reported by: ${entry.reporter}`);
  if (entry.dateReported) lines.push(`Date reported: ${entry.dateReported}`);
  lines.push("", `From the Building Maintenance Log (entry ${docId}).`);
  // trim() so an entry with no location/reporter/date doesn't open with
  // a stray blank line.
  return lines.join("\n").trim();
}

/* Todoist has moved its REST task endpoint between versions, and the
 * Sync API's item_add command has been stable across all of them. Try
 * the current REST endpoint first, and fall back to Sync if this
 * account/version answers with a 404/410 -- rather than silently
 * failing and quietly dropping maintenance requests. */
async function createTask(entry, docId) {
  const content = buildTitle(entry);
  const description = buildDescription(entry, docId);
  const priority = PRIORITY_MAP[entry.priority] || 1;

  const restResponse = await fetch("https://api.todoist.com/api/v1/tasks", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${TODOIST_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      content,
      description,
      project_id: PROJECT_ID,
      priority,
    }),
  });

  if (restResponse.ok) {
    const created = await restResponse.json();
    return created.id || "created";
  }

  if (restResponse.status !== 404 && restResponse.status !== 410) {
    const body = await restResponse.text();
    throw new Error(`Todoist REST error ${restResponse.status}: ${body}`);
  }

  // Fallback: Sync API item_add.
  const uuid = `${docId}-${Date.now()}`;
  const commands = JSON.stringify([
    {
      type: "item_add",
      temp_id: `tmp-${docId}`,
      uuid,
      args: { content, description, project_id: PROJECT_ID, priority },
    },
  ]);

  const syncResponse = await fetch("https://api.todoist.com/api/v1/sync", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${TODOIST_TOKEN}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ commands }),
  });

  const syncBody = await syncResponse.json();
  const status = (syncBody.sync_status || {})[uuid];
  if (status && status !== "ok" && status.error) {
    throw new Error(`Todoist Sync error: ${status.error}`);
  }
  const mapping = syncBody.temp_id_mapping || {};
  return mapping[`tmp-${docId}`] || "created";
}

async function main() {
  const snap = await db.collection("maintenance_log").get();

  const pending = [];
  snap.forEach((doc) => {
    const data = doc.data() || {};
    if (data.todoistTaskId) return; // already sent
    pending.push({ id: doc.id, data });
  });

  if (pending.length === 0) {
    console.log("No new maintenance entries to send.");
    return;
  }

  console.log(`${pending.length} entr${pending.length === 1 ? "y" : "ies"} to send.`);

  let sent = 0;
  let failed = 0;
  for (const { id, data } of pending) {
    try {
      const taskId = await createTask(data, id);
      // Written back before anything else can run again, so a crash
      // later in this loop can't cause a re-send of this one.
      await db.collection("maintenance_log").doc(id).set(
        {
          todoistTaskId: String(taskId),
          todoistSyncedAt: new Date().toISOString(),
        },
        { merge: true }
      );
      sent++;
      console.log(`Sent: ${buildTitle(data)}`);
    } catch (err) {
      failed++;
      console.error(`FAILED for entry ${id}: ${err.message}`);
    }
  }

  console.log(`\nDone. ${sent} sent, ${failed} failed.`);
  // A failure shouldn't look like success in the Actions log, but it
  // also shouldn't stop the successfully-sent ones from being recorded.
  if (failed > 0) process.exit(1);
}

main().catch((err) => {
  console.error("Sync failed:", err.message || err);
  process.exit(1);
});
