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

import unittest
from unittest import TestCase, mock
import os
import sys
from pathlib import Path

# Add src directory to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from scholar_scout.classifier import ScholarClassifier
from scholar_scout.email_client import EmailClient
from scholar_scout.config import (
    AppConfig,
    EmailConfig,
    PerplexityConfig,
    ResearchTopic,
    SlackConfig,
    load_config,
)
from dotenv import load_dotenv


def test_extract_and_classify_papers(mocker):
    """Test the paper extraction and classification functionality using pytest-mock."""
    # Create test config using Pydantic models
    email_config = EmailConfig(username="test@example.com", password="test")
    slack_config = SlackConfig(api_token="test-token", default_channel="#scholar-scout-default")
    perplexity_config = PerplexityConfig(api_key="test-key")
    
    research_topics = [
        ResearchTopic(
            name="LLM Inference",
            keywords=["llm", "inference"],
            slack_users=["@test1"],
            description="LLM inference research"
        ),
        ResearchTopic(
            name="Serverless Computing",
            keywords=["serverless"],
            slack_users=["@test2"],
            description="Serverless computing research"
        )
    ]
    
    config = AppConfig(
        email=email_config,
        slack=slack_config,
        perplexity=perplexity_config,
        research_topics=research_topics
    )

    # Set up mock email message with multipart content
    email_message = mocker.Mock()
    email_message.is_multipart.return_value = True

    # Create sample HTML content simulating a Google Scholar alert
    html_content = """
    <div>
        <h3><a href="http://example.com/paper">Efficient LLM Inference on Serverless Platforms</a></h3>
        <div>John Doe, Jane Smith</div>
        <div>This paper presents novel techniques for optimizing LLM inference in serverless environments.</div>
    </div>
    """

    # Mock email part containing HTML content
    email_part = mocker.Mock()
    email_part.get_content_type.return_value = "text/html"
    email_part.get_payload.return_value = html_content.encode()

    # Set up email structure
    email_message.walk.return_value = [email_part]

    # Create mock response from Perplexity API
    mock_response = mocker.Mock()
    mock_response.choices = [
        mocker.Mock(
            message=mocker.Mock(
                content="""{
                    "title": "Efficient LLM Inference on Serverless Platforms",
                    "authors": ["John Doe", "Jane Smith"],
                    "venue": "SOSP 2024",
                    "link": "http://example.com/paper",
                    "abstract": "This paper presents novel techniques for optimizing LLM inference in serverless environments.",
                    "relevant_topics": ["LLM Inference", "Serverless Computing"]
                }"""
            )
        )
    ]

    # Mock the OpenAI/Perplexity API call
    mocker.patch("scholar_scout.classifier.OpenAI").return_value.chat.completions.create.return_value = mock_response

    # Initialize classifier with test config
    classifier = ScholarClassifier(config)

    # Execute the method being tested
    results = classifier.classify_papers([email_message])

    # Verify results
    assert len(results) == 1, "Should extract exactly one paper"
    paper, topics = results[0]

    # Verify paper details
    assert paper.title == "Efficient LLM Inference on Serverless Platforms"
    assert paper.authors == ["John Doe", "Jane Smith"]
    assert paper.venue == "SOSP 2024"
    assert paper.url == "http://example.com/paper"
    assert "llm inference" in paper.abstract.lower()

    # Verify topic classification
    assert len(topics) == 2, "Should identify two relevant topics"
    topic_names = [t.name for t in topics]
    assert "LLM Inference" in topic_names
    assert "Serverless Computing" in topic_names


