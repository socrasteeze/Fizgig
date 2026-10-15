"""Repair Studio's state on the server (fizgig.web.studio) and its worker's Save (fizgig.scripts.studio_worker).

    python -m unittest discover -s checks -p "test_studio.py" -v
"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import isolate  # noqa: F401  (before fizgig.web)
from fizgig.web import studio


class _Proc:
    """A worker process that quits when asked."""
    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class StopWorker(unittest.TestCase):
    def setUp(self):
        self.saved = dict(studio._S)
        self.addCleanup(lambda: (studio._S.clear(), studio._S.update(self.saved)))
        p = patch.object(studio, "_send", lambda cmd: None)
        p.start()
        self.addCleanup(p.stop)

    def test_stopped_worker_leaves_studio_unloaded(self):
        with studio._lock:
            studio._S.update(proc=_Proc(), sock=object(), port=1, state="ready", primary="fake.safetensors",
                             family="klein", rendering=True, pending=({}, None))
        studio.stop_worker()                    # a training run wants the GPU
        with studio._lock:
            self.assertEqual((studio._S["state"], studio._S["rendering"], studio._S["primary"],
                              studio._S["pending"]), ("idle", False, "", None))
        self.assertEqual(studio.render({}), {"error": "Load a LoRA first."})
        self.assertFalse(studio.holding_gpu())

    def test_load_switching_models_stays_loading(self):
        # load() stops another model's worker itself, mid-load: that load goes on
        with studio._lock:
            studio._S.update(proc=_Proc(), sock=object(), port=1, state="loading", family="klein")
        studio.stop_worker()
        with studio._lock:
            self.assertEqual((studio._S["state"], studio._S["family"]), ("loading", "klein"))


class SaveBakesStudiosLora(unittest.TestCase):
    """Studio and Royale share one engine: Royale swaps its LoRA in. Save must bake Studio's, or refuse."""

    def setUp(self):
        self.saved = dict(studio._S)
        self.addCleanup(lambda: (studio._S.clear(), studio._S.update(self.saved)))

    def test_server_sends_studios_lora(self):
        sent = []
        with studio._lock:
            studio._S.update(state="ready", primary="C:/loras/fake_studio.safetensors")
        with patch.object(studio, "_send", sent.append):
            studio.save("C:/out/fake_fixed.safetensors", {}, False)
        self.assertEqual(sent[0]["primary"], "C:/loras/fake_studio.safetensors")

    def test_server_refuses_when_royale_took_the_worker(self):
        with studio._lock:
            studio._S.update(state="idle", primary="")
        with patch.object(studio, "_send", side_effect=AssertionError("nothing sent")):
            with self.assertRaises(ValueError):
                studio.save("C:/out/fake_fixed.safetensors", {}, False)

    def test_worker_refuses_another_lora(self):
        from fizgig.scripts import studio_worker as w
        baked = []
        eng = SimpleNamespace(primary_network=object(), primary_path="C:/loras/fake_royale-000008.safetensors",
                              save_repaired=lambda out, state, include_donor=False: baked.append(out) or {})
        with patch.dict(w.S, engine=eng), patch.object(w, "_state", lambda d: d), patch.object(w, "emit"):
            with self.assertRaises(ValueError):
                w.cmd_save({"out": "fake_fixed.safetensors", "state": {},
                            "primary": "C:/loras/fake_studio.safetensors"})
            self.assertEqual(baked, [])
            w.cmd_save({"out": "fake_fixed.safetensors", "state": {},
                        "primary": "C:/loras/fake_royale-000008.safetensors"})
            self.assertEqual(baked, ["fake_fixed.safetensors"])


if __name__ == "__main__":
    unittest.main()
