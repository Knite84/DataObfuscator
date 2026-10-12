import csv
import io
import unittest

from app.csv_text import csv_cells, csv_scan, filter_csv_findings, render_csv_edits


class CsvTextTests(unittest.TestCase):
    def test_decoded_field_deduplication_and_exact_offset_mapping(self):
        text = 'Name,Memo\r\n"Acme ""Alpha"", Inc",first\r\n"Acme ""Alpha"", Inc",second\r\n'
        scan = csv_scan(text)
        unit = next(u for u in scan.units if u.value == 'Acme "Alpha", Inc')
        self.assertEqual(len(unit.occurrences), 2)
        start = unit.value.index('"Alpha"')
        mapped, skipped = scan.map_findings([{
            'start': unit.start + start, 'end': unit.start + start + len('"Alpha"'),
            'quote': '"Alpha"', 'category': 'org',
        }])
        self.assertEqual(skipped, [])
        self.assertEqual(len(mapped), 2)
        self.assertTrue(all(text[f['start']:f['end']] == '""Alpha""' for f in mapped))
        edits = [{**f, 'replacement': '"Beta"'} for f in mapped]
        output = render_csv_edits(text, csv_cells(text), edits)
        self.assertEqual(list(csv.reader(io.StringIO(output)))[1:], [
            ['Acme "Beta", Inc', 'first'], ['Acme "Beta", Inc', 'second'],
        ])

    def test_scan_rejects_detection_spanning_independent_values(self):
        scan = csv_scan('Name,Hours\n"Doe, Jane",1\n')
        unit = next(u for u in scan.units if u.value == 'Doe, Jane')
        mapped, skipped = scan.map_findings([{'start': unit.start + 5, 'end': unit.end + 3, 'quote': 'Jane\n\n1'}])
        self.assertEqual(mapped, [])
        self.assertEqual(len(skipped), 1)

    def test_no_edits_preserves_quotes_special_characters_and_line_endings(self):
        text = 'Customer,Employee,Memo\r\n"Acme O&M, Year 4","Doe, Jane","<tag> => café & literal &amp;"\r\n'
        cells = csv_cells(text)
        self.assertIsNotNone(cells)
        self.assertEqual(render_csv_edits(text, cells, []), text)

    def test_quoted_replacement_preserves_rows_and_escapes_quotes(self):
        text = 'Name,Memo\r\n"Doe, Jane","Line 1\r\nLine 2"\r\n'
        start = text.index('Doe, Jane')
        replacement = 'Alex "AJ", Smith & Co'
        output = render_csv_edits(text, csv_cells(text), [
            {"start": start, "end": start + len('Doe, Jane'), "replacement": replacement},
        ])
        self.assertEqual(list(csv.reader(io.StringIO(output, newline=''))), [
            ['Name', 'Memo'], [replacement, 'Line 1\r\nLine 2'],
        ])
        self.assertIn('"Alex ""AJ"", Smith & Co"', output)
        self.assertTrue(output.endswith('\r\n'))

    def test_unquoted_field_is_quoted_only_when_replacement_requires_it(self):
        text = 'Name,Memo\nJane,unchanged\n'
        start = text.index('Jane')
        for replacement in ['Alex', 'Smith, Alex', 'Alex "AJ"', 'Alex\nSmith', 'Alex\rSmith', 'Álex & <Co>']:
            with self.subTest(replacement=replacement):
                output = render_csv_edits(text, csv_cells(text), [
                    {"start": start, "end": start + 4, "replacement": replacement},
                ])
                self.assertEqual(list(csv.reader(io.StringIO(output, newline=''))), [
                    ['Name', 'Memo'], [replacement, 'unchanged'],
                ])

    def test_multiple_replacements_inside_one_field(self):
        text = 'Name,Memo\n"Jane met Jane",ok\n'
        first = text.index('Jane')
        second = text.index('Jane', first + 1)
        output = render_csv_edits(text, csv_cells(text), [
            {"start": first, "end": first + 4, "replacement": 'A "B"'},
            {"start": second, "end": second + 4, "replacement": 'C,D'},
        ])
        self.assertEqual(list(csv.reader(io.StringIO(output)))[1], ['A "B" met C,D', 'ok'])

    def test_cross_field_quotes_and_row_boundaries_are_skipped(self):
        text = 'Name,Hours\n"Doe, Jane",1\nSmith,2\n'
        valid_start = text.index('Doe, Jane')
        bad_start = text.index('Jane')
        row_start = text.index('1\nSmith')
        findings = [
            {"start": valid_start, "end": valid_start + 9, "quote": 'Doe, Jane'},
            {"start": bad_start, "end": bad_start + len('Jane",1'), "quote": 'Jane",1'},
            {"start": row_start, "end": row_start + len('1\nSmith'), "quote": '1\nSmith'},
        ]
        kept, skipped = filter_csv_findings(text, findings)
        self.assertEqual(kept, findings[:1])
        self.assertEqual(len(skipped), 2)
        self.assertTrue(all('CSV' in f['reason'] for f in skipped))

    def test_escaped_quote_pairs_cannot_be_split(self):
        text = 'Name,Memo\n"A ""B"" C",ok\n'
        pos = text.index('""')
        kept, skipped = filter_csv_findings(text, [
            {"start": pos, "end": pos + 1},
            {"start": pos + 1, "end": pos + 2},
            {"start": pos, "end": pos + 2},
        ])
        self.assertEqual(len(skipped), 2)
        self.assertEqual(len(kept), 1)

    def test_empty_cells_blank_lines_and_trailing_comma(self):
        text = '\r\nA,B,C\r\n1,,\r\n\r\n'
        cells = csv_cells(text)
        self.assertEqual(len(cells), 6)
        self.assertEqual(render_csv_edits(text, cells, []), text)

    def test_non_csv_and_malformed_input_are_not_inferred_as_csv(self):
        for text in ['Jane met John.', 'A,B', 'A,B\n1,2,3', 'A,B\n"unclosed,2', 'A,B\n"x"oops,2', 'A,B\nx"y,2']:
            with self.subTest(text=text):
                self.assertIsNone(csv_cells(text))

    def test_renderer_refuses_unsafe_edit(self):
        text = 'A,B\n1,2\n'
        with self.assertRaises(ValueError):
            render_csv_edits(text, csv_cells(text), [{"start": 4, "end": 7, "replacement": 'bad'}])


if __name__ == '__main__':
    unittest.main()