class TestScholarClassifier(TestCase):
    """Test suite for ScholarClassifier using unittest framework."""

    def setUp(self):
        """Set up test fixtures before each test method."""
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

    @mock.patch("scholar_scout.classifier.OpenAI")
    def test_classify_papers(self, mock_openai_class):
        """Test paper classification with unittest mocks."""
        # Set up mock email with Google Scholar format
        email_message = mock.Mock()
        email_message.is_multipart.return_value = True

        # Create HTML content matching Google Scholar format
        html_content = """
        <div class="gs_r gs_or gs_scl">
            <h3>
                <a class="gse_alrt_title" href="http://example.com/paper">Efficient LLM Inference on Serverless Platforms</a>
            </h3>
            <div>John Doe, Jane Smith</div>
            <div>This paper presents novel techniques for optimizing LLM inference in serverless environments.</div>
        </div>
        """

        # Mock email part with proper encoding handling
        email_part = mock.Mock()
        email_part.get_content_type.return_value = "text/html"
        email_part.get_payload.return_value = html_content.encode("utf-8")
        email_part.get_payload.side_effect = lambda decode: (
            html_content.encode("utf-8") if decode else html_content
        )

        email_message.walk.return_value = [email_part]

        # Set up OpenAI client mock
        mock_client = mock.Mock()
        mock_openai_class.return_value = mock_client

        # Create mock API response
        mock_response = mock.Mock()
        mock_response.choices = [
            mock.Mock(
                message=mock.Mock(
                    content="""{
                        "title": "Efficient LLM Inference on Serverless Platforms",
                        "authors": ["John Doe", "Jane Smith"],
                        "venue": "SOSP 2024",
                        "link": "http://example.com/paper",
                        "abstract": "This paper presents novel techniques for optimizing LLM inference in serverless environments.",
                        "relevant_topics": ["LLM Inference", "Serverless Computing"]
                    }"""
                )
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response

        # Execute test
        classifier = ScholarClassifier(self.config)
        results = classifier.classify_papers([email_message])

        # Verify results
        assert len(results) == 1, "Should extract exactly one paper"
        paper, topics = results[0]

        # Check paper metadata
        assert paper.title == "Efficient LLM Inference on Serverless Platforms"
        assert "John Doe" in paper.authors[0]
        assert paper.url == "http://example.com/paper"
        assert "llm inference" in paper.abstract.lower()

        # Verify topic classification
        assert len(topics) == 2, "Should identify two relevant topics"
        topic_names = [t.name for t in topics]
        assert "LLM Inference" in topic_names
        assert "Serverless Computing" in topic_names


class TestEmailClient(TestCase):
    """Test suite for EmailClient functionality."""

    def setUp(self):
        """Set up test fixtures before each test method."""
        # Create test email config
        self.email_config = EmailConfig(
            username="test@example.com",
            password="test",
            folder="INBOX"
        )

    def test_should_process_email_with_chinese_subject(self):
        """Test email filtering with Chinese subject lines."""
        # Create a mock email message with Chinese subject
        email_message = mock.Mock()
        email_message.get.return_value = "新文章 - Google Scholar 学术搜索"
        
        email_client = EmailClient(self.email_config)
        
        # Mock the search_criteria.yml file to include Chinese subjects
        mock_criteria = {
            'email_filter': {
                'from': 'scholaralerts-noreply@google.com',
                'subject': ['new articles', '新文章'],
                'time_window': '7D'
            }
        }
        
        # Mock the file reading and YAML loading for _should_process_email
        mock_file_content = '''email_filter:
  from: "scholaralerts-noreply@google.com"
  subject:
    - "new articles"
    - "新文章"
  time_window: "7D"'''
        
        with mock.patch('builtins.open', mock.mock_open(read_data=mock_file_content)):
            with mock.patch('yaml.safe_load', return_value=mock_criteria):
                # Test that Chinese subject should be processed
                result = email_client._should_process_email(email_message)
                self.assertTrue(result, "Chinese subject should be processed")

    def test_should_process_email_with_unrelated_subject(self):
        """Test email filtering with unrelated subject lines."""
        # Create a mock email message with unrelated subject
        email_message = mock.Mock()
        email_message.get.return_value = "Your weekly newsletter"
        
        email_client = EmailClient(self.email_config)
        
        mock_criteria = {
            'email_filter': {
                'from': 'scholaralerts-noreply@google.com',
                'subject': ['new articles', '新文章'],
                'time_window': '7D'
            }
        }
        
        # Mock the file reading and YAML loading for _should_process_email
        mock_file_content = '''email_filter:
  from: "scholaralerts-noreply@google.com"
  subject:
    - "new articles"
    - "新文章"
  time_window: "7D"'''
        
        with mock.patch('builtins.open', mock.mock_open(read_data=mock_file_content)):
            with mock.patch('yaml.safe_load', return_value=mock_criteria):
                # Test that unrelated subject should NOT be processed
                result = email_client._should_process_email(email_message)
                self.assertFalse(result, "Unrelated subject should NOT be processed")

    def test_should_process_email_with_empty_subject(self):
        """Test email filtering with empty subject."""
        # Create a mock email message with empty subject
        email_message = mock.Mock()
        email_message.get.return_value = ""
        
        email_client = EmailClient(self.email_config)
        
        mock_criteria = {
            'email_filter': {
                'from': 'scholaralerts-noreply@google.com',
                'subject': ['new articles', '新文章'],
                'time_window': '7D'
            }
        }
        
        # Mock the file reading and YAML loading for _should_process_email
        mock_file_content = '''email_filter:
  from: "scholaralerts-noreply@google.com"
  subject:
    - "new articles"
    - "新文章"
  time_window: "7D"'''
        
        with mock.patch('builtins.open', mock.mock_open(read_data=mock_file_content)):
            with mock.patch('yaml.safe_load', return_value=mock_criteria):
                # Test that empty subject should NOT be processed
                result = email_client._should_process_email(email_message)
                self.assertFalse(result, "Empty subject should NOT be processed")

    def test_build_email_search_query_with_chinese_subjects(self):
        """Test IMAP search query building with Chinese subjects."""
        email_client = EmailClient(self.email_config)
        
        # Mock the search_criteria.yml file
        mock_criteria = {
            'email_filter': {
                'from': 'scholaralerts-noreply@google.com',
                'subject': ['new articles', '新文章'],
                'time_window': '7D'
            }
        }

        with mock.patch('builtins.open', mock.mock_open(read_data='email_filter:\n  from: "scholaralerts-noreply@google.com"\n  subject:\n    - "new articles"\n    - "新文章"\n  time_window: "7D"')):
            with mock.patch('yaml.safe_load', return_value=mock_criteria):
                from_query, since_query, subjects = email_client._build_email_search_query()
                
                # Verify FROM query
                self.assertEqual(from_query, 'FROM "scholaralerts-noreply@google.com"')
                
                # Verify SINCE query (should contain a date)
                self.assertIn('SINCE', since_query)
                # Check that it contains a valid date format (DD-MMM-YYYY)
                import re
                date_pattern = r'\d{2}-[A-Za-z]{3}-\d{4}'
                self.assertIsNotNone(re.search(date_pattern, since_query), "Should contain valid date format")
                
                # Verify subjects list contains both English and Chinese
                self.assertIn('new articles', subjects)
                self.assertIn('新文章', subjects)

    def test_mixed_language_subject_processing(self):
        """Test processing of emails with mixed language subjects."""
        # Test various subject combinations
        test_cases = [
            ("新文章 - New articles in your Google Scholar alert", True),
            ("New articles - 新文章 in your Google Scholar alert", True),
            ("Google Scholar: 新结果 for your search", False),
            ("Weekly newsletter from Google", False),
            ("新文章", True),
            ("new articles", True),
            ("", False),
            (None, False)
        ]
        
        email_client = EmailClient(self.email_config)
        
        mock_criteria = {
            'email_filter': {
                'from': 'scholaralerts-noreply@google.com',
                'subject': ['new articles', '新文章'],
                'time_window': '7D'
            }
        }
        
        # Mock the file reading and YAML loading for _should_process_email
        mock_file_content = '''email_filter:
  from: "scholaralerts-noreply@google.com"
  subject:
    - "new articles"
    - "新文章"
  time_window: "7D"'''
        
        with mock.patch('builtins.open', mock.mock_open(read_data=mock_file_content)):
            with mock.patch('yaml.safe_load', return_value=mock_criteria):
                for subject, expected_result in test_cases:
                    email_message = mock.Mock()
                    email_message.get.return_value = subject
                    
                    result = email_client._should_process_email(email_message)
                    self.assertEqual(
                        result,
                        expected_result,
                        f"Subject '{subject}' should {'be' if expected_result else 'NOT be'} processed"
                    )


if __name__ == "__main__":
    unittest.main()
