"""
Core logic for the Scholar Scout application.

This module contains the main classifier class that orchestrates the entire
process of fetching emails, parsing them, classifying papers, and sending
notifications.
"""

import json
import logging
import re
import urllib.parse
from email.message import Message
from typing import List, Tuple

from bs4 import BeautifulSoup, Tag
from openai import OpenAI

from .config import AppConfig, ResearchTopic
from .models import Paper

logger = logging.getLogger(__name__)


class ScholarClassifier:
    """The main classifier for processing Google Scholar alerts."""

    def __init__(self, config: AppConfig):
        """
        Initialize the classifier with the application configuration.

        Args:
            config: The application configuration.
        """
        self.config = config
        self.pplx_client = OpenAI(
            api_key=config.perplexity.api_key,
            base_url="https://api.perplexity.ai",
        )
        self._processed_titles = set()
        self._processed_urls = set()

    def _get_email_content(self, email_message: Message) -> str:
        """Extract the HTML content from an email message."""
        content = ""
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == "text/html":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        content = payload.decode("utf-8", errors="replace")
                        break
        else:
            payload = email_message.get_payload(decode=True)
            if isinstance(payload, bytes):
                content = payload.decode("utf-8", errors="replace")
        return content

    def _extract_paper_metadata(self, content: str) -> List[Paper]:
        """Extract paper metadata from the HTML content of an email."""
        soup = BeautifulSoup(content, "html.parser")
        papers = []

        # Each paper is in an h3 tag
        for h3 in soup.find_all("h3"):
            if not isinstance(h3, Tag):
                continue

            # The link contains the title and URL
            link = h3.find("a")
            if not isinstance(link, Tag):
                continue

            title = link.get_text(strip=True)
            url_attr = link.get("href")
            url = str(url_attr) if url_attr else ""

            # Clean up the URL to get the direct link
            if url:
                try:
                    parsed = urllib.parse.urlparse(url)
                    params = urllib.parse.parse_qs(parsed.query)
                    if "url" in params:
                        url = urllib.parse.unquote(params["url"][0])
                except Exception as e:
                    logger.error(f"Error extracting URL: {e}")
                    url = ""

            # The authors and abstract are in the next two divs
            authors, abstract = "", ""
            current: Tag = h3
            for i in range(2):
                current_div = current.find_next("div")
                if isinstance(current_div, Tag):
                    current = current_div
                    text = current.get_text(strip=True)
                    if text:
                        if i == 0:
                            authors = text
                        else:
                            abstract = text
                else:
                    break

            if authors:
                papers.append(Paper(title=title, authors=[authors], abstract=abstract, url=url))
        return papers

    def _generate_classification_prompt(self, paper: Paper) -> str:
        """Generate the prompt for classifying a paper."""
        topics_list = "\n".join(
            f"- {topic.name}: {topic.description}" for topic in self.config.research_topics
        )
        return f"""
        Below is a paper from Google Scholar. Extract metadata and classify it:

        Title: {paper.title}
        Authors: {', '.join(paper.authors)}
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

        The response must be valid JSON with ALL required fields.
        """

    def classify_papers(
        self, email_messages: List[Message]
    ) -> List[Tuple[Paper, List[ResearchTopic]]]:
        """
        Classify papers from a list of email messages.

        Args:
            email_messages: A list of email messages to process.

        Returns:
            A list of tuples, each containing a paper and a list of matched
            research topics.
        """
        all_results = []
        for email_message in email_messages:
            content = self._get_email_content(email_message)
            papers = self._extract_paper_metadata(content)

            filtered_papers = []
            for paper in papers:
                title = paper.title.lower().strip()
                url = paper.url.lower().strip()

                if title in self._processed_titles or (url and url in self._processed_urls):
                    logger.info(f"Skipping duplicate paper: {paper.title}")
                    continue
                if any(word in title for word in ["patent", "apparatus", "method and system"]):
                    logger.info(f"Skipping patent: {paper.title}")
                    continue

                self._processed_titles.add(title)
                if url:
                    self._processed_urls.add(url)
                filtered_papers.append(paper)

            logger.info(
                f"Found {len(papers)} papers, "
                f"{len(filtered_papers)} after filtering duplicates and patents"
            )

            for paper in filtered_papers:
                prompt = self._generate_classification_prompt(paper)
                try:
                    response = self.pplx_client.chat.completions.create(
                        model=self.config.perplexity.model,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    
                    content = response.choices[0].message.content
                    if not content:
                        logger.error("Received empty content from Perplexity AI.")
                        continue
                    content = content.strip()

                    if "```json" in content:
                        content = content.split("```json")[1].split("```")[0].strip()
                    elif "```" in content:
                        content = content.split("```")[1].split("```")[0].strip()

                    content = re.sub(r",(\s*[}\]])", r"\1", content)
                    parsed_data = json.loads(content)
                    paper_data = (
                        parsed_data[0] if isinstance(parsed_data, list) else parsed_data
                    )

                    paper_obj = Paper(
                        title=paper.title,
                        authors=paper_data["authors"],
                        abstract=paper.abstract,
                        venue=paper_data.get("venue", ""),
                        url=paper.url,
                    )

                    paper_relevant_topics = paper_data.get("relevant_topics", [])
                    relevant_topics = [
                        topic
                        for topic in self.config.research_topics
                        if any(
                            isinstance(t, str) and t.strip().lower() == topic.name.lower()
                            for t in paper_relevant_topics
                        )
                    ]
                    all_results.append((paper_obj, relevant_topics))
                    logger.info(f"Successfully processed paper: {paper_obj.title}")
                except Exception as e:
                    logger.error(f"Error processing paper: {e}")
        return all_results
