"""Rebuild prepared SQL datasets and the standalone dashboard."""

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import urllib.request
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent
URL = "https://archive.ics.uci.edu/static/public/502/online%2Bretail%2Bii.zip"
EXPECTED = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
BOOK = "online_retail_II.xlsx"
SHEETS = ("Year 2009-2010", "Year 2010-2011")
FIELDS = (
    "Invoice",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "Price",
    "Customer ID",
    "Country",
)
SCALE = 100000
MONTHS = [
    f"{y}-{m:02}"
    for y in (2009, 2010, 2011)
    for m in range(1, 13)
    if (y, m) >= (2009, 12) and (y, m) < (2011, 12)
]
SCHEMA = """CREATE TABLE lines(invoice TEXT,stock TEXT,description TEXT,qty INTEGER,sold_at TEXT,price INTEGER,customer TEXT,country TEXT);
CREATE TABLE months(month TEXT PRIMARY KEY);"""


def clean(value):
    return "" if value is None else str(value).strip()


def normalize(row):
    invoice, stock, name, qty, date, price, customer, country = row
    return (
        clean(invoice).upper(),
        clean(stock).upper(),
        clean(name),
        int(qty) if isinstance(qty, (int, float)) and int(qty) == qty else None,
        date.isoformat(sep=" ") if isinstance(date, datetime) else None,
        int(
            (Decimal(str(price)) * SCALE).quantize(Decimal(1), rounding=ROUND_HALF_EVEN)
        )
        if isinstance(price, (int, float))
        else None,
        clean(customer) or None,
        clean(country),
    )


def setup(db, months):
    db.executescript(SCHEMA)
    db.executemany("INSERT INTO months VALUES (?)", ((x,) for x in months))


def analyze(db):
    db.executescript((ROOT / "sql/analysis.sql").read_text(encoding="utf-8"))


def fetch():
    dst = ROOT / ".cache" / "online-retail-ii.zip"
    dst.parent.mkdir(exist_ok=True)
    if not dst.exists():
        tmp = dst.with_suffix(".part")
        with urllib.request.urlopen(URL, timeout=120) as res, tmp.open("wb") as out:
            shutil.copyfileobj(res, out)
        tmp.replace(dst)
    return dst


def records(db, sql):
    return [dict(r) for r in db.execute(sql)]


def export(db, fingerprint, sheets):
    out = ROOT / "powerbi"
    out.mkdir(exist_ok=True)
    db.row_factory = sqlite3.Row
    monthly = records(db, "SELECT * FROM monthly_export ORDER BY month")
    products = records(
        db, "SELECT * FROM product_delta ORDER BY month, contribution DESC, stock"
    )
    overview = records(
        db,
        """SELECT count(*) known_customers, sum(orders>1) repeat_customers,
                             1.0*sum(orders>1)/count(*) repeat_rate FROM customers""",
    )[0]
    audit = records(
        db,
        """SELECT (SELECT count(*) FROM lines) AS source_rows,
       (SELECT count(*) FROM classified WHERE kind IN ('sale','adjustment'))-(SELECT count(*) FROM ledger) AS removed_duplicates,
       (SELECT count(*) FROM ledger WHERE month NOT IN (SELECT month FROM months)) AS outside_window,
       (SELECT count(*) FROM ledger JOIN months USING(month)) AS analyzed_rows,
       (SELECT min(sold_at) FROM lines) AS first_timestamp,
       (SELECT max(sold_at) FROM lines) AS last_timestamp,
       (SELECT sum(amount) FROM ledger JOIN months USING(month) WHERE kind='sale' AND customer IS NULL) AS unidentified_sales,
       (SELECT count(*) FROM (SELECT invoice FROM ledger JOIN months USING(month) WHERE kind='sale' GROUP BY invoice HAVING count(DISTINCT month)>1)) AS invoices_spanning_months""",
    )[0]
    quality = records(db, "SELECT * FROM quality ORDER BY rule")

    def csv_file(name, data, money=()):
        with (out / (name + ".csv")).open("w", newline="", encoding="utf-8-sig") as f:
            cols = [k + "_gbp" if k in money else k for k in data[0]]
            wt = csv.writer(f)
            wt.writerow(cols)
            for row in data:
                wt.writerow(
                    [
                        f"{Decimal(v) / SCALE:.5f}"
                        if k in money and v is not None
                        else v
                        for k, v in row.items()
                    ]
                )

    csv_file(
        "Monthly",
        monthly,
        ("sales", "adjustments", "net", "previous_net", "net_change"),
    )
    csv_file("Products", products, ("current_net", "prior_net", "contribution"))
    csv_file("Overview", [overview])
    csv_file("Quality", quality)
    by_month = defaultdict(list)
    for p in products:
        by_month[p["month"]].append(p)
    drivers = {
        m: {
            "up": [p for p in rows if p["contribution"] > 0][:5],
            "down": [p for p in reversed(rows) if p["contribution"] < 0][:5],
            "total": sum(p["contribution"] for p in rows),
        }
        for m, rows in by_month.items()
    }
    payload = {
        "monthly": monthly,
        "drivers": drivers,
        "overview": overview,
        "audit": audit,
        "quality": quality,
        "sheets": sheets,
        "sha256": fingerprint,
        "scale": SCALE,
    }
    (ROOT / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def render():
    template = (ROOT / "dashboard.template.html").read_text(encoding="utf-8")
    data = json.loads((ROOT / "results.json").read_text(encoding="utf-8"))
    safe = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
        "<", r"\u003c"
    )
    (ROOT / "dashboard.html").write_text(
        template.replace("__RETAIL_DATA__", safe), encoding="utf-8"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive", type=Path, help="Use an existing authentic UCI ZIP")
    ap.add_argument(
        "--render-only",
        action="store_true",
        help="Render from already built results.json",
    )
    ap.add_argument(
        "--data-only", action="store_true", help="Export SQL tables without rendering"
    )
    args = ap.parse_args()
    if args.render_only:
        render()
        return
    from openpyxl import load_workbook

    archive = args.archive or fetch()
    with archive.open("rb") as f:
        fingerprint = hashlib.file_digest(f, "sha256").hexdigest()
    if fingerprint != EXPECTED:
        raise SystemExit(
            f"Unexpected UCI archive SHA-256: {fingerprint}. Check the source before updating the pinned hash."
        )
    (ROOT / ".cache").mkdir(exist_ok=True)
    target = ROOT / ".cache" / "retail.sqlite"
    staging = target.with_suffix(".tmp")
    staging.unlink(missing_ok=True)
    db = sqlite3.connect(staging)
    try:
        setup(db, MONTHS)
        counts = {}
        with ZipFile(archive) as z, z.open(BOOK) as file:
            wb = load_workbook(file, read_only=True, data_only=True)
            try:
                for name in SHEETS:
                    iterator = wb[name].values
                    if tuple(next(iterator)) != FIELDS:
                        raise ValueError(f"Unexpected columns in {name}")
                    start = db.total_changes
                    db.executemany(
                        "INSERT INTO lines VALUES (?,?,?,?,?,?,?,?)",
                        (normalize(row) for row in iterator),
                    )
                    counts[name] = db.total_changes - start
                    print(name, counts[name], flush=True)
            finally:
                wb.close()
        analyze(db)
        payload = export(db, fingerprint, counts)
        db.commit()
    finally:
        db.close()
    staging.replace(target)
    if not args.data_only:
        render()
    print(
        json.dumps(
            {"audit": payload["audit"], "overview": payload["overview"]}, indent=2
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
