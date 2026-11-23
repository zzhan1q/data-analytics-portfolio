"""NYC 311 Street Condition in 2024; fetch only the three analysis fields."""
import csv
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from html import escape
import json
from pathlib import Path
import re
import sqlite3
import sys
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
HOST = 'https://data.cityofnewyork.us'
BASE_ID, VIEW_ID = 'erm2-nwe9', 'aqxm-wpww'
BASE_URL = f'{HOST}/Social-Services/311-Service-Requests-from-2020-to-Present/{BASE_ID}'
VIEW_URL = f'{HOST}/Social-Services/Street-Condition-311/{VIEW_ID}'
START, END = date(2024, 1, 1), date(2025, 1, 1)
FIELDS = ('borough', 'created_date', 'closed_date')
LIMIT = 10000
TS = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?')
EPOCH = datetime(1970, 1, 1)


class SourceError(RuntimeError):
    pass


def request_json(dataset, query):
    url = f'{HOST}/resource/{dataset}.json?{urlencode(query)}'
    try:
        with urlopen(Request(url, headers={'Accept': 'application/json'}), timeout=20) as r:
            result = json.load(r)
    except (URLError, OSError, ValueError) as exc:
        raise SourceError(f'{dataset}: {exc}') from exc
    if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
        raise SourceError(f'{dataset}: unexpected API response')
    return result


def month_windows():
    starts = [date(START.year, month, 1) for month in range(1, 13)]
    return zip(starts, starts[1:] + [END])


def where_clause(start, end):
    return ("complaint_type='Street Condition' AND "
            f"created_date >= '{start}T00:00:00' AND created_date < '{end}T00:00:00'")


def fetch_window(start, end, fetch=request_json):
    query = {'$select': ','.join(FIELDS), '$where': where_clause(start, end),
             '$order': 'created_date,:id', '$limit': LIMIT}
    failures = []
    for dataset in (BASE_ID, VIEW_ID):
        try:
            rows = fetch(dataset, query)
            if len(rows) >= LIMIT:
                raise SourceError(f'{dataset}: reached row limit')
            for row in rows:
                stamp = row.get('created_date')
                if (row.keys() - set(FIELDS) or not isinstance(stamp, str)
                        or not f'{start}T' <= stamp < f'{end}T'):
                    raise SourceError(f'{dataset}: unexpected fields or dates outside query window')
            return rows
        except SourceError as exc:
            failures.append(str(exc))
    if (end - start).days <= 1:
        raise SourceError(f'{start}–{end}: ' + '; '.join(failures))
    middle = start + (end - start) // 2
    return fetch_window(start, middle, fetch) + fetch_window(middle, end, fetch)


def fetch_counts(fetch=request_json):
    query = {'$select': 'borough,count(*) as n', '$where': where_clause(START, END),
             '$group': 'borough'}
    errors = []
    for dataset in (VIEW_ID, BASE_ID, VIEW_ID):
        try:
            return fetch(dataset, query)
        except SourceError as exc:
            errors.append(str(exc))
    raise SourceError('Annual group count unavailable: ' + '; '.join(errors))


def normalize_borough(value):
    return (value or '').strip().upper() or 'UNSPECIFIED'


def to_microseconds(value):
    if not isinstance(value, str) or not TS.fullmatch(value):
        return None
    try:
        elapsed = datetime.fromisoformat(value) - EPOCH
    except ValueError:
        return None
    return (elapsed.days * 86400 + elapsed.seconds) * 1_000_000 + elapsed.microseconds


def normalize_record(row):
    created = row.get('created_date')
    created_us = to_microseconds(created)
    if created_us is None or not f'{START}T' <= created < f'{END}T':
        raise ValueError('Invalid or out-of-cohort created_date')
    closed = row.get('closed_date')
    missing = closed is None or (isinstance(closed, str) and not closed.strip())
    return normalize_borough(row.get('borough')), created_us, to_microseconds(closed), int(missing)


