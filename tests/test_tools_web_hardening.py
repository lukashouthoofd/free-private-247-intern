"""Hardening tests for agent/tools_web.py (issue #1).
Stdlib-only (unittest), no real network. Covers the five fixes:
  security-3  — SSRF: a name resolving to an internal IP is refused by _fetch
  verifyweb-2 — parked-page banner in <body> (not just <title>) is rejected
  verifyweb-3 — multi-word towns (De Pinte, Sint-Niklaas) match again
  verifyweb-4 — *.one.com (website-builder host) is treated as a directory, not own-site
  verifyweb-6 — short brand tokens (Bar, Pub, Zoo) don't spawn bare candidates
plus: the autonomous gate on verify_website is unchanged, and a malformed
response does not crash _owns / _fetch."""
import unittest
from unittest import mock

from agent import tools_web
from agent.tools_web import (
    _candidates,
    _fetch,
    _owns,
    _verify_website,
    _DIRECTORY,
    _DIRECTORY_ONECOM,
    WEB_TOOLS,
)


class TestSSRFGuard(unittest.TestCase):
    """security-3: _fetch must refuse hosts that resolve to private/loopback/link-local IPs."""

    def _patch_resolve(self, addr):
        # getaddrinfo 5-tuple: (family, type, proto, canonname, sockaddr); sockaddr[0] = ip
        return mock.patch.object(
            tools_web.socket, "getaddrinfo",
            return_value=[(2, 0, 0, "", (addr, 0))],
        )

    def test_loopback_is_blocked_before_any_request(self):
        with self._patch_resolve("127.0.0.1"):
            # urlopen must never be reached; if it is, this would raise instead of returning None
            with mock.patch.object(tools_web.urllib.request, "urlopen",
                                   side_effect=AssertionError("urlopen must not run for blocked host")):
                self.assertEqual(_fetch("https://evil.example"), (None, None))

    def test_private_10_is_blocked(self):
        with self._patch_resolve("10.0.0.5"):
            self.assertEqual(_fetch("http://internal.example"), (None, None))

    def test_private_192_168_is_blocked(self):
        with self._patch_resolve("192.168.0.244"):
            self.assertEqual(_fetch("https://agent-hub.lan"), (None, None))

    def test_link_local_169_254_is_blocked(self):
        with self._patch_resolve("169.254.169.254"):  # cloud metadata endpoint
            self.assertEqual(_fetch("https://metadata.example"), (None, None))

    def test_ipv6_loopback_is_blocked(self):
        with mock.patch.object(tools_web.socket, "getaddrinfo",
                               return_value=[(23, 0, 0, "", ("::1", 0, 0, 0))]):
            self.assertEqual(_fetch("https://v6.example"), (None, None))

    def test_public_ip_is_allowed_through_to_urlopen(self):
        with self._patch_resolve("93.184.216.34"):  # public
            cm = mock.MagicMock()
            cm.geturl.return_value = "https://ok.example"
            cm.read.return_value = b"<title>ok</title>"
            cm.__enter__.return_value = cm
            cm.__exit__.return_value = False
            # _fetch uses the module-local SSRF opener (not urllib.request.urlopen) so redirects
            # are re-validated; mock that opener's .open here.
            with mock.patch.object(tools_web._SSRF_OPENER, "open", return_value=cm):
                final, html = _fetch("https://ok.example")
                self.assertEqual(final, "https://ok.example")
                self.assertIn("ok", html)

    def test_resolution_failure_does_not_crash(self):
        with mock.patch.object(tools_web.socket, "getaddrinfo",
                               side_effect=OSError("nxdomain")):
            self.assertEqual(_fetch("https://nope.example"), (None, None))

    def test_blocked_candidate_skipped_in_verify(self):
        # End-to-end: every guessed domain resolves internal -> UNCERTAIN, never HAS_SITE.
        with self._patch_resolve("127.0.0.1"):
            out = _verify_website({"name": "Bakkerij Dumalin", "town": "Deinze"})
            self.assertTrue(out.startswith("UNCERTAIN"), out)


