## Instructions

Fetch the abstract for each paper below. For each paper:

1. Fetch the "ee" URL. Extract the abstract if visible on the page.
2. If that fails, fetch the "dblp_url" and look for an arxiv or paper link, then fetch that.
3. If still nothing, set abstract to "".

Max 2 fetches per paper. Process one at a time. Move on quickly.

When ALL papers are done, write the output file immediately.

## Output Format (CRITICAL)

Write a JSON array to the output file. Each element is the original paper object UNCHANGED, with only `"abstract"` added.

CORRECT:
```json
[
  {"key": "conf/sosp/X25", "mdate": "2026-03-31", "title": "Example.", "authors": ["A", "B"], "venue": "SOSP", "ee": "https://www.usenix.org/...", "dblp_url": "https://dblp.org/rec/conf/sosp/X25", "abstract": "We present a system that..."},
  {"key": "conf/asplos/Y26", "mdate": "2026-03-24", "title": "Another.", "authors": ["C"], "venue": "ASPLOS", "ee": "https://doi.org/10.1145/123.456", "dblp_url": "https://dblp.org/rec/conf/asplos/Y26", "abstract": ""}
]
```

WRONG (do NOT do these):
- `{"papers": [...]}` — must be a bare array `[...]`
- Adding fields like "categories", "doi", "date", "note", "enrichment_status", "rank"
- Renaming "ee" to "ee_url" or "mdate" to "date"
- Inventing abstracts from titles — use "" if you cannot fetch it
- Removing "0001" etc from author names

## Rules

- Output is `[...]` not `{...}`
- Paper count in = paper count out
- Copy each paper verbatim, only append `"abstract"`
- Do NOT add, remove, or rename any fields
- Do NOT invent abstracts — only use text actually fetched from a URL
- Do NOT stop until all papers are done and the file is written
