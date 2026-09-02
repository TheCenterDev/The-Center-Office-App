/* Builds the receipts-vs-QuickBooks report for last month and emails it.
 *
 * Run by .github/workflows/monthly-receipts-report.yml on the 1st.
 * Receipts come straight from Firestore (service account); QuickBooks
 * purchases come through the Receipts worker, which holds the Intuit
 * connection (this script sends the shared CRON_SECRET instead of a
 * person's login).
 *
 * The matching rules here are deliberately identical to the ones in the
 * Receipts tool's on-screen report (html/Receipts.html): exact amount,
 * dates within 6 days, closest date wins. If one changes, change both.
 *
 * Test without sending: node scripts/monthly_receipts_report.mjs --dry-run
 * writes report.html next to this script instead of emailing.
 */

import { createSign } from "node:crypto";
import { writeFileSync } from "node:fs";

const DRY = process.argv.includes("--dry-run");

// --------------------------------------------------------- last month --

function lastMonthRange() {
  const now = new Date();
  const first = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1));
  const last = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 0));
  const iso = d => d.toISOString().slice(0, 10);
  return {
    month: iso(first).slice(0, 7),
    from: iso(first),
    to: iso(last),
    label: first.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" }),
  };
}

// ------------------------------------------- Firestore (service account) --

async function firestoreToken(sa) {
  const now = Math.floor(Date.now() / 1000);
  const enc = o => Buffer.from(JSON.stringify(o)).toString("base64url");
  const unsigned = enc({ alg: "RS256", typ: "JWT" }) + "." + enc({
    iss: sa.client_email,
    scope: "https://www.googleapis.com/auth/datastore",
    aud: "https://oauth2.googleapis.com/token",
    iat: now, exp: now + 3600,
  });
  const signer = createSign("RSA-SHA256");
  signer.update(unsigned);
  const jwt = unsigned + "." + signer.sign(sa.private_key).toString("base64url");
  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: "grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer&assertion=" + jwt,
  });
  if (!res.ok) throw new Error("Google token exchange failed: " + res.status + " " + await res.text());
  return (await res.json()).access_token;
}

function fromValue(v) {
  if ("stringValue" in v) return v.stringValue;
  if ("booleanValue" in v) return v.booleanValue;
  if ("integerValue" in v) return parseInt(v.integerValue, 10);
  if ("doubleValue" in v) return v.doubleValue;
  return null;
}

async function fetchReceipts(sa, month) {
  const token = await firestoreToken(sa);
  const res = await fetch(
    "https://firestore.googleapis.com/v1/projects/" + sa.project_id +
    "/databases/(default)/documents:runQuery", {
    method: "POST",
    headers: { Authorization: "Bearer " + token, "Content-Type": "application/json" },
    body: JSON.stringify({
      structuredQuery: {
        from: [{ collectionId: "receipts" }],
        where: { fieldFilter: { field: { fieldPath: "month" }, op: "EQUAL",
          value: { stringValue: month } } },
        limit: 2000,
      },
    }),
  });
  if (!res.ok) throw new Error("Firestore query failed: " + res.status + " " + await res.text());
  const rows = await res.json();
  return rows.filter(r => r.document).map(r => {
    const f = r.document.fields || {};
    const out = {};
    for (const k of Object.keys(f)) out[k] = fromValue(f[k]);
    out.id = r.document.name.split("/").pop();
    return out;
  });
}

// -------------------------------------------------- QuickBooks (worker) --

async function fetchQb(range) {
  const res = await fetch(process.env.RECEIPTS_WORKER_URL +
    "/qb/expenses?from=" + range.from + "&to=" + range.to, {
    headers: { "X-Cron-Secret": process.env.RECEIPTS_CRON_SECRET },
  });
  const out = await res.json();
  if (out.notConnected) throw new Error("QuickBooks isn't connected — open the Receipts tool and press Connect QuickBooks.");
  if (out.reconnect) throw new Error("The QuickBooks connection lapsed — reconnect from the Receipts tool.");
  if (!out.ok) throw new Error("Worker error: " + (out.error || res.status));
  return out.expenses;
}

// ------------------------------------------------------------ matching --
// Identical rules to html/Receipts.html -- change both or neither.

function matchReceiptsToQb(receipts, qb) {
  const cents = n => Math.round((n || 0) * 100);
  const days = (a, b) => Math.abs(new Date(a) - new Date(b)) / 86400000;
  const candidates = [];
  receipts.forEach(r => qb.forEach(q => {
    if (cents(r.amount) !== cents(q.amount)) return;
    const gap = days(r.date, q.date);
    if (gap > 6) return;
    candidates.push({ gap, r, q });
  }));
  candidates.sort((a, b) => a.gap - b.gap);
  const rUsed = new Set(), qUsed = new Set(), pairs = [];
  candidates.forEach(c => {
    if (rUsed.has(c.r.id) || qUsed.has(c.q.id)) return;
    rUsed.add(c.r.id); qUsed.add(c.q.id);
    pairs.push(c);
  });
  return {
    pairs,
    unmatchedReceipts: receipts.filter(r => !rUsed.has(r.id)),
    unmatchedQb: qb.filter(q => !qUsed.has(q.id)),
  };
}

// -------------------------------------------------------------- report --

