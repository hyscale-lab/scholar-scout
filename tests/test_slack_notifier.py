"""
MIT License

Copyright (c) 2024 Dmitrii Ustiugov

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
"""

from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from slack_sdk.errors import SlackApiError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from scholar_scout.config import ResearchTopic, SlackConfig
from scholar_scout.models import Paper
from scholar_scout.notifications import SlackNotifier


class TestSlackNotifier(unittest.TestCase):
    def setUp(self):
        self.config = SlackConfig(
            api_token="test", default_channel="#default", pending_user_id="U123456789"
        )
        self.topics = [
            ResearchTopic(
                name="Serverless Computing", slack_users=["@one"], slack_channel="C123456789"
            ),
            ResearchTopic(
                name="Sustainable Computing", slack_users=["@two"], slack_channel="C123456789"
            ),
            ResearchTopic(name="LLM Inference", slack_users=["@three"], slack_channel="#inference"),
        ]
        client = patch("scholar_scout.notifications.WebClient")
        self.client = client.start().return_value
        self.addCleanup(client.stop)
        self.notifier = SlackNotifier(self.config, self.topics)
        self.period = (date(2026, 9, 13), date(2026, 9, 27))
        self.paper = Paper(
            title="Example Paper",
            authors=["A Author"],
            abstract="Example abstract",
            url="https://example.org/paper",
            venue="Example Conference",
        )

    def pending(self, count=1):
        return {
            f"paper-{i}": {
                "paper": dict(self.paper.model_dump(), title=f"Pending {i:03d} " + "x" * 180),
                "status": "pending_abstract",
            }
            for i in range(count)
        }

    def test_paper_and_summary_routing_keeps_topics_independent(self):
        papers = [self.paper.model_copy(update={"title": f"Paper {i}"}) for i in range(3)]
        self.notifier.notify_matches(
            [(paper, [topic]) for paper, topic in zip(papers, self.topics)]
        )
        calls = self.client.chat_postMessage.call_args_list
        self.assertEqual(len(calls), 3)
        for call, paper, topic in zip(calls, papers, self.topics):
            self.assertEqual(call.kwargs["channel"], topic.slack_channel)
            for text in (topic.name, topic.slack_users[0], paper.title, paper.url):
                self.assertIn(text, call.kwargs["text"])
        self.client.reset_mock()
        self.notifier.send_weekly_update(
            {topic.name: [paper] for topic, paper in zip(self.topics, papers)}, period=self.period
        )
        calls = self.client.chat_postMessage.call_args_list
        self.assertEqual(len(calls), len(self.topics))
        for call, topic in zip(calls, self.topics):
            self.assertEqual(call.kwargs["channel"], topic.slack_channel)
            text = call.kwargs["text"]
            for day in self.period:
                self.assertIn(day.isoformat(), text)
            for other_topic, paper in zip(self.topics, papers):
                if other_topic.name == topic.name:
                    self.assertIn(other_topic.name, text)
                    self.assertIn(paper.title, text)
                else:
                    self.assertNotIn(other_topic.name, text)
                    self.assertNotIn(paper.title, text)

    def test_empty_and_unmatched_results_never_send_paper_notifications(self):
        for results in ([], [(self.paper, [])]):
            self.notifier.notify_matches(results)
        self.client.chat_postMessage.assert_not_called()
        self.notifier.send_weekly_update({"Others": [self.paper]}, period=self.period)
        self.assertEqual(self.client.chat_postMessage.call_count, len(self.topics))
        for call, topic in zip(self.client.chat_postMessage.call_args_list, self.topics):
            self.assertEqual(call.kwargs["channel"], topic.slack_channel)
            self.assertIn(topic.name, call.kwargs["text"])
            self.assertNotIn(self.paper.title, call.kwargs["text"])
            self.assertNotIn("Others", call.kwargs["text"])

    def test_pending_is_private_and_batched_without_lost_records(self):
        for count in (1, 40):
            with self.subTest(count=count):
                self.client.reset_mock()
                self.notifier.send_pending_update(self.pending(count))
                calls = self.client.chat_postMessage.call_args_list
                self.assertGreaterEqual(len(calls), 1)
                if count == 40:
                    self.assertGreater(len(calls), 1)
                for call in calls:
                    self.assertEqual(call.kwargs["channel"], self.config.pending_user_id)
                    self.assertLessEqual(len(call.kwargs["text"]), 3500)
                    self.assertFalse(call.kwargs["mrkdwn"])
                    self.assertFalse(call.kwargs["unfurl_links"])
                combined = "\n".join(call.kwargs["text"] for call in calls)
                for i in range(count):
                    self.assertEqual(combined.count(f"Pending {i:03d}"), 1)
                self.client.reset_mock()
                self.notifier.send_weekly_update({}, period=self.period)
                for call in self.client.chat_postMessage.call_args_list:
                    self.assertNotIn("Pending", call.kwargs["text"])
        self.client.reset_mock()
        expired = self.pending()
        for row in expired.values():
            row["expiration_reason"] = "max_attempts"
        self.notifier.send_pending_update({}, expired, run_failed=True)
        call = self.client.chat_postMessage.call_args
        self.assertEqual(call.kwargs["channel"], self.config.pending_user_id)
        self.assertIn("Stopped retrying: attempt limit", call.kwargs["text"])
        self.assertIn("No papers could be classified", call.kwargs["text"])
        self.client.reset_mock()
        self.notifier.send_pending_update({}, {})
        self.client.chat_postMessage.assert_not_called()

    def test_missing_or_invalid_dm_recipient_never_falls_back_to_channels(self):
        self.notifier.send_pending_update({})
        self.config.pending_user_id = None
        with self.assertLogs("scholar_scout.notifications", level="WARNING"):
            self.notifier.send_pending_update(self.pending())
        self.client.chat_postMessage.assert_not_called()
        for recipient in ("#channel", "C123456789", "G123456789", "D123456789"):
            with self.subTest(recipient=recipient), self.assertRaises(ValueError):
                SlackConfig(api_token="test", default_channel="#default", pending_user_id=recipient)

    def test_dm_failure_raises_without_broadcast_or_secret_logging(self):
        for error in (
            SlackApiError("secret-token", {"error": "missing_scope"}),
            TimeoutError("secret-token"),
        ):
            with self.subTest(error=type(error).__name__):
                self.client.reset_mock()
                self.client.chat_postMessage.side_effect = error
                with self.assertLogs("scholar_scout.notifications", level="ERROR") as logs:
                    with self.assertRaises(RuntimeError):
                        self.notifier.send_pending_update(self.pending())
                self.assertNotIn("secret-token", str(logs.output))
                self.client.chat_postMessage.assert_called_once()
                self.assertEqual(
                    self.client.chat_postMessage.call_args.kwargs["channel"],
                    self.config.pending_user_id,
                )

    def test_paper_send_failure_is_logged_and_other_topics_continue(self):
        self.client.chat_postMessage.side_effect = [
            SlackApiError("Error", {"error": "channel_not_found"}),
            {"ok": True},
        ]
        with self.assertLogs("scholar_scout.notifications", level="ERROR") as logs:
            self.notifier.notify_matches([(self.paper, [self.topics[0], self.topics[2]])])
        self.assertIn("channel_not_found", str(logs.output))
        self.assertEqual(
            [call.kwargs["channel"] for call in self.client.chat_postMessage.call_args_list],
            ["C123456789", "#inference"],
        )


if __name__ == "__main__":
    unittest.main()
