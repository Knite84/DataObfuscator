"""Pass 1b: spaCy NER findings."""
import spacy

_LABEL_MAP = {
    "PERSON": ("person", 0.90),
    "ORG": ("org", 0.85),
    "GPE": ("place", 0.85),
    "LOC": ("place", 0.80),
    "FAC": ("place", 0.80),
}

_MODEL_NAME = "en_core_web_trf"
_model = None


def _get_model():
    global _model
    if _model is None:
        spacy.require_cpu()
        _model = spacy.load(_MODEL_NAME)
    return _model


def find(text: str) -> list:
    doc = _get_model()(text)
    hits = []
    for ent in doc.ents:
        label = ent.label_
        if label not in _LABEL_MAP:
            continue
        category, confidence = _LABEL_MAP[label]
        quote = ent.text
        stripped = quote.strip()
        if len(stripped) < 3:
            continue
        if "@" in stripped and category in ("org", "place"):
            continue
        delta = quote.index(stripped) if quote != stripped else 0
        start = ent.start_char + delta
        end = start + len(stripped)
        hits.append(
            {
                "start": start,
                "end": end,
                "quote": stripped,
                "category": category,
                "source": "spacy-" + _MODEL_NAME,
                "confidence": confidence,
            }
        )
    hits.sort(key=lambda h: (h["start"], -(h["end"] - h["start"])))
    return hits
