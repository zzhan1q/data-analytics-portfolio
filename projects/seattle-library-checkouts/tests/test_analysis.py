import csv
import io
import unittest

try:
    import analyze
except ModuleNotFoundError as exc:
    if exc.name != 'analyze':
        raise
    analyze = None


def fixture():
    rows = [dict(checkoutyear='2022', checkoutmonth=str(month), usageclass=label, n=str(n))
            for month, counts in [(1, (1, 1)), (2, (9, 1))]
            for label, n in zip(('Digital', 'Physical'), counts)]
    return rows, [dict(checkoutyear='2022', n='12')]


class AnalysisTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(analyze, 'Analysis module not implemented')
        self.source, self.control = fixture()

    def run_analysis(self):
        return analyze.summarize(self.source, self.control, years=(2022,), months=(1, 2))

    def test_annual_share_is_weighted_by_count(self):
        monthly, annual = self.run_analysis()
        self.assertEqual([r['total'] for r in monthly], [2, 10])
        self.assertEqual(annual[0]['digital'], 10)
        self.assertEqual(annual[0]['physical'], 2)
        self.assertAlmostEqual(annual[0]['digital_share_pct'], 83.33333333333333)

    def test_missing_month_class_fails(self):
        self.source.pop()
        with self.assertRaisesRegex(ValueError, 'missing'):
            self.run_analysis()

    def test_duplicate_group_fails(self):
        self.source.append(self.source[0].copy())
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.run_analysis()

    def test_unknown_class_fails(self):
        self.source[0]['usageclass'] = 'Other'
        with self.assertRaisesRegex(ValueError, 'class'):
            self.run_analysis()

    def test_invalid_month_fails(self):
        self.source[0]['checkoutmonth'] = '13'
        with self.assertRaisesRegex(ValueError, 'period'):
            self.run_analysis()

    def test_invalid_counts_fail(self):
        for value in ['-1', '1.5', None, True]:
            with self.subTest(value=value):
                self.source[0]['n'] = value
                with self.assertRaisesRegex(ValueError, 'integer'):
                    self.run_analysis()

    def test_annual_control_mismatch_fails(self):
        self.control[0]['n'] = '11'
        with self.assertRaisesRegex(ValueError, 'reconcil'):
            self.run_analysis()

    def test_missing_annual_control_fails(self):
        self.control.clear()
        with self.assertRaisesRegex(ValueError, 'control'):
            self.run_analysis()

    def test_zero_total_share_is_not_defined(self):
        for row in self.source[:2]:
            row['n'] = '0'
        self.control[0]['n'] = '10'
        monthly, _ = self.run_analysis()
        self.assertIsNone(monthly[0]['digital_share_pct'])

    def test_csv_contains_monthly_and_annual_rows(self):
        monthly, annual = self.run_analysis()
        target = io.StringIO()
        analyze.write_csv(target, monthly, annual)
        rows = list(csv.DictReader(io.StringIO(target.getvalue())))
        self.assertEqual([(r['period'], r['total'], r['digital_share_pct']) for r in rows],
                         [('2022-01', '2', '50.0000'), ('2022-02', '10', '90.0000'),
                          ('2022', '12', '83.3333')])

    def test_report_has_offline_chart_and_data_tables(self):
        markup = analyze.render_html(*self.run_analysis())
        self.assertIn('<svg ', markup)
        self.assertEqual(markup.count('<table>'), 2)
        self.assertIn('83,33', markup)
        self.assertNotIn('<script', markup)
        self.assertNotIn('src=', markup)

    def test_sql_produces_same_totals_on_full_period_fixture(self):
        rows = [dict(checkoutyear=year, checkoutmonth=month, usageclass=label, n=n)
                for year in (2022, 2023, 2024) for month in range(1, 13)
                for label, n in [('Digital', 7), ('Physical', 3)]]
        control = [dict(checkoutyear=y, n=120) for y in (2022, 2023, 2024)]
        monthly, annual = analyze.summarize(rows, control)
        analyze.verify_sql(rows, control, monthly, annual)
        control[0]['n'] = 121
        with self.assertRaisesRegex(ValueError, 'SQL'):
            analyze.verify_sql(rows, control, monthly, annual)
