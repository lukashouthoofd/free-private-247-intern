"""Reflection tests — stdlib only, no network, no creds.
   agent.llm.complete is monkeypatched and MEMORY_DIR points at a fresh tempdir, so the real
   data/ is never touched and no model is ever called. Covers the fail-closed contract:
     - < 3 notes              -> nothing stored
     - signal + 2 lessons     -> 2 'lesson'-kind records stored
     - model returns "NONE"   -> nothing stored
     - model raises LLMError  -> caught, nothing stored
"""
import os
import tempfile
import unittest

from agent import memory, reflect
from agent import llm


def _lessons_stored():
    return [r for r in memory.recent(50) if r.get("kind") == "lesson"]


class TestReflect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("MEMORY_DIR")
        os.environ["MEMORY_DIR"] = self.tmp
        self._orig_complete = llm.complete
        self.cfg = {"model": {"provider": "gemini", "model": "gemini-2.5-flash"}}

    def tearDown(self):
        llm.complete = self._orig_complete
        if self._prev is None:
            os.environ.pop("MEMORY_DIR", None)
        else:
            os.environ["MEMORY_DIR"] = self._prev

    def _seed(self, n):
        for i in range(n):
            memory.add(f"note {i}", kind="note")

    def _patch(self, fn):
        llm.complete = fn

    def test_fail_closed_too_few_notes(self):
        self._seed(2)                      # < 3 -> never even calls the model
        called = {"n": 0}
        self._patch(lambda *a, **k: called.__setitem__("n", called["n"] + 1) or {"content": "x"})
        out = reflect.reflect(self.cfg, logger=lambda m: None)
        self.assertEqual(out, "no signal -> no lesson")
        self.assertEqual(called["n"], 0)               # model not called
        self.assertEqual(_lessons_stored(), [])

    def test_signal_stores_two_lessons(self):
        self._seed(5)
        self._patch(lambda *a, **k: {"content": "lesson A\nlesson B"})
        out = reflect.reflect(self.cfg, logger=lambda m: None)
        stored = _lessons_stored()
        self.assertEqual(len(stored), 2)
        self.assertEqual({r["text"] for r in stored}, {"lesson A", "lesson B"})
        self.assertIn("stored 2", out)

    def test_none_reply_stores_nothing(self):
        self._seed(5)
        self._patch(lambda *a, **k: {"content": "NONE"})
        out = reflect.reflect(self.cfg, logger=lambda m: None)
        self.assertEqual(_lessons_stored(), [])
        self.assertIn("NONE", out)

    def test_empty_reply_stores_nothing(self):
        self._seed(5)
        self._patch(lambda *a, **k: {"content": "   "})
        reflect.reflect(self.cfg, logger=lambda m: None)
        self.assertEqual(_lessons_stored(), [])

    def test_model_error_is_caught_and_stores_nothing(self):
        self._seed(5)
        def boom(*a, **k):
            raise llm.LLMError("provider down")
        self._patch(boom)
        out = reflect.reflect(self.cfg, logger=lambda m: None)
        self.assertEqual(_lessons_stored(), [])
        self.assertIn("model error", out)

    def test_caps_at_three_lessons(self):
        self._seed(5)
        self._patch(lambda *a, **k: {"content": "L1\nL2\nL3\nL4\nL5"})
        reflect.reflect(self.cfg, logger=lambda m: None)
        self.assertEqual(len(_lessons_stored()), 3)


if __name__ == "__main__":
    unittest.main()
