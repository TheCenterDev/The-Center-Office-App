/*
 * Creates a Todoist task ahead of each recurring reporting deadline in
 * the shared Reporting Calendar (see html/Reporting Calendar.html).
 * Run by .github/workflows/todoist-sync.yml on the same schedule as the
 * maintenance sync.
 *
 * Only items marked active generate tasks. That's how an obligation
 * that has ended -- the CCLC grant after 24/25 -- stays recorded without
 * nagging anyone about deadlines that no longer exist.
 *
 * Duplicate protection: each posted deadline is recorded as
 * "<itemId>@<YYYY-MM-DD>" in reporting_calendar/posted. A given
 * occurrence is therefore posted once, no matter how often this runs.
 * That record is a separate document from the calendar itself so this
 * job can never overwrite somebody's edit.
 *
 * Environment (GitHub Actions secrets):
 *   TODOIST_API_TOKEN, FIREBASE_SERVICE_ACCOUNT
 *   TODOIST_PROJECT_ID     -- optional
 *   CALENDAR_LEAD_DAYS     -- optional, default 10
 */

const admin = require("firebase-admin");

const DEFAULT_PROJECT_ID = "6CrfG2HXhxfV58Qw";
const LEAD_DAYS = parseInt(process.env.CALENDAR_LEAD_DAYS || "10", 10);

const TODOIST_TOKEN = process.env.TODOIST_API_TOKEN;
const PROJECT_ID = process.env.TODOIST_PROJECT_ID || DEFAULT_PROJECT_ID;
const SERVICE_ACCOUNT_RAW = process.env.FIREBASE_SERVICE_ACCOUNT;

if (!TODOIST_TOKEN || !SERVICE_ACCOUNT_RAW) {
  console.error("TODOIST_API_TOKEN and FIREBASE_SERVICE_ACCOUNT must both be set.");
  process.exit(1);
}

admin.initializeApp({ credential: admin.credential.cert(JSON.parse(SERVICE_ACCOUNT_RAW)) });
const db = admin.firestore();

function iso(date) {
  return date.toISOString().slice(0, 10);
}

/** Next occurrence on or after today, mirroring the tool's own logic --
 *  including clamping day 31 to the end of a short month. */
function nextDue(item, today) {
  if (!item.day) return null;
  function candidate(year, monthIndex) {
    const lastDay = new Date(year, monthIndex + 1, 0).getDate();
    return new Date(year, monthIndex, Math.min(item.day, lastDay));
  }
  const midnight = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  if (item.cadence === "monthly") {
    let d = candidate(today.getFullYear(), today.getMonth());
    if (d < midnight) d = candidate(today.getFullYear(), today.getMonth() + 1);
    return d;
  }
  const m = (item.month || 1) - 1;
  let d = candidate(today.getFullYear(), m);
  if (d < midnight) d = candidate(today.getFullYear() + 1, m);
  return d;
}

async function createTask(item, due) {
  const content = item.text;
  const description =
    (item.party && item.party !== "Internal" ? "Reported to: " + item.party + "\n" : "") +
    (item.note ? item.note + "\n" : "") +
    "From the Reporting Calendar in the Office app.";

  const response = await fetch("https://api.todoist.com/api/v1/tasks", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${TODOIST_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      content,
      description,
      project_id: PROJECT_ID,
      due_date: iso(due),
      // Reporting deadlines to an outside funder are the ones that hurt
      // to miss, so those come in a step above internal work.
      priority: item.party && item.party !== "Internal" ? 3 : 2,
    }),
  });

  if (response.ok) return true;

  if (response.status === 404 || response.status === 410) {
    // Older API version -- fall back to the Sync endpoint, same as the
    // maintenance sync does.
    const uuid = `${item.id}-${iso(due)}`;
    const sync = await fetch("https://api.todoist.com/api/v1/sync", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${TODOIST_TOKEN}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: new URLSearchParams({
        commands: JSON.stringify([{
          type: "item_add",
          temp_id: `tmp-${uuid}`,
          uuid,
          args: {
            content, description, project_id: PROJECT_ID,
            due: { date: iso(due) },
          },
        }]),
      }),
    });
    const body = await sync.json();
    const status = (body.sync_status || {})[uuid];
    if (status && status !== "ok" && status.error) throw new Error(status.error);
    return true;
  }

  throw new Error(`Todoist error ${response.status}: ${await response.text()}`);
}

async function main() {
  const calendarSnap = await db.collection("reporting_calendar").doc("default").get();
  if (!calendarSnap.exists) {
    console.log("No reporting calendar yet -- open the Reporting Calendar tool once to create it.");
    return;
  }
  const items = (calendarSnap.data() || {}).items || [];

  const postedRef = db.collection("reporting_calendar").doc("posted");
  const postedSnap = await postedRef.get();
  const posted = postedSnap.exists ? (postedSnap.data() || {}) : {};

  const today = new Date();
  const horizon = new Date(today.getTime() + LEAD_DAYS * 86400000);

  let created = 0;
  let skipped = 0;
  const newlyPosted = {};

  for (const item of items) {
    if (item.active === false) { skipped++; continue; }
    const due = nextDue(item, today);
    if (!due) { skipped++; continue; }          // no set date -- nothing to schedule
    if (due > horizon) { skipped++; continue; } // too far out yet

    const key = `${item.id}@${iso(due)}`;
    if (posted[key]) { skipped++; continue; }

    try {
      await createTask(item, due);
      newlyPosted[key] = true;
      created++;
      console.log(`Scheduled for ${iso(due)}: ${item.text}`);
    } catch (err) {
      console.error(`FAILED for "${item.text}": ${err.message}`);
    }
  }

  if (Object.keys(newlyPosted).length) {
    await postedRef.set(newlyPosted, { merge: true });
  }

  console.log(`\nDone. ${created} task(s) created, ${skipped} not due yet or inactive.`);
}

main().catch((err) => {
  console.error("Calendar sync failed:", err.message || err);
  process.exit(1);
});
