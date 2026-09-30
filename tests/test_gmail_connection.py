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

import os
import sys
import unittest
from pathlib import Path

from dotenv import load_dotenv

# Add src directory to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from scholar_scout.config import load_config
from scholar_scout.email_client import EmailClient


@unittest.skipUnless(os.getenv("RUN_LIVE_TESTS") == "1", "Live services require explicit opt-in")
class TestGmailConnection(unittest.TestCase):
    def setUp(self):
        load_dotenv(Path(__file__).with_name(".env.test"))
        missing = [name for name in ("GMAIL_USERNAME", "GMAIL_APP_PASSWORD") if not os.getenv(name)]
        if missing:
            raise RuntimeError(f"Missing live Gmail credentials: {missing}")
        self.config = load_config(str(Path(__file__).with_name("test_config.yml")))

    def test_gmail_connection_and_retrieval(self):
        with EmailClient(self.config.email) as client:
            messages = client.fetch_scholar_alerts(readonly=True)
        self.assertIsInstance(messages, list)


if __name__ == "__main__":
    unittest.main()
