import csv
import io
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app


class CsvApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_finalize_without_decisions_preserves_csv_exactly(self):
        text = 'Customer,Employee,Memo\r\n"Acme O&M, Year 4","Doe, Jane","=> café &amp; <tag>"\r\n'
        result = self.client.post('/api/finalize', json={'text': text, 'decisions': []})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['txt'], text)

    def test_finalize_escapes_custom_replacements_without_changing_columns(self):
        text = 'Name,Memo\r\nJane,"Doe, John"\r\n'
        replacement = 'Smith, "Alex" & <Co>\nsecond line'
        result = self.client.post('/api/finalize', json={
            'text': text,
            'decisions': [{'start': text.index('Jane'), 'end': text.index('Jane') + 4,
                           'quote': 'Jane', 'category': 'person', 'status': 'edited', 'replacement': replacement}],
        })
        self.assertEqual(result.status_code, 200)
        self.assertEqual(list(csv.reader(io.StringIO(result.json()['txt'], newline=''))), [
            ['Name', 'Memo'], [replacement, 'Doe, John'],
        ])

    def test_finalize_reports_manual_quote_crossing_csv_syntax(self):
        text = 'Name,Hours\n"Doe, Jane",1\nSmith,2\n'
        result = self.client.post('/api/finalize', json={
            'text': text,
            'decisions': [{'quote': 'Jane",1', 'category': 'person', 'status': 'approved'}],
        })
        data = result.json()
        self.assertEqual(data['txt'], text)
        self.assertEqual(data['applied'], 0)
        self.assertIn('CSV', data['warnings'][0])

    def test_analyze_scans_decoded_fields_without_csv_syntax(self):
        text = 'Name,Hours\n"Doe, Jane",1\nSmith,2\n'

        def detect_fields(values):
            self.assertEqual(values, ['Name', 'Hours', 'Doe, Jane', '1', 'Smith', '2'])
            return [[{'start': 5, 'end': 9, 'quote': 'Jane', 'category': 'person', 'source': 'spacy', 'confidence': 0.9}]
                    if value == 'Doe, Jane' else [] for value in values]

        with patch('app.render.ner_find_many', side_effect=detect_fields), patch('app.render.regex_find', return_value=[]), patch('app.main.pass2_llm.detect', return_value=([], [], [])) as llm:
            result = self.client.post('/api/analyze', json={'text': text})
        self.assertEqual(llm.call_args.args[0], 'Name\n\nHours\n\nDoe, Jane\n\n1\n\nSmith\n\n2')
        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertEqual([f['quote'] for f in data['findings']], ['Jane'])
        self.assertEqual(data['dropped'], [])
        self.assertEqual([len(row) for row in csv.reader(io.StringIO(data['txt_preview']))], [2, 2, 2])

    def test_finalize_refuses_pending_or_unknown_status(self):
        for status in ['pending', 'unknown']:
            result = self.client.post('/api/finalize', json={'text': 'Jane', 'decisions': [
                {'start': 0, 'end': 4, 'quote': 'Jane', 'category': 'person', 'status': status},
            ]})
            self.assertEqual(result.status_code, 422)

    def test_llm_decoded_quote_maps_to_repeated_escaped_fields(self):
        text = 'Name,Memo\n"Acme ""Alpha""",ok\n"Acme ""Alpha""",done\n'

        def llm_detect(decoded):
            quote = 'Acme "Alpha"'
            start = decoded.index(quote)
            return ([{'start': start, 'end': start + len(quote), 'quote': quote,
                      'category': 'org', 'source': 'llm', 'confidence': 0.6}], [], [])

        with patch('app.render.ner_find_many', side_effect=lambda values: [[] for _ in values]), patch('app.render.regex_find', return_value=[]), patch('app.main.pass2_llm.detect', side_effect=llm_detect):
            result = self.client.post('/api/analyze', json={'text': text})
        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertEqual(len(data['findings']), 2)
        self.assertEqual(data['llm_unverified'], [])
        self.assertEqual(data['dropped'], [])
        for finding in data['findings']:
            self.assertEqual(text[finding['start']:finding['end']], 'Acme ""Alpha""')
        self.assertEqual([len(row) for row in csv.reader(io.StringIO(data['txt_preview']))], [2, 2, 2])

    def test_manual_quote_matches_decoded_escaped_quotes_in_each_field(self):
        text = 'Name,Memo\r\n"Acme ""Alpha""",ok\r\n"Acme ""Alpha""",done\r\n'
        result = self.client.post('/api/finalize', json={'text': text, 'decisions': [
            {'quote': 'Acme "Alpha"', 'category': 'org', 'status': 'edited', 'replacement': 'New "Beta", Co'},
        ]})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['applied'], 2)
        self.assertEqual(list(csv.reader(io.StringIO(result.json()['txt']))), [
            ['Name', 'Memo'], ['New "Beta", Co', 'ok'], ['New "Beta", Co', 'done'],
        ])

    def test_plain_prose_preserves_literal_entities_and_quotes(self):
        text = '"Hello" &amp; café => <tag>\nNext line.'
        result = self.client.post('/api/finalize', json={'text': text, 'decisions': []})
        self.assertEqual(result.json()['txt'], text)


if __name__ == '__main__':
    unittest.main()
