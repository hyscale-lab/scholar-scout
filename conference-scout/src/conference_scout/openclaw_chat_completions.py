"""
OpenClaw agent pipeline — fire-and-monitor via /v1/chat/completions.

The agent runs autonomously with full tools (web_fetch, read, write, exec).
Python sends the task once, then monitors for completion by checking the output file.
If the agent stalls, Python nudges with a short "continue" (no history replay).

The gateway persists session history internally (gateway.sessions.enabled = true),
so nudges don't need to resend the full conversation — the agent already remembers.

Usage (standalone):
    python openclaw_chat_completions.py

Usage (from pipeline):
    from openclaw_chat_completions import run_agent_enrichment
    run_agent_enrichment(input_file, output_file, prompt_file)
"""

import json
import logging
import os
import time
import requests

logger = logging.getLogger(__name__)

# --- Config defaults ---
_DEFAULT_OPENCLAW_URL = "http://127.0.0.1:18789/v1/chat/completions"

MODEL = "openclaw:main"

POLL_INTERVAL = 15     # seconds between output file checks
NUDGE_AFTER = 60       # seconds before nudging (give agent time to use tools)
MAX_TOTAL_TIME = 900   # 15 minutes max


def _get_url() -> str:
    """Get the OpenClaw API URL from environment or use default."""
    return os.environ.get("OPENCLAW_URL", _DEFAULT_OPENCLAW_URL)


def _get_headers() -> dict:
    """Build request headers using the OPENCLAW_TOKEN env var."""
    token = os.environ.get("OPENCLAW_TOKEN", "")
    if not token:
        logger.warning("OPENCLAW_TOKEN not set in environment.")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _send_message(messages: list, session_id: str) -> str:
    """Send a chat completion request with session ID. Returns agent's text reply."""
    url = _get_url()
    try:
        resp = requests.post(
            url,
            headers=_get_headers(),
            json={"model": MODEL, "user": session_id, "messages": messages},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except (requests.RequestException, ValueError) as e:
        logger.error(f"OpenClaw API error: {e}")
        return "(error)"


def _check_output_file(output_file: str) -> str | None:
    """Check if the agent has written the output file."""
    if not os.path.exists(output_file):
        return None
    try:
        with open(output_file, "r") as f:
            content = f.read().strip()
        return content if content else None
    except OSError:
        return None


def run_agent_enrichment(input_file: str, output_file: str, prompt_file: str) -> bool:
    """
    Run the OpenClaw agent enrichment pipeline.

    Returns True if output file is available with valid format.
    Returns False if agent timed out, failed, or produced bad output.
    """
    # If output file already exists (from a previous run or agent already wrote it),
    # just return — let the classifier decide if the format is good enough.
    if os.path.exists(output_file):
        logger.info(f"Agent output file already exists: {output_file} — skipping agent call.")
        return True

    # Pre-flight checks: bail early if the agent infrastructure isn't available
    token = os.environ.get("OPENCLAW_TOKEN", "")
    url = _get_url()
    if not token:
        logger.warning("OPENCLAW_TOKEN not set — skipping agent enrichment.")
        return False

    # Quick connectivity check (don't wait 15 min if agent is unreachable)
    try:
        probe = requests.get(url.rsplit("/", 1)[0], timeout=5)
    except requests.RequestException:
        logger.warning(f"OpenClaw API unreachable at {url} — skipping agent enrichment.")
        return False

    # Load prompt and papers (handle missing files gracefully)
    try:
        with open(prompt_file) as f:
            prompt = f.read()
    except FileNotFoundError:
        logger.warning(f"Prompt file not found: {prompt_file} — skipping agent enrichment.")
        return False

    try:
        with open(input_file) as f:
            papers = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"Cannot load input file {input_file}: {e} — skipping agent enrichment.")
        return False

    if not papers:
        logger.info("No unenriched papers to process — skipping agent enrichment.")
        return False

    session_id = f"paper-enrichment-{int(time.time())}"
    output_basename = os.path.basename(output_file)
    agent_output_path = f"data/{output_basename}"

    logger.info(f"Loaded {len(papers)} papers from {input_file}")
    logger.info(f"Agent: {MODEL} @ {_get_url()}")
    logger.info(f"Session: {session_id}")
    logger.info(f"Task: fetch abstracts → write to {agent_output_path}")

    # Send initial task
    initial_messages = [
        {"role": "user", "content": (
            f"{prompt}\n\n---\n\n"
            f"Process these {len(papers)} papers.\n"
            f"Process papers ONE AT A TIME to avoid rate limits.\n"
            f"Write the result to `{agent_output_path}` when ALL are done.\n\n"
            f"Papers:\n```json\n{json.dumps(papers, indent=2)}\n```"
        )},
    ]

    logger.info("Dispatching task to agent...")
    reply = _send_message(initial_messages, session_id)
    logger.info(f"Agent: {reply[:150]}")

    # Monitor loop
    start = time.time()
    last_nudge = start
    nudge_count = 0

    logger.info(f"Polling for {agent_output_path} (interval={POLL_INTERVAL}s, nudge={NUDGE_AFTER}s, max={MAX_TOTAL_TIME}s)")

    while True:
        elapsed = time.time() - start
        if elapsed > MAX_TOTAL_TIME:
            logger.warning(f"Agent timed out after {MAX_TOTAL_TIME}s")
            return False

        time.sleep(POLL_INTERVAL)

        # Check if output file exists
        content = _check_output_file(output_file)
        if content:
            try:
                enriched = json.loads(content)
            except json.JSONDecodeError:
                logger.debug(f"[{elapsed:.0f}s] File exists but not valid JSON yet...")
                continue

            # Save locally
            with open(output_file, "w") as f:
                json.dump(enriched, f, indent=2, ensure_ascii=False)

            found = sum(1 for p in enriched if isinstance(p, dict) and p.get("abstract"))
            logger.info(f"Output file detected after {elapsed:.0f}s")
            logger.info(f"  Papers: {len(enriched)}/{len(papers)} | Abstracts found: {found}")
            return True

        # Nudge if agent seems stalled
        since_nudge = time.time() - last_nudge
        if since_nudge > NUDGE_AFTER:
            nudge_count += 1
            logger.info(f"[{elapsed:.0f}s] Nudging agent (#{nudge_count})...")

            reply = _send_message([
                {"role": "user", "content": "Continue. Do not restart. Write the file when done."}
            ], session_id)
            if reply and reply != "No response from OpenClaw.":
                logger.info(f"  Agent: {reply[:150]}")

            last_nudge = time.time()
        else:
            logger.debug(f"[{elapsed:.0f}s] waiting...")

    return False


# ==============================================================================
# Standalone execution
# ==============================================================================

def main():
    """Run agent enrichment standalone."""
    from dotenv import load_dotenv

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    load_dotenv(os.path.join(project_root, ".env"))

    data_dir = os.path.join(project_root, "data")

    input_file = os.path.join(data_dir, "papers_unenriched.json")
    output_file = os.path.join(data_dir, "papers_agent_enriched.json")
    prompt_file = os.path.join(project_root, "prompt", "openclaw_prompt.md")

    success = run_agent_enrichment(input_file, output_file, prompt_file)
    if success:
        print("\nAgent enrichment complete.")
    else:
        print("\nAgent enrichment failed or timed out.")


if __name__ == "__main__":
    main()
