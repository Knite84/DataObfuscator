# Lessons Learned — Data Obfuscator

Practical notes captured while building ingestion, detection, review, and Docker packaging. Historical examples are retained, with implementation claims checked against the current repository.

## 1. Offset alignment is the whole game

The single most important architectural decision so far: **detection always happens on plain text with exact character offsets, and every decision maps back to spans deterministically.** Once we had that invariant, regex passes, NER, mapping tables, and rendering all compose cleanly without string surgery in unexpected places.

The key trick for HTML: keep entity sequences (`&amp;`) VERBATIM in the plain text instead of decoding them. That makes plain-text offsets 1:1 with source offsets within every text node — alignment becomes trivial arithmetic instead of an entity-width tracking problem. Trade-off: detection sees `&amp;` literally; acceptable for PII finding, and honestly stated in the README.

## 2. Write generation code only after the design is settled — or you write garbage

Twice during step 2 and step 3, `app/ingest.py` and `tests/` ended up with half-experimented code (`if False` branches, dead helpers, placeholder tests) because I started typing before committing to a design on paper. The fix was always the same: throw the file away, write a short design header in the module docstring, THEN write the implementation once. Regex-based tag tokenization + raw-segment scan + a canonical re-basing pass was the clean final shape — it took three attempts to arrive at writing that file in a single pass.

Rule of thumb going forward: **if a file needs a `# placeholder removed below` comment, it's not done — stop and rewrite it from its docstring.**

## 3. HTMLParser was the wrong tool for offset maps

First instinct was `html.parser.HTMLParser` for step 2. Its line/column positions require translation to absolute character offsets, and mixing decoded entities with source offsets adds complexity. The current regex tag tokenizer (`<[^>]*>` + `_scan`) keeps text runs verbatim and documents its limitation with `>` inside attribute values. Prefer a mechanism whose offset behavior you can fully reason about; this tokenizer is not a general-purpose HTML parser or sanitizer.

## 4. Determinism gives consistency for free — hash, don't store

Requirement: same source string and category → same default replacement for every detected occurrence. `replacement_for(category, source)` is a pure function: category selects the format or pools, while SHA-1 of the source string drives selection. It does not hash `source + category`. Benefits that fell out:

- consistency across sessions and restarts, no persistence layer needed (matching the "no data persistence" requirement anyway)
- tests can assert determinism with no setup
- reviewer edits override individual detected occurrences while their status remains `edited`; the default remains hash-based

Consistency holds with unchanged code and pools. It does not imply unique replacements, alias recognition, or consistent custom edits across a group.

## 5. Check generated formats before claiming reserved ranges

The generator emits `(555) xxx-xxxx` phones, national IDs beginning with `9`, Luhn-valid 16-digit card-like values beginning with `4`, `XX` account placeholders, and addresses on `example.net`/`example.com`. Earlier notes overstated this as universally reserved output. Phones are not limited to `555-01xx`, cards do not use a test-number allowlist, and names or places may coincide with real entities. A prefix or checksum test cannot establish that an identifier is reserved.

A historical modulus bug produced a 17-digit card-like value. A test of length and the full Luhn property caught it. Test the precise guarantee you want, and keep documentation within what the implementation enforces.

## 6. Confidence tiers encode *who is trusted*

Regex scores are fixed at 0.85–1.00. NER scores are fixed by label: PERSON 0.90, ORG/GPE 0.85, LOC/FAC 0.80. LLM scores are `min(0.80, max(0, raw)) * 0.8` (maximum 0.64). Every detected finding now starts pending, regardless of its source or score.

These are trust heuristics, not calibrated probabilities. They do not determine approval or overlap resolution. The API rejects pending decision statuses, and the UI requires a decision for every detected finding and unique manual suggestion before enabling Finalize.

## 7. Regex confidences have surprises hiding in ranges

Two test-driven adjustments: phone patterns are noisy (they also match card segments and random digit runs, hence 0.85 not 1.0), and an IBAN regex must allow whitespace grouping. Identical spans are deduplicated in regex → NER → LLM order. Other overlaps are resolved greedily by earlier start, then longer span, then source priority for ties. Regex does not always win against an earlier-starting LLM or NER span.

