"""Deterministic synthetic replacement generator.

Same source string -> same replacement, forever: selection is driven by a
SHA-1 hash of the (source, category) pair — no state, no storage. This also
means replacements stay consistent across sessions and restarts.

Value style per category:
- person  : realistic first/last name from built-in open pools
- org     : plausible company name
- place   : plausible city name
- email   : fictional mailbox on example.net
- phone   : fictional (555) 01xx range (reserved for fiction in NANP)
- national_id : SSA-never-issued 9xx range
- financial/finaid : Luhn-valid test card numbers
- url / account_id : example.com / fictional IBAN
"""
import hashlib
from .pools import (
    FIRST_NAMES,
    LAST_NAMES,
    ORG_PREFIXES,
    ORG_SUFFIXES,
    CITIES,
)

_fallback = "person"


def _stream(source: str):
    seed = int.from_bytes(hashlib.sha1(source.encode("utf-8")).digest()[:8], "big")
    while True:
        yield seed & 0xFFFFFFFF
        seed = seed * 1103515245 + 12345 & 0xFFFFFFFF


def _take(source: str, n: int) -> int:
    return next(iter(__import__("itertools").islice(_stream(source), n, n + 1)))


def _pick(pool, source: str, salt: str = "") -> str:
    return pool[_take(source or salt, 32) % len(pool)]


def replacement_for(category: str, source: str) -> str:
    if category == "person":
        first = _pick(FIRST_NAMES, source, "first")
        last = _pick(LAST_NAMES, source, "last")
        return f"{first} {last}"
    if category == "org":
        return f"{_pick(ORG_PREFIXES, source, 'org')} {_pick(ORG_SUFFIXES, source, 'orgsfx')}"
    if category == "place":
        return _pick(CITIES, source, "place")
    if category == "email":
        first = _pick(FIRST_NAMES, source, "first").lower()
        last = _pick(LAST_NAMES, source, "last").lower()
        raw = f"{first}.{last}"
        n = _take(source or "email", 64)
        return f"{raw}{n % 100}@example.net"
    if category == "phone":
        n = _take(source or "phone", 64)
        return f"(555) {100 + (n % 900):03d}-{(n >> 10) % 10000:04d}"
    if category == "national_id":
        n = _take(source or "nid", 64)
        d = f"9{n % 100_000_000:08d}"
        return f"{d[:3]}-{d[3:5]}-{d[5:9]}"
    if category == "financial":
        n = _take(source or "card", 128)
        digits = "4" + f"{n % 10**14:014d}"
        s = 0
        for i, d in enumerate(digits):
            v = int(d)
            if i % 2 == 0:
                v *= 2
                if v > 9:
                    v -= 9
            s += v
        digits = digits + str((10 - (s % 10)) % 10)
        return " ".join(digits[i : i + 4] for i in range(0, 16, 4))
    if category == "account_id":
        n = _take(source or "iban", 96)
        body = f"{n:022d}"[:22]
        return f"XX{body[:2]} {body[2:6]} {body[6:10]} {body[10:14]} {body[14:18]} {body[18:22]}"
    if category == "url":
        n = _take(source or "url", 64)
        slug = f"{_pick(ORG_PREFIXES, source, 'url')}{n % 1000}".lower()
        return f"https://{slug}.example.com"
    if category == "free_text":
        # Business-sensitive free text cannot be faked realistically; use an
        # opaque, deterministic placeholder tagged with a short hash so the
        # reviewer can see which spans came from the same source string.
        tag = hashlib.sha1((source or "").encode("utf-8")).hexdigest()[:6]
        return f"[REDACTED-{tag}]"
    return replacement_for(_fallback, source)
