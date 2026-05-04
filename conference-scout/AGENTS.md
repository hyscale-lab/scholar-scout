# AGENTS.md

## Session Startup

1. Read `SOUL.md`
2. Start the task immediately

## Rules

- If you start a task, finish it completely before reporting back.
- You MUST complete every task to 100% before stopping. No partial results. No pausing.
- When processing a list of N items, your output MUST contain exactly N results.
- NEVER call external AI services, LLM APIs (OpenAI, Anthropic, Gemini, etc.), or spawn sub-agents. You do all the work yourself with your own tools.
- If a web fetch fails or is blocked, immediately skip it and continue with the next item. Never retry, never get stuck.
- NEVER stop to ask "should I continue?" — the answer is always YES, continue until done.
- Do not exfiltrate private data. Use `trash` over `rm`.
