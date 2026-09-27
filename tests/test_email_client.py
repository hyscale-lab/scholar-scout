"""Offline mailbox search and failure handling."""

from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scholar_scout.config import EmailConfig
from scholar_scout.email_client import EmailClient

CRITERIA = """email_filter:
  from: "scholaralerts-noreply@google.com"
  subject: ["new articles", "新文章"]
  time_window: "7D"
"""


class TestEmailClient(unittest.TestCase):
    def setUp(self):
        self.client = EmailClient(EmailConfig(username="test", password="test", folder="Scholar"))
        self.mail = Mock()
        self.client.mail = self.mail
        self.mail.select.return_value = ("OK", [])
        self.mail.search.return_value = ("OK", [b"1"])
        self.mail.fetch.return_value = self.fetch_response("new articles")
        file_patch = patch("builtins.open", mock_open(read_data=CRITERIA))
        file_patch.start()
        self.addCleanup(file_patch.stop)
        clock = patch("scholar_scout.email_client.datetime")
        clock.start().now.return_value = datetime(2026, 9, 27, 15, 30)
        self.addCleanup(clock.stop)
        self.query = 'FROM "scholaralerts-noreply@google.com" SINCE "20-Sep-2026"'

    @staticmethod
    def fetch_response(subject):
        message = EmailMessage()
        if subject is not None:
            message["Subject"] = subject
        message.set_content("Sample Scholar alert")
        return "OK", [(b"1 (RFC822)", message.as_bytes()), b")"]

    def test_search_window_and_empty_result(self):
        self.mail.search.return_value = ("OK", [b""])
        self.assertEqual(self.client.fetch_scholar_alerts(), [])
        self.mail.search.assert_called_once_with(None, self.query)
        self.mail.fetch.assert_not_called()

    def test_subjects_are_decoded_and_filtered_locally(self):
        for subject, accepted in (
            ("Researcher - new articles", True),
            ("Researcher - 新文章", True),
            ("新文章 - New articles", True),
            ("Unrelated newsletter", False),
            ("", False),
            (None, False),
        ):
            with self.subTest(subject=subject):
                self.mail.search.reset_mock()
                self.mail.fetch.return_value = self.fetch_response(subject)
                self.assertEqual(len(self.client.fetch_scholar_alerts()), int(accepted))
                self.mail.search.assert_called_once_with(None, self.query)

    def test_operation_failure_never_returns_empty_or_partial_success(self):
        for operation in ("select", "search", "fetch"):
            with self.subTest(operation=operation):
                self.mail.reset_mock(return_value=False, side_effect=True)
                self.mail.select.return_value = ("OK", [])
                self.mail.search.return_value = ("OK", [b"1 2"])
                self.mail.fetch.return_value = self.fetch_response("new articles")
                if operation == "fetch":
                    self.mail.fetch.side_effect = [self.fetch_response("new articles"), ("NO", [])]
                else:
                    getattr(self.mail, operation).return_value = ("NO", [])
                with self.assertRaises(RuntimeError):
                    self.client.fetch_scholar_alerts()
                if operation == "select":
                    self.mail.search.assert_not_called()
                elif operation == "search":
                    self.mail.search.assert_called_once()
                    self.mail.fetch.assert_not_called()
                else:
                    self.assertEqual(self.mail.fetch.call_count, 2)

    def test_malformed_responses_fail_explicitly(self):
        for operation, data in (
            ("search", [None]),
            ("search", [b"invalid"]),
            ("fetch", []),
            ("fetch", [b")"]),
            ("fetch", [(b"1", b"")]),
        ):
            with self.subTest(operation=operation, data=data):
                self.mail.search.return_value = ("OK", [b"1"])
                self.mail.fetch.return_value = self.fetch_response("new articles")
                getattr(self.mail, operation).return_value = ("OK", data)
                with self.assertRaises(RuntimeError):
                    self.client.fetch_scholar_alerts()


if __name__ == "__main__":
    unittest.main()
