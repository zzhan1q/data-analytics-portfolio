"""Build demand summaries and an Excel workbook from UCI day.csv."""

import csv
import io
import json
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import xlsxwriter

ROOT = Path(__file__).resolve().parent
SOURCE = "https://archive.ics.uci.edu/dataset/275/bike%2Bsharing%2Bdataset"
URL = "https://archive.ics.uci.edu/static/public/275/bike+sharing+dataset.zip"


def load():
    cache = ROOT / ".cache"
    cache.mkdir(exist_ok=True)
    file = cache / "source.zip"
    if not file.exists():
        with urllib.request.urlopen(URL, timeout=60) as response:
            b = response.read()
        if not zipfile.is_zipfile(io.BytesIO(b)):
            raise ValueError("UCI did not return a ZIP archive")
        file.write_bytes(b)
    with zipfile.ZipFile(file) as z, z.open("day.csv") as raw:
        return [
            (
                date.fromisoformat(r["dteday"]),
                *[
                    int(r[k])
                    for k in (
                        "workingday",
                        "weathersit",
                        "casual",
                        "registered",
                        "cnt",
                    )
                ],
            )
            for r in csv.DictReader(io.TextIOWrapper(raw, encoding="utf8"))
        ]


def workbook(rows, monthly):
    with xlsxwriter.Workbook(ROOT / "Demand.xlsx") as w:
        w.set_properties(
            {
                "title": "Capital Bikeshare — спрос по месяцам",
                "author": "",
                "company": "",
            }
        )
        head = w.add_format(
            {
                "bold": True,
                "bg_color": "#163946",
                "font_color": "#FFFFFF",
                "text_wrap": True,
                "valign": "vcenter",
            }
        )
        integer = w.add_format({"num_format": "#,##0"})
        dt = w.add_format({"num_format": "yyyy-mm-dd"})
        pct = w.add_format({"num_format": "0.0%"})
        intro = w.add_format({"font_size": 17, "bold": True, "font_color": "#163946"})
        dash = w.add_worksheet("Сводка")
        data = w.add_worksheet("Дни")
        calc = w.add_worksheet("Месяцы")
        note = w.add_worksheet("Методика")
        for sh in (dash, data, calc, note):
            sh.hide_gridlines(2)
        data.set_column("A:F", 18)
        data.freeze_panes(1, 0)
        data.add_table(
            0,
            0,
            len(rows),
            5,
            {
                "columns": [
                    {"header": s}
                    for s in (
                        "Дата",
                        "Рабочий день",
                        "Код погоды",
                        "Разовые",
                        "Регулярные",
                        "Всего",
                    )
                ],
                "style": "Table Style Medium 2",
            },
        )
        for i, (d, *r) in enumerate(rows, 1):
            data.write_datetime(i, 0, d, dt)
            data.write_row(i, 1, r, integer)
        calc.set_column("A:G", 18)
        calc.set_row(0, 34)
        calc.freeze_panes(1, 1)
        calc.autofilter(0, 0, len(monthly), 6)
        calc.write_row(
            0,
            0,
            [
                "Месяц",
                "Следующий месяц",
                "Дней",
                "Разовые",
                "Регулярные",
                "Всего",
                "Среднее в день",
            ],
            head,
        )
        lo = 2
        hi = len(rows) + 1
        date_range = f"'Дни'!$A${lo}:$A${hi}"
        for i, (key, (n, c, r, t)) in enumerate(monthly.items(), 1):
            y, m = map(int, key.split("-"))
            row = i + 1
            calc.write_datetime(i, 0, datetime(y, m, 1), dt)
            calc.write_formula(
                i,
                1,
                f"=DATE(YEAR(A{row}),MONTH(A{row})+1,1)",
                dt,
                (datetime(y + (m == 12), m % 12 + 1, 1) - datetime(1899, 12, 30)).days,
            )
            where = f'{date_range},">="&A{row},{date_range},"<"&B{row}'
            calc.write_formula(i, 2, f"=COUNTIFS({where})", integer, n)
            for col, src, val in ((3, "D", c), (4, "E", r), (5, "F", t)):
                calc.write_formula(
                    i,
                    col,
                    f"=SUMIFS('Дни'!${src}${lo}:${src}${hi},{where})",
                    integer,
                    val,
                )
            calc.write_formula(i, 6, f"=IFERROR(F{row}/C{row},0)", integer, t / n)
        dash.set_column("A:A", 33)
        dash.set_column("B:B", 20)
        dash.set_column("C:H", 14)
        dash.merge_range("A1:H2", "Capital Bikeshare / Спрос на велопрокат", intro)
        total = sum(r[-1] for r in rows)
        casual = sum(r[3] for r in rows)
        dash.write_row("A4", ["Показатель", "Значение"], head)
        for y, label, formula, val, fmt in [
            (
                4,
                "Всего поездок",
                f"=SUM('Месяцы'!F2:F{len(monthly) + 1})",
                total,
                integer,
            ),
            (
                5,
                "Дней в источнике",
                f"=SUM('Месяцы'!C2:C{len(monthly) + 1})",
                len(rows),
                integer,
            ),
            (
                6,
                "Доля разовых поездок",
                f"=SUM('Месяцы'!D2:D{len(monthly) + 1})/B5",
                casual / total,
                pct,
            ),
        ]:
            dash.write(y, 0, label)
            dash.write_formula(y, 1, formula, fmt, val)
        chart = w.add_chart({"type": "line"})
        chart.add_series(
            {
                "name": "Поездок в день",
                "categories": ["Месяцы", 1, 0, len(monthly), 0],
                "values": ["Месяцы", 1, 6, len(monthly), 6],
                "line": {"color": "#0C7268", "width": 2.5},
            }
        )
        chart.set_x_axis(
            {
                "date_axis": True,
                "num_format": "mmm yy",
                "major_unit": 3,
                "major_unit_type": "months",
            }
        )
        chart.set_y_axis({"min": 0, "name": "Поездок в день"})
        chart.set_legend({"none": True})
        chart.set_title({"name": "Средний спрос по месяцам"})
        dash.insert_chart("A9", chart, {"x_scale": 1.4, "y_scale": 1.2})
        note.set_column("A:A", 105)
        note.write("A1", "Методика", intro)
        for i, item in enumerate(
            [
                "Данные: один ряд на календарный день.",
                "Дневной спрос = число поездок, а не уникальные клиенты.",
                "Среднее за месяц = сумма поездок / число дней.",
                "Столбец B на листе «Месяцы» — исключающая верхняя граница периода.",
                "Перейдите на лист «Месяцы» и откройте любую формулу SUMIFS.",
                "Источник: Fanaee-T (2013), UCI Bike Sharing, CC BY 4.0.",
            ],
            2,
        ):
            note.write(i, 0, item)
        note.write_url("A10", SOURCE, string="Карточка датасета UCI")


