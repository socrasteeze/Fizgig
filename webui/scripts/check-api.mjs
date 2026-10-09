import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const webui = resolve(here, "..");
const repo = resolve(webui, "..");
const py = resolve(repo, "venv/Scripts/python.exe");
const cli = resolve(webui, "node_modules/openapi-typescript/bin/cli.js");
const committed = resolve(webui, "src/api.d.ts");
const dir = mkdtempSync(resolve(tmpdir(), "fizgig-api-"));
try {
  const spec = resolve(dir, "openapi.json");
  const generated = resolve(dir, "api.d.ts");
  execFileSync(py, [resolve(here, "dump_openapi.py"), spec], { cwd: repo, stdio: "inherit" });
  execFileSync(process.execPath, [cli, spec, "-o", generated], { cwd: webui, stdio: "inherit" });
  const have = readFileSync(committed, "utf8").replace(/\r\n/g, "\n");
  const want = readFileSync(generated, "utf8").replace(/\r\n/g, "\n");
  if (have !== want) {
    console.error("webui/src/api.d.ts does not match the server. Run: node webui/scripts/gen-api.mjs");
    process.exit(1);
  }
} finally {
  rmSync(dir, { recursive: true, force: true });
}
