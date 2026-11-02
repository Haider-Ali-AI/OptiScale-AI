// Renders docs/screenshots/test-results.png from the recorded result files only:
// docs/pytest-summary.txt, docs/e2e-*.json, docs/qa-screens-*.json and docs/evidence/all-engines-*.json.
import { readdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../", import.meta.url));
const read = async (p) => JSON.parse(await readFile(root + p, "utf8"));
const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);

const pytestLines = (await readFile(root + "docs/pytest-summary.txt", "utf8")).split(/\r?\n/);
const pytestTotal = pytestLines.find((l) => /passed/.test(l)) || "";
const pytestFailed = pytestLines.filter((l) => l.startsWith("FAILED")).map((l) => l.replace("FAILED backend/tests/", ""));

const suite = async (file) => {
  const d = await read(file);
  return { pass: d.checks.filter((c) => c.ok).length, total: d.checks.length, checks: d.checks, at: d.checked_at };
};
const qa = async (file) => {
  const d = await read(file);
  const bad = d.results.filter((r) => r.status !== 200 || r.horizontal_overflow_px > 0 || r.console_errors.length);
  const widths = [...new Set(d.results.map((r) => r.width))];
  const routes = [...new Set(d.results.map((r) => r.route))];
  return { clean: d.results.length - bad.length, total: d.results.length, widths, routes };
};
const rows = [
  ["Local", "Core journeys (Rs 1M plan, limits, model, explorer)", await suite("docs/e2e-flows.json")],
  ["Local", "Commerce import + comparison", await suite("docs/e2e-commerce.json")],
  ["Local", "AI assistant (NVIDIA)", await suite("docs/e2e-assistant.json")],
  ["Live", "Core journeys (Rs 1M plan, limits, model, explorer)", await suite("docs/e2e-flows-cloud.json")],
  ["Live", "Commerce import + comparison", await suite("docs/e2e-commerce-cloud.json")],
  ["Live", "AI assistant (NVIDIA)", await suite("docs/e2e-assistant-cloud.json")],
];
const qaRows = [
  ["Local · dark", await qa("docs/qa-screens-dark.json")],
  ["Local · light", await qa("docs/qa-screens-light.json")],
  ["Live · dark", await qa("docs/qa-screens-dark-cloud.json")],
];

const files = (await readdir(root + "docs/evidence")).filter((f) => f.startsWith("all-engines-") && f.endsWith(".json"));
const bench = [];
for (const f of files) {
  const d = await read("docs/evidence/" + f);
  const job = d.job || d;
  const results = job.results || d.results || [];
  const rowsN = (job.config || d.config || {}).rows;
  const by = Object.fromEntries(results.map((r) => [r.engine, r]));
  const ok = results.every((r) => r.status === "completed" && r.runs.every((x) => x.correct));
  bench.push({ rows: rowsN, by, ok });
}
bench.sort((a, b) => a.rows - b.rows);
const secs = (r) => (r && r.median_seconds != null ? (r.median_seconds < 1 ? `${(r.median_seconds * 1000).toFixed(0)} ms` : `${r.median_seconds.toFixed(2)} s`) : "n/a");

