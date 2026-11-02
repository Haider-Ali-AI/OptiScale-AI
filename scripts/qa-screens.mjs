// Visual + console QA across routes and viewport widths.
// Usage (services running): node scripts/qa-screens.mjs [--widths=375,1440] [--routes=/,/overview]
// Browser: CHROMIUM_EXECUTABLE, else the installed Microsoft Edge/Chrome channel.
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const { chromium } = require("playwright");
const root = fileURLToPath(new URL("../", import.meta.url));
const arg = (name, fallback) => process.argv.find((a) => a.startsWith(`--${name}=`))?.split("=")[1] ?? fallback;
const BASE = process.env.APP_URL || "http://127.0.0.1:3000";
const ROUTES = arg("routes", "/,/overview,/campaigns,/data,/budget,/models,/lab,/commerce,/assistant,/methodology,/story").split(",");
const WIDTHS = arg("widths", "320,375,430,768,1024,1280,1440").split(",").map(Number);
const THEME = arg("theme", "dark");
const SHOTS = new Set(arg("shots", "375,1440").split(",").map(Number));

const launch = process.env.CHROMIUM_EXECUTABLE
  ? { executablePath: process.env.CHROMIUM_EXECUTABLE }
  : { channel: process.env.PW_CHANNEL || "msedge" };
const browser = await chromium.launch({ headless: true, ...launch });
await mkdir(`${root}docs/screenshots`, { recursive: true });
const results = [];
for (const width of WIDTHS) {
  const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: THEME });
  await context.addInitScript((t) => localStorage.setItem("signalspend.theme", t), THEME);
  for (const route of ROUTES) {
    const page = await context.newPage();
    const errors = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text().slice(0, 300)));
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message.slice(0, 300)}`));
    const response = await page.goto(BASE + route, { waitUntil: "networkidle", timeout: 90_000 });
    await page.waitForTimeout(900);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    const h1 = await page.locator("h1").first().textContent().catch(() => null);
    const name = `${route === "/" ? "welcome" : route.slice(1)}-${width}${THEME === "light" ? "-light" : ""}`;
    if (SHOTS.has(width)) await page.screenshot({ path: `${root}docs/screenshots/${name}.png`, fullPage: true });
    results.push({ route, width, status: response?.status(), h1, horizontal_overflow_px: overflow, console_errors: errors });
    console.log(`${String(response?.status()).padEnd(4)} ${String(width).padEnd(5)} ${route.padEnd(13)} overflow=${overflow}px errors=${errors.length} ${h1 ?? ""}`);
    await page.close();
  }
  await context.close();
}
await browser.close();
await writeFile(`${root}docs/qa-screens-${THEME}.json`, JSON.stringify({ checked_at: new Date().toISOString(), base: BASE, results }, null, 2) + "\n");
const bad = results.filter((r) => r.status !== 200 || r.horizontal_overflow_px > 0 || r.console_errors.length);
console.log(bad.length ? `\n${bad.length} issue(s) found` : "\nAll routes clean");
if (bad.length) process.exitCode = 1;