## 8. Testing property, not example

The Luhn bug (lesson 5) was caught because the test validated the *property* (full Luhn check) rather than a fixed example string. Same principle validated span alignment: tests assert `plain[k]` ↔ `source[k + delta]` as an invariant, not that `(6,26)` maps to `(6,26)` — which is only true when the coincidence allowed it.

## 9. When tests fail, re-derive the invariant before "fixing"

On two occasions, a failing test revealed the production code was right and the test was wrong (hand-computed spans). Caught because I re-derived the mapping by hand instead of trusting test failure as truth. In span-offset code, the failure rate of *hand arithmetic in tests* is high enough that tests here should be built structurally (find the prefix via `str.find`, derive lengths from the found quote) rather than hard-coded numbers.

## 10. Measure latency and recall on representative documents

The implementation loads `en_core_web_trf` lazily on CPU. An earlier development run reported roughly four seconds for the suite, but that is a historical observation without a recorded hardware/model baseline, not a current performance guarantee. First analysis also includes model loading.

Pass 2 processes overlapping 2,400-character chunks sequentially before regex + NER. Model choice, server availability, document length, and chunk count affect latency. Measure latency and detection recall on representative documents before changing models; no model-quality benchmark is checked into this repository.

## 11. Surface resolvability, don't hide it

The API returns `unresolved_render_edits` during analysis; expanded review rows show whether HTML spans resolve, and finalize emits warnings. TXT replacements still apply, but unresolved HTML text remains original. The `applied` count reflects selected spans, not proof that every HTML edit succeeded. Review output and warnings together.

## 12. Every `getElementById` is a contract with the HTML — enforce it

End-to-end testing caught three `null` derefs in a row (`html-preview`, `mapping-body`, then the removed Findings `findings-body`): `app.js` referenced IDs that `index.html` didn't define. The browser throws `Cannot read/set properties of null`, and each fix just exposed the next one. Lesson: after any static-UI change, check that every `getElementById` in `app.js` resolves to an `id=` in `index.html` — a one-line audit that would have caught all three at once.

## 13. A `try/catch` around render can hide the real failure by one click

`analyze()` wraps fetch + `renderResults()` in `try/catch`, so the first missing-element throw was swallowed into an `Analysis failed: ...` banner while the findings rows (appended before the throw) still showed — looking like success. The very next click (`refreshTable()` → `renderResults()` with no `try/catch`) surfaced the same bug as an uncaught error. When a render step can throw *after* partially mutating the DOM, the catch path misleads. Keep render side-effect-free until validated, or don't catch render errors as analysis errors.

## 14. Removed UI must die in the JS too, not just the HTML

The `html-preview` iframe was superseded by the final-output panel, but only the HTML was dropped — `app.js` kept reading/writing `srcdoc`, and `refreshTable()` even tried to *preserve* it. Dead code that touches the DOM isn't dead; it's a crash waiting for the next render path. When removing a widget, grep for its ID across `app.js`/`style.css` and delete every touchpoint (lookups, reads, writes, preservation logic).

## 15. Grouped review beats a flat findings list at CSV scale

Pasting CSV-scale text produced dozens of repeated quotes, so the flat Findings table duplicated the same decision per occurrence. Grouping by `(category, quote, replacement)` with bulk `Approve all` / `Reject all` plus `Approve/ Reject remaining` for the still-pending set cut review to one decision per unique value; expanding a group (`▸/▾`, collapsed by default) exposes the per-occurrence rows with full controls (source, confidence, resolvability, editable replacement). Rule: bulk at the group level, granular in the expansion — never two separate tables showing the same decisions.

## 16. `free_text` redaction is a requirement question, not a bug

`[REDACTED-<hash>]` appearing on user IDs looked wrong in testing but was working as designed: `namer.py` returns opaque placeholders for `free_text` because business-sensitive spans can't be faked realistically, and the Pass-2 prompt explicitly routes codenames/contract terms/internal names there. The fix was documentation (README + review hint) plus keeping the replacement editable — not changing the generator. When synthetic output looks "weird," check the category contract before touching the code.