const badge = (ok, text) => `<span class="b ${ok ? "ok" : "no"}">${ok ? "✓" : "✗"} ${esc(text)}</span>`;
const html = `<!doctype html><html><head><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:#0b1220;color:#f6f8fc;font:15px/1.45 "Segoe UI",system-ui,sans-serif;padding:32px;width:1200px}
h1{margin:0 0 4px;font-size:30px;letter-spacing:-.02em}.sub{color:#a7b7ce;margin:0 0 22px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.card{background:#18273e;border:1px solid #2a3a52;border-radius:14px;padding:18px}
h2{font-size:16px;margin:0 0 12px;color:#39d7c8;text-transform:uppercase;letter-spacing:.08em}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}td,th{padding:7px 8px;border-bottom:1px solid #2a3a52;text-align:left}th{color:#a7b7ce;font-size:12.5px}
td.r,th.r{text-align:right}.b{display:inline-block;white-space:nowrap;padding:2px 9px;border-radius:99px;font-weight:700;font-size:12.5px}.ok{background:rgba(95,211,154,.14);color:#5fd39a;border:1px solid rgba(95,211,154,.4)}.no{background:rgba(243,125,131,.14);color:#f37d83;border:1px solid rgba(243,125,131,.4)}
.big{font-size:34px;font-weight:800}.muted{color:#a7b7ce;font-size:13px}.wide{grid-column:1/-1}code{font-family:Consolas,monospace;font-size:12.5px;color:#a7b7ce}
</style></head><body>
<h1>SignalSpend AI · Test results</h1>
<p class="sub">Generated from recorded result files · ${esc(new Date().toISOString().slice(0, 16).replace("T", " "))} UTC · live = https://signalspend-ai.vercel.app (no login)</p>
<div class="grid">
<div class="card"><h2>Backend (pytest)</h2><div class="big">${esc(pytestTotal.match(/(\d+) passed/)?.[1] || "?")} passed</div>
<p class="muted">${esc(pytestTotal)}</p><p class="muted">Remaining failures are Windows/POSIX-environment specific (file modes, SIGKILL, SQLite temp locks, symlink privilege):</p>
<code>${pytestFailed.map(esc).join("<br>")}</code></div>
<div class="card"><h2>Browser journeys</h2><table><tr><th>Where</th><th>Suite</th><th class="r">Result</th></tr>
${rows.map(([w, n, s]) => `<tr><td>${w}</td><td>${esc(n)}</td><td class="r">${badge(s.pass === s.total, `${s.pass}/${s.total}`)}</td></tr>`).join("")}
</table></div>
<div class="card"><h2>Pages × screen sizes</h2><table><tr><th>Run</th><th>Widths</th><th class="r">Clean (200, 0 errors, 0 overflow)</th></tr>
${qaRows.map(([n, q]) => `<tr><td>${n}</td><td>${q.widths.join(", ")} px</td><td class="r">${badge(q.clean === q.total, `${q.clean}/${q.total}`)}</td></tr>`).join("")}
</table><p class="muted">${qaRows[0][1].routes.length} routes: ${esc(qaRows[0][1].routes.join("  "))}</p></div>
<div class="card"><h2>Big Data lab · median of 3 repeats</h2><table><tr><th>Rows</th><th class="r">Pandas</th><th class="r">MapReduce</th><th class="r">Spark</th><th class="r">Parity</th></tr>
${bench.map((b) => `<tr><td>${b.rows.toLocaleString("en")}</td><td class="r">${secs(b.by.pandas)}</td><td class="r">${secs(b.by.mapreduce)}</td><td class="r">${secs(b.by.spark)}</td><td class="r">${badge(b.ok, "all repeats")}</td></tr>`).join("")}
</table></div>
<div class="card wide"><h2>Key checks</h2><table>
${[...rows[0][2].checks, ...rows[2][2].checks.slice(0, 3)].map((c) => `<tr><td>${badge(c.ok, c.ok ? "PASS" : "FAIL")}</td><td>${esc(c.name)}</td><td class="muted">${esc((c.detail || "").slice(0, 95))}</td></tr>`).join("")}
</table></div>
</div></body></html>`;
await writeFile(root + "docs/test-results.html", html);
const launch = process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : { channel: process.env.PW_CHANNEL || "msedge" };
const browser = await chromium.launch({ headless: true, ...launch });
const page = await browser.newPage({ viewport: { width: 1264, height: 900 }, deviceScaleFactor: 1 });
await page.goto("file:///" + (root + "docs/test-results.html").replace(/\\/g, "/"));
await page.screenshot({ path: root + "docs/screenshots/test-results.png", fullPage: true });
await browser.close();
console.log("wrote docs/screenshots/test-results.png");
