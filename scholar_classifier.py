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

# Standard library imports
import email
import imaplib
import json
import logging
import os
import urllib.parse
from string import Template

import html2text
import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import OpenAI

from config import ResearchTopic
from paper import Paper
from slack_notifier import SlackNotifier

# Configure logging for external libraries
logging.getLogger("openai").setLevel(logging.INFO)
logging.getLogger("httpcore").setLevel(logging.INFO)


def load_config(config_file):
    """
    Load and process configuration file with environment variable substitution.

    Args:
        config_file: Path to YAML configuration file

    Returns:
        dict: Parsed configuration with environment variables substituted
    """
    # Read the config file as a template
    with open(config_file) as f:
        template = Template(f.read())

    # Substitute environment variables in the template
    config_str = template.safe_substitute(os.environ)

    # Parse the YAML with substituted values
    return yaml.safe_load(config_str)


class ScholarClassifier:
    """
    Main class for processing Google Scholar alerts and classifying papers.

    This class handles:
    - Connecting to Gmail to fetch Scholar alerts
    - Extracting paper information from emails
    - Classifying papers using Perplexity AI
    - Notifying relevant team members via Slack
    - Sending weekly updates to system channels
    """

    def __init__(self, config_file=None, config_dict=None, pplx_client=None, slack_notifier=None):
        """
        Initialize the classifier with configuration and clients.

        Args:
            config_file: Path to YAML config file (optional)
            config_dict: Configuration dictionary (optional)
            pplx_client: Pre-configured Perplexity client (optional)
            slack_notifier: Pre-configured Slack notifier (optional)

        Raises:
            ValueError: If neither config_file nor config_dict is provided
        """
        # Set up logging
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)  # Set to DEBUG level

        # Add a console handler if none exists
        if not self.logger.handlers:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            formatter = logging.Formatter("%(message)s")
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

        # Load configuration with environment variable substitution
        if config_file:
            self.config = load_config(config_file)  # Use the new load_config function
        elif config_dict:
            self.config = config_dict
        else:
            raise ValueError("Either config_file or config_dict must be provided")

        # Initialize topics
        self.topics = self._init_research_topics()

        # Initialize Perplexity client
        self.pplx_client = OpenAI(
            api_key=self.config["perplexity"]["api_key"],
            base_url="https://api.perplexity.ai",
        )

        # Initialize Slack client
        self.slack_notifier = SlackNotifier(
            token=self.config["slack"]["api_token"],
            default_channel=self.config["slack"]["default_channel"],
            config=self.config,
        )

        # Add sets to track processed papers
        self._processed_titles = set()
        self._processed_urls = set()

    def _init_research_topics(self):
        """Initialize research topics from configuration."""
        return [ResearchTopic(**topic_config) for topic_config in self.config["research_topics"]]

    def connect_to_gmail(self) -> imaplib.IMAP4_SSL:
        """Establish connection to Gmail using IMAP."""
        username = os.getenv("GMAIL_USERNAME")
        password = os.getenv("GMAIL_APP_PASSWORD")
        try:
            self.logger.info(
                f"Connecting to Gmail with username: {self.config['email']['username']}"
            )

            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            self.logger.info("IMAP SSL connection established")

            mail.login(username, password)
            self.logger.info("Successfully logged into Gmail")

            return mail
        except Exception as e:
            self.logger.error(f"Error connecting to Gmail: {str(e)}")
            self.logger.error(f"Error type: {type(e)}")
            raise

    def _extract_paper_urls(self, html):
        """Extract paper URLs and titles from HTML content."""
        try:
            soup = BeautifulSoup(html, "html.parser")
            paper_links = {}

            # Find all paper title links,
            # they have both class='gse_alrt_title' and href containing 'scholar_url'
            for title_link in soup.find_all("a", class_="gse_alrt_title"):
                title = title_link.get_text(strip=True)
                url = title_link.get("href", "")

                # Extract the actual paper URL from the Google Scholar redirect URL
                if url and "scholar_url?url=" in url:
                    try:
                        # The actual URL is the value of the 'url' parameter in the query string
                        from urllib.parse import parse_qs, urlparse

                        parsed = urlparse(url)
                        actual_url = parse_qs(parsed.query)["url"][0]
                        if actual_url:
                            paper_links[title] = actual_url
                    except Exception as e:
                        self.logger.error(f"Error extracting actual URL: {str(e)}")
                        continue

            return paper_links

        except Exception as e:
            self.logger.error(f"Error extracting URLs: {str(e)}")
            return {}

    def _extract_paper_metadata(self, content):
        """Extract paper metadata from HTML content."""
        self.logger.debug("Parsing HTML content")
        soup = BeautifulSoup(content, "html.parser")
        papers = []

        # Find all paper entries (h3 tags)
        title_links = soup.find_all("h3")
        self.logger.debug(f"Found {len(title_links)} title links")

        for h3 in title_links:
            link = h3.find("a")
            if not link:  # Skip h3s without links
                continue

            # Get title and URL from the link
            title = link.get_text(strip=True)
            url = link.get("href", "")

            self.logger.debug(f"\nProcessing paper: {title}")
            self.logger.debug(f"Raw URL from href: {url}")

            # Clean up Google Scholar redirect URL to get actual paper URL
            if url:
                try:
                    # Parse the URL and extract the 'url' parameter
                    parsed = urllib.parse.urlparse(url)
                    self.logger.debug(f"Parsed URL parts: {parsed}")

                    params = urllib.parse.parse_qs(parsed.query)
                    self.logger.debug(f"Parsed query parameters: {params}")

                    if "url" in params:
                        url = params["url"][0]  # Get the first URL if multiple exist
                        url = urllib.parse.unquote(url)  # Decode the URL
                        self.logger.debug(f"Extracted and decoded URL: {url}")
                    else:
                        self.logger.debug("No 'url' parameter found in query string")
                        url = ""
                except Exception as e:
                    self.logger.error(f"Error extracting URL: {e}")
                    self.logger.error(f"URL that caused error: {url}")
                    url = ""

            self.logger.debug(f"Final URL: {url}")

            # Get the next elements
            current = h3
            authors = ""
            abstract = ""

            # Look for the next 2 divs (authors and abstract)
            for i in range(2):
                current = current.find_next("div")
                if current:
                    text = current.get_text(strip=True)
                    if text:
                        if i == 0:  # First div is authors
                            authors = text
                        else:  # Second div is abstract
                            abstract = text

            # Only add if we found required content
            if authors:  # At minimum we need authors
                paper = Paper(title=title, authors=authors, abstract=abstract, url=url)
                papers.append(paper)

        self.logger.debug(f"\nExtracted {len(papers)} papers total")
        return papers

    def extract_and_classify_papers(self, email_message):
        """Extract papers from email and classify them according to research topics."""
        self.logger.info("\n=== Starting paper extraction and classification ===")

        if not hasattr(self, "processed_papers"):
            self.processed_papers = []

        content = self._get_email_content(email_message)
        papers = self._extract_paper_metadata(content)
        if not papers:
            self.logger.info("No papers found in email")
            return []

        # Filter out duplicates before processing
        filtered_papers = []
        for paper in papers:
            title = paper.title.lower().strip()
            url = paper.url.lower().strip()

            # Skip if we've seen this title or URL before
            if title in self._processed_titles:
                self.logger.info(f"Skipping duplicate paper (by title): {paper.title}")
                continue
            if url and url in self._processed_urls:
                self.logger.info(f"Skipping duplicate paper (by URL): {paper.title}")
                continue

            # Add to tracking sets
            self._processed_titles.add(title)
            if url:
                self._processed_urls.add(url)

            filtered_papers.append(paper)

        self.logger.info(
            f"Found {len(papers)} papers, {len(filtered_papers)} after duplicate filtering"
        )

        results = []
        for paper in filtered_papers:
            prompt = self._generate_classification_prompt(paper)
            self.logger.debug(f"Generated prompt:\n{prompt}")
            try:
                response = self.pplx_client.chat.completions.create(
                    model="llama-3.1-sonar-small-128k-online",
                    messages=[{"role": "user", "content": prompt}],
                )

                content = response.choices[0].message.content.strip()
                self.logger.info(f"LLM response:\n{content}")

                # Clean up JSON from markdown if present
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()

                # More careful JSON cleanup
                import re

                lines = content.split("\n")
                cleaned_lines = []
                in_string = False

                for line in lines:
                    # Process each character to handle strings correctly
                    cleaned_line = ""
                    i = 0
                    while i < len(line):
                        char = line[i]

                        # Handle escape sequences in strings
                        if char == "\\" and i + 1 < len(line):
                            cleaned_line += char + line[i + 1]
                            i += 2
                            continue

                        # Track string boundaries
                        if char == '"':
                            in_string = not in_string

                        # Only remove comments when not in a string
                        if (
                            not in_string
                            and char == "/"
                            and i + 1 < len(line)
                            and line[i + 1] == "/"
                        ):
                            break  # Stop processing this line at comment

                        cleaned_line += char
                        i += 1

                    # Add non-empty lines
                    if cleaned_line.strip():
                        cleaned_lines.append(cleaned_line)

                content = "\n".join(cleaned_lines)

                # Remove trailing commas before closing braces/brackets
                content = re.sub(r",(\s*[}\]])", r"\1", content)

                # Additional validation before parsing
                if not content:
                    self.logger.error("Empty content after cleanup")
                    continue

                try:
                    parsed_data = json.loads(content)
                    # Handle both single object and array responses
                    paper_data = parsed_data[0] if isinstance(parsed_data, list) else parsed_data

                except (json.JSONDecodeError, IndexError) as e:
                    self.logger.error(f"JSON parsing error: {e}")
                    self.logger.error(f"Failed content: {repr(content)}")
                    continue

                # Create Paper object using original paper data
                paper_obj = Paper(
                    title=paper.title,
                    authors=paper_data["authors"],
                    abstract=paper.abstract,
                    venue=paper_data.get("venue", ""),
                    url=paper_data.get("link", ""),
                )

                # Match topics exactly as defined in the prompt
                relevant_topics = [
                    topic
                    for topic in self.topics
                    if any(
                        t.strip().lower() == topic.name.lower()
                        for t in paper_data.get("relevant_topics", [])
                    )
                ]

                # Also check if any topic appears in the list with its full description
                relevant_topics.extend(
                    [
                        topic
                        for topic in self.topics
                        if any(
                            t.strip().lower()
                            == f"{topic.name.lower()}: {topic.description.lower()}"
                            for t in paper_data.get("relevant_topics", [])
                        )
                    ]
                )

                # Remove duplicates while preserving order
                seen = set()
                relevant_topics = [
                    x for x in relevant_topics if not (x.name in seen or seen.add(x.name))
                ]

                results.append((paper_obj, relevant_topics))
                self.logger.info(f"Successfully processed paper: {paper_obj.title}")
                self.logger.info(f"Matched topics: {[t.name for t in relevant_topics]}")

                self.processed_papers.append((paper_obj, relevant_topics))

            except Exception as e:
                self.logger.error(f"Error processing paper: {str(e)}")
                continue

            self.logger.debug(f"Processing results: {results}")

        return results

    def _build_email_search_query(self):
        """Build IMAP search query based on search criteria."""
        from datetime import datetime, timedelta
        with open("search_criteria.yml", "r") as f:
            criteria = yaml.safe_load(f)["email_filter"]

        # Base query parts
        query_parts = [f'FROM "{criteria["from"]}"', f'SUBJECT "{criteria["subject"]}"']

        # Add time window
        if criteria["time_window"]:

            # Parse time window
            amount = int(criteria["time_window"][:-1])
            unit = criteria["time_window"][-1]

            if unit == "D":
                delta = timedelta(days=amount)
            elif unit == "W":
                delta = timedelta(weeks=amount)
            elif unit == "M":
                delta = timedelta(days=amount * 30)

            # Calculate date range
            since_date = datetime.now() - delta
            date_str = since_date.strftime("%d-%b-%Y")
            query_parts.append(f'SINCE "{date_str}"')

        return " ".join(query_parts)

    def run(self, folder=None):
        """Main execution loop."""
        try:
            folder_name = folder or self.config['email'].get('folder', 'INBOX')

            if ' ' in folder_name and not folder_name.startswith('"'):
                folder_name = f'"{folder_name}"'
            self.logger.info(f"Attempting to access folder: {folder_name}")

            # First connect to Gmail
            mail = self.connect_to_gmail()
            # select the folder
            status, folder_info = mail.select(folder_name)
            if status != "OK":
                self.logger.error(f"Failed to select folder {folder_name}: {folder_info}")
                return
            # Build and execute search query
            search_query = self._build_email_search_query()
            self.logger.info(f"Using search query: {search_query}")
            status, message_numbers = mail.search(None, search_query)
            if status != "OK":
                self.logger.error(f"Search failed: {message_numbers}")
                return

            self.logger.info(f"Searching in folder: {folder}")

            processed_papers = False
            for num in message_numbers[0].split():
                _, msg_data = mail.fetch(num, "(RFC822)")
                email_body = msg_data[0][1]
                email_message = email.message_from_bytes(email_body)

                # Extract and classify papers in one step
                paper_results = self.extract_and_classify_papers(email_message)

                # Send notifications using slack_notifier directly
                if paper_results:
                    processed_papers = True
                    if self.slack_notifier:
                        self.slack_notifier.notify_matches(paper_results)

            # Send weekly update if papers were processed
            if processed_papers:
                self.send_weekly_update_notification()

            mail.logout()

        except Exception as e:
            self.logger.error(f"Error in main execution: {e}")
            raise

    def list_folders(self):
        """List all available folders in the Gmail account."""
        try:
            mail = self.connect_to_gmail()
            _, folders = mail.list()
            for folder in folders:
                folder_name = folder.decode().split('"/"')[-1].strip('"')
                self.logger.info(f"Found folder: {folder_name}")
            mail.logout()
            return folders
        except Exception as e:
            self.logger.error(f"Error listing folders: {e}")
            raise

    def _extract_papers_from_html(self, html):
        """Extract papers as plain text, just like reading an email."""
        self.logger.debug("Parsing HTML content")
        soup = BeautifulSoup(html, "html.parser")
        papers = []

        # Find all paper entries (h3 tags)
        title_links = soup.find_all("h3")
        self.logger.debug(f"Found {len(title_links)} title links")

        for h3 in title_links:
            if not h3.find("a"):  # Skip h3s without links
                continue

            # Get all text content from h3 (includes PDF tag if present)
            title = h3.get_text(strip=True)
            self.logger.debug(f"\nFound paper title: {title}")

            # Get the next elements
            current = h3
            paper_text = [title]  # Start with title

            # Look for the next 2 divs (authors and abstract)
            for _ in range(2):
                current = current.find_next("div")
                if current:
                    text = current.get_text(strip=True)
                    if text:
                        paper_text.append(text)

            # Only add if we found some content
            if len(paper_text) > 1:  # At least title and one more element
                papers.append("\n".join(paper_text))

        self.logger.debug(f"\nExtracted {len(papers)} papers total")
        return "\n\n".join(papers)

    def _get_email_content(self, email_message):
        """Extract HTML content from email message."""
        self.logger.debug("Email structure:")
        self.logger.debug(f"Is multipart: {email_message.is_multipart()}")
        self.logger.debug(f"Content type: {email_message.get_content_type()}")

        content = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/html":
                    self.logger.debug("Found HTML part in multipart message")
                    content = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    break
        else:
            self.logger.debug("Processing single-part message")
            payload = email_message.get_payload(decode=True)
            if payload:
                content = payload.decode("utf-8", errors="replace")

        self.logger.debug(f"Extracted content length: {len(content)}")
        if len(content) > 0:
            self.logger.debug(f"First 200 chars of content: {content[:200]}")

        return content

    def _extract_text_from_html(self, html):
        """Extract readable text from HTML content."""
        try:
            # Parse HTML
            soup = BeautifulSoup(html, "html.parser")

            # Find the paper title and details
            title_link = soup.find("a", class_="gse_alrt_title")
            venue_div = soup.find("div", style="color:#006621")
            abstract_div = soup.find("div", class_="gse_alrt_sni")

            # Extract text
            parts = []
            if title_link:
                parts.append(title_link.get_text())
            if venue_div:
                parts.append(venue_div.get_text())
            if abstract_div:
                parts.append(abstract_div.get_text())

            # Join with newlines
            return "\n".join(parts)

        except Exception as e:
            self.logger.error(f"Error parsing HTML: {str(e)}")
            # Fall back to basic HTML to text conversion
            h = html2text.HTML2Text()
            h.ignore_links = True
            return h.handle(html)

    def _format_research_topics(self):
        """Format research topics for the prompt."""
        topics = []
        for topic in self.config["research_topics"]:
            topics.append(f"- {topic['name']}: {topic['description']}")
        return "\n".join(topics)

    def _generate_classification_prompt(self, paper):
        """Generate prompt for paper classification."""
        # First create the topics list
        topics_list = self._format_research_topics()

        # Create the prompt with proper escaping of curly braces
        prompt = f"""Below is a paper from Google Scholar. Extract metadata and classify it:

Title: {paper.title}
Authors: {paper.authors}
Abstract: {paper.abstract}

Return a SINGLE JSON object with ALL these required fields:
{{
    "title": "the paper title",
    "authors": ["list", "of", "authors"],
    "abstract": "the paper abstract",
    "venue": "use these rules:
      - 'arXiv preprint' if author line has 'arXiv'
      - 'Patent Application' if author line has 'Patent'
      - text between dash and year for published papers
      - 'NOT-FOUND' otherwise",
    "link": "the paper URL",
    "relevant_topics": []  // ONLY choose from these topics:
{topics_list}
}}

CRITICAL RULES:
1. Return ONLY ONE JSON object, NOT an array of objects
2. ALL fields (title, authors, abstract, venue, link, relevant_topics) are REQUIRED
3. For relevant_topics, ONLY include topics from the list above - do not create new topics
4. For LLM/VLM papers:
   - Include ANY paper that uses or studies language/vision-language models
   - Include papers about LLM/VLM applications, systems, or benchmarks
   - Include papers about model serving, deployment, or optimization
   - When in doubt about LLM/VLM relevance, include it
5. Leave relevant_topics as empty list if no topics match
6. Do not include any comments or signs in the JSON object

The response must be valid JSON with ALL required fields."""

        return prompt

    def _load_research_topics(self):
        """Load research topics from config."""
        topics = [ResearchTopic(**topic_config) for topic_config in self.config["research_topics"]]
        for topic in topics:
            self.logger.debug(f"Loaded topic from config: {topic}")
        return topics

    def send_weekly_update_notification(self):
        """Send notifications to systems channels about weekly paper updates."""

        def format_topic_summary(papers_by_topic):
            summary = []
            for topic, papers in papers_by_topic.items():
                paper_list = [f"• {paper.title}" for paper in papers]
                summary.append(f"*{topic}*:\n" + "\n".join(paper_list))
            return "\n\n".join(summary)

        # Get channel-topic mapping from config
        channel_topics = self.config["slack"].get("channel_topics", {})

        # Get papers processed in the last week
        if hasattr(self, "processed_papers"):
            # Organize papers by topic
            papers_by_topic = {}
            for paper, topics in self.processed_papers:
                for topic in topics:
                    if topic.name not in papers_by_topic:
                        papers_by_topic[topic.name] = []
                    papers_by_topic[topic.name].append(paper)

            # Send to each channel with relevant topics only
            for channel, relevant_topics in channel_topics.items():
                channel_papers = {
                    topic: papers
                    for topic, papers in papers_by_topic.items()
                    if topic in relevant_topics
                }

                if channel_papers:
                    message = (
                        "📚 *Weekly Scholar Scout Update*\n"
                        f"Here are the relevant papers for #{channel} this week:\n\n"
                        f"{format_topic_summary(channel_papers)}"
                    )
                else:
                    message = (
                        "📚 *Weekly Scholar Scout Update*\n"
                        f"No relevant papers were found for #{channel} this week."
                    )

                try:
                    self.slack_notifier.send_message(channel=f"#{channel}", message=message)
                    self.logger.info(f"Sent weekly update notification to #{channel}")
                except Exception as e:
                    self.logger.error(f"Failed to send weekly update to #{channel}: {str(e)}")
        else:
            self.logger.info("No papers were processed this week")


if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    # Load environment variables
    load_dotenv()

    # Load config and print relevant parts (without sensitive data)
    logger.info("Loading configuration...")
    classifier = ScholarClassifier(config_file="config.yml")

    # Print config structure (without passwords)
    safe_config = classifier.config.copy()
    safe_config["email"]["password"] = f"<{len(safe_config['email']['password'])} chars>"
    logger.debug(f"Loaded config: {safe_config}")

    # Run the classifier
    classifier.run()
