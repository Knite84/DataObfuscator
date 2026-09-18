# Data Obfuscator

Local-only, single-tenant data obfuscation tool. Paste rich text (HTML) or plain text; Pass 1 (deterministic regex + spaCy NER) plus Pass 2 (local LLM detection only) finds identifying data — emails, phones, IDs, names, orgs, places, business-sensitive free text — and replaces each occurrence consistently with a synthetic value.

## Current status — Steps 1–6 complete

| Step | Scope | Status |
|------|-------|--------|
| 1 | FastAPI skeleton, static UI, Pass-1 regex pass | done |
| 2 | HTML ↔ plain-text offset maps + HTML re-injection | done |
| 3 | spaCy NER, deterministic mapping table, TXT + HTML render | done |
| 4 | Pass 2: local LLM (LM Studio / Unsloth Studio on host) | done |
| 5 | Human-in-the-loop review UI (approve / edit / reject) + finalize | done |
| 6 | Docker packaging + end-to-end polish | done |

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m spacy download en_core_web_trf   # ~457 MB, one-time
.venv\Scripts\python -m uvicorn app.main:app
# open http://127.0.0.1:8000
```

No other services are required until Step 4.

### Docker (recommended)

```powershell
# 1. Optional: start your HOST LLM server (LM Studio / Unsloth Studio) at :8888
# 2. Build & run (reads .env for the LLM API key; the LLM itself stays on the host)
docker compose -f docker/compose.yml up -d
# open http://127.0.0.1:8000
```

The container reaches the host LLM via `host.docker.internal:8888` — Unsloth Studio / LM Studio NEVER runs inside Docker. With the LLM down, the app still does full Pass 1 (regex + spaCy NER) and reports pass-2 unavailability instead of failing. To turn the LLM off for a pass-type run: set `OBFUSCATOR_LLM_ENABLED=0`.

Manual Docker without Compose:

```powershell
docker build -f docker/Dockerfile -t data-obfuscator .
docker run -d -p 8000:8000 --add-host host.docker.internal:host-gateway --env-file .env data-obfuscator
```

## How it works

1. **Ingestion** (`app/ingest.py`) — HTML is tokenized deterministically and mapped to plain text: text runs kept verbatim (1:1 offsets, entities left as-is), `<br>`/block-tag closings insert newlines, `<script>/<style>` content skipped. Any plain-text span maps back to the exact source span — or is reported *unresolved* if it crosses a tag boundary.
2. **Pass 1** (`app/pass1_regex.py`, `app/pass1_ner.py`) — regex for email / phone / SSN / URL / card / IBAN (high confidence), spaCy `en_core_web_trf` for PERSON / ORG / GPE / LOC / FAC (capped confidence, since NER is less precise).
3. **Merge** (`app/render.py`) — findings sorted by `(start, -length)`; regex spans win overlaps. Each kept finding gets a replacement.
4. **Mapping table** — one entry per unique `(category, quote)`, with occurrence counts. Same source string → same replacement, every time.
5. **Replacements** (`app/namer.py`) — deterministic synthetic values driven by a SHA-1 hash of `(source, category)`: no state, yet consistent across sessions. Fictional-safe ranges only: `555-01xx` phones, SSA-never-issued `9xx` IDs, Luhn-valid test-style cards, `example.net` / `example.com` domains. `free_text` (business-sensitive spans the LLM flags) is intentionally opaque: `[REDACTED-<hash>]`, editable in review.
6. **Render** — back-to-front replacement applied to plain text directly, and to HTML through the ingest map; unresolvable edits are reported, never guessed.
7. **Pass 2** (`app/pass2_llm.py`) — local LLM (LM Studio / Unsloth Studio on the host, OpenAI-compatible `/chat/completions`) detects only, never rewrites: it returns strict JSON `[{quote, category, confidence, reason}]` for `person | org | place | free_text`, mapped back to verbatim spans. Confidence is trust-capped below the review threshold so regex/NER always win overlaps; unmappable quotes surface as `llm_unverified`, never auto-replaced.
8. **Review UI** (`app/static/`) — grouped Mapping table only (no separate Findings table): each row is one `(category, quote, replacement)` group with `Approve all` / `Reject all`, expandable (`▸/▾`, all collapsed by default) to per-finding rows with source, confidence, resolvability, editable replacement, and individual Approve/Reject. `Approve remaining` / `Reject remaining` above the grid act on all still-`pending` findings.
9. **Finalize** — `POST /api/finalize` applies approved/edited decisions (pending counts as approved, rejected skipped, manual quotes mapped to all verbatim occurrences) and returns TXT + HTML. The UI shows plain text first; HTML output sits in a closed accordion.

## Consistency guarantee

"John Smith" appearing 20 times maps to e.g. "Marlow Ashford" 20 times — the mapping is a pure function of the source string and category, so consistency holds even after restarting the app.

## Review workflow

1. Paste text → **Analyze** (regex + spaCy + LLM).
2. **Mapping table**: bulk `Approve all` / `Reject all` per group, or expand (`▸`) for per-finding edits and decisions. `Approve remaining` / `Reject remaining` settle everything still pending.
3. Unmappable Pass-2 hits appear under **Pass 2 — not resolvable**; re-add exact spans via Manual add if verified.
4. **Approve decisions & finalize** → plain-text output first, HTML in the accordion; copy or download TXT.

## API

- `GET  /api/health` — status + which passes are active + LLM model
- `POST /api/analyze` — `{html? | text?}` → findings (with `replacement`, `source_span`), mapping table, obfuscated TXT draft, `llm_unverified`, `llm_errors`, `dropped`
- `POST /api/finalize` — `{html? | text?, decisions[]}` → `{html, txt, mapping_table, applied, dropped, warnings}`

Unauthenticated and localhost-only by design — no data is persisted anywhere.

## Privacy notes

- No network calls except the spaCy model download at setup time, and later (Step 4) the LLM call to your own LM Studio on the host. No third-party APIs.
- NER confidence is capped at 0.90 and LLM confidence is trust-capped below the 0.85 review threshold, so the review queue is populated by lower-confidence signals while regex holds its own.
- `example.net` / `example.com` / fictional ranges are reserved or never-issued, so generated values cannot route to real people.

## Design limitations (documented, deliberate)

- HTML entities are kept verbatim in the plain text (they are part of the source substring), which keeps offset alignment exact; detection sees `&amp;` rather than `&`.
- Tags are matched with `<[^>]+>`: a literal `>` inside an attribute value is a known edge case.
- A span that crosses an inline tag (e.g. a card number split by `<b>`) is reported unresolved rather than approximated — those surface in the review queue.
- spaCy NER can miss domain-specific person/org mentions; that is exactly what Pass 2 (local LLM) is meant to catch.
- `free_text` replacements are opaque `[REDACTED-<hash>]` by design (nothing realistic to fake); edit the replacement in the expanded group row if a readable stand-in is needed.

## Tests

```powershell
.venv\Scripts\python -m pytest tests -q
```