def summarize(records):
    with sqlite3.connect(':memory:') as db:
        db.row_factory = sqlite3.Row
        db.execute('CREATE TABLE requests (borough TEXT NOT NULL, created_us INTEGER NOT NULL, '
                   'closed_us INTEGER, closed_missing INTEGER NOT NULL)')
        db.executemany('INSERT INTO requests VALUES (?, ?, ?, ?)', map(normalize_record, records))
        return [dict(row) for row in db.execute((ROOT / 'analysis.sql').read_text(encoding='utf-8'))]


def verify_counts(rows, counts):
    expected = Counter()
    for row in counts:
        expected[normalize_borough(row.get('borough'))] += int(row['n'])
    actual = {row['borough']: row['total_requests'] for row in rows}
    if not actual or actual != expected:
        raise ValueError(f'API count mismatch: loaded {actual}; official totals {dict(expected)}')
    for row in rows:
        if sum(row[k] for k in ('closed_within_7_days', 'closed_after_7_days',
                               'missing_closed_date', 'invalid_closed_date')) != row['total_requests']:
            raise ValueError(f"Outcome count mismatch: {row['borough']}")
    return sum(expected.values())


def fmt(value):
    return f'{value:,}'.replace(',', '\u202f')


def pct(value):
    return f'{value:.2f}'.replace('.', ',') + '\u00a0%'


