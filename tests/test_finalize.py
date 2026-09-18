from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    res = client.get("/api/health")
    assert res.status_code == 200 and res.json()["ok"]


def test_finalize_text_simple_flow():
    res = client.post(
        "/api/finalize",
        json={
            "text": "John Smith met jane@x.com.",
            "decisions": [
                {"start": 0, "end": 10, "quote": "John Smith", "category": "person", "status": "approved"},
                {"start": 15, "end": 25, "quote": "jane@x.com", "category": "email", "status": "approved"},
            ],
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["applied"] == 2
    assert "John Smith" not in data["txt"] and "jane@x.com" not in data["txt"]
    assert data["dropped"] == []


def test_finalize_reject_and_edit():
    res = client.post(
        "/api/finalize",
        json={
            "text": "John Smith met John Smith.",
            "decisions": [
                {"start": 0, "end": 10, "quote": "John Smith", "category": "person", "status": "rejected"},
                {"start": 15, "end": 25, "quote": "John Smith", "category": "person", "replacement": "My Edited Name", "status": "edited"},
            ],
        },
    )
    data = res.json()
    assert data["applied"] == 1
    assert data["txt"] == "John Smith met My Edited Name."
    assert any(d["reason"] == "rejected by reviewer" for d in data["dropped"])
    assert [m["replacement"] for m in data["mapping_table"]] == ["My Edited Name"]


def test_finalize_manual_quote_all_occurrences():
    res = client.post(
        "/api/finalize",
        json={
            "text": "Secret project. Secret project again.",
            "decisions": [
                {"start": None, "end": None, "quote": "Secret project", "category": "free_text", "status": "approved"},
            ],
        },
    )
    data = res.json()
    assert data["applied"] == 2
    assert "Secret project" not in data["txt"]
    replacements = {m["replacement"] for m in data["mapping_table"]}
    assert len(replacements) == 1
    assert next(iter(replacements)).startswith("[REDACTED-")


def test_finalize_manual_quote_missing_warns():
    res = client.post(
        "/api/finalize",
        json={
            "text": "nothing here",
            "decisions": [
                {"start": None, "end": None, "quote": "absent+z", "category": "free_text", "status": "approved"},
            ],
        },
    )
    data = res.json()
    assert data["applied"] == 0
    assert any("not found verbatim" in w for w in data["warnings"])


def test_finalize_html_flow_with_ingest_layer():
    src = "<p>John Smith met <b>John Smith</b>.</p>"
    res = client.post(
        "/api/finalize",
        json={
            "html": src,
            "decisions": [
                # The FIRST John Smith (inside text run, before <b>) is sanely replaced.
                {"start": 3, "end": 13, "quote": "John Smith", "category": "person", "status": "approved"},
            ],
        },
    )
    data = res.json()
    assert data["applied"] == 1
    assert "<p>" in data["html"]
    assert data["mapping_table"][0]["category"] == "person"
