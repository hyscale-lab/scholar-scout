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
# from embedding_classification import GeminiEmbeddingSetup
from generative_classification import GeminiGenerativeClassifier

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


# def build_classification_text(paper: dict) -> str:
#     """Build the text to classify from title + abstract."""
#     title = paper.get("title", "").strip()
#     abstract = paper.get("abstract", "").strip()

#     if abstract:
#         return f"{title} {abstract}"
#     else:
#         return title


def _paper_identity(paper: dict) -> str:
    """Stable identity used to resume a classification checkpoint."""
    key = paper.get("key")
    if key:
        return str(key)
    return "|".join(
        str(paper.get(field, "") or "")
        for field in ("title", "venue", "ee")
    )


def _write_json(filepath: str, data) -> None:
    """Write JSON atomically so an interrupted run does not corrupt the file."""
    temp_path = filepath + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(temp_path, filepath)


def classify_all_papers(
    papers: list,
    classifier: GeminiGenerativeClassifier,
    minimal_output: bool = True,
    checkpoint_file: str | None = None,
    failed_file: str | None = None,
) -> list:
    """Classify papers, checkpoint successes, and continue past individual failures."""
    completed = {}
    failed = []

    # Resume successful classifications from a prior interrupted run.
    if checkpoint_file and os.path.isfile(checkpoint_file):
        try:
            with open(checkpoint_file, "r", encoding="utf-8") as f:
                checkpoint = json.load(f)
            if isinstance(checkpoint, dict) and isinstance(checkpoint.get("completed"), dict):
                completed = checkpoint["completed"]
                logger.info("Resuming %d previously classified papers from %s",
                            len(completed), checkpoint_file)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Ignoring unreadable checkpoint %s: %s", checkpoint_file, exc)

    total = len(papers)

    for i, paper in enumerate(papers):
        identity = _paper_identity(paper)
        if identity in completed:
            logger.info("[%d/%d] Already classified; skipping: %s",
                        i + 1, total, paper.get("title", "")[:60])
            continue

        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        logger.info("[%d/%d] Classifying: %s...", i + 1, total, title[:60])

        try:
            categories = classifier.classify(title, abstract)
        except Exception as exc:
            logger.exception("Classification failed for %r; will record for retry", title)
            failed.append({
                "identity": identity,
                "paper": paper,
                "error": f"{type(exc).__name__}: {exc}",
            })
            if failed_file:
                _write_json(failed_file, failed)
            continue

        if not categories:
            categories = ["Others"]

        authors = paper.get("authors", [])
        authors_str = (
            ", ".join(authors) if isinstance(authors, list) else str(authors)
        )

        result = {
            "paper_title": title,
            "authors": authors_str,
            "conference": paper.get("venue", ""),
            "url": paper.get("ee", ""),
            "category": categories,
        }

        if not minimal_output:
            for field in ("key", "mdate", "dblp_url", "abstract"):
                if paper.get(field):
                    result[field] = paper[field]

        completed[identity] = result
        logger.info("  → %s", categories)

        # Save after each successful paper; reruns can resume without repeating it.
        if checkpoint_file:
            _write_json(checkpoint_file, {"completed": completed})

    # Return successes in original input order.
    results = [
        completed[_paper_identity(paper)]
        for paper in papers
        if _paper_identity(paper) in completed
    ]

    if checkpoint_file:
        _write_json(checkpoint_file, {"completed": completed})
    if failed_file:
        _write_json(failed_file, failed)

    if failed:
        logger.warning(
            "%d papers failed after retries. Details saved to %s",
            len(failed), failed_file or "(no failure file configured)",
        )

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
            raise RuntimeError("GEMINI_API_KEY not set. Add it to .env or export it.")
        client = genai.Client(api_key=api_key)

    classifier = GeminiGenerativeClassifier(config, client)

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
        raise RuntimeError("No papers to classify. Check input files.")

    # Classify
    logger.info("=" * 60)
    logger.info("Classifying papers via Gemini generative")
    logger.info("=" * 60)

    output_root, output_ext = os.path.splitext(output_file)
    checkpoint_file = output_root + ".checkpoint.json"
    failed_file = output_root + ".failed.json"

    results = classify_all_papers(
        all_papers,
        classifier,
        minimal_output,
        checkpoint_file=checkpoint_file,
        failed_file=failed_file,
    )

    # Write the final output atomically.
    _write_json(output_file, results)

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
    logger.info("  Category distribution:")
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

    try:
        run_classification(
            config=config,
            enriched_file=os.path.join(data_dir, "papers_enriched.json"),
            agent_enriched_file=os.path.join(data_dir, "papers_agent_enriched.json"),
            unenriched_file=os.path.join(data_dir, "papers_unenriched.json"),
            output_file=os.path.join(data_dir, "classified_papers.json"),
            minimal_output=True,
        )
    except RuntimeError as e:
        logger.error(str(e))
        sys.exit(1)
