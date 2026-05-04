"""
Slack notifier for sending paper classification results.

This module provides a client for sending notifications to Slack channels
about newly classified research papers. It uploads the classified papers
JSON file directly to the configured Slack channel.
"""

import logging
import os

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from config import AppConfig, SlackConfig

logger = logging.getLogger(__name__)


class SlackNotifier:
    """A client for sending Slack notifications."""

    def __init__(self, config: AppConfig):
        """
        Initialize the Slack notifier with the given configuration.

        Args:
            config: The full application configuration.
        """
        self.client = WebClient(token=config.slack.api_token)
        self.config = config

    def send_classified_papers(self, filepath: str) -> None:
        """
        Upload the classified papers JSON file to the default Slack channel,
        pinging everyone in the channel.

        Args:
            filepath: Path to the classified_papers.json file.
        """
        channel = f"{self.config.slack.default_channel_id}"
        message = "📚 *Conference Scout Update*\n<!channel>"
    
        try:
            self.client.files_upload_v2(
                file=filepath,
                channel=channel,
                title="Classified Papers",
                filename="classified_papers.json",
                initial_comment=message,
            )
            logger.info(f"Uploaded {filepath} to {channel}")
        except SlackApiError as e:
            logger.error(f"Failed to upload to {channel}: {e.response['error']}")
            raise


if __name__ == "__main__":
    import sys

    from dotenv import load_dotenv

    # Add src/conference_scout to path so we can import config directly
    sys.path.insert(0, os.path.dirname(__file__))
    from config import load_config

    # Setup
    project_root = os.path.join(os.path.dirname(__file__), "..", "..")
    load_dotenv(os.path.join(project_root, ".env"))

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    config = load_config(os.path.join(project_root, "config", "config.yml"))
    notifier = SlackNotifier(config)
    notifier.send_classified_papers(os.path.join(project_root, "data", "classified_papers.json"))
