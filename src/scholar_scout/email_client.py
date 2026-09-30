"""
Email client for fetching Google Scholar alerts from a Gmail account.

This module provides a client for connecting to a Gmail account via IMAP,
searching for specific emails, and fetching their content. It is designed to
be used by the Scholar Scout application to retrieve emails for classification.
"""

import email
import imaplib
import logging
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.message import Message
from typing import List

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
        self.search_period = None

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

    def delete_old_emails(self) -> None:
        """Deletes emails from the configured folder that are older than the time window."""
        assert self.mail is not None

        with open("config/search_criteria.yml", "r") as f:
            criteria = yaml.safe_load(f).get("email_empty", {})

        time_window = criteria.get("time_window")
        if not time_window:
            logger.info("No time_window for email_empty, skipping deletion.")
            return

        try:
            amount = int(time_window[:-1])
            unit = time_window[-1]
            delta = timedelta()
            if unit == "D":
                delta = timedelta(days=amount)
            elif unit == "W":
                delta = timedelta(weeks=amount)
            elif unit == "M":
                delta = timedelta(days=amount * 30)  # Approximation
            else:
                logger.warning(f"Unknown time unit '{unit}', skipping deletion.")
                return

            before_date = (datetime.now() - delta).strftime("%d-%b-%Y")
            search_criteria = f'(BEFORE "{before_date}")'

            folder_name = self.config.folder
            if " " in folder_name and not folder_name.startswith('"'):
                folder_name = f'"{folder_name}"'

            self.mail.select(folder_name, readonly=False)
            status, msg_ids = self.mail.search(None, search_criteria)

            if status == "OK":
                email_ids = msg_ids[0].split()
                if email_ids:
                    logger.info(f"Deleting {len(email_ids)} old emails.")
                    for eid in email_ids:
                        self.mail.store(eid, "+FLAGS", "\\Deleted")
                    self.mail.expunge()
                else:
                    logger.info("No old emails to delete.")
        except Exception as e:
            logger.error(f"Error deleting old emails: {e}")

    def build_email_search_query(self) -> tuple[str, str, list[str]]:
        """Build the IMAP search query for finding Google Scholar alerts."""
        with open("config/search_criteria.yml", "r") as f:
            criteria = yaml.safe_load(f)["email_filter"]

        from_query = f'FROM "{criteria["from"]}"'
        since_query = ""
        end_date = datetime.now(timezone.utc).date()
        start_date = None
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
            start_date = end_date - delta
            date_str = start_date.strftime("%d-%b-%Y")
            since_query = f'SINCE "{date_str}"'

        self.search_period = (start_date, end_date)
        subjects = criteria.get("subject", [])
        return from_query, since_query, subjects

    def should_process_email(self, email_message: Message) -> bool:
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

    def fetch_scholar_alerts(self, readonly: bool = False) -> List[Message]:
        """
        Fetch Google Scholar alert emails from the configured folder.

        Returns:
            A list of email messages.

        Raises:
            RuntimeError: A mailbox operation fails or returns malformed data.
        """
        assert self.mail is not None
        folder_name = self.config.folder
        if " " in folder_name and not folder_name.startswith('"'):
            folder_name = f'"{folder_name}"'
        logger.info(f"Attempting to access folder: {folder_name}")

        status, _ = self.mail.select(folder_name, readonly=readonly)
        if status != "OK":
            raise RuntimeError(f"Failed to select email folder {folder_name}")

        from_query, since_query, _ = self.build_email_search_query()

        base_search_terms = []
        if from_query:
            base_search_terms.append(from_query)
        if since_query:
            base_search_terms.append(since_query)

        if not base_search_terms:
            raise RuntimeError("Email search criteria are empty")
        base_criteria = " ".join(base_search_terms)
        logger.info(f"Using base search query: {base_criteria}")
        status, message_numbers = self.mail.search(None, base_criteria)
        if status != "OK":
            raise RuntimeError("Failed to search Scholar emails")
        if (
            not isinstance(message_numbers, list)
            or len(message_numbers) != 1
            or not isinstance(message_numbers[0], bytes)
        ):
            raise RuntimeError("Invalid email search response")
        all_message_numbers = message_numbers[0].split()
        if any(not num.isdigit() or int(num) < 1 for num in all_message_numbers):
            raise RuntimeError("Invalid message numbers in email search response")

        logger.info(f"Found {len(all_message_numbers)} messages to process")

        emails = []
        for num in all_message_numbers:
            message_number = num.decode("ascii")
            status, msg_data = self.mail.fetch(
                message_number, "(BODY.PEEK[])" if readonly else "(RFC822)"
            )
            if status != "OK":
                raise RuntimeError(f"Failed to fetch email {message_number}")

            # Ensure msg_data is not empty and has the expected structure
            if not msg_data or not isinstance(msg_data, list) or len(msg_data) < 1:
                raise RuntimeError(f"No data returned for email {message_number}")

            # The actual email content is in the second part of the first tuple
            email_body = msg_data[0]
            if not isinstance(email_body, tuple) or len(email_body) < 2:
                raise RuntimeError(f"Invalid fetch response for email {message_number}")

            email_content = email_body[1]
            if not isinstance(email_content, bytes) or not email_content.strip():
                raise RuntimeError(f"Invalid content returned for email {message_number}")

            email_message = email.message_from_bytes(email_content)
            if self.should_process_email(email_message):
                emails.append(email_message)
        return emails
