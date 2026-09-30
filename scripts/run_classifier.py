"""
Main entry point for the Scholar Scout application.

This script initializes the application and runs the classification process.
"""

import argparse
from contextlib import ExitStack
import logging
import os
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory

from dotenv import load_dotenv

# Add the src directory to the Python path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

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
        help="Enable detailed application logs (does not disable side effects)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read-only mail, no Slack, and temporary state; external API calls still run",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if args.debug:
        logging.getLogger("scholar_scout").setLevel(logging.DEBUG)
    logger = logging.getLogger(__name__)

    load_dotenv()

    logger.info("Dry run: %s", args.dry_run)

    config = load_config()

    with EmailClient(config.email) as email_client:
        emails = email_client.fetch_scholar_alerts(readonly=args.dry_run)
        search_period = email_client.search_period
        if not args.dry_run:
            email_client.delete_old_emails()

    with ExitStack() as stack:
        if args.dry_run:
            state_dir = stack.enter_context(TemporaryDirectory(prefix="scholar-scout-dry-run-"))
            if Path(config.state_dir).exists():
                shutil.copytree(config.state_dir, state_dir, dirs_exist_ok=True)
            config = config.model_copy(update={"state_dir": state_dir})
        classifier = ScholarClassifier(config)
        results = classifier.classify_papers(emails)

    if not args.dry_run:
        notifier = SlackNotifier(config.slack, config.research_topics)
        notifier.notify_matches(results)

        papers_by_topic = {}
        for paper, topics in results:
            for topic in topics:
                if topic.name not in papers_by_topic:
                    papers_by_topic[topic.name] = []
                papers_by_topic[topic.name].append(paper)
        notifier.send_weekly_update(papers_by_topic, period=search_period)
        notifier.send_pending_update(classifier.pending, classifier.newly_expired)


if __name__ == "__main__":
    main()
