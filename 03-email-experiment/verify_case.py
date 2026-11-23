"""End-to-end regression checks; run after analyze.py."""

import csv
import json
import math
import re
from pathlib import Path

here = Path(__file__).resolve().parent
assert (here / "summary.csv").is_file(), "analyze.py did not generate its aggregate CSV"
with (here / "summary.csv").open(encoding="utf-8", newline="") as f:
    rows = list(csv.DictReader(f))
by_arm = {r["arm"]: r for r in rows}
assert len(rows) == len(by_arm) == 3
for arm, totals in {
    "control": (21306, 2262, 122, 13908.33),
    "mens": (21307, 3894, 267, 30311.69),
    "womens": (21387, 3238, 189, 23038.11),
}.items():
    row = by_arm[arm]
    assert (
        tuple(float(row[k]) for k in ("n", "visits", "conversions", "spend_total_usd"))
        == totals
    )
    assert all(
        math.isfinite(float(value))
        for key, value in row.items()
        if key != "arm"
        and not (
            arm == "control"
            and key in {"conversion_ci_low_pp", "conversion_ci_high_pp"}
        )
    )
assert by_arm["control"]["conversion_ci_low_pp"] == ""
assert by_arm["control"]["conversion_ci_high_pp"] == ""
for arm, expected in {
    "mens": (0.680501, 0.474101, 0.886900, 7.658956, 0.769827),
    "womens": (0.311106, 0.126715, 0.495496, 4.523311, 0.424412),
}.items():
    keys = (
        "conversion_lift_pp",
        "conversion_ci_low_pp",
        "conversion_ci_high_pp",
        "visit_lift_pp",
        "spend_lift_usd_per_customer",
    )
    assert all(
        abs(float(by_arm[arm][k]) - x) < 1e-6
        for k, x in zip(keys, expected, strict=True)
    )
case = json.loads((here / "case.json").read_text(encoding="utf-8"))
assert set(case) == {
    "title",
    "eyebrow",
    "subtitle",
    "question",
    "method",
    "findings",
    "limits",
    "action",
    "sources",
    "groups",
    "checks",
}
for key in ("title", "eyebrow", "subtitle", "question", "action"):
    assert isinstance(case[key], str) and case[key].strip()
for key in ("method", "findings", "limits", "checks"):
    assert (
        isinstance(case[key], list)
        and case[key]
        and all(isinstance(v, str) and v.strip() for v in case[key])
    )
assert len(case["checks"]) >= 3
assert case["sources"] and all(
    source["url"].startswith("https://") for source in case["sources"]
)
assert all(
    set(s) == {"name", "url"}
    and s["name"]
    and s["url"].startswith(("http://", "https://"))
    for s in case["sources"]
)
assert len(case["groups"]) >= 2
for group in case["groups"]:
    assert set(group) == {"name", "kpis", "charts"} and group["name"]
    assert 2 <= len(group["kpis"]) <= 4 and 1 <= len(group["charts"]) <= 2
    assert all(
        set(k) == {"label", "value"}
        and all(isinstance(v, str) and v.strip() for v in k.values())
        for k in group["kpis"]
    )
    for chart in group["charts"]:
        assert (
            set(chart) == {"title", "unit", "type", "rows"}
            and chart["title"]
            and chart["unit"]
        )
        assert chart["type"] in ("line", "bar") and 1 <= len(chart["rows"]) <= 16
        assert all(
            set(r) == {"label", "value"}
            and isinstance(r["label"], str)
            and type(r["value"]) in (int, float)
            and math.isfinite(r["value"])
            for r in chart["rows"]
        )
for name in ("analyze.py", "verify_case.py", "summary.csv", "case.json"):
    assert not re.search(
        r"[A-Z]:[/\\]|/(?:home|Users)/", (here / name).read_text(encoding="utf-8")
    )
print(
    "Verified: arm totals, numeric effects and intervals, case schema, portable paths."
)
