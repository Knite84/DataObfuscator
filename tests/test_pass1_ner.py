import pytest

spacy = pytest.importorskip("spacy")

from app.pass1_ner import find  # noqa: E402

try:
    import en_core_web_trf  # noqa: F401

    HAS_MODEL = True
except Exception:
    HAS_MODEL = False


@pytest.mark.skipif(not HAS_MODEL, reason="en_core_web_trf not installed")
def test_person_detection():
    text = "Contact Jane Doe about accounts; she met John Smith on Thursday."
    hits = find(text)
    persons = {h["quote"]: h["category"] for h in hits if h["category"] == "person"}
    assert "Jane Doe" in persons and "John Smith" in persons
    en_core_map = find(text)
    for h in en_core_map:
        assert h["quote"] is not None


@pytest.mark.skipif(not HAS_MODEL, reason="en_core_web_trf not installed")
def test_dates_and_times_ignored():
    text = "Contact Jane Doe on 12 March."
    hits = find(text)
    assert not [h for h in hits if h["category"] not in ("person",)]
