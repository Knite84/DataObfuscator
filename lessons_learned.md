# Lessons Learned — Data Obfuscator

Practical notes captured while building steps 1–3, written down so we don't pay for them twice.

## 1. Offset alignment is the whole game

The single most important architectural decision so far: **detection always happens on plain text with exact character offsets, and every decision maps back to spans deterministically.** Once we had that invariant, regex passes, NER, mapping tables, and rendering all compose cleanly without string surgery in unexpected places.

The key trick for HTML: keep entity sequences (`&amp;`) VERBATIM in the plain text instead of decoding them. That makes plain-text offsets 1:1 with source offsets within every text node — alignment becomes trivial arithmetic instead of an entity-width tracking problem. Trade-off: detection sees `&amp;` literally; acceptable for PII finding, and honestly stated in the README.

## 2. Write generation code only after the design is settled — or you write garbage

Twice during step 2 and step 3, `app/ingest.py` and `tests/` ended up with half-experimented code (`if False` branches, dead helpers, placeholder tests) because I started typing before committing to a design on paper. The fix was always the same: throw the file away, write a short design header in the module docstring, THEN write the implementation once. Regex-based tag tokenization + raw-segment scan + a canonical re-basing pass was the clean final shape — it took three attempts to arrive at writing that file in a single pass.

Rule of thumb going forward: **if a file needs a `# placeholder removed below` comment, it's not done — stop and rewrite it from its docstring.**

## 3. HTMLParser was the wrong tool for offset maps

First instinct was `html.parser.HTMLParser` for step 2. Its byte-level anchoring (via `getpos()`) is ambiguous for entity events, and mixing decoded values with source offsets gets messy fast. A hand-rolled regex tag tokenizer (`<[^>]+>` + `_scan`) with explicit trade-offs (documented: `>` inside attribute values is a known limitation) turned out simpler, fully deterministic, and 40 lines long. For structured HTML→spans work, prefer the smallest mechanism you can fully reason about.

## 4. Determinism gives consistency for free — hash, don't store

Requirement: same source string → same replacement for every occurrence. The naive way is a session-scoped dict; the better way is making replacement a pure function: `replacement_for(category, source) = pick_from_pool(sha1(source + category))`. Benefits that fell out:

- consistency across sessions and restarts, no persistence layer needed (matching the "no data persistence" requirement anyway)
- tests can assert determinism with no setup
- user-edited replacements later (step 5) can simply override entries in the table; the default remains hash-based

## 5. Encode safety *styles* into generators, not documentation

Synthetic values are deliberately drawn from reserved or never-issued ranges: NANP `555-01xx`, SSA `9xx` group, Luhn-valid cards built only from `4...` test-style payloads, `example.net`/`example.com` domains. These can never reach a real person, and this is enforced in code, not promised in comments. (One real bug: a modulus typo produced a 17-digit "card" that broke Luhn validation — caught immediately by a test that asserted the full Luhn property, not just length.)

## 6. Confidence tiers encode *who is trusted*

Regex hits: 0.85–1.00 (high precision). NER: capped at 0.90 so common NER false positives (dates-as-persons, org names inside emails) fall below the 0.85 review threshold planned for step 5. This "trust tier" pattern is cheap: it means the review queue is automatically populated by *lower* confidence signals rather than by ad-hoc flags. Expect to tune the boundary once Pass-2 LLM scores join the same scale in step 4.

## 7. Regex confidences have surprises hiding in ranges

Two test-driven adjustments: phone patterns are inherently noisy (they also match card segments and random digit runs, hence 0.85 not 1.0), and an IBAN regex must allow whitespace grouping to match realistic formatted IBANs. Overlap resolution (regex wins, longer-span wins) handles the cases where both categories claim the same span.

## 8. Testing property, not example

The Luhn bug (lesson 5) was caught because the test validated the *property* (full Luhn check) rather than a fixed example string. Same principle validated span alignment: tests assert `plain[k]` ↔ `source[k + delta]` as an invariant, not that `(6,26)` maps to `(6,26)` — which is only true when the coincidence allowed it.

## 9. When tests fail, re-derive the invariant before "fixing"

On two occasions, a failing test revealed the production code was right and the test was wrong (hand-computed spans). Caught because I re-derived the mapping by hand instead of trusting test failure as truth. In span-offset code, the failure rate of *hand arithmetic in tests* is high enough that tests here should be built structurally (find the prefix via `str.find`, derive lengths from the found quote) rather than hard-coded numbers.

## 10. Speed matters more than size below 1B params

`en_core_web_trf` (457 MB + torch download) loads and runs on CPU at ~4s for the full test suite at document scale. Don't pre-optimize by reaching for `en_core_web_md`; revisit only if real documents show latency problems. Same expected principle for step 4: a gemma-class quant served by LM Studio is plenty for detection-sized prompts at this text scale; don't reach for a bigger local model until detection recall on real documents says so.

## 11. Surface resolvability, don't hide it

Making "Resolves?" a UI column and returning `unresolved_render_edits` alongside every render keeps silent failures out of the pipeline. A tool whose whole job is replacing text exactly where it was found must never quietly drop an edit — those need to become human review items (step 5), not disappearing failures.

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

`GET /favicon.ico 404` is a real (cosmetic) gap — no favicon shipped in `app/static/`. The `web-client-content-script.js ... Could not find identifiable element` stack, by contrast, exists nowhere in the repo and comes from a browser extension re-scanning the DOM on every approve. Verify by searching the repo for the filename, then confirm in an extension-free window before spending any effort.
