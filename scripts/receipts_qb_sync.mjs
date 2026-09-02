/* Brings new card charges from QuickBooks into Receipts, unattended.
 *
 * The chain: Capital One posts a charge -> QuickBooks picks it up on the
 * bank feed -> this puts it in Receipts, filed to whoever's card it was,
 * so that person can say what it was for and attach a photo if they
 * have one. Nobody downloads a spreadsheet.
 *
 * Run by .github/workflows/receipts-qb-sync.yml every few hours.
 * QuickBooks is reached through the Receipts worker (which holds the
 * Intuit connection); Firestore is written directly with the service
 * account. Reads a five-week window each time and relies on duplicate
 * filtering rather than remembering where it got to -- restartable, and
 * a late-posting charge still gets caught.
 *
 * Duplicate rule, same as the tool's: a charge is already here if its
 * QuickBooks id matches, OR if a row describes the same transaction
 * (date + amount + vendor + card). The second half matters because the
 * same charge may have arrived earlier from a hand-imported CSV.
 *
 * Test without writing: node scripts/receipts_qb_sync.mjs --dry-run
 */

import { createSign } from "node:crypto";

const DRY = process.argv.includes("--dry-run");
const WINDOW_DAYS = 35;

// Keep in step with PEOPLE in html/Receipts.html -- only used to show a
// name rather than an email address on a row.
const PEOPLE = {
  "jeff@thecentercc.com": "Jeff Wike",
  "brad@thecentercc.com": "Brad Boyles",
  "jake@thecentercc.com": "Jake Johnson",
  "shawna@thecentercc.com": "Shawna Balsiger",
  "dave@thecentercc.com": "Dave Wieringa",
  "sarah@thecentercc.com": "Sarah Johnson",
  "isaiah@thecentercc.com": "Isaiah Humiston",
  "tim@thecentercc.com": "Tim LaRue",
  "amanda@thecentercc.com": "Amanda Chapple",
  "kylee@thecentercc.com": "Kylee Gudeman",
  "liam@thecentercc.com": "Liam Strong",
  "natalee@thecentercc.com": "Natalee Wieringa",
};

const iso = d => d.toISOString().slice(0, 10);
const slug = s => String(s || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const last4From = t => { const m = String(t || "").match(/(\d{4})(?!.*\d)/); return m ? m[1] : ""; };
const monthOf = d => String(d || "").slice(0, 7);

// ------------------------------------------- Firestore (service account) --

let saCache = null;
function sa() {
  if (!saCache) saCache = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT);
  return saCache;
}

let tokenCache = { token: "", expires: 0 };
async function fsToken() {
  if (tokenCache.token && Date.now() < tokenCache.expires - 60000) return tokenCache.token;
  const key = sa();
  const now = Math.floor(Date.now() / 1000);
  const enc = o => Buffer.from(JSON.stringify(o)).toString("base64url");
  const unsigned = enc({ alg: "RS256", typ: "JWT" }) + "." + enc({
    iss: key.client_email,
    scope: "https://www.googleapis.com/auth/datastore",
    aud: "https://oauth2.googleapis.com/token",
    iat: now, exp: now + 3600,
  });
  const signer = createSign("RSA-SHA256");
  signer.update(unsigned);
  const jwt = unsigned + "." + signer.sign(key.private_key).toString("base64url");
  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=" + jwt,
  });
  if (!res.ok) throw new Error("Google token exchange failed: " + res.status + " " + await res.text());
  const data = await res.json();
  tokenCache = { token: data.access_token, expires: Date.now() + (data.expires_in || 3600) * 1000 };
  return tokenCache.token;
}

const DOCS = () => "https://firestore.googleapis.com/v1/projects/" + sa().project_id +
  "/databases/(default)/documents";

function decode(v) {
  if ("stringValue" in v) return v.stringValue;
  if ("booleanValue" in v) return v.booleanValue;
  if ("integerValue" in v) return parseInt(v.integerValue, 10);
  if ("doubleValue" in v) return v.doubleValue;
  if ("mapValue" in v) {
    const o = {};
    Object.entries(v.mapValue.fields || {}).forEach(([k, vv]) => { o[k] = decode(vv); });
    return o;
  }
  return null;
}
function encode(value) {
  if (typeof value === "boolean") return { booleanValue: value };
  if (typeof value === "number") {
    return Number.isInteger(value) ? { integerValue: String(value) } : { doubleValue: value };
  }
  if (value === null || value === undefined) return { nullValue: null };
  if (typeof value === "object") {
    const fields = {};
    Object.entries(value).forEach(([k, v]) => { fields[k] = encode(v); });
    return { mapValue: { fields } };
  }
  return { stringValue: String(value) };
}

async function receiptsForMonth(month) {
  const res = await fetch(DOCS() + ":runQuery", {
    method: "POST",
    headers: { Authorization: "Bearer " + await fsToken(), "Content-Type": "application/json" },
    body: JSON.stringify({ structuredQuery: {
      from: [{ collectionId: "receipts" }],
      where: { fieldFilter: { field: { fieldPath: "month" }, op: "EQUAL",
        value: { stringValue: month } } },
      limit: 2000,
    } }),
  });
  if (!res.ok) throw new Error("Firestore query failed: " + res.status + " " + await res.text());
  return (await res.json()).filter(r => r.document).map(r => {
    const o = {};
    Object.entries(r.document.fields || {}).forEach(([k, v]) => { o[k] = decode(v); });
    return o;
  });
}

