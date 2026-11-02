// AI insight assistant journey: for each report type, the Explain button stays disabled
// until the user approves the exact summary, then a real NVIDIA explanation appears.
// Needs NVIDIA_API_KEY configured on the target server. APP_URL defaults to local.
import { writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../", import.meta.url));
const BASE = process.env.APP_URL || "http://127.0.0.1:3000";
const launch = process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : { channel: process.env.PW_CHANNEL || "msedge" };
const httpCredentials = process.env.HTTP_USER ? { username: process.env.HTTP_USER, password: process.env.HTTP_PASS || "" } : undefined;
const browser = await chromium.launch({ headless: true, ...launch });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 }, httpCredentials })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const checks = [];
const check = (name, ok, detail = "") => {
  checks.push({ name, ok, detail });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? ` · ${detail}` : ""}`);
};

await page.goto(`${BASE}/assistant`, { waitUntil: "networkidle" });
const keyStatus = (await page.locator("dd").filter({ hasText: "configured" }).first().textContent())?.trim() || "";
check("NVIDIA key configured on the server", keyStatus.startsWith("configured"), keyStatus);
for (const kind of ["Performance", "Model", "Budget plan"]) {
  const summaryResponse = page.waitForResponse((r) => r.url().includes("/api/v1/ai/summary") && r.ok(), { timeout: 60_000 });
  await page.getByRole("button", { name: kind, exact: true }).click();
  await summaryResponse.catch(() => undefined); // the first type may already be loaded
  await page.locator("pre.pre").waitFor({ timeout: 60_000 });
  const explain = page.getByRole("button", { name: "Explain" });
  check(`${kind}: Explain disabled until approval`, await explain.isDisabled());
  await page.getByLabel(/I approve sending exactly this summary/).check();
  await explain.click();
  const answer = page.locator(".panel.flat p").first();
  await answer.waitFor({ timeout: 120_000 });
  const text = ((await answer.textContent()) || "").replace(/\s+/g, " ");
  check(`${kind}: explanation received`, text.length > 40, text.slice(0, 110) + "…");
}
check("No uncaught page errors", errors.length === 0, errors.join(" | "));
await browser.close();
await writeFile(`${root}docs/e2e-assistant${process.env.QA_TAG ? "-" + process.env.QA_TAG : ""}.json`, JSON.stringify({ checked_at: new Date().toISOString(), base: BASE, checks }, null, 2) + "\n");
if (checks.some((c) => !c.ok)) process.exitCode = 1;
