"""What deletes or moves files: Delete run lists what it would delete and touches nothing until confirmed, then
takes only that run's own files (never a longer-named run's, never the training folder); Remove from the training
set moves a file and its caption into removed/ inside the folder, and Undo brings them back.

    python -m unittest discover -s checks -p "test_destructive.py" -v
"""
import os
import tempfile
import unittest

import isolate
from fizgig.web import history, server
from webserve import Served


def _touch(path, data=b"fake"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _files(root):
    return sorted(os.path.relpath(os.path.join(r, f), root).replace("\\", "/") for r, _d, fs in os.walk(root)
                  for f in fs)


class DeleteRun(unittest.TestCase):
    def setUp(self):
        root = tempfile.mkdtemp(prefix="delete_run-", dir=isolate.ROOT)        # each test its own folders
        self.out, self.data = os.path.join(root, "out"), os.path.join(root, "data")
        for p in ("fake_run.safetensors", "fake_run-000002.safetensors", "fake_run-000002-state/model.bin",
                  "sample/fake_run_e000002_00_1_1.png", "fake_run2.safetensors", "fake_run2-000002-state/model.bin",
                  "sample/fake_run2_e000002_00_1_1.png", "notes.txt"):
            _touch(os.path.join(self.out, p))
        _touch(os.path.join(self.data, "photo.png"))
        self.id = history.start("web", "klein", "fake_run", self.out, self.data, {})
        history.end(self.id, "finished")

    def test_asks_first(self):
        before = _files(self.out)
        r = server.delete_run(self.id)
        self.assertEqual((r["checkpoints"], r["states"], r["previews"]), (2, 1, 1))
        self.assertEqual(_files(self.out), before)
        self.assertIsNotNone(history.get(self.id))

    def test_route_asks_first(self):
        before = _files(self.out)
        s = Served()
        try:
            status, d = s.json("POST", "/api/runs/delete", {"id": self.id})
        finally:
            s.close()
        self.assertEqual(status, 200)
        self.assertEqual(_files(self.out), before)

    def test_confirmed_takes_only_its_own(self):
        self.assertTrue(server.delete_run(self.id, confirm=True).get("ok"))
        self.assertEqual(_files(self.out), ["fake_run2-000002-state/model.bin", "fake_run2.safetensors", "notes.txt",
                                            "sample/fake_run2_e000002_00_1_1.png"])
        self.assertEqual(_files(self.data), ["photo.png"])
        self.assertIsNone(history.get(self.id))

    def test_training_run_refused(self):
        with server._lock:
            server._run.update(state="running", output_dir=self.out, lora="fake_run")
        try:
            r = server.delete_run(self.id, confirm=True)
        finally:
            with server._lock:
                server._run.update(state="idle", output_dir="", lora="")
        self.assertIn("error", r)
        self.assertIn("fake_run.safetensors", _files(self.out))


class RemoveFromDataset(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="remove-", dir=isolate.ROOT)
        self.folder = os.path.join(self.root, "set")
        for p in ("set/a.png", "set/a.txt", "set/b.png", "outside.png", "outside.txt"):
            _touch(os.path.join(self.root, p))

    def test_moves_into_removed_and_back(self):
        moved = server.remove_from_dataset(self.folder, "a.png", ".txt")
        self.assertEqual(sorted(m[0] for m in moved), ["a.png", "a.txt"])
        self.assertEqual(_files(self.folder), ["b.png", "removed/a.png", "removed/a.txt"])
        self.assertEqual(sorted(server.restore_to_dataset(self.folder, moved)), ["a.png", "a.txt"])
        self.assertEqual(_files(self.folder), ["a.png", "a.txt", "b.png"])

    def test_stays_inside_the_folder(self):
        for name in ("../outside.png", "..\\outside.png", os.path.join(self.root, "outside.png")):
            with self.assertRaises(ValueError, msg=name):
                server.remove_from_dataset(self.folder, name, ".txt")
        self.assertEqual(_files(self.root), ["outside.png", "outside.txt", "set/a.png", "set/a.txt", "set/b.png"])
        # Undo can't be pointed outside either
        self.assertEqual(server.restore_to_dataset(self.folder, [["../outside2.png", "../../outside.png"]]), [])
        self.assertEqual(_files(self.root), ["outside.png", "outside.txt", "set/a.png", "set/a.txt", "set/b.png"])

    def test_never_overwrites_an_earlier_removal(self):
        first = server.remove_from_dataset(self.folder, "a.png", ".txt")
        _touch(os.path.join(self.folder, "a.png"), b"second")
        second = server.remove_from_dataset(self.folder, "a.png", ".txt")
        self.assertEqual(second, [["a.png", "a (2).png"]])
        self.assertEqual(len(first), 2)


if __name__ == "__main__":
    unittest.main()
