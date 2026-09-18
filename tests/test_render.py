from app.render import resolve_overlaps, merge_findings, build_mapping_table, render_outputs
from app.ingest import HtmlTextMap


def _f(start, end, quote, category, source="t", conf=0.9):
    return {"start": start, "end": end, "quote": quote, "category": category, "source": source, "confidence": conf}


def test_regex_wins_by_priority_in_overlap_resolution():
    fa = _f(8, 28, "jane.doe@example.com", "email", source="regex", conf=1.0)
    fb = _f(14, 22, "example.com", "place", source="spacy-en_core_web_trf")
    kept, dropped = resolve_overlaps([fb, fa])
    dropped_quotes = [f["quote"] for f in dropped]
    assert {f["quote"] for f in kept} == {fa["quote"]}
    assert fb["quote"] in dropped_quotes


def test_merge_findings_attaches_deterministic_replacements():
    text = "Contact Jane Doe at jane@x.com — call John Smith too."
    combined, _dropped = merge_findings(text)
    johns = [f for f in combined if f["quote"] == "John Smith"]
    assert len(johns) == 1
    john_replacement = johns[0]["replacement"]
    combined2, _ = merge_findings(text)
    johns2 = [f for f in combined2 if f["quote"] == "John Smith"]
    assert johns2[0]["replacement"] == john_replacement
    assert all(f.get("replacement") for f in combined)


def test_mapping_table_counts_consistent_replacements():
    text = "John Smith met John Smith once."
    combined, _ = merge_findings(text)
    table = build_mapping_table(combined)
    entry = [m for m in table if m["quote"] == "John Smith"][0]
    assert entry["count"] == 2
    occurrences = [f for f in combined if f["quote"] == "John Smith"]
    assert {occ["replacement"] for occ in occurrences} == {entry["replacement"]}


def test_render_txt_replaces_duplicate_instances():
    text = "John Smith met John Smith."
    combined, _ = merge_findings(text)
    mapping = build_mapping_table(combined)
    replacement = [m for m in mapping if m["quote"] == "John Smith"][0]["replacement"]
    _html, txt, unresolved = render_outputs(None, text, combined)
    assert unresolved == []
    assert txt.count(replacement) == 2 and "John Smith" not in txt


def test_render_html_through_ingest_layer():
    src = "<p>John Smith met John Smith twice.</p>"
    # Render HTML through the apply-plain-edits path (step 2 pipeline).
    html_map = HtmlTextMap.from_html(src)
    combined, _ = merge_findings(html_map.plain_text)
    mapping = build_mapping_table(combined)
    replacement = [m for m in mapping if m["quote"] == "John Smith"][0]["replacement"]
    for f in combined:
        f["source_span"] = html_map.source_span_for_plain_span(f["start"], f["end"])
    html_out, _txt, unresolved = render_outputs(src, html_map.plain_text, combined)
    assert unresolved == []
    assert html_out.count(replacement) == 2 and "John Smith" not in html_out
    assert html_out.startswith("<p>") and html_out.endswith("</p>")
