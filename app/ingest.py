"""HTML -> plain-text mapping with a deterministic, regex-based tag tokenizer.

Documented trade-offs:
- Entities (e.g. `&amp;`) are kept VERBATIM in the plain text. Plain-text
  offsets stay 1:1 with source offsets inside every text node, which makes
  span alignment exact. Detection sees the entity sequence rather than the
  decoded character — acceptable for PII finding.
- Tags are matched with `<[^>]+>`; `>` inside quoted attribute values is a
  known practical limitation.
- `<br>`, `<hr>`, and closing `p/div/h1..h6/li/tr/blockquote/section/article`
  insert one newline into the plain text.
- Content of `<script>` and `<style>` is skipped entirely (mapped as "skip").

A plain-text span that is not fully inside ONE text segment (crosses a
newline or skipped run) is returned as unresolved rather than guessed.
"""

from dataclasses import dataclass, field
import re

BLOCK_CLOSING = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "section", "article"}
VOID_LINEBREAK = {"br", "hr"}
SKIP_CONTENT = {"script", "style"}

_TAG_RE = re.compile(r"<[^>]*>")
_NAME_RE = re.compile(r"<\s*/?\s*([a-zA-Z][a-zA-Z0-9]*)")


@dataclass
class Segment:
    start: int          # plain-text offset
    end: int
    source_start: int   # offset in the original HTML string
    source_end: int
    kind: str           # "text" | "newline" | "skip"


@dataclass
class HtmlTextMap:
    src: str
    plain_text: str
    segments: list = field(default_factory=list)

    @classmethod
    def from_html(cls, src: str) -> "HtmlTextMap":
        segments = list(_scan(src))
        canonical = []
        plain_cursor = 0
        for seg in segments:
            if seg.kind == "text":
                canonical.append(Segment(plain_cursor, plain_cursor + seg.end - seg.start, seg.source_start, seg.source_end, "text"))
                plain_cursor += seg.end - seg.start
            elif seg.kind == "newline":
                canonical.append(Segment(plain_cursor, plain_cursor + 1, seg.source_start, seg.source_end, "newline"))
                plain_cursor += 1
            else:
                canonical.append(Segment(plain_cursor, plain_cursor, seg.source_start, seg.source_end, "skip"))
        plain_text = "".join(
            src[s.source_start: s.source_end] if s.kind == "text" else "\n"
            for s in canonical
            if s.kind in ("text", "newline")
        )
        return cls(src=src, plain_text=plain_text, segments=canonical)

    def source_span_for_plain_span(self, start: int, end: int):
        """Align a plain-text span into the original HTML string.

        Returns (source_start, source_end), or None when the span is not
        fully contained in ONE text segment (crosses tags/newlines).
        """
        if end <= start:
            return None
        for seg in self.segments:
            if seg.kind == "text" and start >= seg.start and end <= seg.end:
                delta = seg.source_start - seg.start
                return start + delta, end + delta
        return None


def _scan(src: str):
    """Yield raw Segments: text runs verbatim (source span == text span),
    newline-producing tags, and all tags (mapped as skip)."""
    out = []
    plain_cursor = 0
    skip = None
    last_tag_end = 0
    any_tag = False
    for m in _TAG_RE.finditer(src):
        any_tag = True
        name_match = _NAME_RE.match(m.group(0))
        name = name_match.group(1).lower() if name_match else ""
        is_closing = m.group(0).startswith("</")
        if skip is not None:
            if is_closing and name == skip:
                skip = None
            last_tag_end = m.end()
            out.append(Segment(plain_cursor, plain_cursor, m.start(), m.end(), "skip"))
            continue
        head = src[last_tag_end: m.start()]
        if head:
            out.append(Segment(plain_cursor, plain_cursor + len(head), last_tag_end, m.start(), "text"))
            plain_cursor += len(head)
        if not is_closing and name in SKIP_CONTENT:
            skip = name
        elif name in VOID_LINEBREAK or (is_closing and name in BLOCK_CLOSING):
            out.append(Segment(plain_cursor, plain_cursor + 1, m.start(), m.end(), "newline"))
            plain_cursor += 1
        last_tag_end = m.end()
    tail = src[last_tag_end:]
    if not any_tag:
        out.append(Segment(0, len(src), 0, len(src), "text"))
    elif tail and skip is None:
        out.append(Segment(plain_cursor, plain_cursor + len(tail), last_tag_end, len(src), "text"))
    return out


def apply_plain_edits(src: str, edits: list) -> tuple:
    """edits: [{start, end, replacement}] in plain-text coordinates.

    Returns (new_src, unresolved_edits, plain_text). Resolved edits are applied
    to the original HTML string back-to-front; an edit is unresolved when its
    span is not fully inside ONE text segment.
    """
    html_map = HtmlTextMap.from_html(src)
    resolved = []
    unresolved = []
    for edit in edits:
        span = html_map.source_span_for_plain_span(edit["start"], edit["end"])
        if span is None:
            unresolved.append({**edit, "reason": "span crosses multiple text runs"})
            continue
        resolved.append((span[0], span[1], edit["replacement"]))
    new_src = src
    for source_start, source_end, replacement in sorted(resolved, key=lambda r: -r[0]):
        new_src = new_src[: source_start] + replacement + new_src[source_end:]
    return new_src, unresolved, html_map.plain_text
