"""Recognize CSV text and keep replacements inside fields without changing syntax."""
from dataclasses import dataclass


@dataclass(frozen=True)
class CsvCell:
    start: int
    end: int
    quoted: bool


@dataclass
class CsvValue:
    value: str
    offsets: list[int]


@dataclass
class CsvUnit:
    value: str
    start: int
    end: int
    occurrences: list[CsvValue]


@dataclass
class CsvScan:
    source: str
    text: str
    units: list[CsvUnit]

    def map_findings(self, findings: list) -> tuple[list, list]:
        """Map decoded detection spans to every matching original CSV field."""
        mapped, skipped = [], []
        for finding in findings:
            unit = next((u for u in self.units if u.start <= finding["start"] < finding["end"] <= u.end), None)
            if unit is None:
                skipped.append({**finding, "reason": "finding crosses CSV field values"})
                continue
            start, end = finding["start"] - unit.start, finding["end"] - unit.start
            for occurrence in unit.occurrences:
                source_start, source_end = occurrence.offsets[start], occurrence.offsets[end]
                mapped.append({**finding, "start": source_start, "end": source_end,
                               "quote": self.source[source_start:source_end]})
        return mapped, skipped

    def quote_spans(self, quote: str) -> list[tuple[int, int]]:
        """Find manual quotes in decoded values, never in CSV punctuation."""
        spans = []
        if not quote:
            return spans
        for unit in self.units:
            search_at = 0
            while True:
                start = unit.value.find(quote, search_at)
                if start < 0:
                    break
                end = start + len(quote)
                spans.extend((o.offsets[start], o.offsets[end]) for o in unit.occurrences)
                search_at = end
        return sorted(spans)


def csv_scan(text: str) -> CsvScan | None:
    cells = csv_cells(text)
    if cells is None:
        return None
    by_value = {}
    for cell in cells:
        chars, offsets = [], [cell.start]
        pos = cell.start
        while pos < cell.end:
            chars.append(text[pos])
            pos += 2 if cell.quoted and text[pos:pos + 2] == '""' else 1
            offsets.append(pos)
        value = "".join(chars)
        if value:
            by_value.setdefault(value, []).append(CsvValue(value, offsets))
    units, parts = [], []
    cursor = 0
    for value, occurrences in by_value.items():
        units.append(CsvUnit(value, cursor, cursor + len(value), occurrences))
        parts.append(value)
        cursor += len(value) + 2
    return CsvScan(text, "\n\n".join(parts), units)


def csv_cells(text: str) -> list[CsvCell] | None:
    """Conservatively recognize comma-separated input with at least two rows.

    Nonempty rows must have the same number of fields (at least two). Offsets
    refer to the original serialized text, excluding enclosing quote marks.
    Doubled quotes and embedded newlines in quoted fields are preserved.
    """
    cells = []
    widths = []
    pos = 0
    size = len(text)
    while pos < size:
        row = []
        row_start = pos
        while True:
            quoted = pos < size and text[pos] == '"'
            if quoted:
                pos += 1
                start = pos
                while pos < size:
                    if text[pos] != '"':
                        pos += 1
                    elif pos + 1 < size and text[pos + 1] == '"':
                        pos += 2
                    else:
                        break
                if pos == size:
                    return None
                end = pos
                pos += 1
                if pos < size and text[pos] not in ",\r\n":
                    return None
            else:
                start = pos
                while pos < size and text[pos] not in ",\r\n":
                    if text[pos] == '"':
                        return None
                    pos += 1
                end = pos
            row.append(CsvCell(start, end, quoted))
            if pos < size and text[pos] == ",":
                pos += 1
                continue
            break
        # Ignore empty lines, including the blank lines left after some pastes.
        if pos != row_start:
            widths.append(len(row))
            cells.extend(row)
        if pos < size and text[pos] == "\r":
            pos += 1
        if pos < size and text[pos] == "\n":
            pos += 1
    if len(widths) < 2 or widths[0] < 2 or len(set(widths)) != 1:
        return None
    return cells


def _splits_quote_pair(text: str, pos: int, cell: CsvCell) -> bool:
    if not cell.quoted or not (cell.start < pos < cell.end):
        return False
    if text[pos - 1:pos + 1] != '""':
        return False
    run_start = pos - 1
    while run_start > cell.start and text[run_start - 1] == '"':
        run_start -= 1
    return (pos - run_start) % 2 == 1


def cell_for_span(text: str, cells: list[CsvCell], start: int, end: int) -> CsvCell | None:
    for cell in cells:
        if cell.start <= start < end <= cell.end:
            if not _splits_quote_pair(text, start, cell) and not _splits_quote_pair(text, end, cell):
                return cell
            return None
    return None


def filter_csv_findings(text: str, findings: list) -> tuple[list, list]:
    cells = csv_cells(text)
    if cells is None:
        return findings, []
    kept, skipped = [], []
    for finding in findings:
        if cell_for_span(text, cells, finding["start"], finding["end"]) is None:
            skipped.append({**finding, "reason": "crosses CSV field boundaries or splits an escaped quote"})
        else:
            kept.append(finding)
    return kept, skipped


def render_csv_edits(text: str, cells: list[CsvCell], edits: list) -> str:
    """Escape replacement text as CSV data, preserving untouched source bytes."""
    by_cell = {}
    for edit in edits:
        cell = cell_for_span(text, cells, edit["start"], edit["end"])
        if cell is None:
            raise ValueError("replacement crosses CSV field boundaries")
        by_cell.setdefault(cell, []).append(edit)
    result = text
    for cell, cell_edits in sorted(by_cell.items(), key=lambda item: -item[0].start):
        value = text[cell.start:cell.end]
        for edit in sorted(cell_edits, key=lambda edit: -edit["start"]):
            replacement = edit["replacement"]
            if cell.quoted:
                replacement = replacement.replace('"', '""')
            start, end = edit["start"] - cell.start, edit["end"] - cell.start
            value = value[:start] + replacement + value[end:]
        if not cell.quoted and any(char in value for char in ',"\r\n'):
            value = '"' + value.replace('"', '""') + '"'
        result = result[:cell.start] + value + result[cell.end:]
    return result
