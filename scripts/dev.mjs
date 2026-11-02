// Starts FastAPI (127.0.0.1:8000) and Next.js (127.0.0.1:3000) together.
// Works on Windows (.venv\Scripts\python.exe) and macOS/Linux (.venv/bin/python).
// Optional: ADS_DATA_DIR (disposable workspace), JAVA_HOME (Spark). A JDK unpacked under
// ./.runtime/<jdk-folder>/bin/java(.exe) is detected automatically for Spark.
import { spawn } from "node:child_process";
import { existsSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("../", import.meta.url));
const win = process.platform === "win32";
const candidates = [join(root, ".venv", win ? "Scripts/python.exe" : "bin/python"), join(root, "..", ".venv", win ? "Scripts/python.exe" : "bin/python")];
const python = process.env.PYTHON || candidates.find(existsSync);
if (!python) {
  console.error("Python environment not found. Create .venv and install requirements (see README.md).");
  process.exit(1);
}
const env = { ...process.env };
if (!env.JAVA_HOME) {
  for (const base of [join(root, ".runtime"), join(root, "..", ".runtime")]) {
    if (!existsSync(base)) continue;
    const jdk = readdirSync(base).map((d) => join(base, d)).find((d) => existsSync(join(d, "bin", win ? "java.exe" : "java")));
    if (jdk) {
      env.JAVA_HOME = jdk;
      break;
    }
  }
}
if (env.JAVA_HOME) console.log(`Spark Java runtime: ${env.JAVA_HOME}`);
const children = [
  spawn(python, ["-m", "uvicorn", "ads_optimizer.api:app", "--app-dir", "backend/src", "--host", "127.0.0.1", "--port", "8000"], { cwd: root, stdio: "inherit", env }),
  spawn(process.execPath, [join(root, "frontend/node_modules/next/dist/bin/next"), "dev", "--hostname", "127.0.0.1", "--port", "3000"], { cwd: join(root, "frontend"), stdio: "inherit", env }),
];
let stopping = false;
const stop = (code) => {
  if (stopping) return;
  stopping = true;
  children.forEach((c) => c.kill());
  process.exitCode = code;
};
for (const c of children) {
  c.on("error", (e) => (console.error(e.message), stop(1)));
  c.on("exit", (code) => stop(code || 0));
}
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));
