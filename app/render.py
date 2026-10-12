"""Pass-1 merge, mapping table, and deterministic rendering."""
from .ingest import apply_plain_edits
from .pass1_regex import find as regex_find
from .pass1_ner import find as ner_find
from .pass1_ner import find_many as ner_find_many
from .namer import replacement_for
from .csv_text import csv_cells, csv_scan, filter_csv_findings, render_csv_edits

_SOURCE_PRIORITY = {"regex": 0, "spacy": 1, "llm": 2}


def _priority(finding: dict) -> int:
    source = finding.get("source", "")
    prefix = source.split("-")[0] if source else ""
    return _SOURCE_PRIORITY.get(prefix, 3)


def resolve_overlaps(findings: list) -> tuple:
    """Greedy: sort by (start, -length, priority); drop any finding that
    overlaps an already-kept one. Returns (kept, dropped)."""
    kept = []
    dropped = []
    cursor = -1
    for finding in sorted(
        findings, key=lambda f: (f["start"], -(f["end"] - f["start"]), _priority(f))
    ):
        if finding["start"] < cursor:
            dropped.append({**finding, "reason": "overlaps an earlier finding"})
            continue
        kept.append(finding)
        cursor = finding["end"]
    return kept, dropped


def merge_findings(plain_text: str, extra_findings: list | None = None) -> tuple:
    """Run regex + NER on plain text (plus optional Pass-2 findings), resolve
    overlaps, and attach a deterministic replacement to each kept finding.

    Returns (findings, dropped)."""
    scan = csv_scan(plain_text)
    if scan is None:
        pass1 = regex_find(plain_text) + ner_find(plain_text)
    else:
        decoded_findings = []
        ner_results = ner_find_many([unit.value for unit in scan.units])
        for unit, ner_hits in zip(scan.units, ner_results):
            for hit in regex_find(unit.value) + ner_hits:
                decoded_findings.append({**hit, "start": unit.start + hit["start"], "end": unit.start + hit["end"]})
        pass1, _ = scan.map_findings(decoded_findings)
    all_findings = pass1 + list(extra_findings or [])
    combined = []
    seen_cross = set()
    for f in all_findings:
        key = (f["start"], f["end"])
        if key in seen_cross:
            continue
        seen_cross.add(key)
        combined.append(f)
    combined, csv_skipped = filter_csv_findings(plain_text, combined)
    kept, dropped = resolve_overlaps(combined)
    dropped.extend(csv_skipped)
    for f in kept:
        f["replacement"] = replacement_for(f["category"], f["quote"])
    return kept, dropped


def build_mapping_table(findings: list) -> list:
    """Same quote -> same replacement, one entry per unique (category, quote)."""
    table = []
    index = {}
    for f in findings:
        key = (f["category"], f["quote"])
        if key not in index:
            index[key] = {
                "category": f["category"],
                "quote": f["quote"],
                "replacement": f["replacement"],
                "count": 0,
            }
            table.append(index[key])
        index[key]["count"] += 1
    return table


def render_outputs(src_html: str | None, plain_text: str, findings: list) -> tuple:
    """Apply replacements back-to-front.

    Returns (html, txt, unresolved_edits). When src_html is provided, HTML edits
    go through the ingest mapping layers (from step 2)."""
    edits = [
        {"start": f["start"], "end": f["end"], "replacement": f["replacement"]}
        for f in findings
        if f.get("replacement") is not None
    ]
    text_out = plain_text
    unresolved = []
    for edit in sorted(edits, key=lambda e: -e["start"]):
        text_out = text_out[: edit["start"]] + edit["replacement"] + text_out[edit["end"] :]
    cells = csv_cells(plain_text) if src_html is None else None
    if cells is not None:
        text_out = render_csv_edits(plain_text, cells, edits)
    if src_html is not None:
        html_out, unresolved, _ = apply_plain_edits(src_html, edits)
    else:
        html_out = None
    return html_out, text_out, unresolved
