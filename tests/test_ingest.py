from app.ingest import HtmlTextMap, apply_plain_edits


def test_text_run_verbatim_and_offsets_1to1():
    src = "<p>Email jane.doe@example.com or call (555) 123-4567.</p>"
    html_map = HtmlTextMap.from_html(src)
    assert html_map.plain_text == "Email jane.doe@example.com or call (555) 123-4567.\n"
    span = html_map.source_span_for_plain_span(6, 26)
    assert span == (9, 29)
    assert src[9:29] == "jane.doe@example.com"


def test_entities_kept_verbatim():
    src = "<p>Card &amp; IBAN DE89 3704 0044 0532 0130 00.</p>"
    html_map = HtmlTextMap.from_html(src)
    assert html_map.plain_text == "Card &amp; IBAN DE89 3704 0044 0532 0130 00.\n"


def test_newlines_from_block_tags_and_br():
    src = "<p>A</p><p>B<br>C</p>"
    html_map = HtmlTextMap.from_html(src)
    assert html_map.plain_text == "A\nB\nC\n"


def test_script_and_style_skipped():
    src = "<script>var x = 123-45-6789;</script><style>.x{color:#fff}</style><p>Safe text here</p>"
    html_map = HtmlTextMap.from_html(src)
    assert html_map.plain_text == "Safe text here\n"
    assert "6789" not in html_map.plain_text


def test_spans_across_tags_do_not_resolve():
    src = "<h2>Summary</h2><p>Card 4111 <b>1111</b> contact <a>x@y.com</a> done.</p>"
    html_map = HtmlTextMap.from_html(src)
    plain = html_map.plain_text  # "Summary\nCard 4111 1111 contact x@y.com done.\n"
    start = plain.find("Card")
    end = plain.find("1111 ") + len("1111 ")  # crosses the <b> boundary
    assert plain[start:end] == "Card 4111 1111 "
    assert html_map.source_span_for_plain_span(start, end) is None
    email_index = plain.find("x@y.com")
    span = html_map.source_span_for_plain_span(email_index, email_index + len("x@y.com"))
    assert span is not None
    assert html_map.src[span[0] : span[1]] == "x@y.com"


def test_apply_plain_edits_single():
    src = "<p>Call (555) 123-4567 today.</p>"
    resolved, unresolved, plain = apply_plain_edits(src, [{"start": 1, "end": 2, "replacement": "X"}])
    assert unresolved == []
    assert resolved == "<p>CXll (555) 123-4567 today.</p>"


def test_apply_multiple_back_to_front():
    src = "<p>Call (555) 123-4567 or (555) 999-8888.</p>"
    html_map = HtmlTextMap.from_html(src)
    first = html_map.plain_text.find("(555) 123-4567")
    second = html_map.plain_text.find("(555) 999-8888")
    edits = [
        {"start": first, "end": first + len("(555) 123-4567"), "replacement": "REDACTED"},
        {"start": second, "end": second + len("(555) 999-8888"), "replacement": "REDACTED"},
    ]
    resolved, unresolved, plain = apply_plain_edits(src, edits)
    assert unresolved == []
    assert resolved == "<p>Call REDACTED or REDACTED.</p>"


def test_apply_reports_unresolved():
    src = "<p>Card 4111 <b>1111</b> done.</p>"
    html_map = HtmlTextMap.from_html(src)
    plain = html_map.plain_text
    start = plain.find("Card")
    end = plain.find("1111 ") + len("1111 ")
    resolved, unresolved, _ = apply_plain_edits(src, [{"start": start, "end": end, "replacement": "X"}])
    assert resolved == src
    assert len(unresolved) == 1
    assert unresolved[0]["reason"] == "span crosses multiple text runs"