const money = n => (n || 0).toLocaleString("en-US", { style: "currency", currency: "USD" });
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export function buildReportHtml(range, receipts, qb) {
  const m = matchReceiptsToQb(receipts, qb);
  const catDisagree = m.pairs.filter(p =>
    p.r.category && p.q.category && p.q.category.indexOf(p.r.category) === -1);
  const sum = list => list.reduce((s, x) => s + (x.amount || 0), 0);
  const tbl = rows => rows.length ?
    "<table style='width:100%;border-collapse:collapse;font-size:13px'>" +
    rows.map(r => "<tr>" + r.map(c =>
      "<td style='padding:6px 10px;border-bottom:1px solid #e3e6eb'>" + c + "</td>").join("") + "</tr>").join("") +
    "</table>" : "";
  const sec = (title, n, rowsHtml, empty) =>
    "<h3 style='margin:20px 0 8px;font-size:15px'>" + title + " (" + n + ")</h3>" +
    (rowsHtml || "<p style='color:#6b7486;font-size:13px'>" + empty + "</p>");
  const rRow = r => [r.date, esc(r.vendor), money(r.amount),
    esc(r.categoryCode ? r.categoryCode + " · " + r.category : (r.category || "—")),
    esc(r.paidBy || ""), esc(r.notes || "")];
  const qRow = q => [q.date, esc(q.vendor), money(q.amount),
    esc(q.category || "—"), esc(q.paidFrom || ""), esc(q.memo || "")];

  const totals = {};
  receipts.forEach(r => { const k = r.category || "(uncategorised)";
    totals[k] = totals[k] || { r: 0, q: 0 }; totals[k].r += r.amount || 0; });
  qb.forEach(q => { const k = q.category || "(no account)";
    totals[k] = totals[k] || { r: 0, q: 0 }; totals[k].q += q.amount || 0; });
  const totalRows = Object.keys(totals).sort().map(k => {
    const t = totals[k];
    const off = Math.abs(t.r - t.q) > 0.005;
    return [esc(k), money(t.r), money(t.q),
      off ? "<strong style='color:#b3261e'>" + money(t.r - t.q) + "</strong>" : "—"];
  });

  return "<div style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;color:#1a2233;max-width:860px'>" +
    "<h2 style='font-size:18px;margin-bottom:2px'>Receipts vs QuickBooks — " + esc(range.label) + "</h2>" +
    "<p style='color:#6b7486;font-size:13px'>" +
    receipts.length + " receipts (" + money(sum(receipts)) + ") · " +
    qb.length + " QuickBooks purchases (" + money(sum(qb)) + ") · " + m.pairs.length + " matched</p>" +
    sec("Receipts not yet entered in QuickBooks", m.unmatchedReceipts.length,
      tbl(m.unmatchedReceipts.map(rRow)), "Every receipt is in QuickBooks.") +
    sec("In QuickBooks with no receipt on file", m.unmatchedQb.length,
      tbl(m.unmatchedQb.map(qRow)), "Every QuickBooks purchase has a receipt.") +
    sec("Matched, but categorised differently", catDisagree.length,
      tbl(catDisagree.map(p => [p.r.date, esc(p.r.vendor), money(p.r.amount),
        "receipt says <strong>" + esc(p.r.category) + "</strong>",
        "QB says <strong>" + esc(p.q.category) + "</strong>"])),
      "Matched purchases agree on the category.") +
    "<h3 style='margin:20px 0 8px;font-size:15px'>Category totals</h3>" +
    tbl([["<strong>Account</strong>", "<strong>Receipts</strong>", "<strong>QuickBooks</strong>", "<strong>Gap</strong>"]]
      .concat(totalRows)) +
    "<p style='color:#6b7486;font-size:12px;margin-top:20px'>Sent automatically on the 1st by the " +
    "monthly-receipts-report workflow. The same report is available any time from the Receipts tool.</p></div>";
}

// ---------------------------------------------------------------- main --

/* Exits quietly until the credentials exist, so the schedule can be in
 * place before the setup is. */
function notConfigured() {
  const needed = ["FIREBASE_SERVICE_ACCOUNT", "RECEIPTS_WORKER_URL", "RECEIPTS_CRON_SECRET"];
  if (!DRY) needed.push("GMAIL_APP_PASSWORD", "REPORT_FROM", "REPORT_TO");
  const missing = needed.filter(k => !process.env[k]);
  if (!missing.length) return false;
  console.log("Not set up yet — missing " + missing.join(", ") + ". Doing nothing.");
  return true;
}

async function main() {
  if (notConfigured()) return;
  const range = lastMonthRange();
  const sa = JSON.parse(process.env.FIREBASE_SERVICE_ACCOUNT);
  const [receipts, qb] = await Promise.all([
    fetchReceipts(sa, range.month),
    fetchQb(range),
  ]);
  const html = "<!DOCTYPE html><meta charset='utf-8'><body>" +
    buildReportHtml(range, receipts, qb) + "</body>";

  if (DRY) {
    writeFileSync(new URL("./report.html", import.meta.url), html);
    console.log("dry run: wrote scripts/report.html —",
      receipts.length, "receipts,", qb.length, "QB purchases");
    return;
  }

  const { default: nodemailer } = await import("nodemailer");
  const transport = nodemailer.createTransport({
    host: "smtp.gmail.com", port: 465, secure: true,
    auth: { user: process.env.REPORT_FROM, pass: process.env.GMAIL_APP_PASSWORD },
  });
  await transport.sendMail({
    from: '"Receipts" <' + process.env.REPORT_FROM + ">",
    to: process.env.REPORT_TO,
    subject: "Receipts vs QuickBooks — " + range.label,
    html,
  });
  console.log("emailed", process.env.REPORT_TO, "—", receipts.length, "receipts,", qb.length, "QB purchases");
}

// Only run when executed directly (so tests can import buildReportHtml).
if (import.meta.url === "file://" + process.argv[1] ||
    process.argv[1] && import.meta.url.endsWith(process.argv[1].split("/").pop())) {
  main().catch(err => { console.error(err.message || err); process.exit(1); });
}
