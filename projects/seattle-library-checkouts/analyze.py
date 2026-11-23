"""Rebuild the Seattle Public Library checkout analysis with Python's stdlib."""

import csv
import json
import math
import re
import sqlite3
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
SOURCE = 'https://data.seattle.gov/Community-and-Culture/Checkouts-by-Title/tmmm-ytt6'
ENDPOINT = 'https://data.seattle.gov/resource/tmmm-ytt6.json'
CONTEXT = 'https://www.spl.org/Seattle-Public-Library/documents/about-us/impact/2024StatisticalFinancialSummaryOnePage.pdf'
YEARS = (2022, 2023, 2024)
MONTHS = tuple(range(1, 13))
CLASSES = ('Digital', 'Physical')
FIELDS = ('grain', 'period', 'digital', 'physical', 'total', 'digital_share_pct')


def fetch(groups):
    columns = ','.join(groups)
    limit = 1000
    query = urlencode({'$select': f'{columns},sum(checkouts) as n',
                       '$where': f'checkoutyear between {YEARS[0]} and {YEARS[-1]}',
                       '$group': columns, '$order': columns, '$limit': limit})
    with urlopen(f'{ENDPOINT}?{query}', timeout=60) as response:
        data = json.load(response)
    if not isinstance(data, list) or not 0 < len(data) < limit or any(not isinstance(r, dict) for r in data):
        raise ValueError('Invalid or potentially truncated API result')
    return data


def integer(row, field):
    value = row.get(field)
    if type(value) not in (str, int) or not re.fullmatch(r'[0-9]+', str(value)):
        raise ValueError(f'{field} must be a nonnegative integer: {value!r}')
    return int(value)


def record(grain, period, digital, physical):
    total = digital + physical
    return dict(grain=grain, period=period, digital=digital, physical=physical, total=total,
                digital_share_pct=100 * digital / total if total else None)


def summarize(rows, controls, years=YEARS, months=MONTHS):
    keys = {(y, m, c) for y in years for m in months for c in CLASSES}
    counts = {}
    for row in rows:
        y, m = integer(row, 'checkoutyear'), integer(row, 'checkoutmonth')
        label = row.get('usageclass')
        if label not in CLASSES:
            raise ValueError(f'unexpected usage class: {label!r}')
        key = (y, m, label)
        if key not in keys:
            raise ValueError(f'unexpected period: {y}-{m:02d}')
        if key in counts:
            raise ValueError(f'duplicate group: {key}')
        counts[key] = integer(row, 'n')
    if missing := keys.difference(counts):
        raise ValueError(f'missing groups: {sorted(missing)}')
    control = {}
    for row in controls:
        year = integer(row, 'checkoutyear')
        if year not in years or year in control:
            raise ValueError(f'unexpected or duplicate annual control: {year}')
        control[year] = integer(row, 'n')
    if set(control) != set(years):
        raise ValueError('missing annual control')
    monthly, annual = [], []
    for y in sorted(years):
        rows_for_year = [record('month', f'{y}-{m:02d}', *(counts[y, m, c] for c in CLASSES))
                         for m in sorted(months)]
        year = record('year', str(y), sum(r['digital'] for r in rows_for_year),
                      sum(r['physical'] for r in rows_for_year))
        if year['total'] != control[y]:
            raise ValueError(f'annual reconciliation failed for {y}: {year["total"]} != {control[y]}')
        monthly.extend(rows_for_year)
        annual.append(year)
    return monthly, annual


def verify_sql(rows, controls, monthly, annual):
    """Run the shipped SQL in memory and compare every output row with Python."""
    db = sqlite3.connect(':memory:')
    try:
        db.executescript('CREATE TEMP TABLE source_monthly(checkoutyear INTEGER, checkoutmonth INTEGER, '
                         'usageclass TEXT, n INTEGER); CREATE TEMP TABLE source_annual(checkoutyear INTEGER, n INTEGER);')
        db.executemany('INSERT INTO source_monthly VALUES (?, ?, ?, ?)',
                       [(integer(r, 'checkoutyear'), integer(r, 'checkoutmonth'), r['usageclass'], integer(r, 'n'))
                        for r in rows])
        db.executemany('INSERT INTO source_annual VALUES (?, ?)',
                       [(integer(r, 'checkoutyear'), integer(r, 'n')) for r in controls])
        db.executescript((ROOT / 'analysis.sql').read_text(encoding='utf-8'))
        if issues := db.execute('SELECT * FROM issues').fetchall():
            raise ValueError(f'SQL issues: {issues}')
        for period, table, order, expected in (("printf('%04d-%02d', checkoutyear, checkoutmonth)", 'monthly', '1', monthly),
                                                ('CAST(checkoutyear AS TEXT)', 'annual', '1', annual)):
            actual = db.execute(f'SELECT {period}, digital, physical, total, digital_share_pct '
                                f'FROM {table} ORDER BY {order}').fetchall()
            want = [tuple(r[k] for k in FIELDS[1:]) for r in expected]
            if actual != want:
                raise ValueError(f'SQL and Python disagree: {table}')
    finally:
        db.close()


