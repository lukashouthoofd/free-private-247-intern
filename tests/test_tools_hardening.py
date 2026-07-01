"""Hardening tests for agent/tools.py — SSRF guard, redirect re-validation,
secret-path denylist, env scrub, and gate pinning. Stdlib-only (unittest), no
real network: getaddrinfo is monkeypatched so resolution is deterministic."""
import os
import shutil
import tempfile
import unittest
import urllib.error
from pathlib import Path

from agent import tools as T
from agent.tools import DEFAULT_TOOLS


def _fake_getaddrinfo(ip):
    """Return a getaddrinfo replacement that always resolves to `ip`."""
    return lambda host, port, *a, **k: [(2, 1, 6, "", (ip, port or 0))]


class TestSafeUrl(unittest.TestCase):
    def test_loopback_refused(self):
        self.assertFalse(T._is_safe_url("http://127.0.0.1/"))
        self.assertFalse(T._is_safe_url("http://localhost/"))

    def test_metadata_ip_refused(self):
        self.assertFalse(T._is_safe_url("http://169.254.169.254/latest/meta-data/"))

    def test_private_ranges_refused(self):
        for u in ("http://10.0.0.5/", "http://192.168.1.1/", "http://172.16.3.4/"):
            self.assertFalse(T._is_safe_url(u), u)

    def test_userinfo_bypass_refused(self):
        # public name in userinfo, internal host after @ — must refuse on '@' alone
        self.assertFalse(T._is_safe_url("http://trusted.example.com@169.254.169.254/"))

    def test_public_ip_allowed(self):
        orig = T.socket.getaddrinfo
        T.socket.getaddrinfo = _fake_getaddrinfo("93.184.216.34")  # example.com-ish public
        try:
            self.assertTrue(T._is_safe_url("https://example.com/"))
        finally:
            T.socket.getaddrinfo = orig

    def test_dns_failure_refused(self):
        orig = T.socket.getaddrinfo

        def boom(*a, **k):
            raise OSError("dns down")

        T.socket.getaddrinfo = boom
        try:
            self.assertFalse(T._is_safe_url("http://whatever.invalid/"))
        finally:
            T.socket.getaddrinfo = orig

    def test_garbage_url_refused(self):
        self.assertFalse(T._is_safe_url("not a url"))


class TestWebFetch(unittest.TestCase):
    def test_bad_scheme(self):
        self.assertIn("must start with", T._web_fetch({"url": "ftp://x/"}))

    def test_internal_url_refused_before_request(self):
        out = T._web_fetch({"url": "http://169.254.169.254/latest/meta-data/"})
        self.assertIn("refusing to fetch internal", out)

    def test_private_url_refused(self):
        self.assertIn("refusing to fetch internal", T._web_fetch({"url": "http://10.1.2.3/"}))


class TestSafeRedirect(unittest.TestCase):
    def _handler(self):
        return T._SafeRedirect()

    def test_redirect_to_internal_blocked(self):
        h = self._handler()
        with self.assertRaises(urllib.error.URLError):
            h.redirect_request(object(), None, 302, "Found", {},
                               "http://169.254.169.254/")

    def test_redirect_blocks_userinfo(self):
        h = self._handler()
        with self.assertRaises(urllib.error.URLError):
            h.redirect_request(object(), None, 302, "Found", {},
                               "http://ok@127.0.0.1/")


class TestReadFileDenylist(unittest.TestCase):
    def test_refuses_dotenv(self):
        d = Path(tempfile.mkdtemp())
        (d / ".env").write_text("GROQ_API_KEY=secret")
        out = T._read_file({"path": str(d / ".env")})
        self.assertIn("refusing to read a secrets file", out)

    def test_refuses_key_suffix(self):
        d = Path(tempfile.mkdtemp())
        (d / "server.pem").write_text("-----BEGIN-----")
        self.assertIn("refusing to read a secrets file",
                      T._read_file({"path": str(d / "server.pem")}))

    def test_refuses_substring_token(self):
        d = Path(tempfile.mkdtemp())
        (d / "my_token.txt").write_text("abc")
        self.assertIn("refusing to read a secrets file",
                      T._read_file({"path": str(d / "my_token.txt")}))

    def test_refuses_secrets_dir(self):
        d = Path(tempfile.mkdtemp())
        sub = d / "secrets"
        sub.mkdir()
        (sub / "notes.txt").write_text("hi")
        self.assertIn("refusing to read a secrets file",
                      T._read_file({"path": str(sub / "notes.txt")}))

    def test_allows_ordinary_file(self):
        # read_file is jailed to the working dir, so the file must live under it.
        d = Path(tempfile.mkdtemp(dir=T._workdir_root()))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "readme.txt").write_text("hello world")
        self.assertEqual(T._read_file({"path": str(d / "readme.txt")}), "hello world")

    def test_missing_file_does_not_crash(self):
        d = Path(tempfile.mkdtemp(dir=T._workdir_root()))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        out = T._read_file({"path": str(d / "nope.txt")})
        self.assertTrue(out.startswith("ERROR:"))

    def test_refuses_outside_workdir(self):
        # A non-secret file outside the working dir is still refused (jail, not just denylist).
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        (d / "readme.txt").write_text("hello world")
        self.assertIn("jailed to the working directory",
                      T._read_file({"path": str(d / "readme.txt")}))


class TestScrubEnv(unittest.TestCase):
    def test_strips_secrets_keeps_path(self):
        saved = {k: os.environ.get(k) for k in
                 ("GROQ_API_KEY", "TELEGRAM_TOKEN", "MY_SECRET", "DB_PASSWORD", "PATH")}
        os.environ["GROQ_API_KEY"] = "x"
        os.environ["TELEGRAM_TOKEN"] = "x"
        os.environ["MY_SECRET"] = "x"
        os.environ["DB_PASSWORD"] = "x"
        try:
            env = T._scrub_env()
            self.assertNotIn("GROQ_API_KEY", env)
            self.assertNotIn("TELEGRAM_TOKEN", env)
            self.assertNotIn("MY_SECRET", env)
            self.assertNotIn("DB_PASSWORD", env)
            self.assertIn("PATH", env)  # benign vars survive
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_run_shell_child_cannot_see_secret(self):
        os.environ["LEAKME_API_KEY"] = "supersecret"
        try:
            out = T._run_shell({"command": 'python -c "import os;print(os.environ.get(\'LEAKME_API_KEY\',\'GONE\'))"'})
            self.assertIn("GONE", out)
            self.assertNotIn("supersecret", out)
        finally:
            os.environ.pop("LEAKME_API_KEY", None)


class TestGatesUnchanged(unittest.TestCase):
    def test_read_and_fetch_stay_autonomous(self):
        g = {t.name: t.gate for t in DEFAULT_TOOLS}
        self.assertEqual(g["read_file"], "autonomous")
        self.assertEqual(g["web_fetch"], "autonomous")

    def test_write_stays_ask_first(self):
        g = {t.name: t.gate for t in DEFAULT_TOOLS}
        self.assertEqual(g["write_file"], "ask_first")

    def test_run_shell_is_opt_in(self):
        # run_shell is no longer a default tool — it must be explicitly enabled in config,
        # and it stays ask_first when it is. (See build_default_tools.)
        from agent.tools import build_default_tools
        self.assertNotIn("run_shell", {t.name for t in DEFAULT_TOOLS})
        on = build_default_tools({"tools": {"run_shell": {"enabled": True}}})
        self.assertEqual({t.name: t.gate for t in on}.get("run_shell"), "ask_first")


if __name__ == "__main__":
    unittest.main()
