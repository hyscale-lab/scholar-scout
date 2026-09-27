"""
Slack notifier for sending paper classification results.

This module provides a client for sending notifications to Slack channels
about newly classified research papers. It is designed to be used by the
Scholar Scout application to report results.
"""

from datetime import datetime, timedelta, timezone
import logging
from typing import List, Tuple

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .config import ResearchTopic, SlackConfig
from .models import Paper

logger = logging.getLogger(__name__)


class SlackNotifier:
    """A client for sending Slack notifications."""

    def __init__(self, config: SlackConfig, research_topics: List[ResearchTopic]):
        """
        Initialize the Slack notifier with the given configuration.

        Args:
            config: The Slack configuration.
            research_topics: Topics and their shared paper/summary destinations.
        """
        self.client = WebClient(token=config.api_token)
        self.config = config
        self.research_topics = research_topics

    def _channel_for(self, topic: ResearchTopic) -> str:
        """Resolve the destination shared by individual papers and summaries."""
        return topic.slack_channel or self.config.default_channel

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
                channel = self._channel_for(topic)
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
                    self.client.chat_postMessage(channel=channel, text=message, unfurl_links=True, link_names=True)
                    logger.info(f"Notification sent to channel {channel} for topic {topic.name}")
                except SlackApiError as e:
                    logger.error(f"Failed to send notification to {channel}: {e.response['error']}")

    def send_weekly_update(self, papers_by_topic: dict[str, list[Paper]]):
        """
        Send one summary per topic to its paper notification channel.

        Args:
            papers_by_topic: A dictionary mapping topic names to a list of papers.
        """
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=7)
        for topic in self.research_topics:
            channel = self._channel_for(topic)
            papers = papers_by_topic.get(topic.name, [])
            message = (
                "📚 *Weekly Scholar Scout Update*\n"
                f"Here are the relevant papers for {topic.name} this week "
                f"({start_date.isoformat()} – {end_date.isoformat()}):\n\n"
            )
            if papers:
                message += "\n".join(f"• {paper.title}" for paper in papers)
            else:
                message += "No matched papers to report this week."

            try:
                self.client.chat_postMessage(channel=channel, text=message)
                logger.info(f"Sent weekly update for {topic.name} to {channel}")
            except SlackApiError as e:
                logger.error(f"Failed to send weekly update for {topic.name} to {channel}: {e.response['error']}")

    def send_pending_update(self, pending: dict) -> None:
        if not pending:
            return
        recipient = self.config.pending_user_id
        if not recipient:
            logger.warning("Pending DM disabled: no pending_user_id configured")
            return
        labels = {
            "pending_abstract": "Awaiting source abstract",
            "pending_model": "Awaiting a valid model response",
        }
        header = (
            f"Scholar Scout: {len(pending)} pending papers across all topics.\n"
            "Automatic retries remain enabled; no manual review is required.\n"
        )
        messages, message = [], header
        for key, row in pending.items():
            paper = row["paper"]
            title = " ".join(paper.get("title", "").split())[:240]
            url = " ".join(paper.get("url", "").split())[:500]
            status = labels.get(row["status"], "Awaiting processing")
            entry = f"\n{title}\n{status} | {key}\n{url}\n"
            if len(message) + len(entry) > 3500:
                messages.append(message)
                message = header
            message += entry
        messages.append(message)
        try:
            for message in messages:
                self.client.chat_postMessage(
                    channel=recipient,
                    text=message,
                    mrkdwn=False,
                    parse="none",
                    unfurl_links=False,
                    unfurl_media=False,
                )
            logger.info("Sent pending report to configured user (%d papers)", len(pending))
        except SlackApiError as exc:
            logger.error("Pending DM failed: %s", exc.response.get("error", "unknown_error"))
            raise RuntimeError("Pending DM failed; no channel fallback was attempted") from None
        except Exception as exc:
            logger.error("Pending DM failed (%s)", type(exc).__name__)
            raise RuntimeError("Pending DM failed; no channel fallback was attempted") from None
