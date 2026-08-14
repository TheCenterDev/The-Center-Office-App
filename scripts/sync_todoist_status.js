/*
 * Keeps the Building Maintenance Log and the Todoist "Facilities"
 * project in step, in both directions.
 *
 * scripts/sync_todoist.js sends new requests *to* Todoist. This script
 * brings the answer back, because until now closing a task in Todoist
 * left the log entry sitting there as Open forever -- the two lists
 * quietly drifted apart and the log stopped being trustworthy.
 *
 * What it does, per entry that has a todoistTaskId:
 *
 *   completed in Todoist -> the entry is marked Done, with the date it
 *                           was completed recorded so the row can say
 *                           where the change came from.
 *   deleted in Todoist   -> the entry is NOT closed. It stays Open and
 *                           gets flagged. Deleting a task usually means
 *                           "this shouldn't have been posted", not
 *                           "the work is finished", and silently
 *                           closing a real maintenance request on that
 *                           basis would lose it.
 *   Done in the app      -> the Todoist task is closed, so whoever
 *                           finishes the job can close it wherever they
 *                           happen to be.
 *
 * Deliberately conservative: any entry whose state can't be established
 * -- a network failure, a rate limit, an unexpected response -- is left
 * exactly as it is and reported. A sync job that guesses is worse than
 * one that does nothing, because the thing it would be guessing about
 * is whether a building repair still needs doing.
 *
 * Environment variables (set as GitHub Actions secrets):
 *   TODOIST_API_TOKEN          -- Todoist personal API token
 *   TODOIST_PROJECT_ID         -- optional; defaults to Facilities
 *   FIREBASE_SERVICE_ACCOUNT   -- contents of a service account JSON key
 *
 * To run it by hand:
 *   export TODOIST_API_TOKEN="..."
 *   export FIREBASE_SERVICE_ACCOUNT="$(cat scripts/service-account.json)"
 *   node scripts/sync_todoist_status.js
 *
 * Add --dry-run to print what it would do without writing anything.
 */

const DEFAULT_PROJECT_ID = "6CrfG2HXhxfV58Qw";
const API = "https://api.todoist.com/api/v1";

/* ------------------------------------------------------------------ *
 * The decision, kept free of network and database calls so it can be  *
 * tested directly. `task` is one of:                                  *
 *   { state: "active" }                                               *
 *   { state: "completed", completedAt: "2026-08-14T..." }             *
 *   { state: "deleted" }                                              *
 *   { state: "unknown" }   -- lookup failed; do nothing               *
 * ------------------------------------------------------------------ */
function decide(entry, task) {
  const status = entry.status || "Open";

  if (task.state === "unknown") {
    return { action: "skip", reason: "couldn't establish the task's state" };
  }

  if (task.state === "completed") {
    if (status === "Done" && entry.todoistCompletedAt) {
      return { action: "none" };
    }
    return {
      action: "update",
      fields: {
        status: "Done",
        todoistCompletedAt: task.completedAt || new Date().toISOString(),
        todoistDeleted: false,
      },
      reason: "completed in Todoist",
    };
  }

  if (task.state === "deleted") {
    // Already noted, or already finished here -- nothing useful to add.
    if (entry.todoistDeleted || status === "Done") return { action: "none" };
    return {
      action: "update",
      fields: {
        todoistDeleted: true,
        todoistDeletedAt: new Date().toISOString(),
      },
      reason: "task deleted in Todoist; leaving the request open",
    };
  }

  // Still an open task in Todoist. If it's been finished here, close it
  // there.
  if (status === "Done") {
    return { action: "close", reason: "marked Done in the app" };
  }
  return { action: "none" };
}

/* ------------------------------------------------------------------ *
 * Everything below this point talks to the network.                   *
 * ------------------------------------------------------------------ */

async function todoist(path, token, options) {
  const response = await fetch(API + path, Object.assign({
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
  }, options || {}));
  return response;
}

/* Every id currently sitting in the project as an open task. Paginated
 * -- a project with more tasks than one page would otherwise look like
 * a project where everything past the first page had been deleted. */
async function activeTaskIds(token, projectId) {
  const ids = new Set();
  let cursor = null;
  do {
    const query = `?project_id=${encodeURIComponent(projectId)}&limit=200` +
      (cursor ? `&cursor=${encodeURIComponent(cursor)}` : "");
    const response = await todoist(`/tasks${query}`, token);
    if (!response.ok) {
      throw new Error(`Couldn't list tasks (${response.status}): ${await response.text()}`);
    }
    const body = await response.json();
    const rows = Array.isArray(body) ? body : (body.results || []);
    rows.forEach((task) => ids.add(String(task.id)));
    cursor = Array.isArray(body) ? null : (body.next_cursor || null);
  } while (cursor);
  return ids;
}

