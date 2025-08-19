"""
Main entry point for the Scholar Scout application.

This script initializes the application and runs the classification process.
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from scholar_scout.classifier import ScholarClassifier
from scholar_scout.config import load_config
from scholar_scout.email_client import EmailClient
from scholar_scout.notifications import SlackNotifier


def main():
    """Main function to run the Scholar Scout application."""
    parser = argparse.ArgumentParser(description="Run the Scholar Classifier")
    parser.add_argument(
        "--debug",
        action="store_true",
        default=False,
        help="Run in debug mode (disable Slack notifications)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    load_dotenv()

    logger.info(f"Debug mode: {'enabled' if args.debug else 'disabled'}")

    config = load_config()

    with EmailClient(config.email) as email_client:
        emails = email_client.fetch_scholar_alerts()

    classifier = ScholarClassifier(config)
    results = classifier.classify_papers(emails)

    if not args.debug:
        notifier = SlackNotifier(config.slack)
        notifier.notify_matches(results)

        papers_by_topic = {}
        for paper, topics in results:
            for topic in topics:
                if topic.name not in papers_by_topic:
                    papers_by_topic[topic.name] = []
                papers_by_topic[topic.name].append(paper)
        notifier.send_weekly_update(papers_by_topic)


if __name__ == "__main__":
    main()
