import csv
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import analyze


class AnalysisTests(unittest.TestCase):
    def test_sql_uses_all_requests_as_denominator(self):
        created = '2024-12-31T12:00:00.000'
        records = [{'borough': ' queens ', 'created_date': created, 'closed_date': closed}
                   for closed in ('2025-01-07T12:00:00.000', '2025-01-07T12:00:00.001',
                                  None, '', '2025-02-30T12:00:00',
                                  '2024-12-31T11:59:59.999', created)]
        records.append({'created_date': created, 'closed_date': created})
        records.append({'borough': 'Unspecified', 'created_date': created})
        rows = {row['borough']: row for row in analyze.summarize(records)}
        self.assertEqual(rows['QUEENS'], dict(borough='QUEENS', total_requests=7,
            closed_within_7_days=2, closed_after_7_days=1, missing_closed_date=2,
            invalid_closed_date=2, pct_closed_within_7_days=28.57))
        self.assertEqual(rows['UNSPECIFIED']['total_requests'], 2)
        self.assertEqual(rows['UNSPECIFIED']['pct_closed_within_7_days'], 50.0)

    def test_invalid_created_date_is_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, 'created_date'):
            analyze.summarize([{'created_date': '2024-02-30T00:00:00'}])

    def test_month_windows_cover_leap_year(self):
        windows = list(analyze.month_windows())
        self.assertEqual(len(windows), 12)
        self.assertEqual(windows[0][0], date(2024, 1, 1))
        self.assertEqual(windows[-1][1], date(2025, 1, 1))
        self.assertEqual(sum((b-a).days for a,b in windows), 366)
        self.assertEqual([b for a,b in windows[:-1]], [a for a,b in windows[1:]])

    def test_subdivision_keeps_both_sides_without_overlapping(self):
        def fetch(dataset, query):
            where = query['$where']
            self.assertEqual(query['$select'], 'borough,created_date,closed_date')
            if "2024-01-01" in where and "2024-01-03" in where:
                raise analyze.SourceError('HTTP 503')
            return [{'borough': 'QUEENS', 'created_date': '2024-01-01T00:00:00' if
                     '2024-01-01' in where else '2024-01-02T00:00:00'}]
        rows = analyze.fetch_window(date(2024,1,1), date(2024,1,3), fetch)
        self.assertEqual([r['created_date'] for r in rows],
                         ['2024-01-01T00:00:00', '2024-01-02T00:00:00'])

    def test_truncated_response_falls_back(self):
        def fetch(dataset, query):
            return [{'created_date': '2024-01-01T00:00:00'}] * (analyze.LIMIT if
                        dataset == analyze.BASE_ID else 1)
        self.assertEqual(len(analyze.fetch_window(date(2024,1,1), date(2024,1,2), fetch)), 1)

    def test_completeness_check_compares_borough_totals(self):
        rows = analyze.summarize([{'borough': 'QUEENS', 'created_date': '2024-01-01T00:00:00'}])
        with self.assertRaisesRegex(ValueError, 'count mismatch'):
            analyze.verify_counts(rows, [{'borough': 'BRONX', 'n': '1'}])
        self.assertEqual(analyze.verify_counts(rows, [{'borough': 'QUEENS', 'n': '1'}]), 1)

    def test_outputs_have_same_aggregate_and_offline_chart(self):
        rows = analyze.summarize([{'borough': 'QUEENS', 'created_date': '2024-01-01T00:00:00',
                                   'closed_date': '2024-01-01T00:00:00'}])
        with TemporaryDirectory() as d:
            root = Path(d)
            analyze.write_outputs(root, rows, '2026-11-23')
            with (root / 'summary.csv').open(encoding='utf-8', newline='') as f:
                self.assertEqual(next(csv.DictReader(f))['pct_closed_within_7_days'], '100.00')
            page = (root / 'report.html').read_text(encoding='utf-8')
            self.assertIn('<table>', page)
            self.assertIn('<figure', page)
            self.assertIn('100,00', page)
            self.assertNotIn('<script', page)
            self.assertNotIn(' src=', page)


if __name__ == '__main__':
    unittest.main()