class TestRedirectSSRF(unittest.TestCase):
    """A public domain must not be able to 302-redirect into an internal host.
    _fetch's initial-host check alone can't stop that; _SafeRedirect re-validates each hop."""

    def _resolve(self, addr):
        return mock.patch.object(tools_web.socket, "getaddrinfo",
                                 return_value=[(2, 0, 0, "", (addr, 0))])

    def test_host_is_internal_true_for_private_and_metadata(self):
        for addr in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254"):
            with self._resolve(addr):
                self.assertTrue(tools_web._host_is_internal("whatever.example"), addr)

    def test_host_is_internal_false_for_public(self):
        with self._resolve("93.184.216.34"):
            self.assertFalse(tools_web._host_is_internal("example.com"))

    def test_host_is_internal_fail_closed_on_resolve_error(self):
        with mock.patch.object(tools_web.socket, "getaddrinfo", side_effect=OSError("nxdomain")):
            self.assertTrue(tools_web._host_is_internal("nope.example"))   # unresolved -> treat as internal

    def test_safe_redirect_blocks_internal_target(self):
        with self._resolve("169.254.169.254"):
            handler = tools_web._SafeRedirect()
            req = tools_web.urllib.request.Request("https://public.example")
            with self.assertRaises(tools_web.urllib.error.URLError):
                handler.redirect_request(req, None, 302, "Found", {},
                                         "http://metadata.internal/latest/meta-data/")

    def test_safe_redirect_allows_public_target(self):
        with self._resolve("93.184.216.34"):
            handler = tools_web._SafeRedirect()
            req = tools_web.urllib.request.Request("https://public.example")
            new = handler.redirect_request(req, None, 302, "Found", {}, "https://other-public.example/x")
            self.assertIsNotNone(new)   # a public->public redirect is permitted


class TestParkedBody(unittest.TestCase):
    """verifyweb-2: parked banners outside <title> must still be rejected."""

    def test_parked_banner_in_div_is_rejected(self):
        html = ("<title>Dumalin</title>"
                "<div class='x'>This domain is for sale</div>"
                "<p>dumalin deinze</p>")
        self.assertFalse(_owns(html, "Bakkerij Dumalin", "Deinze", False))

    def test_te_koop_in_body_is_rejected(self):
        html = "<title>welkom</title><h2>te koop</h2><body>dumalin deinze dumalin</body>"
        self.assertFalse(_owns(html, "Bakkerij Dumalin", "Deinze", False))

    def test_real_page_without_banner_still_accepted(self):
        html = "<title>Bakkerij Dumalin Deinze</title><body>dumalin deinze</body>"
        self.assertTrue(_owns(html, "Bakkerij Dumalin", "Deinze", False))

    def test_parking_word_far_below_cap_does_not_falsely_reject(self):
        # 'domain for sale' only after >2000 chars of real content -> not treated as parked.
        filler = ("dumalin deinze " * 200)  # well over 2000 chars
        html = "<title>Bakkerij Dumalin Deinze</title><body>" + filler + " domain for sale</body>"
        self.assertTrue(_owns(html, "Bakkerij Dumalin", "Deinze", False))


class TestMultiWordTown(unittest.TestCase):
    """verifyweb-3: spaces in town names must no longer break the match."""

    def test_de_pinte_matches(self):
        html = "<title>Slagerij Steven De Pinte</title><body>steven de pinte</body>"
        self.assertTrue(_owns(html, "Slagerij Steven", "De Pinte", False))

    def test_sint_niklaas_matches(self):
        html = "<title>Frituur Max</title><body>max sint niklaas max</body>"
        self.assertTrue(_owns(html, "Frituur Max", "Sint-Niklaas", False))

    def test_wrong_town_still_fails_strict(self):
        # strict .com with name but town absent -> not owned.
        html = "<title>Steven</title><body>steven</body>"
        self.assertFalse(_owns(html, "Slagerij Steven", "De Pinte", True))

    def test_single_word_town_unaffected(self):
        html = "<title>Bakkerij Dumalin</title><body>dumalin deinze</body>"
        self.assertTrue(_owns(html, "Bakkerij Dumalin", "Deinze", False))


