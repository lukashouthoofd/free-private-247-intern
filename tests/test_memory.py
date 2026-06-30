"""Memory + digest tests — stdlib only, no network, no creds.
   Each test points MEMORY_DIR at a fresh tempdir so the real data/ is never touched."""
import os
import tempfile
import unittest

from agent import memory, digest


class TestMemory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("MEMORY_DIR")
        os.environ["MEMORY_DIR"] = self.tmp

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("MEMORY_DIR", None)
        else:
            os.environ["MEMORY_DIR"] = self._prev

    def test_missing_file_never_crashes(self):
        # nothing written yet — reads must return empty, not raise
        self.assertEqual(memory.recent(), [])
        self.assertEqual(memory.search("anything"), [])

    def test_add_recent_search_roundtrip(self):
        memory.add("operator prefers Flemish, short answers", kind="fact")
        memory.add("call KVC Deinze back about the SLA", kind="task")
        memory.add("just a note")

        recent = memory.recent(20)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[-1]["text"], "just a note")          # newest last
        self.assertEqual(recent[0]["kind"], "fact")

        hits = memory.search("KVC")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["kind"], "task")

        # kind is searchable too
        self.assertEqual(len(memory.search("task")), 1)
        self.assertEqual(memory.search("nope-not-there"), [])

    def test_recent_n_window(self):
        for i in range(5):
            memory.add(f"note {i}")
        self.assertEqual(len(memory.recent(2)), 2)
        self.assertEqual(memory.recent(2)[-1]["text"], "note 4")
        self.assertEqual(memory.recent(0), [])

    def test_empty_text_is_ignored(self):
        self.assertEqual(memory.add("   "), {})
        self.assertEqual(memory.recent(), [])

    def test_remember_and_recall_tools(self):
        r = memory.MEMORY_TOOLS[0].fn({"text": "deploy via netlify --site", "kind": "decision"})
        self.assertIn("remembered", r)
        out = memory.MEMORY_TOOLS[1].fn({"query": "netlify"})
        self.assertIn("netlify", out)
        # recall without query returns recent
        self.assertIn("netlify", memory.MEMORY_TOOLS[1].fn({}))

    def test_tools_registered_and_autonomous(self):
        names = {t.name: t.gate for t in memory.MEMORY_TOOLS}
        self.assertEqual(names["remember"], "autonomous")
        self.assertEqual(names["recall"], "autonomous")


class TestDigest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._prev = os.environ.get("MEMORY_DIR")
        os.environ["MEMORY_DIR"] = self.tmp

    def tearDown(self):
        if self._prev is None:
            os.environ.pop("MEMORY_DIR", None)
        else:
            os.environ["MEMORY_DIR"] = self._prev

    def test_build_digest_nonempty_with_seeded_memory(self):
        memory.add("operator is Lukas in Deinze", kind="fact")
        memory.add("finish the KVC proposal", kind="task")
        cfg = {"agent": {"name": "Aria", "operator": "Lukas"}}
        brief = digest.build_digest(cfg)
        self.assertTrue(brief.strip())
        self.assertIn("Daily brief", brief)
        self.assertIn("Aria", brief)
        self.assertIn("KVC proposal", brief)        # pulled from memory
        self.assertIn("task", brief)                # 'task'-tagged section

    def test_build_digest_nonempty_when_memory_empty(self):
        brief = digest.build_digest({})
        self.assertTrue(brief.strip())
        self.assertIn("empty", brief.lower())

    def test_deliver_without_token_just_prints(self):
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
        logs = []
        brief = digest.deliver({"agent": {"name": "Aria"}}, logger=logs.append)
        self.assertTrue(brief.strip())
        self.assertTrue(any("not sent" in m for m in logs))   # delivery skipped, no crash


if __name__ == "__main__":
    unittest.main()
