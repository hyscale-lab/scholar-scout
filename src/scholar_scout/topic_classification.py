"""Gemini topic decisions with verified abstract evidence."""

import json
from pathlib import Path
import re
import unicodedata

from google.genai import types


def normalize_quote(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def validate_decisions(text, abstract, topic_names):
    data = json.loads(text)
    if not isinstance(data, dict) or set(data) != {"decisions"}:
        raise ValueError("Invalid decision object")
    rows = data["decisions"]
    if not isinstance(rows, list) or len(rows) != len(topic_names):
        raise ValueError("Missing topic decisions")
    decisions = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"topic", "decision", "evidence", "reason"}:
            raise ValueError("Invalid decision fields")
        name = row["topic"]
        if not isinstance(name, str) or name not in topic_names or name in decisions:
            raise ValueError("Invalid topic name")
        if row["decision"] not in ("match", "no_match"):
            raise ValueError("Invalid decision")
        evidence = row["evidence"]
        if not isinstance(row["reason"], str) or not isinstance(evidence, list):
            raise ValueError("Invalid evidence or reason")
        if row["decision"] == "match" and not evidence:
            raise ValueError("Missing match evidence")
        for quote in evidence:
            if (
                not isinstance(quote, str)
                or not quote.strip()
                or normalize_quote(quote) not in normalize_quote(abstract)
            ):
                raise ValueError("Unverified quotation")
        decisions[name] = row
    return decisions


class TopicClassifier:
    def __init__(self, client, model, topics):
        self.client, self.model = client, model
        directory = Path(__file__).resolve().parent
        policy_path = directory.parent.parent / "config/topic_policy.json"
        policies = json.loads(policy_path.read_text())
        if not isinstance(policies, dict) or any(
            not name.strip() or not isinstance(scope, str) or not scope.strip()
            for name, scope in policies.items()
        ):
            raise ValueError("Policies require nonempty names and scopes")
        if (
            not topics
            or any(not t.name.strip() for t in topics)
            or len({t.name for t in topics}) != len(topics)
        ):
            raise ValueError("Topic names must be nonempty and unique")
        missing = [t.name for t in topics if t.name not in policies]
        if missing:
            raise ValueError("Topics missing from topic_policy.json: " + ", ".join(missing))
        self.topics = {t.name: t for t in topics}
        scopes = {name: policies[name] for name in self.topics}
        prompt = (directory / "classification_prompt.txt").read_text()
        self.prompt = prompt + "\nTOPICS:\n" + json.dumps(scopes, ensure_ascii=False)
        self.generation_config = types.GenerateContentConfig(
            system_instruction=self.prompt,
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
            max_output_tokens=4096,
        )

    def classify(self, paper):
        contents = json.dumps({"title": paper.title, "abstract": paper.abstract})
        for attempt in range(2):
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=self.generation_config,
            )
            try:
                if (
                    not response.candidates
                    or response.candidates[0].finish_reason != types.FinishReason.STOP
                ):
                    raise ValueError("Incomplete model response")
                return validate_decisions(response.text, paper.abstract, self.topics)
            except (ValueError, TypeError):
                if attempt:
                    raise
