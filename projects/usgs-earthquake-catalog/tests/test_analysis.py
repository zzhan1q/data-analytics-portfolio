import csv
import io
import tempfile
import unittest
from pathlib import Path

import analyze as a

START = '2023-01-01T00:00:00Z'


def event(id='us1', time=START, mag='5', depth='10', type='earthquake'):
    return (id, time, mag, depth, type)


def run(*rows):
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(['id', 'time', 'mag', 'depth', 'type'])
    writer.writerows(rows)
    return a.aggregate(text.getvalue())


class CatalogTests(unittest.TestCase):
    def test_half_open_utc_boundaries_and_empty_months(self):
        data = run(event(), event('us2', '2025-01-01T00:00:00Z'),
                   event('us3', '2022-12-31T23:59:59.999Z'),
                   event('us4', '2024-12-31T23:59:59.999Z'),
                   event('us5', '2023-01-01T01:00:00+01:00'))
        self.assertEqual(len(data.monthly), 24)
        self.assertEqual((data.monthly['2023-01'], data.monthly['2023-02'], data.monthly['2024-12']), (2, 0, 1))
        self.assertEqual(data.excluded, 2)

    def test_type_and_minimum_magnitude_filters(self):
        data = run(event(mag='4.99'), event('us2', type='explosion'), event('us3', mag='5.0'))
        self.assertEqual(sum(data.monthly.values()), 1)
        self.assertEqual(data.excluded, 2)

    def test_magnitude_thresholds_are_not_rounded(self):
        data = run(*(event(f'us{i}', mag=mag) for i, mag in enumerate(('5.99', '6', '6.99', '7', '7.99', '8'))))
        self.assertEqual(tuple(data.magnitude.values()), (1, 2, 2, 1))

    def test_depth_bins_include_unknown_without_dropping_events(self):
        data = run(*(event(f'us{i}', depth=depth) for i, depth in enumerate(('-1', '69.99', '70', '299.99', '300', '', 'NaN', 'n/a'))))
        self.assertEqual(tuple(data.depth.values()), (2, 2, 1, 3))
        self.assertEqual(sum(data.monthly.values()), 8)

    def test_repeated_id_same_metrics_counts_once(self):
        data = run(event(), event(mag='5.00', time='2023-01-01T00:00:00.000Z'))
        self.assertEqual(sum(data.monthly.values()), 1)
        self.assertEqual(data.duplicates, 1)

    def test_conflicting_duplicate_fails(self):
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            run(event(), event(depth='11'))

    def test_invalid_id_fails(self):
        for id in ('', 'invalid ID', 'bad/ID'):
            with self.subTest(id=id), self.assertRaisesRegex(ValueError, 'id'):
                run(event(id))

    def test_undated_or_nonfinite_magnitude_fails(self):
        for row in (event(time='2023-01-01'), event(mag='nan')):
            with self.subTest(row=row), self.assertRaises(ValueError):
                run(row)

    def test_outputs_contain_only_aggregate_counts(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            a.publish(run(event('uniquesourceid')), root)
            with (root / 'summary.csv').open(encoding='utf-8', newline='') as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 32)
            self.assertEqual(set(rows[0]), {'group', 'bucket', 'count'})
            html = (root / 'report.html').read_text(encoding='utf-8')
            self.assertIn('<svg', html)
            self.assertIn('<table', html)
            self.assertNotIn('uniquesourceid', html)
