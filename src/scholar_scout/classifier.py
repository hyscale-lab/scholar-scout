"""Resolve Scholar abstracts before classifying their systems contributions."""

import hashlib
import json
import logging
from pathlib import Path
import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup, Tag
from google import genai
from google.genai import types

from .abstract_sources import AbstractResolver, atomic_json, normalized
from .config import AppConfig
from .models import Paper
from .topic_classification import TopicClassifier

logger = logging.getLogger(__name__)


class ScholarClassifier:
    def __init__(self, config: AppConfig):
        self.config = config
        options = {
            "http_options": types.HttpOptions(
                timeout=90000, retry_options=types.HttpRetryOptions(attempts=1)
            )
        }
        if isinstance(config.gemini.api_key, dict):
            from google.oauth2 import service_account

            credentials = service_account.Credentials.from_service_account_info(
                config.gemini.api_key, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            options.update(
                vertexai=True,
                project=credentials.project_id,
                location="global",
                credentials=credentials,
            )
        else:
            options["api_key"] = config.gemini.api_key
        self.gemini_client = genai.Client(**options)
        self.topic_classifier = TopicClassifier(
            self.gemini_client, config.gemini.gen_ai_model, config.research_topics
        )
        self.state_dir = Path(config.state_dir)
        self.resolver = AbstractResolver(self.state_dir / "abstracts")
        self.pending_path = self.state_dir / "pending-papers.json"
        self.pending = (
            json.loads(self.pending_path.read_text()) if self.pending_path.exists() else {}
        )
        self.diagnostics = []

    def _get_email_content(self, message):
        parts = message.walk() if message.is_multipart() else [message]
        for part in parts:
            if part.get_content_type() == "text/html":
                payload = part.get_payload(decode=True)
                if isinstance(payload, bytes):
                    charset = part.get_content_charset() or "utf-8"
                    try:
                        return payload.decode(charset, errors="replace")
                    except LookupError:
                        return payload.decode("utf-8", errors="replace")
        return ""

    def _extract_paper_metadata(self, content):
        papers = []
        for heading in BeautifulSoup(content, "html.parser").find_all("h3"):
            link = heading.find("a", href=True)
            if not link or not link.get_text(" ", strip=True):
                continue
            title = link.get_text(" ", strip=True)
            url = link["href"]
            for _ in range(3):
                parsed = urlparse(url)
                targets = parse_qs(parsed.query).get("url")
                if (
                    parsed.hostname
                    not in ("scholar.google.com", "scholar.google.com.hk", "scholar.google.cn")
                    or not targets
                ):
                    break
                url = targets[0]
            if urlparse(url).scheme not in ("http", "https"):
                url = ""
            metadata, snippet = "", ""
            for sibling in heading.next_siblings:
                if not isinstance(sibling, Tag):
                    continue
                if sibling.name == "h3":
                    break
                if sibling.name == "div":
                    text = sibling.get_text(" ", strip=True)
                    if not metadata:
                        metadata = text
                    elif not snippet:
                        snippet = text
                if "gse_alrt_sni" in sibling.get("class", []):
                    snippet = sibling.get_text(" ", strip=True)
            author_line = re.split(r"\s[-–—]\s", metadata, maxsplit=1)[0]
            authors = [a.strip(" .…") for a in author_line.split(",") if a.strip(" .…")]
            papers.append(Paper(title=title, authors=authors, abstract=snippet, url=url))
        return papers

    @staticmethod
    def _merge_candidate(candidate: dict, paper: Paper) -> None:
        urls = dict.fromkeys([candidate.get("url", ""), *candidate.get("urls", []), paper.url])
        candidate["urls"] = [url for url in urls if url]
        if not candidate.get("url"):
            candidate["url"] = paper.url
        candidate["authors"] = list(dict.fromkeys([*candidate.get("authors", []), *paper.authors]))
        if len(paper.abstract) > len(candidate.get("abstract", "")):
            candidate["abstract"] = paper.abstract
        if not candidate.get("venue"):
            candidate["venue"] = paper.venue

    def classify_papers(self, email_messages):
        candidates = {key: row["paper"] for key, row in self.pending.items()}
        seen_urls = {
            url
            for candidate in candidates.values()
            for url in [candidate.get("url", ""), *candidate.get("urls", [])]
            if url
        }
        for message in email_messages:
            for paper in self._extract_paper_metadata(self._get_email_content(message)):
                key = hashlib.sha256(normalized(paper.title).encode()).hexdigest()[:20]
                if key in candidates:
                    self._merge_candidate(candidates[key], paper)
                elif paper.url and paper.url in seen_urls:
                    continue
                else:
                    candidates[key] = dict(paper.model_dump(), id=key)
                    self._merge_candidate(candidates[key], paper)
                if paper.url:
                    seen_urls.add(paper.url)
        results = []
        self.diagnostics = []
        for key, candidate in candidates.items():
            status, decisions, notes = "pending_abstract", {}, []
            try:
                record, notes = self.resolver.resolve(candidate)
                if record:
                    paper = Paper(
                        **{
                            name: record.get(name, candidate.get(name, ""))
                            for name in Paper.model_fields
                        }
                    )
                    status = "pending_model"
                    decisions = self.topic_classifier.classify(paper)
                    matches = [
                        self.topic_classifier.topics[c]
                        for c, d in decisions.items()
                        if d["decision"] == "match"
                    ]
                    status = "matched" if matches else "no_match"
                    results.append((paper, matches))
            except Exception as exc:
                logger.warning("Paper %s remains pending (%s)", key, type(exc).__name__)
                notes.append(type(exc).__name__)
            if status.startswith("pending"):
                self.pending[key] = {"paper": candidate, "status": status}
            else:
                self.pending.pop(key, None)
            atomic_json(self.pending_path, self.pending)
            self.diagnostics.append(
                {"id": key, "status": status, "decisions": decisions, "notes": notes}
            )
        atomic_json(self.state_dir / "last-run.json", self.diagnostics)
        return results
