#!/usr/bin/env python3
"""
Conference Scout Orchestrator — Runs the full pipeline end-to-end.

Steps:
    1. Extract papers from dblp + fetch abstracts via Semantic Scholar
    2. (Agent) Enrich unenriched papers — placeholder for OpenClaw API
    3. Classify papers via Gemini embeddings
    4. Upload classified_papers.json to Slack

Usage:
    python scripts/run_pipeline.py                  # Run all steps
    python scripts/run_pipeline.py --step extract   # Run only extraction
    python scripts/run_pipeline.py --step classify  # Run only classification
    python scripts/run_pipeline.py --step notify    # Run only Slack notification
    python scripts/run_pipeline.py --verbose        # Enable debug logging
"""

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(PROJECT_ROOT, "src", "conference_scout")

sys.path.insert(0, SRC_DIR)
sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# ---------------------------------------------------------------------------
# Data paths
# ---------------------------------------------------------------------------
CONFIG_FILE = os.path.join(PROJECT_ROOT, "config", "config.yml")
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
ENRICHED_FILE = os.path.join(DATA_DIR, "papers_enriched.json")
UNENRICHED_FILE = os.path.join(DATA_DIR, "papers_unenriched.json")
AGENT_ENRICHED_FILE = os.path.join(DATA_DIR, "papers_agent_enriched.json")
CLASSIFIED_FILE = os.path.join(DATA_DIR, "classified_papers.json")

logger = logging.getLogger(__name__)


# ===========================================================================
# Step 1 — Extract papers from dblp + enrich with abstracts
# ===========================================================================
def step_extract(config):
    logger.info("=" * 60)
    logger.info("STEP 1: Extracting papers from dblp")
    logger.info("=" * 60)

    from papers_extractor import run_pipeline

    run_pipeline(
        conferences_config=config.conferences,
        output_enriched=ENRICHED_FILE,
        output_unenriched=UNENRICHED_FILE,
    )

    logger.info("Step 1 complete.\n")


# ===========================================================================
# Step 2 — Agent enrichment via OpenClaw
# ===========================================================================
def step_agent_enrich(config):
    logger.info("=" * 60)
    logger.info("STEP 2: Agent enrichment of unenriched papers")
    logger.info("=" * 60)

    from openclaw_chat_completions import run_agent_enrichment

    prompt_file = os.path.join(PROJECT_ROOT, "prompt", "openclaw_prompt.md")

    success = run_agent_enrichment(
        input_file=UNENRICHED_FILE,
        output_file=AGENT_ENRICHED_FILE,
        prompt_file=prompt_file,
    )

    if success:
        logger.info("Agent enrichment succeeded.")
    else:
        logger.warning(
            "Agent enrichment failed or timed out. "
            "Classifier will fall back to unenriched papers (title-only)."
        )

    logger.info("Step 2 complete.\n")


# ===========================================================================
# Step 3 — Classify papers via Gemini embeddings
# ===========================================================================
def step_classify(config):
    logger.info("=" * 60)
    logger.info("STEP 3: Classifying papers via Gemini embeddings")
    logger.info("=" * 60)

    from classify_papers import run_classification

    run_classification(
        config=config,
        enriched_file=ENRICHED_FILE,
        agent_enriched_file=AGENT_ENRICHED_FILE,
        unenriched_file=UNENRICHED_FILE,
        output_file=CLASSIFIED_FILE,
        minimal_output=True,
    )

    logger.info("Step 3 complete.\n")


# ===========================================================================
# Step 4 — Upload classified papers to Slack
# ===========================================================================
def step_notify(config):
    logger.info("=" * 60)
    logger.info("STEP 4: Sending classified papers to Slack")
    logger.info("=" * 60)

    from notifications import SlackNotifier

    notifier = SlackNotifier(config)
    notifier.send_classified_papers(CLASSIFIED_FILE)

    logger.info("Step 4 complete.\n")


# ===========================================================================
# Main
# ===========================================================================
STEPS = {
    "extract": step_extract,
    "agent": step_agent_enrich,
    "classify": step_classify,
    "notify": step_notify,
}


def main():
    parser = argparse.ArgumentParser(description="Conference Scout Pipeline Orchestrator")
    parser.add_argument(
        "--step",
        choices=list(STEPS.keys()),
        default=None,
        help="Run a single step instead of the full pipeline.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug-level logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    from config import load_config
    config = load_config(CONFIG_FILE)

    if args.step:
        logger.info(f"Running single step: {args.step}")
        STEPS[args.step](config)
    else:
        logger.info("Running full pipeline")
        for name, func in STEPS.items():
            func(config)

    logger.info("Done.")


if __name__ == "__main__":
    main()
