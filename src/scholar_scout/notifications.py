"""
Slack notifier for sending paper classification results.

This module provides a client for sending notifications to Slack channels
about newly classified research papers. It is designed to be used by the
Scholar Scout application to report results.
"""

import logging
from typing import List, Tuple

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .config import ResearchTopic, SlackConfig
from .models import Paper

logger = logging.getLogger(__name__)


class SlackNotifier:
    """A client for sending Slack notifications."""

    def __init__(self, config: SlackConfig):
        """
        Initialize the Slack notifier with the given configuration.

        Args:
            config: The Slack configuration.
        """
        self.client = WebClient(token=config.api_token)
        self.config = config

    def notify_matches(self, paper_results: List[Tuple[Paper, List[ResearchTopic]]]):
        """
        Notify about matching papers to their specific channels.

        Args:
            paper_results: A list of tuples, each containing a paper and a list
                           of matched research topics.
        """
        if not paper_results:
            return

        for paper, matched_topics in paper_results:
            for topic in matched_topics:
                channel = topic.slack_channel or self.config.default_channel
                users_mention = " ".join(topic.slack_users)

                message = (
                    f"{users_mention}\n"
                    f"New paper matching topic: {topic.name}\n"
                    f"Title: {paper.title}\n"
                    f"Authors: {', '.join(paper.authors)}\n"
                    f"Venue: {paper.venue}\n"
                    f"URL: {paper.url}\n"
                    f"Abstract: {paper.abstract[:500]}..."
                )

                try:
                    self.client.chat_postMessage(channel=channel, text=message, unfurl_links=True)
                    logger.info(f"Notification sent to channel {channel} for topic {topic.name}")
                except SlackApiError as e:
                    logger.error(f"Failed to send notification to {channel}: {e.response['error']}")

    def send_weekly_update(self, papers_by_topic: dict[str, list[Paper]]):
        """
        Send a weekly update of all classified papers to the relevant channels.

        Args:
            papers_by_topic: A dictionary mapping topic names to a list of papers.
        """
        for channel, topics in self.config.channel_topics.items():
            channel_papers = {
                topic: papers
                for topic, papers in papers_by_topic.items()
                if topic in topics
            }

            if channel_papers:
                summary = []
                for topic, papers in channel_papers.items():
                    paper_list = [f"• {paper.title}" for paper in papers]
                    summary.append(f"*{topic}*:\n" + "\n".join(paper_list))
                message = (
                    "📚 *Weekly Scholar Scout Update*\n"
                    f"Here are the relevant papers for #{channel} this week:\n\n"
                    + "\n\n".join(summary)
                )
            else:
                message = (
                    "📚 *Weekly Scholar Scout Update*\n"
                    f"No relevant papers were found for #{channel} this week."
                )

            try:
                self.client.chat_postMessage(channel=f"#{channel}", text=message)
                logger.info(f"Sent weekly update notification to #{channel}")
            except SlackApiError as e:
                logger.error(f"Failed to send weekly update to #{channel}: {e.response['error']}")
