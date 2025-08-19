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

import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import os

from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

# Add src directory to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from scholar_scout.models import Paper
from scholar_scout.config import load_config
from scholar_scout.notifications import SlackNotifier


class TestSlackNotifier(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        # Load test configuration
        env_path = os.path.join(os.path.dirname(__file__), ".env.test")
        if not load_dotenv(env_path, override=True):
            # For CI environment, ensure required env vars are set
            required_vars = ["GMAIL_USERNAME", "GMAIL_APP_PASSWORD", "PPLX_API_KEY"]
            missing_vars = [var for var in required_vars if not os.getenv(var)]
            if missing_vars:
                raise RuntimeError(f"Missing required environment variables: {missing_vars}")
        config_path = os.path.join(os.path.dirname(__file__), "test_config.yml")
        self.config = load_config(config_path)
        self.notifier = SlackNotifier(self.config.slack)

        # Sample paper
        self.paper = Paper(
            title="Test Paper",
            authors=["Author One", "Author Two"],
            abstract="This is a test abstract",
            url="https://example.com/paper",
            venue="arXiv preprint",
        )

        # Sample topics from config
        self.topic1 = self.config.research_topics[0]
        self.topic2 = self.config.research_topics[1]

    @patch("slack_sdk.WebClient")
    def test_notify_matches_success(self, mock_client):
        # Setup mock
        mock_client.return_value.chat_postMessage.return_value = {"ok": True}
        self.notifier.client = mock_client.return_value

        # Test with multiple topics
        topics = [self.topic1, self.topic2]
        # Create a list of paper-topic pairs
        paper_results = [(self.paper, topics)]
        self.notifier.notify_matches(paper_results)

        # Check calls to Slack API
        calls = mock_client.return_value.chat_postMessage.call_args_list
        self.assertEqual(len(calls), 2)

        # Check first call (topic with specific channel)
        self.assertEqual(calls[0][1]["channel"], "#scholar-scout-llm")
        self.assertIn("@test1", calls[0][1]["text"])
        self.assertIn("Test Paper", calls[0][1]["text"])

        # Check second call (topic using default channel)
        self.assertEqual(calls[1][1]["channel"], "#scholar-scout-serverless")
        self.assertIn("@test3", calls[1][1]["text"])

    @patch("slack_sdk.WebClient")
    def test_notify_matches_empty_topics(self, mock_client):
        # Should not make any API calls if no topics
        self.notifier.notify_matches([])
        mock_client.return_value.chat_postMessage.assert_not_called()

    @patch("slack_sdk.WebClient")
    def test_notify_matches_api_error(self, mock_client):
        # Setup mock to raise error
        mock_client.return_value.chat_postMessage.side_effect = SlackApiError(
            "Error", {"error": "channel_not_found"}
        )
        self.notifier.client = mock_client.return_value

        # Should handle error gracefully
        try:
            paper_results = [(self.paper, [self.topic1])]
            self.notifier.notify_matches(paper_results)
        except Exception as e:
            self.fail(f"Should not raise exception, but raised {e}")

    @patch("slack_sdk.WebClient")
    def test_notify_matches_with_multiple_topics(self, mock_client):
        """Test notification with multiple topics."""
        # Setup mock
        mock_client.return_value.chat_postMessage.return_value = {"ok": True}
        self.notifier.client = mock_client.return_value

        # Test with multiple topics
        paper_results = [(self.paper, [self.topic1, self.topic2])]
        self.notifier.notify_matches(paper_results)

        # Should be called once for each topic
        self.assertEqual(mock_client.return_value.chat_postMessage.call_count, 2)


if __name__ == "__main__":
    unittest.main()