/* Called only for tasks that have left the active list, to tell a
 * completed one from a deleted one. Todoist still serves a completed
 * task by id; a deleted one is gone. */
async function lookupTask(token, taskId) {
  let response;
  try {
    response = await todoist(`/tasks/${encodeURIComponent(taskId)}`, token);
  } catch (err) {
    return { state: "unknown", detail: err.message };
  }
  if (response.status === 404) return { state: "deleted" };
  if (!response.ok) {
    return { state: "unknown", detail: `HTTP ${response.status}` };
  }
  const task = await response.json();
  const done = task.checked === true || task.is_completed === true ||
    !!task.completed_at;
  if (!done) return { state: "active" };
  return { state: "completed", completedAt: task.completed_at || null };
}

async function closeTask(token, taskId) {
  const response = await todoist(`/tasks/${encodeURIComponent(taskId)}/close`, token, {
    method: "POST",
  });
  if (!response.ok && response.status !== 204) {
    throw new Error(`close failed (${response.status})`);
  }
}

async function main() {
  const dryRun = process.argv.includes("--dry-run");
  const token = process.env.TODOIST_API_TOKEN;
  const projectId = process.env.TODOIST_PROJECT_ID || DEFAULT_PROJECT_ID;
  const serviceAccountRaw = process.env.FIREBASE_SERVICE_ACCOUNT;

  if (!token) {
    console.error("TODOIST_API_TOKEN is not set. Nothing to do.");
    process.exit(1);
  }
  if (!serviceAccountRaw) {
    console.error("FIREBASE_SERVICE_ACCOUNT is not set. Nothing to do.");
    process.exit(1);
  }

  const admin = require("firebase-admin");
  let serviceAccount;
  try {
    serviceAccount = JSON.parse(serviceAccountRaw);
  } catch (e) {
    console.error("FIREBASE_SERVICE_ACCOUNT isn't valid JSON:", e.message);
    process.exit(1);
  }
  admin.initializeApp({ credential: admin.credential.cert(serviceAccount) });
  const db = admin.firestore();

  const snap = await db.collection("maintenance_log").get();
  const tracked = [];
  snap.forEach((doc) => {
    const data = doc.data() || {};
    if (data.todoistTaskId) tracked.push({ id: doc.id, data });
  });

  if (!tracked.length) {
    console.log("No entries are linked to a Todoist task yet.");
    return;
  }
  console.log(`${tracked.length} linked entr${tracked.length === 1 ? "y" : "ies"}.`);

  const active = await activeTaskIds(token, projectId);
  console.log(`${active.size} task(s) still open in Todoist.`);

  let closedHere = 0, closedThere = 0, flagged = 0, skipped = 0;

  for (const { id, data } of tracked) {
    const taskId = String(data.todoistTaskId);
    const task = active.has(taskId)
      ? { state: "active" }
      : await lookupTask(token, taskId);

    const verdict = decide(data, task);
    const label = `${data.location || "?"}: ${(data.description || "").split("\n")[0].slice(0, 60)}`;

    if (verdict.action === "none") continue;

    if (verdict.action === "skip") {
      skipped++;
      console.warn(`SKIPPED ${label} — ${verdict.reason}${task.detail ? ` (${task.detail})` : ""}`);
      continue;
    }

    if (verdict.action === "update") {
      if (verdict.fields.status === "Done") closedHere++; else flagged++;
      console.log(`${dryRun ? "[dry run] " : ""}${label} — ${verdict.reason}`);
      if (!dryRun) {
        await db.collection("maintenance_log").doc(id).set(verdict.fields, { merge: true });
      }
      continue;
    }

    if (verdict.action === "close") {
      console.log(`${dryRun ? "[dry run] " : ""}${label} — ${verdict.reason}, closing it in Todoist`);
      if (!dryRun) {
        try {
          await closeTask(token, taskId);
          await db.collection("maintenance_log").doc(id).set(
            { todoistClosedFromApp: new Date().toISOString() }, { merge: true }
          );
          closedThere++;
        } catch (err) {
          skipped++;
          console.warn(`SKIPPED ${label} — ${err.message}`);
        }
      } else {
        closedThere++;
      }
    }
  }

  console.log(
    `\nDone. ${closedHere} closed from Todoist, ${closedThere} closed in Todoist, ` +
    `${flagged} flagged as deleted, ${skipped} left alone.`
  );
  // Skips are reported but aren't a failure: leaving an entry untouched
  // is the correct outcome when its state is unclear, and failing the
  // workflow over it would cry wolf every time Todoist has a blip.
}

// Only run when invoked directly, so the decision logic above can be
// required and tested without needing credentials.
if (require.main === module) {
  main().catch((err) => {
    console.error("Sync failed:", err.message || err);
    process.exit(1);
  });
}

module.exports = { decide };
