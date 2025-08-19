"""
Email client for fetching Google Scholar alerts from a Gmail account.

This module provides a client for connecting to a Gmail account via IMAP,
searching for specific emails, and fetching their content. It is designed to
be used by the Scholar Scout application to retrieve emails for classification.
"""

import email
import imaplib
import logging
from datetime import datetime, timedelta
from email.header import decode_header
from email.message import Message
from typing import List, Set

import yaml

from .config import EmailConfig

logger = logging.getLogger(__name__)


class EmailClient:
    """A client for fetching emails from a Gmail account."""

    def __init__(self, config: EmailConfig):
        """
        Initialize the email client with the given configuration.

        Args:
            config: The email configuration.
        """
        self.config = config
        self.mail = None

    def __enter__(self):
        """Connect to the Gmail server and log in."""
        try:
            logger.info(f"Connecting to Gmail with username: {self.config.username}")
            self.mail = imaplib.IMAP4_SSL("imap.gmail.com")
            self.mail.login(self.config.username, self.config.password)
            return self
        except Exception as e:
            logger.error(f"Error connecting to Gmail: {e}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Log out from the Gmail server."""
        if self.mail:
            self.mail.logout()

    def _build_email_search_query(self) -> tuple[str, str, list[str]]:
        """Build the IMAP search query for finding Google Scholar alerts."""
        with open("config/search_criteria.yml", "r") as f:
            criteria = yaml.safe_load(f)["email_filter"]

        from_query = f'FROM "{criteria["from"]}"'
        since_query = ""
        if criteria["time_window"]:
            amount = int(criteria["time_window"][:-1])
            unit = criteria["time_window"][-1]
            if unit == "D":
                delta = timedelta(days=amount)
            elif unit == "W":
                delta = timedelta(weeks=amount)
            elif unit == "M":
                delta = timedelta(days=amount * 30)
            else:
                delta = timedelta(days=amount)
            since_date = datetime.now() - delta
            date_str = since_date.strftime("%d-%b-%Y")
            since_query = f'SINCE "{date_str}"'

        subjects = criteria.get("subject", [])
        return from_query, since_query, subjects

    def _should_process_email(self, email_message: Message) -> bool:
        """Check if an email should be processed based on its subject."""
        subject = email_message.get("subject", "")
        if not subject:
            return False

        try:
            decoded_parts = decode_header(subject)
            subject_decoded = ""
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    subject_decoded += part.decode(encoding or "utf-8", errors="replace")
                else:
                    subject_decoded += part
        except Exception:
            subject_decoded = subject

        with open("config/search_criteria.yml", "r") as f:
            criteria = yaml.safe_load(f)["email_filter"]
        target_subjects = criteria.get("subject", [])

        return any(target_subject in subject_decoded for target_subject in target_subjects)

    def fetch_scholar_alerts(self) -> List[Message]:
        """
        Fetch Google Scholar alert emails from the configured folder.

        Returns:
            A list of email messages.
        """
        assert self.mail is not None
        folder_name = self.config.folder
        if " " in folder_name and not folder_name.startswith('"'):
            folder_name = f'"{folder_name}"'
        logger.info(f"Attempting to access folder: {folder_name}")

        status, _ = self.mail.select(folder_name)
        if status != "OK":
            logger.error(f"Failed to select folder {folder_name}")
            return []

        from_query, since_query, subjects = self._build_email_search_query()
        all_message_numbers: Set[bytes] = set()

        base_search_terms = []
        if from_query:
            base_search_terms.append(from_query)
        if since_query:
            base_search_terms.append(since_query)

        if base_search_terms:
            base_criteria = " ".join(base_search_terms)
            logger.info(f"Using base search query: {base_criteria}")
            status, message_numbers = self.mail.search(None, base_criteria)
            if status == "OK":
                all_message_numbers.update(message_numbers[0].split())
            else:
                logger.error(f"Base search failed: {message_numbers}")

        if not all_message_numbers:
            for subj in subjects:
                search_terms = []
                if from_query:
                    search_terms.append(from_query)
                if since_query:
                    search_terms.append(since_query)
                search_terms.append(f'SUBJECT "{subj}"')
                search_criteria = " ".join(search_terms)
                logger.info(f"Using search query: {search_criteria}")
                status, message_numbers = self.mail.search(None, search_criteria)
                if status == "OK":
                    all_message_numbers.update(message_numbers[0].split())
                else:
                    logger.error(f"Search failed for subject {subj}: {message_numbers}")

        logger.info(f"Found {len(all_message_numbers)} messages to process")

        emails = []
        for num in all_message_numbers:
            # The message number needs to be decoded from bytes to a string
            status, msg_data = self.mail.fetch(num.decode("utf-8"), "(RFC822)")
            if status != "OK":
                logger.warning(f"Failed to fetch email with number: {num.decode('utf-8')}")
                continue

            # Ensure msg_data is not empty and has the expected structure
            if not msg_data or not isinstance(msg_data, list) or len(msg_data) < 1:
                logger.warning(f"No data returned for email number: {num.decode('utf-8')}")
                continue

            # The actual email content is in the second part of the first tuple
            email_body = msg_data[0]
            if not isinstance(email_body, tuple) or len(email_body) < 2:
                logger.warning(f"Unexpected data structure for email number: {num.decode('utf-8')}")
                continue

            email_content = email_body[1]
            if not isinstance(email_content, bytes):
                logger.warning(f"Email content is not bytes for email number: {num.decode('utf-8')}")
                continue

            email_message = email.message_from_bytes(email_content)
            if self._should_process_email(email_message):
                emails.append(email_message)
        return emails
