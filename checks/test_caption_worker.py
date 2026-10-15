"""A caption job the worker can't run (no pictures it reads, no instruction) still ends with DONE, so the Captions
tab leaves "running" (it waits for DONE or STOPPED). Reached by Re-caption on a clip in a photo model's folder, or
on a picture type the page lists and the worker doesn't read.

    python -m unittest discover -s checks -p "test_caption_worker.py" -v
"""
import contextlib
import io
import os
import threading
import unittest
from types import SimpleNamespace

import isolate
from fizgig.scripts import batch_caption
from fizgig.web import captions


def _job_lines(state, job):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        batch_caption._run_job(state, job)
    return out.getvalue().splitlines()


class FailedJobsEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = os.path.join(isolate.ROOT, "caption_worker")
        os.makedirs(cls.dir, exist_ok=True)
        cls.clip = os.path.join(cls.dir, "clip.mp4")
        cls.photo = os.path.join(cls.dir, "photo.png")
        for p in (cls.clip, cls.photo):
            with open(p, "wb") as f:
                f.write(b"fake")

    def _list(self, *paths):
        path = os.path.join(self.dir, "list.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(paths))
        return path

    def test_nothing_it_reads(self):
        lines = _job_lines(SimpleNamespace(include_video=False, backend="florence"),
                           {"list_file": self._list(self.clip)})
        self.assertEqual(lines, ["FAIL: no images in list", "DONE"])

    def test_no_instruction_file(self):
        lines = _job_lines(SimpleNamespace(include_video=False, backend="qwen"), {"list_file": self._list(self.photo)})
        self.assertEqual(lines, ["FAIL: instruction_file required", "DONE"])

    def test_empty_instruction(self):
        instr = os.path.join(self.dir, "instr.txt")
        with open(instr, "w", encoding="utf-8") as f:
            f.write("  \n")
        lines = _job_lines(SimpleNamespace(include_video=False, backend="qwen"),
                           {"list_file": self._list(self.photo), "instruction_file": instr})
        self.assertEqual(lines, ["FAIL: empty instruction", "DONE"])


class ReaderLeavesRunning(unittest.TestCase):
    def test_done_after_fail(self):
        seen = {}

        def worker_output():                    # the worker stays up (its model loaded) after the job
            yield "FAIL: no images in list\n"
            yield "DONE\n"
            seen.update(state=captions._st["state"], job=captions._st["job"], fail=captions._st["fail"])

        proc = SimpleNamespace(stdout=worker_output())
        with captions._lock:
            saved = dict(captions._st)
            captions._st.update(proc=proc, state="running", job="fake-job", fail=0, ready=threading.Event())
        try:
            captions._reader(proc)
            self.assertEqual(seen, {"state": "loaded", "job": "", "fail": 1})
        finally:
            with captions._lock:
                captions._st.clear()
                captions._st.update(saved)


if __name__ == "__main__":
    unittest.main()
