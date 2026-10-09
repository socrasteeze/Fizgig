"""Explorer mutation, freeze, a cancellable fake roll, and the bake call.

Nothing here loads a model or touches CUDA. The save test imports the bake
module (that import loads torch) and replaces ``save_repaired_lora`` before it runs.

    python -m unittest checks.test_web_explorer -v
"""
import json
import os
import random
import sys
import tempfile
import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

from fizgig.repair_studio.state import BlockState, SliderState
from fizgig.web import explorer
from fizgig.web.explorer import roll_variants
from fizgig.web.jobs import JobError

_IDS = ["double_0", "double_1", "single_0", "single_1", "single_2"]


def _loop(state, active, mutations, intensity, structure, anchor, last_pick):
    """The desktop loop, written out again so it is not ``roll_variants`` itself."""
    out = []
    for vi in range(4):
        vs_structure = structure if vi < 2 else 0.0
        if vi == 3 and last_pick:
            protected = set(active) - set(last_pick)
            if len(protected) < 2:
                protected = set(active)
            target = protected
        else:
            target = set(active)
        out.append(state.mutate(
            target, num_mutations=int(mutations), intensity=float(intensity),
            structure=float(vs_structure), anchor=str(anchor),
        ))
    return out


class ExplorerStateTests(unittest.TestCase):
    def setUp(self):
        explorer.clear_session()

    def tearDown(self):
        explorer.clear_session()

    def _same(self, last_pick, seed):
        state = SliderState(blocks={bid: BlockState() for bid in _IDS})
        active = list(_IDS)
        anchor = "double_0"
        random.seed(seed)
        got = [item.to_json() for item in roll_variants(state, active, 3, 0.964, 1.0, anchor, last_pick)]
        random.seed(seed)
        expected = [item.to_json() for item in _loop(state, active, 3, 0.964, 1.0, anchor, last_pick)]
        self.assertEqual(len(got), 4)
        self.assertEqual(got, expected)

    def test_roll_variants_matches_mutate_loop(self):
        self._same(set(), 1234)
        self._same({"double_1", "single_0"}, 99)

    def test_freeze_and_undo_do_not_render(self):
        state = SliderState(blocks={bid: BlockState() for bid in _IDS})
        explorer.seed_baseline(state, _IDS, "double_0")
        state.blocks["single_2"].primary_strength = 0.2
        frozen = explorer.freeze({"choice": "freeze"})
        self.assertEqual(frozen["locked"], ["single_2"])
        restored = explorer.freeze({"choice": "undo"})
        self.assertEqual(restored["locked"], [])
        self.assertAlmostEqual(restored["blocks"]["single_2"]["primary_strength"], 0.2)

        explorer.clear_session()
        state = SliderState(blocks={bid: BlockState() for bid in _IDS})
        explorer.seed_baseline(state, _IDS, "double_0")
        state.blocks["double_1"].primary_strength = 0.4
        explorer.freeze({"choice": "freeze"})
        self.assertEqual(explorer.session_view()["locked"], ["double_1"])
        explorer.push_history()
        state.blocks["double_1"].primary_strength = 1.0
        explorer.freeze({"choice": "unlock"})
        self.assertEqual(explorer.session_view()["locked"], [])
        undone = explorer.undo({})
        self.assertEqual(undone["locked"], ["double_1"])
        self.assertAlmostEqual(undone["blocks"]["double_1"]["primary_strength"], 0.4)
        self.assertEqual(undone["history"], 0)
        with self.assertRaises(JobError) as caught:
            explorer.undo({})
        self.assertEqual(caught.exception.status, 422)


