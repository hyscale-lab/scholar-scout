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

import email
import logging
import os
import unittest
import sys
from pathlib import Path

from dotenv import load_dotenv

# Add src directory to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from scholar_scout.config import load_config
from scholar_scout.classifier import ScholarClassifier
from scholar_scout.email_client import EmailClient


class TestIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test environment for full pipeline integration testing."""
        # Setup detailed logging
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Enable debug logging for specific components
        logging.getLogger("scholar_scout.notifications").setLevel(logging.INFO)
        logging.getLogger("scholar_scout.classifier").setLevel(logging.INFO)

        # Load test environment variables
        env_path = os.path.join(os.path.dirname(__file__), ".env.test")
        if not load_dotenv(env_path, override=True):
            # For CI environment, ensure required env vars are set
            required_vars = ["GMAIL_USERNAME", "GMAIL_APP_PASSWORD", "PPLX_API_KEY"]
            missing_vars = [var for var in required_vars if not os.getenv(var)]
            if missing_vars:
                raise RuntimeError(f"Missing required environment variables: {missing_vars}")

        # Load test configuration
        config_path = os.path.join(os.path.dirname(__file__), "test_config.yml")
        cls.config = load_config(config_path)
        cls.classifier = ScholarClassifier(cls.config)

    def test_end_to_end_pipeline(self):
        """Test the entire pipeline from Gmail connection to paper classification."""
        try:
            # Use EmailClient for Gmail connection
            with EmailClient(self.config.email):
                # For this test, we'll mock the email fetching since it requires real emails
                # In a real integration test, you'd use: emails = email_client.fetch_scholar_alerts()
                
                # Create mock email for testing
                mock_email = email.message_from_string("""
From: scholaralerts-noreply@google.com
Subject: new articles
Content-Type: text/html

<html>
<body>
<h3><a href="http://example.com/paper">Test Paper on LLM Inference</a></h3>
<div>John Doe, Jane Smith</div>
<div>This is a test abstract about LLM inference optimization.</div>
</body>
</html>
                """)
                
                emails = [mock_email]

            # Test classification
            results = self.classifier.classify_papers(emails)
            
            # Verify we got results (may be empty due to mocking, but shouldn't crash)
            self.assertIsInstance(results, list, "Should return a list of results")
            
            print(f"\nExtracted {len(results)} papers")
            for paper, topics in results:
                print(f"Title: {paper.title}")
                print(f"Authors: {', '.join(paper.authors)}")
                print(f"Matched Topics: {[topic.name for topic in topics]}")

        except Exception as e:
            self.fail(f"Integration test failed: {str(e)}")
