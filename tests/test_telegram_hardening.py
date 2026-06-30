"""Hardening tests for agent/telegram.py — run with:
    python -m unittest discover -s tests
Stdlib-only (unittest), no network, no API key. Covers issue #1 fixes:
fail-closed allow-list, approval re-queue, wall-clock timeout, empty-send guard,
stale-callback skip, getMe retry, and _api 429 backoff."""
import unittest
import urllib.error

from agent.telegram import TelegramGateway


def _gw(scripted, allowed={42}):
    """Scripted gateway: bypass __init__, stub _api to pop scripted responses.
    Mirrors the _gw helper in test_agent.py; also sets _pending=[] (telegram-1)."""
    gw = TelegramGateway.__new__(TelegramGateway)
    gw.token, gw.allowed, gw.offset, gw.logger = "x", set(allowed), 0, lambda m: None
    gw._pending = []
    gw._scripted = list(scripted)
    gw._api = lambda method, **p: (gw._scripted.pop(0) if gw._scripted else {"ok": True, "result": []})
    return gw


class TestFailClosedAllowList(unittest.TestCase):
    """security-6: empty allowed_users must refuse to start (open-relay guard)."""
    def test_run_refuses_empty_allow_list(self):
        gw = _gw([{"ok": True, "result": {"username": "bot"}}], allowed=set())
        with self.assertRaises(SystemExit) as cm:
            gw.run()
        self.assertIn("allowed_users is empty", str(cm.exception))

    def test_run_refuses_after_getme_ok(self):
        # getMe succeeds but allow-list empty -> still refuse (ordering: check after retry block).
        gw = _gw([{"ok": True, "result": {"username": "bot"}}], allowed=set())
        with self.assertRaises(SystemExit):
            gw.run()


class TestApprovalReQueue(unittest.TestCase):
    """telegram-1 + testgap-1: a non-allowed uid cannot influence a gate; lost updates re-queued."""
    def test_stranger_approve_ignored_owner_deny_wins(self):
        gw = _gw([
            {"ok": True, "result": [  # round 1: stranger uid=99 presses approve
                {"update_id": 1, "callback_query": {
                    "id": "cb1", "from": {"id": 99},
                    "message": {"chat": {"id": 7}}, "data": "approve"}}]},
            {"ok": True, "result": [  # round 2: owner uid=42 presses deny
                {"update_id": 2, "callback_query": {
                    "id": "cb2", "from": {"id": 42},
                    "message": {"chat": {"id": 7}}, "data": "deny"}}]},
        ])
        self.assertFalse(gw._wait_approval(7, timeout_s=60))

    def test_stranger_update_is_requeued_not_dropped(self):
        gw = _gw([
            {"ok": True, "result": [  # stranger update during the wait
                {"update_id": 1, "message": {"from": {"id": 99}, "chat": {"id": 8}, "text": "hi"}}]},
            {"ok": True, "result": [  # then owner denies
                {"update_id": 2, "callback_query": {
                    "id": "cb1", "from": {"id": 42},
                    "message": {"chat": {"id": 7}}, "data": "deny"}}]},
        ])
        self.assertFalse(gw._wait_approval(7, timeout_s=60))
        # the stranger's message was re-queued for run(), not discarded
        self.assertEqual(len(gw._pending), 1)
        self.assertEqual(gw._pending[0]["text"], "hi")

    def test_non_vote_text_in_other_chat_requeued(self):
        gw = _gw([
            {"ok": True, "result": [  # allowed user but DIFFERENT chat -> not our gate
                {"update_id": 1, "message": {"from": {"id": 42}, "chat": {"id": 99}, "text": "new task"}}]},
            {"ok": True, "result": [
                {"update_id": 2, "callback_query": {
                    "id": "cb1", "from": {"id": 42},
                    "message": {"chat": {"id": 7}}, "data": "approve"}}]},
        ])
        self.assertTrue(gw._wait_approval(7, timeout_s=60))
        self.assertEqual(gw._pending[0]["text"], "new task")


class TestWallClockTimeout(unittest.TestCase):
    """telegram-2 + testgap-10: deadline uses monotonic wall time, not a poll counter."""
    def test_timeout_zero_returns_false_immediately(self):
        gw = _gw([])  # empty -> _api fallback returns result=[]
        self.assertFalse(gw._wait_approval(7, timeout_s=0))

    def test_timeout_does_not_consume_pending_updates(self):
        # with timeout_s=0 the loop never runs, so nothing is pulled or dropped
        gw = _gw([])
        gw._wait_approval(7, timeout_s=0)
        self.assertEqual(gw.offset, 0)


class TestEmptySendGuard(unittest.TestCase):
    """telegram-3: send('') must not hit the API with empty text."""
    def test_empty_text_sends_nothing(self):
        gw = _gw([])
        calls = []
        gw._api = lambda method, **p: calls.append((method, p)) or {"ok": True}
        gw.send(7, "")
        self.assertEqual(calls, [])

    def test_nonempty_text_still_sends(self):
        gw = _gw([])
        calls = []
        gw._api = lambda method, **p: calls.append((method, p)) or {"ok": True}
        gw.send(7, "hello")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "sendMessage")


class TestPullOffsetInvariant(unittest.TestCase):
    """testgap-2 + testgap-3: offset only advances per real update; failures don't corrupt it."""
    def test_empty_result_does_not_advance_offset(self):
        gw = _gw([{"ok": True, "result": []}])
        self.assertEqual(gw._pull(timeout=0), [])
        self.assertEqual(gw.offset, 0)

    def test_api_failure_yields_empty_without_advancing(self):
        gw = _gw([])
        gw._api = lambda method, **p: {"ok": False}
        self.assertEqual(gw._pull(timeout=0), [])
        self.assertEqual(gw.offset, 0)

    def test_malformed_result_does_not_crash(self):
        # missing 'result' key entirely -> .get('result', []) -> []
        gw = _gw([])
        gw._api = lambda method, **p: {"ok": True}
        self.assertEqual(gw._pull(timeout=0), [])


