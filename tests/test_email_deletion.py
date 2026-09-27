"""Verify cleanup targets with a simulated mailbox only."""

from datetime import datetime
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, call, mock_open, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scholar_scout.config import EmailConfig
from scholar_scout.email_client import EmailClient


class TestEmailDeletion(unittest.TestCase):
    def test_cleanup_targets_only_the_selected_old_message_ids(self):
        client = EmailClient(EmailConfig(username="test", password="test", folder="Scholar Alerts"))
        client.mail = Mock()
        client.mail.select.return_value = ("OK", [])
        client.mail.search.return_value = ("OK", [b"2 5"])
        client.mail.store.return_value = ("OK", [])
        client.mail.expunge.return_value = ("OK", [])
        with (
            patch("builtins.open", mock_open(read_data='email_empty:\n  time_window: "4W"\n')),
            patch("scholar_scout.email_client.datetime") as clock,
        ):
            clock.now.return_value = datetime(2026, 9, 27, 15, 30)
            client.delete_old_emails()
        self.assertEqual(
            client.mail.method_calls,
            [
                call.select('"Scholar Alerts"', readonly=False),
                call.search(None, '(BEFORE "30-Aug-2026")'),
                call.store(b"2", "+FLAGS", "\\Deleted"),
                call.store(b"5", "+FLAGS", "\\Deleted"),
                call.expunge(),
            ],
        )


if __name__ == "__main__":
    unittest.main()
