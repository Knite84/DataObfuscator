from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .ingest import HtmlTextMap, apply_plain_edits
from .render import merge_findings, build_mapping_table, render_outputs
from .namer import replacement_for
from . import pass2_llm

app = FastAPI(title="Data Obfuscator", version="0.5.0")


class AnalyzeRequest(BaseModel):
    html: str | None = None
    text: str | None = None


class Decision(BaseModel):
    start: int | None = None          # plain-text offsets; None => manual quote
    end: int | None = None
    quote: str
    category: str
    replacement: str | None = None
    status: str                        # approved | edited | rejected
    source: str | None = None


class FinalizeRequest(BaseModel):
    html: str | None = None
    text: str | None = None
    decisions: list[Decision] = []


def _highlight_preview(src: str, findings: list) -> str:
    edits = [
        {"start": f["start"], "end": f["end"], "replacement": f"<mark>{f['quote']}</mark>"}
        for f in findings
        if f.get("source_span") is not None
    ]
    if not edits:
        return src
    new_src, _unresolved, _plain = apply_plain_edits(src, edits)
    return new_src


@app.get("/api/health")
def health():
    llm = pass2_llm.probe()
    model = pass2_llm.model_id(llm)
    return {
        "ok": True,
        "passes": ["regex", "spacy_ner", "llm" if llm.get("ready") else "llm_unavailable"],
        "llm": {**llm, "model": model},
    }


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest) -> dict:
    src = req.html if req.html else None
    if src is not None:
        html_map = HtmlTextMap.from_html(src)
        plain = html_map.plain_text
    else:
        plain = req.text or ""
    pass2_findings, llm_unverified, llm_errors = pass2_llm.detect(plain)
    findings, dropped = merge_findings(plain, pass2_findings)
    if src is not None:
        for f in findings:
            f["source_span"] = html_map.source_span_for_plain_span(f["start"], f["end"])
        preview = _highlight_preview(src, findings)
    else:
        preview = None
    mapping_table = build_mapping_table(findings)
    html_out, txt_out, render_unresolved = render_outputs(src, plain, findings)
    return {
        "plain_text": plain,
        "findings": findings,
        "mapping_table": mapping_table,
        "dropped": dropped,
        "html_preview": preview,
        "txt_preview": txt_out,
        "html_out": html_out,
        "unresolved_render_edits": render_unresolved,
        "llm_unverified": llm_unverified,
        "llm_errors": llm_errors,
    }


@app.post("/api/finalize")
def finalize(req: FinalizeRequest) -> dict:
    src = req.html if req.html else None
    if src is not None:
        html_map = HtmlTextMap.from_html(src)
        plain = html_map.plain_text
    else:
        plain = req.text or ""

    selected = []
    dropped = []
    warnings = []
    for decision in req.decisions:
        if decision.status == "rejected":
            dropped.append({"quote": decision.quote, "reason": "rejected by reviewer"})
            continue
        edit = {"quote": decision.quote, "category": decision.category}
        if decision.start is None or decision.start < 0:
            # Manual review add: map the quote to ALL verbatim occurrences.
            replacement = decision.replacement or replacement_for(decision.category, decision.quote)
            search_at = 0
            occurrences = 0
            while True:
                idx = plain.find(decision.quote, search_at)
                if idx == -1:
                    break
                occurrences += 1
                selected.append(
                    {
                        "start": idx,
                        "end": idx + len(decision.quote),
                        "quote": decision.quote,
                        "category": decision.category,
                        "replacement": replacement,
                        "source": decision.source or "manual",
                        "confidence": 1.0,
                    }
                )
                search_at = idx + len(decision.quote)
            if occurrences == 0:
                warnings.append(f"manual quote not found verbatim: {decision.quote[:60]!r}")
            continue
        replacement = decision.replacement if (decision.status == "edited" and decision.replacement) else replacement_for(decision.category, decision.quote)
        # Prefer the span the review was made on; fall back to verbatim search
        # (safety for drifted quotes).
        matched_span = None
        if decision.start is not None and decision.end is not None and plain[decision.start : decision.end] == decision.quote:
            matched_span = (decision.start, decision.end)
        if matched_span is None:
            idx = plain.find(decision.quote)
            if idx == -1:
                warnings.append(f"could not resolve {decision.quote[:60]!r} in text; skipped")
                continue
            matched_span = (idx, idx + len(decision.quote))
        selected.append(
            {
                "start": matched_span[0],
                "end": matched_span[1],
                "quote": decision.quote,
                "category": decision.category,
                "replacement": replacement,
                "source": decision.source or "review",
                "confidence": 1.0,
            }
        )

    # Overlap safety on final selections (longest span wins).
    ordered = sorted(selected, key=lambda f: (f["start"], -(f["end"] - f["start"])))
    final = []
    cursor = -1
    for f in ordered:
        if f["start"] < cursor:
            dropped.append({"quote": f["quote"], "reason": "overlaps another final selection"})
            continue
        final.append(f)
        cursor = f["end"]

    mapping_table = build_mapping_table(final)
    html_out, txt_out, unresolved = render_outputs(src, plain, final)
    if unresolved:
        warnings.extend(f"unresolved span {u['start']}-{u['end']}" for u in unresolved)
    return {
        "html": html_out,
        "txt": txt_out,
        "mapping_table": mapping_table,
        "applied": len(final),
        "dropped": dropped,
        "warnings": warnings,
    }


app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
