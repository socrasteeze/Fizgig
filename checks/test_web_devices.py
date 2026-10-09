"""Per-device jobs, queue advance, device detection, and the engine lock.

Nothing here loads a model, calls nvidia-smi, or touches CUDA.

    python -m unittest checks.test_web_devices -v
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))
sys.path.insert(0, str(_REPO / "checks"))

from fastapi.testclient import TestClient

from fizgig.gpu_lock import held
from fizgig.web import devices, queue
from fizgig.web.app import app
from fizgig.web.engine_host import get_host, shutdown
from fizgig.web.procs import creationflags
import runner_guard

_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT"
    b"\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

_FAKE = """\
import os
import time
from pathlib import Path

output = Path(os.environ.get("FIZGIG_FAKE_OUTPUT") or ".")
output.mkdir(parents=True, exist_ok=True)
index = (os.environ.get("CUDA_VISIBLE_DEVICES") or "0").split(",")[0].strip()
if not index.isdigit():
    index = "0"
(output / "cuda_device.txt").write_text(index, encoding="utf-8")
(output / "cuda_order.txt").write_text(os.environ.get("CUDA_DEVICE_ORDER") or "", encoding="utf-8")
time.sleep(8.0 if index == "1" else 4.0)
print("steps: 1/1 [00:01<00:00, 1.00it/s, avr_loss=0.10]", flush=True)
"""

_ENV_KEYS = (
    "FIZGIG_WEB_JOBS",
    "FIZGIG_WEB_FAKE_TRAINER",
    "FIZGIG_NO_PERSIST",
    "FIZGIG_PREFS_FILE",
    "FIZGIG_WEB_FAKE_ENGINE",
    "FIZGIG_WEB_ENGINE_IDLE",
    "CUDA_VISIBLE_DEVICES",
    "FIZGIG_WEB_ROOTS",
)


def _reset_queue() -> None:
    queue._SEEN.clear()
    queue._ACTIVE_SEEN.clear()
    queue._READY.clear()
    queue._HOLD.clear()
    queue._DEVICE.clear()


class WebDeviceTests(unittest.TestCase):
    def setUp(self):
        shutdown()
        _reset_queue()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        (self.images / "a.png").write_bytes(_PNG)
        (self.images / "a.txt").write_text("a photo\n", encoding="utf-8")
        self.checkpoint = self.root / "checkpoint.safetensors"
        self.checkpoint.write_bytes(b"not a model")
        self.lora = self.root / "lora.safetensors"
        self.lora.write_bytes(b"not a model")
        script = self.root / "fake_train.py"
        script.write_text(_FAKE, encoding="utf-8")
        self._env = {key: os.environ.get(key) for key in _ENV_KEYS}
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_WEB_ROOTS"] = str(self.root)
        os.environ["FIZGIG_WEB_FAKE_TRAINER"] = str(script)
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ.pop("FIZGIG_WEB_FAKE_ENGINE", None)
        self._detail = None
        self._client = TestClient(app, base_url="http://127.0.0.1")
        self.client = self._client.__enter__()

    def tearDown(self):
        try:
            shutdown()
        except Exception:
            pass
        self._client.__exit__(None, None, None)
        runner_guard.end_runs(Path(os.environ["FIZGIG_WEB_JOBS"]))
        _reset_queue()
        deadline = time.time() + 8
        while time.time() < deadline and (held(0) or held(1)):
            time.sleep(0.05)
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _wait(self, fn, timeout=20):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return last
            time.sleep(0.05)
        self.fail(f"timed out; last={last!r} detail={self._detail!r}")

    def _body(self, output: Path, name: str, device: int):
        output.mkdir(parents=True, exist_ok=True)
        return {
            "family": "sdxl",
            "device": device,
            "values": {
                "LORA_OUTPUT_DIR": str(output),
                "LORA_NAME": name,
                "LEARNING_RATE": 1e-4,
                "NETWORK_DIM": 4,
                "NETWORK_ALPHA": 4,
                "MAX_TRAIN_EPOCHS": 1,
                "SAVE_EVERY_N_EPOCHS": 1,
                "SEED": 1,
                "image_folder": str(self.images),
            },
            "context": {
                "models": {"sdxl_checkpoint": str(self.checkpoint)},
                "image_folder": str(self.images),
            },
        }

    def _jobs(self):
        rows = self.client.get("/api/jobs").json()["jobs"]
        found = {}
        for row in rows:
            path = self.root / "jobs" / row["id"] / "job.json"
            if not path.is_file():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            found[data.get("values", {}).get("LORA_NAME")] = row
        return found

    def _cuda(self, output: Path) -> str:
        return (output / "cuda_device.txt").read_text(encoding="utf-8")

    def test_two_devices_run_together(self):
        os.environ.pop("CUDA_DEVICE_ORDER", None)
        out0 = self.root / "out0"
        out1 = self.root / "out1"
        out_again = self.root / "out-again"
        first = self.client.post("/api/jobs", json=self._body(out0, "A", 0))
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["device"], 0)
        self._wait(lambda: self.client.get(f"/api/jobs/{first.json()['id']}").json()["status"] == "running" and held(0))
        second = self.client.post("/api/jobs", json=self._body(out1, "B", 1))
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["device"], 1)

        def overlap():
            rows = {
                first.json()["id"]: self.client.get(f"/api/jobs/{first.json()['id']}").json(),
                second.json()["id"]: self.client.get(f"/api/jobs/{second.json()['id']}").json(),
            }
            self._detail = {key: row["status"] for key, row in rows.items()}
            return (
                rows[first.json()["id"]]["status"] == "running"
                and rows[second.json()["id"]]["status"] == "running"
                and held(0) and held(1)
                and (out0 / "cuda_device.txt").is_file()
                and (out1 / "cuda_device.txt").is_file()
            )

        self._wait(overlap)
        self.assertTrue(held(0))
        self.assertTrue(held(1))
        self.assertEqual(self._cuda(out0), "0")
        self.assertEqual(self._cuda(out1), "1")
        self.assertEqual((out0 / "cuda_order.txt").read_text(encoding="utf-8"), "PCI_BUS_ID")
        self.assertEqual((out1 / "cuda_order.txt").read_text(encoding="utf-8"), "PCI_BUS_ID")
        denied = self.client.post("/api/jobs", json=self._body(out_again, "Again", 0))
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(denied.json()["detail"], "a run is already active")

    def test_queue_advances_per_device(self):
        out_a = self.root / "a"
        out_b = self.root / "b"
        out_c = self.root / "c"
        out_d = self.root / "d"
        queued_c = self.client.post("/api/queue", json=self._body(out_c, "C", 0))
        queued_d = self.client.post("/api/queue", json=self._body(out_d, "D", 1))
        self.assertEqual(queued_c.status_code, 200, queued_c.text)
        self.assertEqual(queued_d.status_code, 200, queued_d.text)
        self.assertEqual(queued_c.json()["device"], 0)
        self.assertEqual(queued_d.json()["device"], 1)
        started_a = self.client.post("/api/jobs", json=self._body(out_a, "A", 0))
        started_b = self.client.post("/api/jobs", json=self._body(out_b, "B", 1))
        self.assertEqual(started_a.status_code, 200, started_a.text)
        self.assertEqual(started_b.status_code, 200, started_b.text)

        def mid():
            names = self._jobs()
            labels = [item["label"] for item in self.client.get("/api/queue").json()["items"]]
            state = {name: row["status"] for name, row in names.items()}
            self._detail = {"state": state, "queue": labels}
            ok = (
                state.get("A") == "done"
                and state.get("B") in {"queued", "running"}
                and "C" in state
                and "D" not in state
                and labels == ["D"]
            )
            return self._detail if ok else None

        self._wait(mid, timeout=20)
        self.assertEqual(self._cuda(out_a), "0")
        self.assertEqual(self._cuda(out_b), "1")

        def later():
            names = self._jobs()
            state = {name: row["status"] for name, row in names.items()}
            labels = [item["label"] for item in self.client.get("/api/queue").json()["items"]]
            self._detail = {"state": state, "queue": labels}
            ready = state.get("B") == "done" and "D" in state and (out_d / "cuda_device.txt").is_file()
            return self._detail if ready else None

        self._wait(later, timeout=20)
        self.assertEqual(self._cuda(out_c), "0")
        self.assertEqual(self._cuda(out_d), "1")
        self.assertNotIn("D", [item["label"] for item in self.client.get("/api/queue").json()["items"]])

    def test_visible_devices(self):
        os.environ.pop("CUDA_VISIBLE_DEVICES", None)
        calls = []

        def smi(*args, **kwargs):
            calls.append((args, kwargs))

            class _Out:
                stdout = "0\n1\n"

            return _Out()

        with patch.object(devices, "_pynvml_indices", return_value=None):
            with patch.object(devices.subprocess, "run", side_effect=smi):
                self.assertEqual(devices.visible_devices(), [0, 1])
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0][0][0], "nvidia-smi")
            self.assertEqual(calls[0][1]["creationflags"], creationflags())
            with patch.object(devices.subprocess, "run", side_effect=OSError("missing")):
                self.assertEqual(devices.visible_devices(), [0])

        def refused(*_args, **_kwargs):
            raise AssertionError("nvidia-smi should not be called")

        with patch.object(devices, "_pynvml_indices", return_value=[0, 1, 2]):
            with patch.object(devices.subprocess, "run", side_effect=refused):
                self.assertEqual(devices.visible_devices(), [0, 1, 2])

    def test_engine_locks_chosen_device(self):
        os.environ["FIZGIG_WEB_FAKE_ENGINE"] = "1"
        os.environ["FIZGIG_WEB_ENGINE_IDLE"] = "600"
        shutdown()
        seen = []
        real = subprocess.Popen

        def spy(*args, **kwargs):
            cmd = args[0] if args else kwargs.get("args")
            env = kwargs.get("env") or {}
            if isinstance(cmd, (list, tuple)) and any("engine_worker" in str(part) for part in cmd):
                seen.append(env.get("CUDA_VISIBLE_DEVICES"))
            return real(*args, **kwargs)

        with patch("fizgig.web.engine_host.subprocess.Popen", side_effect=spy):
            chosen = self.client.post("/api/engine/device", json={"device": 1})
            self.assertEqual(chosen.status_code, 200, chosen.text)
            self.assertEqual(chosen.json()["device"], 1)
            host = get_host()
            reply = host.load("repair", "klein", {"primary": str(self.lora)})
        self.assertTrue(reply["ok"])
        self.assertEqual(seen, ["1"])
        self.assertTrue(held(1))
        self.assertFalse(held(0))
        self.assertEqual(host.status()["device"], 1)
        host.unload()
        self.assertFalse(held(1))
        self.assertFalse(held(0))
        shutdown()

    def test_desktop_lock_uses_the_chosen_card(self):
        tree = ast.parse((_REPO / "lora_trainer_gui.py").read_text(encoding="utf-8"))
        held_calls = []
        lock_calls = []
        uses_env = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "_cuda_env_for_subprocess":
                    uses_env.append(node)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "_gpu_held":
                    held_calls.append(node)
                elif node.func.id == "GpuLock":
                    lock_calls.append(node)
        self.assertGreaterEqual(len(uses_env), 2)
        self.assertEqual(len(held_calls), 1)
        self.assertEqual(len(held_calls[0].args), 1)
        self.assertEqual(len(lock_calls), 1)
        self.assertEqual(len(lock_calls[0].args), 1)


if __name__ == "__main__":
    unittest.main()
