import json

import httpx
import pytest

from app import pass2_llm


def _client_for(reply: str):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert request.headers.get("Authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

    return httpx.Client(
        base_url=pass2_llm.base_url(),
        headers=pass2_llm._headers(),
        timeout=(5, 30),
        transport=httpx.MockTransport(handler),
    )


_REPLY = {"client": None}


def set_fake_reply(reply: str):
    _REPLY["client"] = _client_for(reply)


@pytest.fixture(autouse=True)
def _inject_fake(monkeypatch):
    monkeypatch.setattr(pass2_llm, "_get_client", lambda: _REPLY["client"])
    yield
    _REPLY["client"] = None


def test_chunking_exact_slices_and_overlap():
    text = "abcdefghij" * 100  # 1000 chars
    chunks = pass2_llm.chunk_text(text, size=400, overlap=100)
    for start, end, chunk in chunks:
        assert chunk == text[start:end]
    assert chunks[0][0] == 0 and chunks[-1][1] == len(text)
    # Coverage with no window gap:
    for (s1, e1, _), (s2, _e2, _c2) in zip(chunks, chunks[1:]):
        assert s2 < e1


def test_json_parsing_tolerant():
    assert pass2_llm.parse_json_array("```json\n[]\n```") == []
    raw = 'Sure! Here you go:\n[{"quote": "Widget X", "category": "free_text", "confidence": 0.8, "reason": "codename"}]\nHope that helps.'
    items = pass2_llm.parse_json_array(raw)
    assert items[0]["quote"] == "Widget X"
    with pytest.raises(ValueError):
        pass2_llm.parse_json_array("no json here")


def test_quote_mapping_absolute_offsets_and_duplicates():
    chunk = "Project Bluebird launches with Widget X and Widget X lite."
    offset = 1200
    items = [
        {"quote": "Widget X", "category": "free_text", "confidence": 0.8, "reason": "codename"},
        {"quote": "Project Bluebird", "category": "free_text", "confidence": 0.8, "reason": "project"},
        {"quote": "not-present-anywhere", "category": "free_text", "confidence": 0.8, "reason": "hallucination"},
    ]
    findings, unverified = pass2_llm.map_quotes(offset, chunk, items)
    widget = [f for f in findings if f["quote"] == "Widget X"]
    assert len(widget) == 2
    for f in widget:
        assert chunk[f["start"] - offset : f["end"] - offset] == "Widget X"
    assert widget[0]["confidence"] < 0.80
    assert len(unverified) == 1
    assert unverified[0]["quote"] == "not-present-anywhere"
    assert unverified[0]["mapping_reason"] == "quote not found verbatim in text"


def test_detect_marks_source_llm_and_dedupes():
    text = "Widget X ships in Q3. Widget X is confidential."
    reply = json.dumps(
        [
            {"quote": "Widget X", "category": "free_text", "confidence": 0.8, "reason": "codename"},
            {"quote": "Widget X", "category": "free_text", "confidence": 0.8, "reason": "codename"},
        ]
    )
    set_fake_reply(reply)
    findings, unverified, errors = pass2_llm.detect(text)
    assert errors == []
    assert unverified == []
    for f in findings:
        assert f["source"] == "llm"
        assert text[f["start"] : f["end"]] == "Widget X"
    assert len(findings) == 2


def test_detect_reports_unavailable_server(monkeypatch):
    monkeypatch.setattr(pass2_llm, "probe", lambda: {"ready": False, "detail": "connection refused"})
    findings, _unverified, errors = pass2_llm.detect("Widget X is confidential.")
    assert findings == []
    assert errors == ["llm unavailable: connection refused"]


def test_merge_priority_regex_beats_llm():
    from app.render import resolve_overlaps

    regex_f = {"start": 8, "end": 20, "quote": "jane@x.com", "category": "email", "source": "regex", "confidence": 1.0}
    llm_f = {"start": 10, "end": 18, "quote": "jane@x.com", "category": "person", "source": "llm", "confidence": 0.5}
    kept, dropped = resolve_overlaps([llm_f, regex_f])
    assert {f["source"] for f in kept} == {"regex"}
    assert dropped[0]["source"] == "llm"


def test_free_text_replacement_deterministic_and_tagged():
    from app.namer import replacement_for

    before = replacement_for("free_text", "Project Bluebird")
    assert replacement_for("free_text", "Project Bluebird") == before
    assert before.startswith("[REDACTED-") and before.endswith("]")
    assert len(before) == len("[REDACTED-XXXXXX]")
    assert replacement_for("free_text", "Widget X") != before


def test_real_payload_with_fakes_produces_findings():
    text = "Internal only: Widget X launches next month per General Manager."
    reply = json.dumps(
        [
            {"quote": "Widget X", "category": "free_text", "confidence": 0.9, "reason": "codename"},
            {"quote": "General Manager", "category": "person", "confidence": 0.7, "reason": "role noee; generic role dropped"},
        ]
    )
    set_fake_reply(reply)
    findings, _unverified, _errors = pass2_llm.detect(text)
    from app.render import merge_findings, build_mapping_table

    merged, dropped = merge_findings(text, findings)
    table = build_mapping_table(merged)
    assert any(m["category"] == "free_text" for m in table)
    for m in table:
        assert m["count"] >= 1