## 17. Console noise triage: favicon is ours, content-scripts are not

Historically, `GET /favicon.ico 404` exposed a missing favicon. The current HTML references `/ObfuscatorShield.svg`, which is shipped in `app/static/`; a separate `/favicon.ico` request may still return 404. The historical `web-client-content-script.js ... Could not find identifiable element` stack referenced no repository file and was attributed to a browser extension. Search for the filename and reproduce in an extension-free window before assigning console errors to the app.

## 18. Review state must survive UI refreshes

Earlier table refreshes cleared diagnostics, and manual add repeated `/api/analyze`, potentially repeating LLM work. The current UI retains the analysis response in `reviewContext`, maintains suggestion decisions separately, and uses `/api/mapping-preview` to check exact occurrences and generate a replacement without detection.

Approving a custom detected replacement now retains the `edited` status needed to honor it at finalization. Group controls include manual mappings; rejecting one reopens its associated suggestions, and reapproving restores their mapped state. Bulk remaining actions still affect detected findings only. Review status, replacement value, and suggestion resolution must be updated together.

Replacement edits are saved to state on input without rebuilding the table on every keystroke or blur. Replacing the row during blur can remove the button the user is about to click and lose the intended action. Row controls retain their member references so regrouping after an edit does not target another mapping.

## 19. Deployment configuration is part of the privacy contract

Local setup needs `requirements-full.txt`, not skeleton-only `requirements.txt`. Compose requires a project-root `.env` and overrides its LLM base URL with `http://host.docker.internal:8888/v1`. Manual Docker must also set the host URL; the Python default points at container loopback inside Docker.

Compose currently publishes `8000:8000`, while the app has no authentication. Restrict it to `127.0.0.1:8000:8000` for machine-local access. No application database does not imply that the separate LLM server avoids logging. Preserved HTML attributes and skipped script/style content are outside obfuscation coverage.

## 20. Make manual verification a visible, complete review step

A manual mapping previously appeared approved with `[pending]` in its replacement column, while the server generated the replacement only at finalization. That prevented meaningful review. Manual mappings now preview their actual default replacement, allow editing, show exact occurrence counts and up to 20 contexts, and require explicit Save mapping.

Detected mappings and manual verification remain on one page, but numbered headings, section navigation with counts, and a distinct manual panel make both parts visible. Finalize requires both sections to be reviewed, nonblank active replacements, and no open manual form. Each unique suggestion requires Add Mapping or Dismiss; duplicates share a decision, and mapped suggestions link to their table row. Overlap statistics belong in Analysis details rather than repeating the manual-review heading.

Use reasons that describe the actual validation failure. A two-character quote may be present in the source yet fail the automatic minimum length check; that is not proof it cannot be found verbatim. Manual mappings can handle verified short quotes, but replace every exact occurrence, including substrings inside longer text.

## 21. Describe execution order separately from pass names

Pass 1 and Pass 2 are responsibility labels. Actual execution is serial: LLM chunks first, then regex and spaCy for ordinary text. For recognized CSV, the order after the LLM is spaCy batches followed by regex per unique decoded field value. Scanners inspect original content independently; the LLM does not consume earlier findings or rewrite text. Multiple LLM requests cover overlapping chunks, not iterative refinement of one answer.

CSV handling recognizes pasted plain text, not a file upload. Repeated decoded field values are scanned once and mapped back to all matching cells. Tab-separated Excel clipboard text is not recognized as CSV. Document supported input paths explicitly so users do not infer an upload control or spreadsheet-format support that is absent.

## Session verification — 2026-10-12

The suite passed with 62 tests and 12 subtests, including new manual-preview tests for matching/finalization parity, custom replacements, CSV and HTML input, missing quotes, and the 20-context limit. Browser checks used synthetic suggestions to verify duplicate grouping, bulk approval isolation, suggested person/free-text replacements, inline edits reaching output, empty replacement gating, and manual rejection reopening a suggestion. These checks validate application behavior, not live LLM detection quality.
