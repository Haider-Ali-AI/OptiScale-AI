// Commerce import + comparison through the real UI forms, using the backend's
// fictional fixtures. Expected values come from the backend's own pilot demo
// (store net sales Rs 6,400.00; 4 matched / 1 unmatched / 1 ambiguous / 2 excluded).
// Requires services running and the fictional pilot ad dataset (Commerce → "Load fictional pilot").
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../", import.meta.url));
const BASE = process.env.APP_URL || "http://127.0.0.1:3000";
const tag = `ui-qa-${Date.now().toString(36)}`;
const dir = join(tmpdir(), tag);
await mkdir(dir, { recursive: true });
for (const name of ["shopify", "expenses"]) {
  const r = await fetch(`${BASE}/api/v1/commerce/examples/${name}`);
  await writeFile(join(dir, `${name}.csv`), Buffer.from(await r.arrayBuffer()));
}
const launch = process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : { channel: process.env.PW_CHANNEL || "msedge" };
const browser = await chromium.launch({ headless: true, ...launch });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const checks = [];
const check = (name, ok, detail = "") => {
  checks.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` · ${detail}` : ""}`);
};
const pick = async (select, re) => {
  const opts = await select.locator("option").evaluateAll((os) => os.map((o) => ({ v: o.value, t: o.textContent })));
  const hit = opts.find((o) => re.test(o.t || ""));
  if (!hit) throw new Error(`No option matching ${re}: ${opts.map((o) => o.t).join(" | ")}`);
  await select.selectOption(hit.v);
};
const importPanel = () => page.locator("section[aria-label='Import orders or costs (CSV)']");

await page.goto(`${BASE}/commerce`, { waitUntil: "networkidle" });
// 1 · Orders
let p = importPanel();
await p.getByLabel("File type").selectOption("shopify");
await p.getByLabel("CSV file").setInputFiles(join(dir, "shopify.csv"));
await p.getByText("rows staged").waitFor();
await p.getByLabel("Snapshot name").fill(`QA orders ${tag}`);
await p.getByLabel("Store namespace").fill(tag);
await p.getByLabel("Snapshot as of").fill("2026-10-30");
await p.getByLabel("Coverage start").fill("2026-01-01");
await p.getByLabel("Coverage end").fill("2026-01-03");
await p.getByLabel("Subtotal is").selectOption("after_discounts");
await p.getByLabel("Data origin").selectOption("true");
await p.getByLabel(/every order in the coverage dates/).check();
await p.getByLabel(/verified refund amounts/).check();
await p.getByRole("button", { name: "Validate" }).click();
await p.getByLabel(/I am authorized/).waitFor({ timeout: 30_000 });
const orders = await p.locator(".kpi", { hasText: "Orders" }).locator(".kpi-value").textContent();
check("Order CSV validates through the UI", orders?.trim() === "8", `orders=${orders}`);
await p.getByLabel(/I am authorized/).check();
await p.getByRole("button", { name: "Confirm and save" }).click();
await p.getByText(`Saved “QA orders ${tag}”`).waitFor({ timeout: 30_000 });
check("Order snapshot saved", true);

// 2 · Costs attached to that snapshot
p = importPanel();
await p.getByLabel("File type").selectOption("expenses");
await p.getByLabel("CSV file").setInputFiles(join(dir, "expenses.csv"));
await p.getByText("rows staged").waitFor();
await p.getByLabel("Snapshot name").fill(`QA costs ${tag}`);
await pick(p.getByLabel("Attach to order snapshot"), new RegExp(`QA orders ${tag}`));
await p.getByLabel("Data origin").selectOption("true");
await p.getByRole("button", { name: "Validate" }).click();
await p.getByLabel(/I am authorized/).waitFor({ timeout: 30_000 });
await p.getByLabel(/I am authorized/).check();
await p.getByRole("button", { name: "Confirm and save" }).click();
await p.getByText(`Saved “QA costs ${tag}”`).waitFor({ timeout: 30_000 });
check("Cost snapshot saved and attached", true);

// 3 · Comparison
const c = page.locator("section[aria-label='Create a comparison']");
await pick(c.getByLabel("Order snapshot"), new RegExp(`QA orders ${tag}`));
await pick(c.getByLabel("Ad campaign dataset"), /Fictional commerce pilot ads/);
await c.getByLabel("Start").fill("2026-01-01");
await c.getByLabel("End").fill("2026-01-03");
await c.getByLabel(/QA costs/).check();
await c.getByLabel("Reference net sales (PKR, optional)").fill("6400");
await c.getByLabel("Reference eligible orders (optional)").fill("6");
await c.getByRole("button", { name: "Add mapping" }).click();
await c.getByLabel("utm_source").fill("merchant-google");
await c.getByLabel("utm_campaign").fill("winter-launch");
const campaign = c.getByRole("combobox", { name: "Ad campaign", exact: true });
await campaign.locator("option", { hasText: "Google · g-01" }).first().waitFor({ state: "attached", timeout: 30_000 });
await pick(campaign, /Google · g-01/);
await c.getByLabel(/same store and all its paid campaigns/).check();
await c.getByLabel(/timezones are comparable/).check();
await c.getByLabel(/verified merchant UTM/).check();
await c.getByRole("button", { name: "Save comparison" }).click();
const store = page.locator(".kpi", { hasText: "Store net sales" }).locator(".kpi-value");
await store.waitFor({ timeout: 60_000 });
const net = (await store.textContent())?.trim();
check("Comparison net sales equal the backend demo (Rs 6,400.00)", net === "Rs 6,400.00", net);
const outcome = async (k) =>
  (await page.locator(".kpi").filter({ has: page.locator(".kpi-label", { hasText: new RegExp(`^${k}$`) }) }).first().locator(".kpi-value").textContent())?.trim();
const matchedSales = (await page.locator(".kpi", { hasText: "Matched store sales" }).locator(".kpi-value").textContent())?.trim();
check("Matched store sales equal the backend demo (Rs 5,150.00)", matchedSales === "Rs 5,150.00", matchedSales);
const counts = [await outcome("Matched"), await outcome("Unmatched"), await outcome("Ambiguous"), await outcome("Excluded")].join("/");
check("Matching outcomes equal the backend demo (4/1/1/2)", counts === "4/1/1/2", counts);
check("Reference check shows zero differences", await page.getByText("net sales difference Rs 0.00, order count difference 0").isVisible());
await page.screenshot({ path: `${root}docs/screenshots/${process.env.QA_TAG ? process.env.QA_TAG + "-" : ""}flow-commerce-import-1440.png`, fullPage: true });
check("No uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
await writeFile(`${root}docs/e2e-commerce${process.env.QA_TAG ? "-" + process.env.QA_TAG : ""}.json`, JSON.stringify({ checked_at: new Date().toISOString(), tag, checks }, null, 2) + "\n");
if (checks.some((x) => !x.ok)) process.exitCode = 1;