def render_html(rows, snapshot):
    labels = {'BRONX': 'Бронкс', 'BROOKLYN': 'Бруклин', 'MANHATTAN': 'Манхэттен',
              'QUEENS': 'Куинс', 'STATEN ISLAND': 'Статен-Айленд', 'UNSPECIFIED': 'Не указан'}
    columns = ('total_requests', 'closed_within_7_days', 'closed_after_7_days',
               'missing_closed_date', 'invalid_closed_date')
    totals = [sum(row[k] for row in rows) for k in columns]
    city = pct(100 * totals[1] / totals[0])
    chart, table = [], []
    for row in rows:
        borough = row['borough']
        label = escape(labels.get(borough, borough))
        value = row['pct_closed_within_7_days']
        table.append(f'<tr><th scope="row">{label}</th>' +
                     ''.join(f'<td>{fmt(row[k])}</td>' for k in columns) + f'<td>{pct(value)}</td></tr>')
        if borough != 'UNSPECIFIED':
            chart.append(f'<li><span>{label}</span><span class="track"><span '
                         f'style="--fill:{value:.2f}%"></span></span><b>{pct(value)}</b></li>')
    foot = ''.join(f'<td>{fmt(x)}</td>' for x in totals) + f'<td>{city}</td>'
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NYC 311 · Street Condition · 2024</title>
<style>
:root{{--ink:#102b28;--muted:#405c57;--paper:#f8f7f1;--line:#c4cfc6;--accent:#087563}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 Arial,sans-serif}}
main{{width:min(1100px,100%);margin:auto;padding:clamp(16px,5vw,62px)}}
header{{border-top:5px solid var(--ink);padding:20px 0 26px;border-bottom:1px solid var(--line)}}
.eyebrow{{font:700 .77rem/1.3 Consolas,monospace;letter-spacing:.13em;color:var(--accent)}}
h1,h2,p,figure{{margin:0}} h1{{font:700 clamp(2.15rem,6vw,4.4rem)/1.02 Georgia,serif;margin:.32em 0}}
h2{{font:700 clamp(1.35rem,3vw,2rem)/1.15 Georgia,serif;margin-bottom:11px}}
.lede{{max-width:640px;color:var(--muted)}} .lede strong{{color:var(--ink)}}
figure,section{{margin-top:30px}} figcaption,p.note{{font-size:.89rem;color:var(--muted)}}
.bars{{padding:0;list-style:none;margin:14px 0 0}} .bars li,.axis{{display:grid;grid-template-columns:clamp(90px,24%,160px) minmax(0,1fr) clamp(60px,14%,80px);align-items:center;gap:8px}}
.bars li{{padding:8px 0;border-bottom:1px solid var(--line);font-size:.9rem}}
.track{{background:#dde6df;height:14px;display:block}} .track span{{display:block;width:var(--fill);height:100%;background:var(--accent)}}
.bars b{{text-align:right;font-variant-numeric:tabular-nums}} .axis span{{grid-column:2;display:flex;justify-content:space-between;font:.72rem Consolas,monospace;color:var(--muted);padding-top:5px}}
.table-wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%;min-width:650px;font-size:.87rem;font-variant-numeric:tabular-nums}}
th,td{{padding:8px 9px;border-bottom:1px solid var(--line);text-align:right}} th:first-child{{text-align:left}} thead{{background:#e7ede6}} tfoot{{font-weight:bold}} p.note{{margin-top:8px}} a{{color:var(--accent)}}
footer{{margin-top:24px;border-top:1px solid var(--line);padding-top:13px;color:var(--muted);font-size:.86rem}}
</style></head>
<body><main><header><p class="eyebrow">NYC OPEN DATA / 311 / 2024</p>
<h1>Закрытие обращений за 7 дней</h1><p class="lede">Street Condition: <strong>{fmt(totals[1])} из {fmt(totals[0])} ({city})</strong> обращений, созданных в 2024 году, закрыты за семь дней или быстрее.</p></header>
<figure aria-labelledby="chart-title"><h2 id="chart-title">Доля закрытых в срок по районам</h2><figcaption>Доля от всех обращений района. Группа без указанного района — в таблице.</figcaption>
<ol class="bars">{''.join(chart)}</ol><div class="axis" aria-hidden="true"><span><b>0%</b><b>50%</b><b>100%</b></span></div></figure>
<section aria-labelledby="counts"><h2 id="counts">Что вошло в расчёт</h2><div class="table-wrap" role="region" aria-label="Таблица результатов" tabindex="0">
<table><thead><tr><th scope="col">Район</th><th scope="col">Всего</th><th scope="col">≤ 7 дней</th><th scope="col">&gt; 7 дней</th><th scope="col">Нет даты</th><th scope="col">Некорректная дата</th><th scope="col">Доля ≤ 7 дней</th></tr></thead>
<tbody>{''.join(table)}</tbody><tfoot><tr><th scope="row">Все обращения</th>{foot}</tr></tfoot></table></div>
<p class="note">Срок — от 0 до 168 часов включительно по записанным локальным меткам времени. Пропуски и некорректные даты закрытия входят в знаменатель, но не в числитель. Закрытие в системе 311 не подтверждает устранение проблемы.</p></section>
<footer>Срез: {escape(snapshot)} · <a href="{BASE_URL}">NYC Open Data · {BASE_ID}</a> · <a href="{VIEW_URL}">представление {VIEW_ID}</a></footer></main></body></html>
'''


def write_outputs(root, rows, snapshot):
    report = render_html(rows, snapshot)
    with (root / 'summary.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, 'pct_closed_within_7_days': f"{row['pct_closed_within_7_days']:.2f}"})
    (root / 'report.html').write_text(report, encoding='utf-8')


def main():
    windows = list(month_windows())
    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = pool.submit(fetch_counts)
        months = [(start, pool.submit(fetch_window, start, end)) for start, end in windows]
        def records():
            for start, future in months:
                rows = future.result()
                print(f'{start:%Y-%m}: {len(rows)}', flush=True)
                yield from rows
        summary = summarize(records())
        total = verify_counts(summary, counts.result())
    snapshot = date.today().isoformat()
    write_outputs(ROOT, summary, snapshot)
    print(f'{snapshot}: official borough counts matched ({total:,} requests).')
    for row in summary:
        print(', '.join(f'{k}={v}' for k, v in row.items()))


if __name__ == '__main__':
    try:
        main()
    except (SourceError, ValueError) as exc:
        sys.exit(f'Analysis stopped: {exc}')