class ExplorerHostTests(unittest.TestCase):
    def setUp(self):
        from fizgig.web.engine_host import shutdown
        shutdown()
        explorer.clear_session()
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.lora = self.output / "Demo.safetensors"
        self.lora.write_bytes(b"not a model")
        (self.root / "prefs.json").write_text(json.dumps({
            "lora_output_dir": str(self.output),
        }), encoding="utf-8")
        self._env = {
            key: os.environ.get(key) for key in (
                "FIZGIG_WEB_JOBS", "FIZGIG_PREFS_FILE", "FIZGIG_NO_PERSIST",
                "FIZGIG_WEB_FAKE_ENGINE", "FIZGIG_WEB_FAKE_STEP", "FIZGIG_WEB_ENGINE_IDLE",
            )
        }
        os.environ["FIZGIG_WEB_JOBS"] = str(self.root / "jobs")
        os.environ["FIZGIG_PREFS_FILE"] = str(self.root / "prefs.json")
        os.environ["FIZGIG_NO_PERSIST"] = "1"
        os.environ["FIZGIG_WEB_FAKE_ENGINE"] = "1"
        os.environ["FIZGIG_WEB_FAKE_STEP"] = "0.08"
        os.environ["FIZGIG_WEB_ENGINE_IDLE"] = "600"

    def tearDown(self):
        from fizgig.web.engine_host import shutdown
        shutdown()
        explorer.clear_session()
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _wait(self, fn, timeout=8):
        end = time.time() + timeout
        last = None
        while time.time() < end:
            last = fn()
            if last:
                return last
            time.sleep(0.02)
        self.fail(f"timed out; last={last!r}")

    def test_roll_newest_gen_matches_seeded_variants(self):
        from fizgig.web.engine_host import get_host
        loaded = explorer.load({"family": "klein", "lora": str(self.lora)})
        self.assertTrue(loaded["loaded"])
        ids = list(loaded["blocks"])
        anchor = ids[0]
        state = explorer.baseline()
        active = set(ids)
        random.seed(1234)
        expected = [item.to_json() for item in roll_variants(state, active, 8, 0.964, 1.0, anchor, set())]
        random.seed(1234)
        first = explorer.roll({"steps": 6, "gen": 1})
        self.assertEqual((first["gen"], first["status"]), (1, "running"))
        self.assertEqual(first["variants"], expected)
        second = explorer.roll({"steps": 2, "gen": 2})
        self.assertEqual(second["gen"], 2)
        host = get_host()
        seen = []
        self._wait(lambda: seen.extend(host.drain()) or any(
            item.get("event") == "done" and item.get("gen") == 2 for item in seen))
        dones = [item for item in seen if item.get("event") == "done"]
        frames = [item for item in seen if item.get("event") == "frame"]
        self.assertEqual([item["gen"] for item in dones], [2])
        self.assertEqual(
            [item["side"] for item in frames],
            ["baseline", "variant", "variant", "variant", "variant"],
        )
        self.assertTrue(all(item["gen"] == 2 for item in frames))
        self.assertEqual(dones[0]["records"]["count"], 5)

    def test_save_calls_bake_with_baseline(self):
        import fizgig.repair_studio.bake as bake_mod
        explorer.load({"family": "klein", "lora": str(self.lora), "prompt": "a cat"})
        seen = {}

        def fake_bake(primary_path, state, out_path, donor_path=None):
            seen["primary"] = primary_path
            seen["state"] = state
            seen["out"] = out_path
            seen["donor"] = donor_path
            return {"keys_in": 1, "keys_out": 1, "dropped_blocks": [], "rescaled_blocks": [], "blended_blocks": []}

        original = bake_mod.save_repaired_lora
        bake_mod.save_repaired_lora = fake_bake
        try:
            saved = explorer.save({})
        finally:
            bake_mod.save_repaired_lora = original
        self.assertTrue(str(saved["path"]).endswith("_explored.safetensors"))
        self.assertTrue(str(seen["out"]).endswith("_explored.safetensors"))
        self.assertIs(seen["state"], explorer.baseline())
        self.assertEqual(seen["state"].prompt, "a cat")
        self.assertIsNone(seen["donor"])
        self.assertEqual(seen["primary"], str(self.lora.resolve()))

    def test_load_rejects_reference_outside_roots(self):
        from fizgig.web.engine_host import get_host
        outside = self.root / "secret.png"
        outside.write_bytes(b"x")
        with self.assertRaises(JobError) as caught:
            explorer.load({"family": "klein", "lora": str(self.lora), "reference": str(outside)})
        self.assertEqual(caught.exception.status, 403)
        self.assertIsNone(explorer.baseline())
        self.assertFalse(get_host().loaded)

    def test_load_accepts_reference_inside_roots(self):
        image = self.output / "ref.png"
        image.write_bytes(b"x")
        explorer.load({"family": "klein", "lora": str(self.lora), "reference": str(image)})
        self.assertEqual(Path(explorer.baseline().ref_image_path), image.resolve())

    def test_roll_rejects_reference_outside_roots(self):
        from fizgig.web.engine_host import get_host
        explorer.load({"family": "klein", "lora": str(self.lora)})
        outside = self.root / "secret.png"
        outside.write_bytes(b"x")
        host = get_host()
        before = host.latest
        with self.assertRaises(JobError) as caught:
            explorer.roll({"reference": str(outside), "gen": 1})
        self.assertEqual(caught.exception.status, 403)
        self.assertEqual(host.latest, before)
        self.assertFalse(host.busy)
        self.assertEqual(explorer.baseline().ref_image_path, "")

    def test_roll_accepts_reference_inside_roots(self):
        image = self.output / "ref.png"
        image.write_bytes(b"x")
        explorer.load({"family": "klein", "lora": str(self.lora)})
        started = explorer.roll({"reference": str(image), "steps": 1, "gen": 1})
        self.assertEqual(started["status"], "running")
        self.assertEqual(Path(explorer.baseline().ref_image_path), image.resolve())


if __name__ == "__main__":
    unittest.main()
