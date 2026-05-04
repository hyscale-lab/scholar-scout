# OpenClaw Gateway — Setup for Conference Scout Pipeline

## Overview

The OpenClaw gateway runs in a Docker container (`openclaw-gateway`) and acts as an autonomous agent that can fetch URLs, read/write files, and execute tasks. We access it via the `/v1/chat/completions` HTTP endpoint using `model: "openclaw:main"` which routes requests to the full agent (with tools), not just an LLM.

The docker container setup guide for OpenClaw can be found [here](https://docs.openclaw.ai/install/docker).

---

## 1. Gateway Config (`~/.openclaw/openclaw.json`)

The following must be present in the `"gateway"` section:

```json
"gateway": {
    "port": 18789,
    "mode": "local",
    "bind": "loopback",
    "http": {
      "endpoints": {
        "chatCompletions": {
          "enabled": true
        }
      }
    },
    "auth": {
      "mode": "token",
      "token": "<YOUR_GATEWAY_TOKEN>"
    }
}
```

**Key settings:**
- `chatCompletions.enabled: true` — this is the endpoint we use (`/v1/chat/completions`)

After editing, restart:
```bash
docker restart openclaw-gateway
```

---

## 2. Together AI API Key

The agent uses Together AI as its LLM provider. The key is stored inside the container:

**Container path:** `/home/node/.openclaw/agents/main/agent/auth-profiles.json`

```json
{
  "version": 1,
  "profiles": {
    "together:default": {
      "type": "api_key",
      "provider": "together",
      "key": "<YOUR_TOGETHER_API_KEY>"
    }
  }
}
```

### Writing the key into the container

```bash
docker exec openclaw-gateway sh -c 'cat > /home/node/.openclaw/agents/main/agent/auth-profiles.json << EOF
{
  "version": 1,
  "profiles": {
    "together:default": {
      "type": "api_key",
      "provider": "together",
      "key": "YOUR_TOGETHER_API_KEY_HERE"
    }
  }
}
EOF'
docker restart openclaw-gateway
```

Since the container stays running locally, binds to loopback only, and is not in any repo — storing the key directly in the container is fine.

---

## 3. Agent Model Config

In `openclaw.json`, the agent's model is configured under `"agents"`:

```json
"agents": {
    "defaults": {
      "model": {
        "primary": "together/Qwen/Qwen3.5-9B",
        "fallbacks": [
          "together/moonshotai/Kimi-K2.5"
        ]
      },
      "models": {
        "together/moonshotai/Kimi-K2.5": {
          "alias": "Together Kimi K2.5"
        },
        "together/Qwen/Qwen3.5-9B": {
          "alias": "Together Qwen 3.5 9B"
        }
      },
      "workspace": "/home/node/.openclaw/workspace",
      "timeoutSeconds": 3600
    },
    "list": [
      {
        "id": "main",
        "model": "together/Qwen/Qwen3.5-9B"
      }
    ]
  }
```

The `"main"` agent uses `Qwen3.5-9B`. When you call `model: "openclaw:main"` from Python, it routes to this agent with full tool access.

---

## 4. How It Works

```
Host Machine                         Docker Container (openclaw-gateway)
─────────────                        ──────────────────────────────────
run_pipeline.py
  │
  ├─ Step 1: papers_extractor.py
  │    → Scrapes dblp, fetches abstracts via Semantic Scholar
  │    → Writes papers_enriched.json + papers_unenriched.json
  │
  ├─ Step 2: openclaw_chat_completions.py
  │    → POST /v1/chat/completions ──────→ Gateway routes to "main" agent
  │       (model: "openclaw:main")         Agent uses tools autonomously
  │                                        (web_fetch, read, write, exec)
  │    ← Polls for output file  ←───────── Agent writes papers_agent_enriched.json
  │       on shared filesystem              to mounted workspace
  │
  ├─ Step 3: classify_papers.py
  │    → Merges enriched + agent-enriched papers
  │    → Classifies via Gemini embeddings
  │    → Writes classified_papers.json
  │
  └─ Step 4: notifications.py
       → Uploads classified_papers.json to Slack
```

**Important:** The HTTP response from `/v1/chat/completions` returns immediately (often before the agent finishes using tools). The agent continues working in the background. Python monitors for the output file to appear on the shared filesystem.

---

## 5. Python Usage

### Full pipeline

```bash
python scripts/run_pipeline.py                  # Run all 4 steps
python scripts/run_pipeline.py --step extract   # Step 1 only
python scripts/run_pipeline.py --step agent     # Step 2 only (OpenClaw)
python scripts/run_pipeline.py --step classify  # Step 3 only
python scripts/run_pipeline.py --step notify    # Step 4 only
python scripts/run_pipeline.py --verbose        # Debug logging
```

### OpenClaw API call (standalone)

```python
import requests

OPENCLAW_URL = "http://127.0.0.1:18789/v1/chat/completions"
OPENCLAW_TOKEN = "<YOUR_GATEWAY_TOKEN>"

response = requests.post(
    OPENCLAW_URL,
    headers={
        "Authorization": f"Bearer {OPENCLAW_TOKEN}",
        "Content-Type": "application/json",
    },
    json={
        "model": "openclaw:main",
        "user": "my-session-id",
        "messages": [
            {"role": "user", "content": "Fetch the abstract from https://example.com and save it to data/output.json"}
        ],
    }
)
```

- `model: "openclaw:main"` — routes to the full agent with tools (not just an LLM)
- `user: "session-id"` — maintains conversation history across calls (gateway-side persistence)

---

## 6. Shared Filesystem

The container workspace is mounted to the host at `~/.openclaw/workspace/`. When the agent writes a file inside the container, it appears directly on the host filesystem — no `docker exec` needed.

```bash
# Check the output file directly on the host:
cat ~/.openclaw/workspace/data/papers_agent_enriched.json
```

The Python pipeline ([`openclaw_chat_completions.py`](src/conference_scout/openclaw_chat_completions.py)) polls for this file using normal `os.path.exists()` / `open()`.

---

## 7. Troubleshooting

**Endpoint returns "Not Found":**
- `chatCompletions.enabled` is not `true` in `openclaw.json`. Add it and restart.

**Agent returns "No response from OpenClaw":**
- This means the agent is working in the background (using tools). It's normal — poll for the output file.

**All web_fetch calls fail with 429:**
- Rate limiting. The prompt should say "process one at a time" to avoid parallel fetches.

**Agent produces wrong JSON format:**
- The classifier ([`classify_papers.py`](src/conference_scout/classify_papers.py)) validates format via `validate_agent_enriched()` and falls back to unenriched papers if the format is bad. Fix the prompt and re-run.

**Together API key invalid (HTTP 401 in logs):**
- Check logs: `docker logs openclaw-gateway --tail 30`
- Update the key in `auth-profiles.json` and restart.

**Models on cooldown after auth failure:**
- Restart the container: `docker restart openclaw-gateway`

---

## 8. Files Summary

| File | Purpose |
|------|---------|
| `~/.openclaw/openclaw.json` | Gateway + agent config (endpoints, auth, models) |
| Container: `auth-profiles.json` | Together AI API key |
| [`config/config.yml`](config/config.yml) | Conference URLs, research topics, Slack/Gemini config |
| [`prompt/openclaw_prompt.md`](prompt/openclaw_prompt.md) | Instructions sent to the OpenClaw agent |
| [`scripts/run_pipeline.py`](scripts/run_pipeline.py) | Full pipeline orchestrator (all 4 steps) |
| [`src/conference_scout/papers_extractor.py`](src/conference_scout/papers_extractor.py) | Step 1: dblp scraping + Semantic Scholar abstracts |
| [`src/conference_scout/openclaw_chat_completions.py`](src/conference_scout/openclaw_chat_completions.py) | Step 2: OpenClaw agent (fire task, poll, nudge) |
| [`src/conference_scout/classify_papers.py`](src/conference_scout/classify_papers.py) | Step 3: Gemini embedding classification |
| [`src/conference_scout/embedding_classification.py`](src/conference_scout/embedding_classification.py) | Embedding + cosine similarity logic |
| [`src/conference_scout/notifications.py`](src/conference_scout/notifications.py) | Step 4: Upload classified papers to Slack |
| [`src/conference_scout/config.py`](src/conference_scout/config.py) | Pydantic config models + YAML loader |
