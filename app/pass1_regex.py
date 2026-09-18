import re

EMAIL = re.compile(r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b", re.IGNORECASE)
PHONE = re.compile(
    r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]?\d{4}"
)
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
URL = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", re.IGNORECASE)
CREDIT_CARD = re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{2,4}){3,7}\b")

_PATTERNS = (
    (EMAIL, "email", 1.0),
    (URL, "url", 0.95),
    (IBAN, "account_id", 0.95),
    (CREDIT_CARD, "financial", 0.95),
    (SSN, "national_id", 1.0),
    (PHONE, "phone", 0.85),
)


def find(text: str) -> list:
    hits = []
    seen_spans = set()
    for pattern, category, confidence in _PATTERNS:
        for match in pattern.finditer(text):
            span = (match.start(), match.end())
            if span in seen_spans:
                continue
            seen_spans.add(span)
            hits.append(
                {
                    "start": match.start(),
                    "end": match.end(),
                    "quote": match.group(0),
                    "category": category,
                    "source": "regex",
                    "confidence": confidence,
                }
            )
    hits.sort(key=lambda h: (h["start"], -(h["end"] - h["start"])))
    return hits
