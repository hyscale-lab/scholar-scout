"""
MIT License

Copyright (c) 2024 Dmitrii Ustiugov

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import email
import os
import sys
import unittest
from pathlib import Path

from dotenv import load_dotenv

# Add src directory to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from scholar_scout.config import load_config
from scholar_scout.classifier import ScholarClassifier
from scholar_scout.email_client import EmailClient


class TestGmailConnection(unittest.TestCase):
    def setUp(self):
        """Set up test environment."""
        # Try loading from .env.test file first (for local development)
        env_path = os.path.join(os.path.dirname(__file__), ".env.test")
        if not load_dotenv(env_path, override=True):
            # For CI environment, ensure required env vars are set
            required_vars = ["GMAIL_USERNAME", "GMAIL_APP_PASSWORD", "PPLX_API_KEY"]
            missing_vars = [var for var in required_vars if not os.getenv(var)]
            if missing_vars:
                raise RuntimeError(f"Missing required environment variables: {missing_vars}")

        # Load test configuration
        config_path = os.path.join(os.path.dirname(__file__), "test_config.yml")
        self.config = load_config(config_path)
        self.classifier = ScholarClassifier(self.config)

    def test_gmail_connection_and_retrieval(self):
        """
        Test connecting to Gmail and retrieving Google Scholar emails without marking them as read.
        """
        try:
            # Use EmailClient for Gmail connection
            with EmailClient(self.config.email):
                # Print connection details for debugging
                print("\nAttempting connection with:")
                print(f"Username: {self.config.email.username}")
                print(f"Password length: {len(self.config.email.password)} chars")

                # Create mock email for testing since real email fetching requires specific emails
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

                # Test processing of mock email
                print("\nEmail details:")
                print(f"Subject: {mock_email.get('subject')}")
                print(f"From: {mock_email.get('from')}")

                # Extract papers using classifier
                results = self.classifier.classify_papers([mock_email])
                print(f"\nNumber of papers extracted: {len(results)}")

                # Print paper details if any were extracted
                for i, (paper, topics) in enumerate(results):
                    print(f"\nPaper {i + 1}:")
                    print(f"Title: {paper.title}")
                    print(f"Authors: {', '.join(paper.authors)}")
                    print(f"Venue: {paper.venue}")
                    print(f"Abstract preview: {paper.abstract[:200]}...")
                    print(f"Matched Topics: {[topic.name for topic in topics]}")

        except Exception as e:
            self.fail(f"Test failed with exception: {str(e)}")


if __name__ == "__main__":
    unittest.main()