class TestOneComSuffix(unittest.TestCase):
    """verifyweb-4: *.one.com builder hosts are directory hosts, not owned domains."""

    def test_regex_matches_real_hostname(self):
        self.assertTrue(_DIRECTORY_ONECOM.search("mysite.one.com"))
        self.assertTrue(_DIRECTORY_ONECOM.search("one.com"))

    def test_regex_does_not_match_unrelated(self):
        self.assertIsNone(_DIRECTORY_ONECOM.search("noone.be"))
        self.assertIsNone(_DIRECTORY_ONECOM.search("done.com"))
        self.assertIsNone(_DIRECTORY_ONECOM.search("one.com.evil.be"))

    def test_one_com_final_host_rejected_in_verify(self):
        # A guessed domain that redirects to mysite.one.com must NOT count as HAS_SITE.
        def fake_fetch(url):
            return "https://mysite.one.com/", "<title>Bakkerij Dumalin Deinze</title><body>dumalin deinze</body>"
        with mock.patch.object(tools_web, "_fetch", side_effect=fake_fetch):
            out = _verify_website({"name": "Bakkerij Dumalin", "town": "Deinze"})
            self.assertTrue(out.startswith("UNCERTAIN"), out)


class TestShortBrandTokens(unittest.TestCase):
    """verifyweb-6: a standalone candidate needs a >=4-char base."""

    def test_short_token_does_not_spawn_bare_candidate(self):
        # 'Bar Zo' -> tokens 'bar','zo' (both <4) -> no 'bar.be' candidate; only the concat form.
        cands = _candidates("Bar Zo", "Deinze")
        self.assertNotIn("bar.be", cands)
        self.assertNotIn("bar.com", cands)
        self.assertIn("barzo.be", cands)  # concatenated full form still tried

    def test_long_brand_still_produces_candidate(self):
        cands = _candidates("Bakkerij Dumalin", "Deinze")
        self.assertIn("dumalin.be", cands)

    def test_all_short_tokens_but_long_full(self):
        # every token <4 but the concatenation >=4 -> full candidate present, no 3-char bare one.
        cands = _candidates("Pub Zoo", "Gent")
        self.assertNotIn("pub.be", cands)
        self.assertNotIn("zoo.be", cands)
        self.assertIn("pubzoo.be", cands)

    def test_short_token_no_standalone_brand_candidate(self):
        # 'Bar Frituur' -> only token is 'bar' (<4; 'frituur' is a stopword);
        # brand is None, so no extra brand candidate beyond the concatenated full form.
        cands = _candidates("Bar Frituur", "Gent")
        self.assertNotIn("bar.be", cands)
        self.assertIn("barfrituur.be", cands)


class TestGateUnchanged(unittest.TestCase):
    """Gate must stay enforced: verify_website remains autonomous and registered."""

    def test_tool_registered_and_autonomous(self):
        self.assertEqual(WEB_TOOLS[0].name, "verify_website")
        self.assertEqual(WEB_TOOLS[0].gate, "autonomous")

    def test_no_extra_tools_added(self):
        self.assertEqual(len(WEB_TOOLS), 1)


class TestRobustness(unittest.TestCase):
    """Malformed / empty input must not crash."""

    def test_owns_empty_html(self):
        self.assertFalse(_owns("", "Bakkerij Dumalin", "Deinze", False))

    def test_owns_no_title_tag(self):
        self.assertTrue(_owns("dumalin deinze dumalin", "Bakkerij Dumalin", "Deinze", False))

    def test_verify_missing_name(self):
        self.assertTrue(_verify_website({"town": "Deinze"}).startswith("ERROR"))

    def test_candidates_empty_name(self):
        self.assertEqual(_candidates("", "Deinze"), [])


if __name__ == "__main__":
    unittest.main()
