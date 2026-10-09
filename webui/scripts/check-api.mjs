import { execFileSync, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const webui = resolve(here, "..");
const repo = resolve(webui, "..");

function pythonBin() {
  const fromEnv = (process.env.FIZGIG_PY || "").trim();
  if (fromEnv) {
    return fromEnv;
  }
  const win = resolve(repo, "venv/Scripts/python.exe");
  const unix = resolve(repo, "venv/bin/python");
  if (existsSync(win)) {
    return win;
  }
  if (existsSync(unix)) {
    return unix;
  }
  const py3 = spawnSync("python3", ["-c", "import sys"], { stdio: "ignore" });
  if (py3.status === 0) {
    return "python3";
  }
  return "python";
}

const py = pythonBin();
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
