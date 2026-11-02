import { cpSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

// Hosted builds only: copy the unchanged Python package beside the Vercel
// function. The copy is generated, Git-ignored and never edited by hand.
const generated = fileURLToPath(new URL("../.backend/", import.meta.url));
rmSync(generated, { recursive: true, force: true });
mkdirSync(generated, { recursive: true });
cpSync(new URL("../../backend/src/", import.meta.url), `${generated}/src`, {
  recursive: true,
  filter: (source) => !source.includes("__pycache__") && !source.endsWith(".pyc"),
});