def write_csv(stream, monthly, annual):
    writer = csv.DictWriter(stream, FIELDS, lineterminator='\n')
    writer.writeheader()
    for row in [*monthly, *annual]:
        share = row['digital_share_pct']
        writer.writerow(dict(row, digital_share_pct='' if share is None else f'{share:.4f}'))


def number(value):
    return f'{value:,}'.replace(',', '\u202f')


def decimal(value):
    return f'{value:.2f}'.replace('.', ',')


def table(rows, caption):
    body = []
    for row in rows:
        share = row['digital_share_pct']
        counts = ''.join(f'<td>{number(row[key])}</td>' for key in ('digital', 'physical', 'total'))
        body.append(f'<tr><th scope="row">{row["period"]}</th>{counts}'
                    f'<td>{"—" if share is None else decimal(share) + "%"}</td></tr>')
    return f'''<div class="scroll" tabindex="0" role="region" aria-label="{caption}"><table>
<caption>{caption}</caption><thead><tr><th scope="col">Период</th><th scope="col">Цифровые</th>
<th scope="col">Физические</th><th scope="col">Всего</th><th scope="col">Доля цифровых</th></tr></thead>
<tbody>{''.join(body)}</tbody></table></div>'''


def chart(rows, annual):
    top_count = max(row[key] for row in rows for key in ('digital', 'physical'))
    unit = max(1, 10 ** max(0, len(str(top_count)) - 2))
    step = max(1, math.ceil(top_count / (3 * unit)) * unit)
    maximum = 3 * step
    result = []
    for year_row in annual:
        year = year_row['period']
        year_rows = [r for r in rows if r['period'].startswith(year + '-')]
        xs = [55 + i * 249 / max(1, len(year_rows) - 1) for i in range(len(year_rows))]
        grid, series, ticks = [], [], []
        for value in range(0, maximum + 1, step):
            y = 143 - value * 118 / maximum
            grid.append(f'<line class="gridline" x1="49" x2="305" y1="{y}" y2="{y}"/>'
                        f'<text x="43" y="{y+4}" text-anchor="end">{number(value)}</text>')
        for i, (x, row) in enumerate(zip(xs, year_rows)):
            if i % 3 == 0 or i == len(year_rows) - 1:
                ticks.append(f'<text x="{x:.1f}" y="166" text-anchor="middle">{row["period"][-2:]}</text>')
        for key, label in (('digital', 'Цифровые'), ('physical', 'Физические')):
            ys = [143 - r[key] * 118 / maximum for r in year_rows]
            points = ' '.join(f'{x:.1f},{y:.1f}' for x, y in zip(xs, ys))
            series.append(f'<polyline class="{key}" points="{points}"/>')
            for row, x, y in zip(year_rows, xs, ys):
                series.append(f'<circle class="{key}" cx="{x:.1f}" cy="{y:.1f}" r="3">'
                              f'<title>{row["period"]} · {label}: {number(row[key])}</title></circle>')
        share = year_row['digital_share_pct']
        subtitle = f'{decimal(share)}% цифровых' if share is not None else 'Нет выдач'
        result.append(f'<figure><figcaption><b>{year}</b><span>{subtitle}</span></figcaption>'
                      f'<svg viewBox="0 0 320 177" role="img" aria-label="Помесячные выдачи, {year}">'
                      f'{"".join(grid + ticks + series)}</svg></figure>')
    return ''.join(result)


