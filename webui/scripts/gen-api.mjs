import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const webui = resolve(here, "..");
const repo = resolve(webui, "..");
const py = resolve(repo, "venv/Scripts/python.exe");
const cli = resolve(webui, "node_modules/openapi-typescript/bin/cli.js");
const dir = mkdtempSync(resolve(tmpdir(), "fizgig-api-"));
const spec = resolve(dir, "openapi.json");
try {
  execFileSync(py, [resolve(here, "dump_openapi.py"), spec], { cwd: repo, stdio: "inherit" });
  execFileSync(process.execPath, [cli, spec, "-o", resolve(webui, "src/api.d.ts")], {
    cwd: webui,
    stdio: "inherit",
  });
} finally {
  rmSync(dir, { recursive: true, force: true });
}
