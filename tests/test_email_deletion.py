"""
Tests for the email deletion functionality in the EmailClient.
"""

import sys
from pathlib import Path
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
    
sys.path.append(str(Path(__file__).parent.parent / "src"))

from scholar_scout.config import EmailConfig
from scholar_scout.email_client import EmailClient


class TestEmailDeletion(unittest.TestCase):
    """Test suite for the email deletion functionality."""

    def setUp(self):
        """Set up the test environment."""
        self.config = EmailConfig(
            username="test@example.com",
            password="password",
            folder="INBOX",
        )

    @patch("scholar_scout.email_client.imaplib.IMAP4_SSL")
    @patch("builtins.open")
    @patch("scholar_scout.email_client.yaml.safe_load")
    def test_delete_old_emails(self, mock_safe_load, mock_open, mock_imaplib):
        """Test that old emails are correctly deleted."""
        # Mock the IMAP server and its methods
        mock_imap_server = MagicMock()
        mock_imaplib.return_value = mock_imap_server

        # Mock the search criteria
        mock_safe_load.return_value = {
            "email_empty": {
                "time_window": "4W",
            }
        }

        # Configure the mock to return some email IDs
        mock_imap_server.search.return_value = ("OK", [b"1 2 3"])

        # Create an instance of the EmailClient and run the deletion method
        with EmailClient(self.config) as email_client:
            email_client.delete_old_emails()

        # Verify that the correct IMAP commands were called
        mock_imap_server.select.assert_called_with("INBOX", readonly=False)
        self.assertTrue(mock_imap_server.search.called)
        self.assertTrue(mock_imap_server.store.called)
        self.assertTrue(mock_imap_server.expunge.called)

        # Check the search criteria
        search_criteria = mock_imap_server.search.call_args[0][1]
        four_weeks_ago = (datetime.now() - timedelta(weeks=4)).strftime("%d-%b-%Y")
        self.assertIn(f'BEFORE "{four_weeks_ago}"', search_criteria)


if __name__ == "__main__":
    unittest.main()
