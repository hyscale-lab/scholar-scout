
"""Generative paper classification using Gemini."""

import json
import logging
import random
import time

from google.genai import errors as genai_errors

import httpx
from google import genai
from google.genai import types
from config import AppConfig

logger = logging.getLogger(__name__)


class GeminiGenerativeClassifier:
    def __init__(self, config: AppConfig, gemini_client: genai.Client):
        self.client = gemini_client
        self.model = config.gemini.gen_ai_model

        # Preserve Conference Scout's existing research taxonomy.
        self.topics = {
            topic.name: {
                "description": topic.description,
                "keywords": topic.keywords,
                "taxonomy": topic.taxonomy,
            }
            for topic in config.research_topics
        }

        if not self.topics:
            raise ValueError("No research topics configured.")

        self.generation_config = types.GenerateContentConfig(  
            system_instruction=(
                "You are an computer science research paper classifier. "
                "Classify each paper using its title, abstract, and the supplied "
                "research-topic definitions. Focus on the paper's actual technical "
                "contribution, not merely its keywords, application domain, or the "
                "technologies it uses. "
                "\n\n"
                "A paper may receive multiple categories, but assign each category "
                "only when the contribution substantively satisfies its definition. "
                "Apply all stated exclusions strictly. Do not force a category when "
                "the evidence is insufficient. Use only evidence supported by the "
                "title and abstract. "
                "\n\n"
                "CATEGORY BOUNDARIES: "
                "LLM Inference requires a contribution directly concerning LLM "
                "inference or serving execution; using an LLM or training a model "
                "alone is insufficient. "
                "Serverless Computing requires the serverless or FaaS execution model "
                "to be central; generic cloud, container, or distributed-systems work "
                "does not qualify automatically. "
                "Agentic Execution Environment requires a contribution to the runtime, "
                "execution substrate, tools, isolation, state, orchestration, or resource "
                "management of AI agents; improving agent accuracy, planning, or an "
                "agent application alone is insufficient. "
                "Video & Embodied Intelligence requires an in-scope visual, video, "
                "VLM, world-model, VLA, or embodied workload AND a substantive systems "
                "or execution-efficiency contribution; capability or accuracy gains "
                "alone are insufficient. "
                "Sustainable Computing requires explicit energy, power, carbon, or "
                "environmental evaluation; lower latency, FLOPs, memory, monetary "
                "cost, or GPU count alone is insufficient. "
                "\n\n"
                "Multiple labels are appropriate only when the paper independently "
                "satisfies multiple category definitions. Do not infer contributions "
                "that the abstract does not establish. If no category applies, return "
                "an empty categories list. "
                "\n\n"
                "Return only valid JSON with exactly one field, categories, whose value "
                "is an array of zero or more exact category names from the supplied "
                "taxonomy. Do not include explanations, confidence scores, markdown, "
                "or additional fields. "
                'Example: {"categories": ["LLM Inference"]}. '
                'If no category applies, return {"categories": []}.'
            ),
            response_mime_type="application/json",
            max_output_tokens=1024,
        )

    def classify(self, title: str, abstract: str) -> list[str]:
        """Return the validated topic labels for one paper."""
        title = (title or "").strip()
        abstract = (abstract or "").strip()

        if not title and not abstract:
            return []

        contents = json.dumps(
            {
                "title": title,
                "abstract": abstract,
                "topics": self.topics,
            },
            ensure_ascii=False,
        )

        # Retry transient service errors; do not retry invalid requests/auth errors.
        max_attempts = 5
        retryable_statuses = {408, 429, 500, 502, 503, 504}

        for attempt in range(1, max_attempts + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=self.generation_config,
                )
                break
            except genai_errors.APIError as exc:
                status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
                if status not in retryable_statuses or attempt == max_attempts:
                    raise
                delay = min(2 ** (attempt - 1), 30) + random.uniform(0, 1)
                logger.warning(
                    "Transient Gemini API error (status=%s) on attempt %d/%d; "
                    "retrying in %.1fs",
                    status, attempt, max_attempts, delay,
                )
                time.sleep(delay)
            except (TimeoutError, ConnectionError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == max_attempts:
                    raise
                delay = min(2 ** (attempt - 1), 30) + random.uniform(0, 1)
                logger.warning(
                    "Transient network/timeout error on attempt %d/%d: %s; "
                    "retrying in %.1fs",
                    attempt, max_attempts, exc, delay,
                )
                time.sleep(delay)

        if not response.text:
            raise ValueError("Gemini returned an empty classification response.")

        data = json.loads(response.text)

        if not isinstance(data, dict) or set(data) != {"categories"}:
            raise ValueError("Invalid classification response structure.")

        categories = data["categories"]

        if not isinstance(categories, list):
            raise ValueError("'categories' must be a list.")

        if any(
            not isinstance(category, str) or category not in self.topics
            for category in categories
        ):
            raise ValueError("Gemini returned an unknown research category.")

        if len(categories) != len(set(categories)):
            raise ValueError("Gemini returned duplicate research categories.")

        logger.info("Classified %r into %s", title[:60], categories)
        return categories