class TestStaleCallbackSkip(unittest.TestCase):
    """telegram-7: a stale Approve/Deny press in run()'s poll is acked and skipped, not run as a task."""
    def test_run_skips_callback_and_acks_spinner(self):
        acked = []
        gw = _gw([
            {"ok": True, "result": {"username": "bot"}},          # getMe
            {"ok": True, "result": [                              # first poll: stale callback
                {"update_id": 1, "callback_query": {
                    "id": "cbX", "from": {"id": 42},
                    "message": {"chat": {"id": 7}}, "data": "approve"}}]},
        ])

        real_api = gw._api
        def spy(method, **p):
            if method == "answerCallbackQuery":
                acked.append(p)
                raise _Stop()      # break the infinite run() loop right after the ack
            return real_api(method, **p)
        gw._api = spy
        gw.agent_factory = lambda approver: (_ for _ in ()).throw(AssertionError("task must NOT run"))

        with self.assertRaises(_Stop):
            gw.run()
        self.assertEqual(len(acked), 1)
        self.assertEqual(acked[0]["text"], "No pending approval.")


class TestGetMeRetry(unittest.TestCase):
    """telegram-5: a transient getMe failure retries, not an instant 'bad token' exit."""
    def test_getme_recovers_on_second_attempt(self):
        slept = []
        gw = _gw([
            {"ok": False},                                        # attempt 1 fails
            {"ok": True, "result": {"username": "bot"}},          # attempt 2 ok
            {"ok": True, "result": []},                           # first _pull
        ])
        import agent.telegram as tg
        orig_sleep = tg.time.sleep
        tg.time.sleep = lambda s: slept.append(s)
        # stop the loop after getMe + allow-list pass by raising from _pull
        real_pull = gw._pull
        gw._pull = lambda *a, **k: (_ for _ in ()).throw(_Stop())
        try:
            with self.assertRaises(_Stop):
                gw.run()
        finally:
            tg.time.sleep = orig_sleep
        self.assertIn(5, slept)   # backed off 5s between attempts

    def test_getme_gives_up_after_three_attempts(self):
        slept = []
        gw = _gw([{"ok": False}, {"ok": False}, {"ok": False}])
        import agent.telegram as tg
        orig_sleep = tg.time.sleep
        tg.time.sleep = lambda s: slept.append(s)
        try:
            with self.assertRaises(SystemExit) as cm:
                gw.run()
        finally:
            tg.time.sleep = orig_sleep
        self.assertIn("after 3 attempts", str(cm.exception))


class TestApiRateLimit(unittest.TestCase):
    """telegram-6: a 429 sleeps for Retry-After and returns {ok:False}; no crash, no new dep."""
    def _gw_real_api(self):
        gw = TelegramGateway.__new__(TelegramGateway)
        gw.token, gw.allowed, gw.offset, gw.logger = "x", {42}, 0, lambda m: None
        gw._pending = []
        return gw

    def test_429_honours_retry_after(self):
        gw = self._gw_real_api()
        slept = []
        import agent.telegram as tg
        orig_sleep, orig_urlopen = tg.time.sleep, tg.urllib.request.urlopen
        tg.time.sleep = lambda s: slept.append(s)

        def boom(req, timeout=40):
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "3"}, None)
        tg.urllib.request.urlopen = boom
        try:
            out = gw._api("getMe")
        finally:
            tg.time.sleep, tg.urllib.request.urlopen = orig_sleep, orig_urlopen
        self.assertEqual(out, {"ok": False})
        self.assertEqual(slept, [3])

    def test_429_bad_retry_after_defaults_to_5(self):
        gw = self._gw_real_api()
        slept = []
        import agent.telegram as tg
        orig_sleep, orig_urlopen = tg.time.sleep, tg.urllib.request.urlopen
        tg.time.sleep = lambda s: slept.append(s)

        def boom(req, timeout=40):
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "soon"}, None)
        tg.urllib.request.urlopen = boom
        try:
            out = gw._api("getMe")
        finally:
            tg.time.sleep, tg.urllib.request.urlopen = orig_sleep, orig_urlopen
        self.assertEqual(out, {"ok": False})
        self.assertEqual(slept, [5])

    def test_other_http_error_returns_false_no_sleep(self):
        gw = self._gw_real_api()
        slept = []
        import agent.telegram as tg
        orig_sleep, orig_urlopen = tg.time.sleep, tg.urllib.request.urlopen
        tg.time.sleep = lambda s: slept.append(s)

        def boom(req, timeout=40):
            raise urllib.error.HTTPError("u", 500, "Server Error", {}, None)
        tg.urllib.request.urlopen = boom
        try:
            out = gw._api("getMe")
        finally:
            tg.time.sleep, tg.urllib.request.urlopen = orig_sleep, orig_urlopen
        self.assertEqual(out, {"ok": False})
        self.assertEqual(slept, [])

    def test_generic_exception_still_swallowed(self):
        gw = self._gw_real_api()
        import agent.telegram as tg
        orig_urlopen = tg.urllib.request.urlopen

        def boom(req, timeout=40):
            raise ConnectionRefusedError("nope")
        tg.urllib.request.urlopen = boom
        try:
            self.assertEqual(gw._api("getMe"), {"ok": False})
        finally:
            tg.urllib.request.urlopen = orig_urlopen


class _Stop(Exception):
    """Sentinel to break out of run()'s infinite loop inside a test."""


if __name__ == "__main__":
    unittest.main()
