"""A .safetensors metadata edit (fizgig.utils.st_meta, the Metadata tab's save) swaps the header only: the tensor
bytes are unchanged, the header stays 8-byte aligned, and a save that fails leaves no .tmp and the file as it was.

    python -m unittest discover -s checks -p "test_st_meta.py" -v
"""
import json
import os
import struct
import unittest
from unittest.mock import patch

import isolate
from fizgig.utils import st_meta

BODY = b"\x00\x00\x80?\x00\x00\x00@" * 3          # three fake float32 pairs


def _pack(header, body=BODY):
    raw = json.dumps(header, separators=(",", ":")).encode("utf-8")
    raw += b" " * (-len(raw) % 8)
    return struct.pack("<Q", len(raw)) + raw + body


def _split(path):
    with open(path, "rb") as f:
        data = f.read()
    n = struct.unpack("<Q", data[:8])[0]
    return n, json.loads(data[8:8 + n]), data[8 + n:]


class StMeta(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.join(isolate.ROOT, "st_meta")
        os.makedirs(self.dir, exist_ok=True)
        self.src = os.path.join(self.dir, "fake_lora.safetensors")
        header = {"__metadata__": {"ss_output_name": "fake_lora", "note": "old"},
                  "w": {"dtype": "F32", "shape": [6], "data_offsets": [0, 24]}}
        with open(self.src, "wb") as f:
            f.write(_pack(header))

    def test_read(self):
        self.assertEqual(st_meta.read_metadata(self.src), {"ss_output_name": "fake_lora", "note": "old"})

    def test_write_keeps_tensors(self):
        dest = os.path.join(self.dir, "fake_out.safetensors")
        st_meta.write_metadata(self.src, dest, {"note": "new, longer than before: " + "x" * 37, "n": 5})
        n, head, body = _split(dest)
        self.assertEqual(body, BODY)
        self.assertEqual(n % 8, 0)
        self.assertEqual(head["__metadata__"], {"note": "new, longer than before: " + "x" * 37, "n": "5"})
        self.assertEqual(head["w"]["data_offsets"], [0, 24])
        self.assertEqual(_split(self.src)[1]["__metadata__"]["note"], "old")        # the source untouched

    def test_write_in_place_and_clear(self):
        st_meta.write_metadata(self.src, self.src, {})
        n, head, body = _split(self.src)
        self.assertNotIn("__metadata__", head)
        self.assertEqual((n % 8, body), (0, BODY))
        self.assertFalse(os.path.exists(self.src + ".tmp"))

    def test_failed_save_leaves_no_tmp(self):
        before = open(self.src, "rb").read()
        with patch.object(st_meta.struct, "pack", side_effect=OSError("fake disk full")):
            with self.assertRaises(OSError):
                st_meta.write_metadata(self.src, self.src, {"note": "new"})
        self.assertFalse(os.path.exists(self.src + ".tmp"))
        self.assertEqual(open(self.src, "rb").read(), before)

    def test_not_safetensors(self):
        bad = os.path.join(self.dir, "fake.safetensors")
        with open(bad, "wb") as f:
            f.write(struct.pack("<Q", 0) + b"junk")
        with self.assertRaises(ValueError):
            st_meta.write_metadata(bad, bad, {"note": "x"})
        self.assertFalse(os.path.exists(bad + ".tmp"))


if __name__ == "__main__":
    unittest.main()
