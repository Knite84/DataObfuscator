from fastapi.testclient import TestClient

from app.main import app
from app.namer import replacement_for

client = TestClient(app)


def test_preview_matches_finalize_without_running_detection(monkeypatch):
    def unexpected(*args):
        raise AssertionError("Manual preview must not rerun detection")

    monkeypatch.setattr("app.pass2_llm.detect", unexpected)
    source = "AA met KF. AA again."
    preview = client.post("/api/mapping-preview", json={
        "text": source, "quote": "AA", "category": "person",
    }).json()
    assert preview["count"] == 2
    assert len(preview["contexts"]) == 2
    assert preview["replacement"] == replacement_for("person", "AA")
    final = client.post("/api/finalize", json={"text": source, "decisions": [{
        "quote": "AA", "category": "person", "replacement": "Custom initials",
        "status": "edited", "source": "manual",
    }]}).json()
    assert final["applied"] == preview["count"]
    assert final["txt"] == "Custom initials met KF. Custom initials again."


def test_preview_decoded_csv_and_html():
    for source in [
        {"text": 'name,note\nAA,"AA said ""hello"""'},
        {"html": "<p><b>AA</b> met <i>AA</i>.</p>"},
    ]:
        preview = client.post("/api/mapping-preview", json={
            **source, "quote": "AA", "category": "free_text",
        }).json()
        final = client.post("/api/finalize", json={**source, "decisions": [{
            "quote": "AA", "category": "free_text", "status": "approved",
        }]}).json()
        assert preview["count"] == final["applied"] == 2
        assert preview["replacement"].startswith("[REDACTED-")


def test_preview_missing_empty_and_limited_contexts():
    for quote in ["", "missing"]:
        data = client.post("/api/mapping-preview", json={
            "text": "AA", "quote": quote, "category": "person",
        }).json()
        assert data["count"] == 0 and data["contexts"] == []
    data = client.post("/api/mapping-preview", json={
        "text": "AA " * 30, "quote": "AA", "category": "person",
    }).json()
    assert data["count"] == 30 and len(data["contexts"]) == 20
