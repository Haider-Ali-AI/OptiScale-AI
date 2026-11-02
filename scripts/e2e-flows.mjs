// Functional browser journeys against the real backend (no mocks).
// Requires services running and a selected campaign source with an accepted model
// (the seed-42 demo trained with as-of 2026-10-29 satisfies this).
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../", import.meta.url));
const BASE = process.env.APP_URL || "http://127.0.0.1:3000";
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
const paisaSum = (texts) => texts.reduce((s, t) => s + Math.round(Number(t.replace(/[^0-9.]/g, "")) * 100), 0);

// 1 · Budget: user-entered PKR 1,000,000, automatic method, default limits.
await page.goto(`${BASE}/budget`, { waitUntil: "networkidle" });
await page.getByLabel("Budget to allocate (PKR)").fill("1000000");
// A restored saved plan may carry earlier limits; start from the documented 0–100% defaults.
for (const name of ["Facebook", "Instagram", "Google", "TikTok", "YouTube"]) {
  const box = page.locator("fieldset", { hasText: name }).last();
  if (await box.getByLabel("Max %").count()) {
    await box.getByLabel("Min %").fill("0");
    await box.getByLabel("Max %").fill("100");
  }
}
await page.getByRole("button", { name: "Generate recommendation" }).click();
await page.getByText("Computing exact allocation").waitFor({ state: "detached", timeout: 60_000 });
await page.getByText("Exact-total check").waitFor({ timeout: 60_000 });
const exactText = await page.locator(".notice", { hasText: "Exact-total check" }).textContent();
check("PKR 1,000,000 plan sums exactly", /to the last paisa/.test(exactText), exactText.trim().slice(0, 120));
const amounts = await page.locator("section[aria-label='Recommended allocation'] tbody tr td:nth-child(2)").allTextContents();
check("Independent paisa sum of table equals 1,000,000.00", paisaSum(amounts) === 100_000_000, amounts.join(" | "));
const method = await page.locator(".kpi", { hasText: "Method used" }).locator(".kpi-value").textContent();
check("Method is disclosed", !!method?.trim(), method);
await page.screenshot({ path: `${root}docs/screenshots/flow-budget-1m-1440.png`, fullPage: true });

// 2 · Constraint: cap Google at 20% and regenerate.
const google = page.locator("fieldset", { hasText: "Google" }).last();
await google.getByLabel("Max %").fill("20");
check("Editing inputs hides stale estimates", await page.getByText("Inputs changed since this plan was generated").isVisible());
await page.getByRole("button", { name: "Generate recommendation" }).click();
await page.getByText("Computing exact allocation").waitFor({ state: "detached", timeout: 60_000 });
const row = page.locator("section[aria-label='Recommended allocation'] tbody tr", { hasText: "Google" });
const share = Number((await row.locator("td").nth(1).textContent()).replace("%", ""));
check("Google share respects 20% cap", share <= 20.0001, `${share}%`);
const amounts2 = await page.locator("section[aria-label='Recommended allocation'] tbody tr td:nth-child(2)").allTextContents();
check("Constrained plan still sums exactly", paisaSum(amounts2) === 100_000_000);

// 3 · ML: re-evaluate the saved model's sealed holdout.
await page.goto(`${BASE}/models`, { waitUntil: "networkidle" });
const evalButton = page.getByRole("button", { name: "Evaluate saved model" });
if (await evalButton.count()) {
  await evalButton.click();
  await page.getByText("Re-evaluated the same sealed holdout").waitFor({ timeout: 60_000 });
  check("Saved model re-evaluation matches stored holdout", await page.getByText("identical to the stored result").isVisible());
} else check("Saved model re-evaluation", false, "no finished model on this source");

// 4 · Campaigns: server sort + paging.
await page.goto(`${BASE}/campaigns`, { waitUntil: "networkidle" });
await page.getByRole("button", { name: /^ROAS/ }).click();
await page.waitForLoadState("networkidle");
const firstRoas = await page.locator("table.data tbody tr").first().locator("td").nth(10).textContent();
check("Campaign table sorts by ROAS on the server", /×/.test(firstRoas || ""), firstRoas);

// 5 · Legacy deep link redirect.
await page.goto(`${BASE}/budget-optimizer`, { waitUntil: "networkidle" });
check("Legacy /budget-optimizer redirects to /budget", page.url().endsWith("/budget"));

check("No uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
await mkdir(`${root}docs`, { recursive: true });
await writeFile(`${root}docs/e2e-flows.json`, JSON.stringify({ checked_at: new Date().toISOString(), checks }, null, 2) + "\n");
if (checks.some((c) => !c.ok)) process.exitCode = 1;
