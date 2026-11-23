import csv
import json
import sqlite3
import unittest
from collections import defaultdict
from decimal import Decimal

from build import EXPECTED, ROOT, SCALE, analyze, setup


class MetricRules(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        setup(self.db, ["2011-01", "2011-02"])

        def row(inv, sku, qty, month, customer):
            return (inv, sku, sku, qty, month + "-01 10:00:00", 100, customer, "UK")

        a = row("1", "A", 2, "2011-01", "X")
        self.db.executemany(
            "INSERT INTO lines VALUES (?,?,?,?,?,?,?,?)",
            [
                a,
                a,
                row("1", "B", 1, "2011-01", "X"),
                row("2", "B", 2, "2011-02", "X"),
                row("3", "A", 1, "2011-02", None),
                row("4", "D", 1, "2011-02", "Y"),
                row("C5", "A", -1, "2011-02", "X"),
                row("C6", "B", 3, "2011-02", "X"),
                row("7", "B", -1, "2011-02", None),
                row("8", "A", 2, "2011-03", "Y"),
            ],
        )
        analyze(self.db)

    def test_duplicate_cancel_and_unknown_customer(self):
        self.assertEqual(
            self.db.execute(
                "SELECT sales,adjustments,net,orders,known_customers FROM month_summary ORDER BY month"
            ).fetchall(),
            [(300, 0, 300, 1, 1), (400, 200, 200, 3, 2)],
        )

    def test_repeat_counts_invoices_not_lines_and_excludes_partial(self):
        self.assertEqual(
            dict(self.db.execute("SELECT customer, orders FROM customers")),
            {"X": 2, "Y": 1},
        )

    def test_product_drivers_include_entering_and_leaving_items(self):
        self.assertEqual(
            dict(self.db.execute("SELECT stock,contribution FROM product_delta")),
            {"A": -200, "B": 0, "D": 100},
        )
        self.assertEqual(
            self.db.execute("SELECT sum(contribution) FROM product_delta").fetchone(),
            (-100,),
        )


class PublishedResults(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))

    def test_source_and_reconciliation(self):
        a = self.data["audit"]
        self.assertEqual(self.data["sha256"], EXPECTED)
        self.assertEqual(sum(self.data["sheets"].values()), 1067371)
        self.assertEqual(a["source_rows"], 1067371)
        excluded = sum(
            q["source_rows"]
            for q in self.data["quality"]
            if q["rule"] not in ("sale", "adjustment")
        )
        self.assertEqual(
            a["analyzed_rows"]
            + a["removed_duplicates"]
            + a["outside_window"]
            + excluded,
            a["source_rows"],
        )
        self.assertEqual(a["invoices_spanning_months"], 0)

    def test_months_csv_and_product_deltas(self):
        months = self.data["monthly"]
        self.assertEqual(
            (len(months), months[0]["month"], months[-1]["month"]),
            (24, "2009-12", "2011-11"),
        )
        totals = defaultdict(int)
        with (ROOT / "powerbi/Products.csv").open(encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                delta = Decimal(r["contribution_gbp"])
                self.assertEqual(
                    delta, Decimal(r["current_net_gbp"]) - Decimal(r["prior_net_gbp"])
                )
                totals[r["month"]] += int(delta * SCALE)
        with (ROOT / "powerbi/Monthly.csv").open(encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), len(months))
        for i, (m, row) in enumerate(zip(months, rows)):
            self.assertEqual(row["month"], m["month"])
            for col in ("sales", "adjustments", "net"):
                self.assertEqual(Decimal(row[col + "_gbp"]) * SCALE, m[col])
            self.assertEqual(m["net"], m["sales"] - m["adjustments"])
            if i:
                self.assertEqual(m["net_change"], m["net"] - months[i - 1]["net"])
                self.assertEqual(totals[m["month"]], m["net_change"])
                self.assertEqual(
                    self.data["drivers"][m["month"]]["total"], m["net_change"]
                )
            else:
                self.assertIsNone(m["net_change"])
                self.assertNotIn(m["month"], totals)

    def test_repeat_rate_is_period_wide(self):
        o = self.data["overview"]
        self.assertGreater(o["known_customers"], o["repeat_customers"])
        self.assertAlmostEqual(
            o["repeat_rate"], o["repeat_customers"] / o["known_customers"]
        )