STYLE = '''
:root{color-scheme:light;--paper:#f5f2e9;--ink:#212b28;--muted:#4c5b54;--line:#c8cec2;--digital:#00655b;--physical:#984920}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 Arial,sans-serif}
main{max-width:1200px;margin:auto;padding:clamp(16px,4vw,50px);min-width:0}header{border-top:5px solid var(--ink);padding-top:18px}
.eyebrow{font:700 12px/1.5 Arial,sans-serif;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);margin:0}
h1,h2,figcaption b{font-family:Georgia,serif}h1{font-size:clamp(2rem,5.2vw,4.3rem);line-height:1.02;letter-spacing:-.045em;margin:10px 0 14px}
h2{font-size:clamp(1.45rem,3vw,2.2rem);line-height:1.13;margin:0 0 10px}.lead{max-width:66ch;margin:0;color:var(--muted)}
section{border-top:1px solid var(--line);margin-top:27px;padding-top:19px}.panel-title{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:0 16px}
.legend{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:.9rem;margin:0 0 12px}.legend span:before{content:'';display:inline-block;width:23px;margin-right:7px;vertical-align:middle;border-top:3px solid var(--digital)}
.legend span+span:before{border-color:var(--physical);border-top-style:dashed}.charts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
figure{margin:0;background:#fffdf7;border:1px solid var(--line);padding:8px 8px 3px}figcaption{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:3px 8px;padding:4px 10px;color:var(--muted);font-size:.83rem}
figcaption b{font-size:1.3rem;color:var(--ink)}svg{width:100%;height:auto;display:block}svg text{font:11px Arial,sans-serif;fill:var(--muted)}
.gridline{stroke:#d3d8ce}polyline{fill:none;stroke-width:2.6;stroke-linejoin:round;stroke-linecap:round}polyline.digital{stroke:var(--digital)}polyline.physical{stroke:var(--physical);stroke-dasharray:5 4}circle.digital{fill:var(--digital)}circle.physical{fill:var(--physical)}
.note{color:var(--muted);font-size:.9rem;margin:11px 0 0}.scroll{overflow-x:auto}.scroll:focus-visible{outline:2px solid var(--digital);outline-offset:2px}
table{border-collapse:collapse;width:100%;min-width:535px;font-variant-numeric:tabular-nums}caption{text-align:left;font-size:.9rem;color:var(--muted);padding:0 0 9px}
th,td{padding:8px 11px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child{text-align:left}thead{background:#e9ece1}td:last-child{font-weight:700;color:var(--digital)}
details{margin-top:18px}summary{cursor:pointer;font-weight:700;padding:12px 0}footer{margin-top:27px;border-top:1px solid var(--line);padding-top:16px;color:var(--muted);font-size:.9rem}
footer a{color:var(--digital)}footer p{margin:0 0 8px}@media(max-width:860px){.charts{grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr))}}@media(max-width:540px){.charts{grid-template-columns:1fr}}
'''


def render_html(monthly, annual):
    total = sum(row['total'] for row in annual)
    count = sum(row['digital'] > row['physical'] for row in monthly)
    first, last = annual[0], annual[-1]
    start, end = first['digital_share_pct'], last['digital_share_pct']
    delta = (f' Доля цифровых: {decimal(start)}% в {first["period"]} году и {decimal(end)}% в {last["period"]} году.'
             if start is not None and end is not None and first is not last else '')
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Выдачи Seattle Public Library · {first['period']}–{last['period']}</title><style>{STYLE}</style></head>
<body><main><header><p class="eyebrow">Seattle Public Library · {first['period']}–{last['period']}</p>
<h1>Что выдавали чаще:<br>цифровое или физическое?</h1>
<p class="lead"><strong>{number(total)} выдач</strong> в открытом наборе. Цифровой формат лидировал в {count} из {len(monthly)} месяцев.{delta}</p></header>
<section aria-labelledby="chart-title"><div class="panel-title"><h2 id="chart-title">Выдачи по месяцам</h2>
<div class="legend"><span>Цифровые</span><span>Физические</span></div></div>
<div class="charts">{chart(monthly, annual)}</div><p class="note">Общая шкала: число выдач. По горизонтали — номер месяца.</p></section>
<section aria-labelledby="annual-title"><h2 id="annual-title">Годовые итоги</h2>
{table(annual, 'Количество выдач и доля цифрового формата')}
<details><summary>Помесячная таблица · {len(monthly)} месяцев</summary>{table(monthly, 'Выдачи за каждый месяц')}</details></section>
<footer><p>Источник: <a href="{SOURCE}">Checkouts by Title</a> (Public Domain). Складываем выдачи, а не строки каталога. Годовая доля — цифровые выдачи, делённые на все выдачи за год.</p>
<p>Это не число уникальных читателей и не весь оборот библиотеки. <a href="{CONTEXT}">По данным библиотеки</a>, сбой с мая по сентябрь 2024 года нарушил работу сервисов выдачи; изменение долей нельзя считать прямой мерой спроса.</p></footer></main></body></html>'''


def main():
    rows = fetch(('checkoutyear', 'checkoutmonth', 'usageclass'))
    controls = fetch(('checkoutyear',))
    monthly, annual = summarize(rows, controls)
    verify_sql(rows, controls, monthly, annual)
    with (ROOT / 'summary.csv').open('w', encoding='utf-8', newline='') as stream:
        write_csv(stream, monthly, annual)
    (ROOT / 'report.html').write_text(render_html(monthly, annual), encoding='utf-8')
    for row in annual:
        print('{period}: digital={digital:,} physical={physical:,} total={total:,} share={digital_share_pct:.4f}%'.format(**row))
    print(f'{len(monthly)} months, {len(rows)} groups, {len(controls)} annual controls, '
          f'{sum(r["total"] for r in annual):,} checkouts; reconciled; SQL issues=0')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, URLError, sqlite3.Error) as exc:
        raise SystemExit(f'Analysis failed: {exc}') from exc
