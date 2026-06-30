"""Email tool tests — run with:  python -m unittest discover -s tests
Stdlib-only (unittest). NO real network, NO real creds: imaplib.IMAP4_SSL and
smtplib.SMTP_SSL are monkeypatched with fakes. Covers: list parses a fake fetch
into subjects, send builds a correct RFC-822 message and calls sendmail, and the
friendly missing-creds error (without ever touching the network)."""
import email
import imaplib
import os
import smtplib
import unittest

from agent import tools_email
from agent.tools_email import EMAIL_TOOLS, _email_list_recent, _email_send, _email_read

_CREDS = {
    "EMAIL_IMAP_HOST": "imap.example.com",
    "EMAIL_SMTP_HOST": "smtp.example.com",
    "EMAIL_ADDRESS": "agent@example.com",
    "EMAIL_PASSWORD": "secret-not-real",
}


def _set_creds(monkey_env):
    for k, v in _CREDS.items():
        monkey_env[k] = v


class _FakeIMAP:
    """Minimal IMAP4_SSL stand-in. Holds one fake message keyed by id b'1'."""
    def __init__(self, host, *a, **k):
        self.host = host
        self.logged_in = False

    def login(self, user, pw):
        self.logged_in = True
        return ("OK", [b"ok"])

    def select(self, mailbox):
        return ("OK", [b"1"])

    def search(self, charset, *criteria):
        return ("OK", [b"1"])

    def fetch(self, mid, spec):
        if "HEADER" in spec:
            hdr = b"Subject: Invoice March\r\nFrom: Klant <klant@firma.be>\r\n\r\n"
            return ("OK", [(b"1 (BODY[HEADER])", hdr)])
        raw = (b"From: Klant <klant@firma.be>\r\nTo: agent@example.com\r\n"
               b"Subject: Invoice March\r\n\r\nPlease find the invoice attached.\r\n")
        return ("OK", [(b"1 (RFC822)", raw)])

    def logout(self):
        return ("BYE", [b"bye"])


class _FakeSMTP:
    """Captures the sendmail call so the test can assert on the RFC-822 message."""
    sent = None

    def __init__(self, host, port, *a, **k):
        self.host, self.port = host, port

    def login(self, user, pw):
        _FakeSMTP.login_user = user

    def sendmail(self, from_addr, to_addrs, msg_str):
        _FakeSMTP.sent = (from_addr, to_addrs, msg_str)

    def quit(self):
        pass


class TestEmailListAndRead(unittest.TestCase):
    def setUp(self):
        for k, v in _CREDS.items():
            os.environ[k] = v
        self._orig = imaplib.IMAP4_SSL
        imaplib.IMAP4_SSL = _FakeIMAP

    def tearDown(self):
        imaplib.IMAP4_SSL = self._orig
        for k in _CREDS:
            os.environ.pop(k, None)

    def test_list_recent_parses_subject_and_sender(self):
        out = _email_list_recent({"count": 5})
        self.assertIn("Invoice March", out)
        self.assertIn("klant@firma.be", out)
        self.assertIn("[1]", out)  # id surfaced for email_read

    def test_read_returns_plain_body(self):
        out = _email_read({"id": "1"})
        self.assertIn("Please find the invoice attached.", out)
        self.assertIn("Subject: Invoice March", out)


class TestEmailSend(unittest.TestCase):
    def setUp(self):
        for k, v in _CREDS.items():
            os.environ[k] = v
        self._orig = smtplib.SMTP_SSL
        smtplib.SMTP_SSL = _FakeSMTP
        _FakeSMTP.sent = None

    def tearDown(self):
        smtplib.SMTP_SSL = self._orig
        for k in _CREDS:
            os.environ.pop(k, None)

    def test_send_builds_rfc822_and_calls_sendmail(self):
        out = _email_send({"to": "bob@firma.be", "subject": "Hello", "body": "Hi Bob"})
        self.assertIn("SENT", out)
        self.assertIsNotNone(_FakeSMTP.sent)
        from_addr, to_addrs, msg_str = _FakeSMTP.sent
        self.assertEqual(from_addr, _CREDS["EMAIL_ADDRESS"])
        self.assertEqual(to_addrs, ["bob@firma.be"])
        # parse the wire message back and check the headers + body
        parsed = email.message_from_string(msg_str)
        self.assertEqual(parsed["To"], "bob@firma.be")
        self.assertEqual(parsed["Subject"], "Hello")
        self.assertEqual(parsed["From"], _CREDS["EMAIL_ADDRESS"])
        self.assertIn("Hi Bob", parsed.get_payload())

    def test_send_rejects_bad_recipient(self):
        out = _email_send({"to": "not-an-email", "subject": "x", "body": "y"})
        self.assertIn("ERROR", out)
        self.assertIsNone(_FakeSMTP.sent)  # never reached the network


class TestMissingCreds(unittest.TestCase):
    def setUp(self):
        for k in _CREDS:
            os.environ.pop(k, None)

    def test_all_tools_return_friendly_error(self):
        for fn in (_email_list_recent, _email_send, _email_read):
            out = fn({"to": "x@y.be", "subject": "s", "body": "b", "id": "1"})
            self.assertIn("set EMAIL", out)
            # never leak any value
            self.assertNotIn("secret-not-real", out)


class TestEmailToolRegistration(unittest.TestCase):
    def test_names_and_gates(self):
        g = {t.name: t.gate for t in EMAIL_TOOLS}
        self.assertEqual(g["email_list_recent"], "autonomous")
        self.assertEqual(g["email_read"], "autonomous")
        self.assertEqual(g["email_send"], "ask_first")  # the human gate on sending

    def test_schema_shape(self):
        s = EMAIL_TOOLS[0].schema()
        self.assertEqual(s["type"], "function")
        self.assertIn("name", s["function"])


if __name__ == "__main__":
    unittest.main()
