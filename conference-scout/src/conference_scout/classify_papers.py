#!/usr/bin/env python3
"""
Paper Classifier — Reads enriched + agent-enriched papers, classifies via Gemini embeddings.

Combines papers_enriched.json and papers_agent_enriched.json (or falls back to
papers_unenriched.json), runs embedding-based classification on each paper's
title + abstract, and outputs classified_papers.json.

Usage (standalone):
    python classify_papers.py
"""

import json
import logging
import os
import sys
from collections import Counter

from google import genai

from config import AppConfig, load_config
from embedding_classification import GeminiEmbeddingSetup

logger = logging.getLogger(__name__)


def load_papers(filepath: str) -> list:
    """Load papers from a JSON file. Returns empty list if file not found."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            papers = json.load(f)
        logger.info(f"Loaded {len(papers)} papers from {filepath}")
        return papers
    except FileNotFoundError:
        logger.warning(f"File not found: {filepath} — skipping")
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {filepath}: {e}")
        return []


def validate_agent_enriched(filepath: str) -> list:
    """
    Load agent-enriched papers with format validation.
    Must be a JSON array of objects, each with at least "key" and "title".
    Skips malformed entries. Returns empty list if format is totally wrong.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Agent-enriched file invalid or missing ({filepath}): {e}")
        return []

    # Must be a list (not {"papers": [...]})
    if not isinstance(data, list):
        logger.warning(
            f"Agent-enriched file has wrong format (expected JSON array, got {type(data).__name__}). "
            f"Skipping — will fall back to unenriched."
        )
        return []

    # Validate each entry — must have at minimum "key" and "title"
    valid = []
    skipped = 0
    for entry in data:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        if "key" not in entry or "title" not in entry:
            skipped += 1
            continue
        valid.append(entry)

    if skipped > 0:
        logger.warning(f"Skipped {skipped} malformed entries from {filepath}")

    logger.info(f"Loaded {len(valid)} valid papers from {filepath}")
    return valid


def build_classification_text(paper: dict) -> str:
    """Build the text to classify from title + abstract."""
    title = paper.get("title", "").strip()
    abstract = paper.get("abstract", "").strip()

    if abstract:
        return f"{title} {abstract}"
    else:
        return title


def classify_all_papers(papers: list, classifier: GeminiEmbeddingSetup,
                        minimal_output: bool = True) -> list:
    """Classify all papers and return the final output list."""
    results = []
    total = len(papers)

    for i, paper in enumerate(papers):
        title = paper.get("title", "")
        title_short = title[:60]
        logger.info(f"[{i+1}/{total}] Classifying: {title_short}...")

        # Build text for embedding
        text = build_classification_text(paper)

        # Classify using embeddings
        categories = classifier.gemini_embedding_classify(text)

        if not categories:
            categories = ["Others"]

        # Build output entry
        authors = paper.get("authors", [])
        if isinstance(authors, list):
            authors_str = ", ".join(authors)
        else:
            authors_str = str(authors)

        result = {
            "paper_title": title,
            "authors": authors_str,
            "conference": paper.get("venue", ""),
            "url": paper.get("ee", ""),
            "category": categories,
        }

        # Include extra fields if not minimal output
        if not minimal_output:
            if paper.get("key"):
                result["key"] = paper["key"]
            if paper.get("mdate"):
                result["mdate"] = paper["mdate"]
            if paper.get("dblp_url"):
                result["dblp_url"] = paper["dblp_url"]
            if paper.get("abstract"):
                result["abstract"] = paper["abstract"]

        logger.info(f"  → {categories}")
        results.append(result)

    return results


def run_classification(config: AppConfig,
                       enriched_file: str,
                       agent_enriched_file: str,
                       unenriched_file: str,
                       output_file: str,
                       minimal_output: bool = True) -> None:
    """
    Run the classification pipeline.

    Args:
        config: Full application config.
        enriched_file: Path to papers_enriched.json.
        agent_enriched_file: Path to papers_agent_enriched.json.
        unenriched_file: Path to papers_unenriched.json (fallback).
        output_file: Path to write classified_papers.json.
        minimal_output: If True, output only essential fields.
    """
    # Initialize Gemini client — supports both API key (string) and service account (dict)
    api_key = config.gemini.api_key

    if isinstance(api_key, dict):
        # Service account credentials (Vertex AI)
        from google.oauth2 import service_account
        credentials = service_account.Credentials.from_service_account_info(
            api_key, scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        client = genai.Client(
            vertexai=True,
            project=credentials.project_id,
            location="global",
            credentials=credentials,
        )
    else:
        # API key (string) — resolve from env if placeholder or empty
        if not api_key or api_key.startswith("${"):
            api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            logger.error("GEMINI_API_KEY not set. Add it to .env or export it.")
            sys.exit(1)
        client = genai.Client(api_key=api_key)

    classifier = GeminiEmbeddingSetup(config, client)

    # Load enriched papers
    enriched = load_papers(enriched_file)

    # Load agent-enriched papers with format validation
    agent_enriched = validate_agent_enriched(agent_enriched_file)
    if not agent_enriched:
        logger.warning(
            f"Agent-enriched file not available or has wrong format. "
            f"Falling back to unenriched papers (title-only classification): {unenriched_file}"
        )
        agent_enriched = load_papers(unenriched_file)

    # Merge
    all_papers = enriched + agent_enriched
    logger.info(f"Total papers to classify: {len(all_papers)} "
                f"({len(enriched)} enriched + {len(agent_enriched)} additional)")

    if not all_papers:
        logger.error("No papers to classify. Check input files.")
        sys.exit(1)

    # Classify
    logger.info("=" * 60)
    logger.info("Classifying papers via Gemini embeddings")
    logger.info("=" * 60)

    results = classify_all_papers(all_papers, classifier, minimal_output)

    # Write output
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Summary
    logger.info("=" * 60)
    logger.info("CLASSIFICATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"  Total classified: {len(results)}")
    logger.info(f"  Output: {output_file}")

    cat_counter = Counter()
    for r in results:
        for c in r["category"]:
            cat_counter[c] += 1
    logger.info(f"  Category distribution:")
    for cat, count in cat_counter.most_common():
        logger.info(f"    {cat}: {count}")


# ==============================================================================
# Standalone execution
# ==============================================================================

if __name__ == "__main__":
    from dotenv import load_dotenv

    sys.path.insert(0, os.path.dirname(__file__))

    project_root = os.path.join(os.path.dirname(__file__), "..", "..")
    load_dotenv(os.path.join(project_root, ".env"))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    config_file = os.path.join(project_root, "config", "config.yml")
    config = load_config(config_file)

    data_dir = os.path.join(project_root, "data")

    run_classification(
        config=config,
        enriched_file=os.path.join(data_dir, "papers_enriched.json"),
        agent_enriched_file=os.path.join(data_dir, "papers_agent_enriched.json"),
        unenriched_file=os.path.join(data_dir, "papers_unenriched.json"),
        output_file=os.path.join(data_dir, "classified_papers.json"),
        minimal_output=True,
    )