async function getDoc(collection, id) {
  const res = await fetch(DOCS() + "/" + collection + "/" + encodeURIComponent(id), {
    headers: { Authorization: "Bearer " + await fsToken() },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error("Firestore read failed: " + res.status);
  const doc = await res.json();
  const o = {};
  Object.entries(doc.fields || {}).forEach(([k, v]) => { o[k] = decode(v); });
  return o;
}

async function writeDoc(collection, id, data) {
  const fields = {};
  Object.entries(data).forEach(([k, v]) => { fields[k] = encode(v); });
  const res = await fetch(DOCS() + "/" + collection + "/" + encodeURIComponent(id), {
    method: "PATCH",
    headers: { Authorization: "Bearer " + await fsToken(), "Content-Type": "application/json" },
    body: JSON.stringify({ fields }),
  });
  if (!res.ok) throw new Error("Firestore write failed: " + res.status + " " + await res.text());
}

// ----------------------------------------------------------- QuickBooks --

async function qboExpenses(from, to) {
  const res = await fetch(process.env.RECEIPTS_WORKER_URL +
    "/qb/expenses?from=" + from + "&to=" + to, {
    headers: { "X-Cron-Secret": process.env.RECEIPTS_CRON_SECRET },
  });
  const out = await res.json().catch(() => ({}));
  if (out.notConnected) throw new Error("QuickBooks isn't connected — open Receipts and press Connect QuickBooks.");
  if (out.reconnect) throw new Error("The QuickBooks connection lapsed — reconnect it from Receipts.");
  if (!out.ok) throw new Error("Worker error: " + (out.error || res.status));
  return out.expenses || [];
}

async function accounts() {
  const res = await fetch(process.env.RECEIPTS_WORKER_URL + "/qb/accounts", {
    headers: { "X-Cron-Secret": process.env.RECEIPTS_CRON_SECRET },
  });
  const out = await res.json().catch(() => ({}));
  return out.ok ? out.accounts : [];
}

// ----------------------------------------------------------------- main --

/* Nothing to do until the credentials exist. Exits quietly rather than
 * failing, so the schedule can be in place before the setup is -- a
 * workflow that emails a failure every six hours just trains people to
 * ignore it. */
function notConfigured() {
  const missing = ["FIREBASE_SERVICE_ACCOUNT", "RECEIPTS_WORKER_URL", "RECEIPTS_CRON_SECRET"]
    .filter(k => !process.env[k]);
  if (!missing.length) return false;
  console.log("Not set up yet — missing " + missing.join(", ") +
    ". Add these under Settings → Secrets and variables → Actions. Doing nothing.");
  return true;
}

async function main() {
  if (notConfigured()) return;
  const to = iso(new Date());
  const from = iso(new Date(Date.now() - WINDOW_DAYS * 86400000));

  const [charges, chart, ownersDoc] = await Promise.all([
    qboExpenses(from, to),
    accounts(),
    getDoc("receipts_config", "card_owners"),
  ]);
  const cardOwners = (ownersDoc && ownersDoc.owners) || {};

  // Only the months these charges touch need reading.
  const months = [...new Set(charges.map(c => monthOf(c.date)).filter(Boolean))];
  const haveImport = new Set(), haveNatural = new Set();
  for (const m of months) {
    for (const r of await receiptsForMonth(m)) {
      if (r.importRef) haveImport.add(r.importRef);
      if (r.naturalRef) haveNatural.add(r.naturalRef);
    }
  }

  let added = 0, skipped = 0, unassigned = 0;
  for (const c of charges) {
    if (!c.date || !c.amount) { skipped++; continue; }
    const last4 = last4From(c.paidFrom);
    const importRef = "qbo_" + c.id;
    const naturalRef = ["nat", c.date, Math.round(c.amount * 100),
      slug(c.vendor).slice(0, 20) || "x", last4 || "x"].join("_");
    if (haveImport.has(importRef) || haveNatural.has(naturalRef)) { skipped++; continue; }

    const hit = c.category
      ? chart.find(a => c.category.toLowerCase().includes(a.name.toLowerCase()))
      : null;
    const owner = cardOwners[last4] || process.env.RECEIPTS_FALLBACK_OWNER || "brad@thecentercc.com";
    if (!cardOwners[last4]) unassigned++;
    const now = new Date().toISOString();
    const record = {
      date: c.date, month: monthOf(c.date), vendor: c.vendor || "(no payee)",
      amount: Math.round(c.amount * 100) / 100,
      category: hit ? hit.name : "",
      categoryCode: hit ? (hit.code || "") : "",
      originalCategory: !hit && c.category ? c.category : "",
      site: "Not site specific", program: "",
      payment: /credit/i.test(c.payment || "") ? "Capital One card"
        : /check/i.test(c.payment || "") ? "Check"
        : /cash/i.test(c.payment || "") ? "Cash" : "Capital One card",
      last4: last4,
      notes: c.memo || "",
      hasImage: false, imageMime: "",
      exported: false, exportedAt: "",
      paidBy: PEOPLE[owner] || owner,
      createdBy: owner,
      createdAt: now, updatedAt: now,
      source: "quickbooks",
      refund: c.amount < 0,
      importRef, naturalRef,
      importedBy: "quickbooks-sync",
      importedAt: now,
    };
    if (DRY) {
      console.log("would add:", record.date, record.vendor, record.amount,
        "->", record.createdBy, record.category || "(uncategorised)");
    } else {
      await writeDoc("receipts", importRef, record);
    }
    haveImport.add(importRef);
    haveNatural.add(naturalRef);
    added++;
  }

  console.log((DRY ? "[dry run] " : "") +
    "QuickBooks " + from + " to " + to + ": " + charges.length + " charge(s), " +
    added + " added, " + skipped + " already here" +
    (unassigned ? ", " + unassigned + " on cards with no owner set (filed to the fallback)" : ""));
}

main().catch(err => { console.error(err.message || err); process.exit(1); });