def main():
    rows = sorted(load(), key=lambda row: row[0])
    monthly = defaultdict(lambda: [0, 0, 0, 0])
    types = defaultdict(lambda: [0, 0, 0, 0])
    yrs = defaultdict(int)
    start = date(2011, 1, 1)
    end = date(2013, 1, 1)
    expected = [start + timedelta(days=i) for i in range((end - start).days)]
    if [row[0] for row in rows] != expected:
        raise ValueError("Expected one row for each calendar day in 2011–2012")
    for d, working, weather, c, r, t in rows:
        if c + r != t or t <= 0 or working not in {0, 1} or weather not in {1, 2, 3}:
            raise ValueError(f"Invalid daily totals or categories for {d}")
        yrs[d.year] += t
        for agg in (monthly[d.strftime("%Y-%m")], types[(d.year, working)]):
            for i, x in enumerate((1, c, r, t)):
                agg[i] += x
    total = sum(yrs.values())
    if total != sum(r[3] for r in monthly.values()) or total != sum(
        r[3] for r in types.values()
    ):
        raise ValueError("Daily totals do not reconcile with both breakdowns")
    with (ROOT / "summary.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "group",
                "period",
                "days",
                "casual",
                "registered",
                "rentals",
                "mean_per_day",
            ]
        )
        w.writerows(
            (g, k, *v, round(v[3] / v[0], 4))
            for g, data in [
                ("month", monthly),
                ("day_type", {f"{y}:{t}": v for (y, t), v in types.items()}),
            ]
            for k, v in data.items()
        )
    workbook(rows, monthly)

    def fmt(x):
        return f"{x:,.0f}".replace(",", " ")

    peak = max(monthly, key=lambda k: monthly[k][3] / monthly[k][0])
    growth = yrs[2012] / yrs[2011] - 1
    groups = []
    for y in (2011, 2012):
        r = [(k, v) for k, v in monthly.items() if k.startswith(str(y))]
        t = yrs[y]
        c = sum(v[1] for _, v in r)
        groups.append(
            {
                "name": str(y),
                "kpis": [
                    {"label": "Поездки", "value": fmt(t)},
                    {
                        "label": "Спрос в день",
                        "value": fmt(t / sum(v[0] for _, v in r)),
                    },
                    {"label": "Доля разовых поездок", "value": f"{c / t:.1%}"},
                ],
                "charts": [
                    {
                        "title": "Средний спрос по месяцам",
                        "type": "line",
                        "unit": "поездок в день",
                        "rows": [
                            {"label": k[5:], "value": round(v[3] / v[0], 2)}
                            for k, v in r
                        ],
                    },
                    {
                        "title": "Рабочий календарь",
                        "type": "bar",
                        "unit": "поездок в день",
                        "rows": [
                            {
                                "label": label,
                                "value": round(types[(y, i)][3] / types[(y, i)][0], 2),
                            }
                            for i, label in [(1, "Рабочий день"), (0, "Нерабочий день")]
                        ],
                    },
                ],
            }
        )
    case = {
        "title": "Спрос на велопрокат",
        "eyebrow": "01 / Excel · транспорт",
        "subtitle": "Capital Bikeshare · Вашингтон · 2011–2012",
        "question": "В какие месяцы системе нужен больший запас велосипедов и как различается спрос в рабочие и нерабочие дни?",
        "method": [
            "Используем дневной файл: одна строка на календарный день. Почасовой файл не суммируем с дневным.",
            "Среднее за период считаем как число поездок, делённое на число дней. В Excel месячные суммы пересчитываются через SUMIFS, число дней — через COUNTIFS.",
            "Разовые и регулярные — категории поездок, а не отдельные люди.",
        ],
        "findings": [
            f"В 2012 году зафиксировано {fmt(yrs[2012])} поездок против {fmt(yrs[2011])} в 2011-м (+{growth:.1%}).",
            f"Максимум по среднесуточному спросу пришёлся на {peak}: {fmt(monthly[peak][3] / monthly[peak][0])} поездок в день.",
            f"За период зарегистрировано {fmt(total)} поездок; рабочий и нерабочий день сравниваем по среднему, а не по суммам.",
        ],
        "limits": [
            "Данные за 2011–2012 годы описывают исторический спрос и не показывают, сколько поездок потеряно из-за нехватки велосипедов.",
            "Сравнение месяцев не выделяет эффект погоды, роста сети или состава пользователей.",
        ],
        "action": "Для планирования запаса сверить сезонные пики со свежими данными об остатках по станциям; отдельно оценить будни и выходные.",
        "sources": [
            {"name": "Fanaee-T (2013), UCI Bike Sharing, CC BY 4.0", "url": SOURCE}
        ],
        "groups": groups,
        "checks": [
            "731 уникальный день без календарных разрывов",
            "Разовые + регулярные = всего для каждого дня",
            "Годовые суммы совпадают с месячной и календарной разбивками",
        ],
    }
    (ROOT / "case.json").write_text(
        json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    print(len(rows), total, peak)


if __name__ == "__main__":
    main()
