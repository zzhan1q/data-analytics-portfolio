"""Aggregate the official worldwide USGS earthquake CSV, without saving raw rows."""

import csv
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from io import StringIO
from math import ceil, isfinite
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
API = 'https://earthquake.usgs.gov/fdsnws/event/1/'
START = datetime(2023, 1, 1, tzinfo=timezone.utc)
END = datetime(2025, 1, 1, tzinfo=timezone.utc)
MONTHS = tuple(f'{year}-{month:02d}' for year in (2023, 2024) for month in range(1, 13))
MAG_BINS = ('[5,6)', '[6,7)', '[7,8)', '[8,+inf)')
DEPTH_BINS = ('<70', '[70,300)', '>=300', 'unknown')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]*', re.ASCII)


@dataclass
class Counts:
    monthly: dict = field(default_factory=lambda: dict.fromkeys(MONTHS, 0))
    magnitude: dict = field(default_factory=lambda: dict.fromkeys(MAG_BINS, 0))
    depth: dict = field(default_factory=lambda: dict.fromkeys(DEPTH_BINS, 0))
    excluded: int = 0
    duplicates: int = 0


def aggregate(text):
    rows = csv.DictReader(StringIO(text))
    if not {'id', 'time', 'mag', 'depth', 'type'}.issubset(rows.fieldnames or ()):
        raise ValueError('Unexpected USGS CSV columns')
    data = Counts()
    seen = {}
    for row in rows:
        if row['type'] != 'earthquake':
            data.excluded += 1
            continue
        stamp = datetime.fromisoformat((row['time'] or '').replace('Z', '+00:00'))
        if stamp.utcoffset() is None:
            raise ValueError('Event time must include a UTC offset')
        stamp = stamp.astimezone(timezone.utc)
        if not START <= stamp < END:
            data.excluded += 1
            continue
        mag = float(row['mag'] or '')
        if not isfinite(mag):
            raise ValueError('Magnitude must be finite')
        if mag < 5:
            data.excluded += 1
            continue
        id_ = row['id'] or ''
        if not ID.fullmatch(id_):
            raise ValueError(f'invalid event id: {id_!r}')
        try:
            depth = float(row['depth'] or '')
        except ValueError:
            depth = None
        if depth is not None and not isfinite(depth):
            depth = None
        payload = (stamp, mag, depth)
        if id_ in seen:
            if seen[id_] != payload:
                raise ValueError(f'conflicting records for event id {id_!r}')
            data.duplicates += 1
            continue
        seen[id_] = payload
        data.monthly[stamp.strftime('%Y-%m')] += 1
        data.magnitude[MAG_BINS[0 if mag < 6 else 1 if mag < 7 else 2 if mag < 8 else 3]] += 1
        data.depth[DEPTH_BINS[3 if depth is None else 0 if depth < 70 else 1 if depth < 300 else 2]] += 1
    if sum(data.monthly.values()) != sum(data.magnitude.values()) or len(seen) != sum(data.depth.values()):
        raise ValueError('Aggregate totals do not reconcile')
    return data


def bar_chart(monthly):
    step = 50
    top = max(step, ceil(max(monthly.values()) / step) * step)
    parts = ['<svg viewBox="0 0 720 245" role="img" aria-label="Число событий по месяцам"><title>Число событий по месяцам</title>']
    for tick in range(0, top + 1, step):
        y = 182 - tick * 160 / top
        parts.append(f'<line x1="53" x2="701" y1="{y:.2f}" y2="{y:.2f}" class="gridline"/><text x="44" y="{y + 4:.2f}" text-anchor="end">{tick}</text>')
    for i, (month, count) in enumerate(monthly.items()):
        x = 57 + i * 27
        height = count * 160 / top
        parts.append(f'<rect x="{x}" y="{182-height:.2f}" width="17" height="{height:.2f}" class="year{23+i//12}"><title>{month}: {count}</title></rect>')
        if i % 3 == 0:
            parts.append(f'<text x="{x+8}" y="205" text-anchor="middle">{month[5:]}</text>')
    parts.append('<text x="210" y="231" text-anchor="middle">2023</text><text x="534" y="231" text-anchor="middle">2024</text></svg>')
    return ''.join(parts)


STYLE = '''
:root{color-scheme:light;--ink:#252620;--muted:#50564b;--rule:#d5d5c7;--paper:#f3f1e8;--panel:#fffef8}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.55 'Segoe UI',Arial,sans-serif}
main{width:min(100% - 32px,1020px);margin:auto;padding:32px 0 48px}header{border-top:4px solid var(--ink);padding-top:12px}
.eyebrow{font:700 .78rem/1.4 Consolas,monospace;color:var(--muted);letter-spacing:.1em}h1{font:700 clamp(2rem,5vw,3.4rem)/1.08 Georgia,serif;margin:.35em 0}
h2{font-size:1.2rem;margin:0 0 .55em}p{margin:0 0 .8em}section,figure{margin:20px 0}figure,.sheet{background:var(--panel);border:1px solid var(--rule);padding:clamp(10px,3vw,24px)}
figcaption{font-weight:700}svg{display:block;width:100%;height:auto}svg text{font:13px 'Segoe UI',Arial,sans-serif;fill:var(--muted)}.gridline{stroke:var(--rule)}.year23{fill:#82725a}.year24{fill:#25665e}
.split{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.split section{margin:0}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{padding:.45rem .55rem;border-bottom:1px solid var(--rule);text-align:right}th:first-child{text-align:left}thead{background:#efeee5}a{color:#1a6159}a:focus-visible{outline:2px solid #1a6159;outline-offset:2px}footer{color:var(--muted);font-size:.9rem}
@media(max-width:600px){main{padding-top:18px}.split{grid-template-columns:1fr}svg text{font-size:18px}}
'''


def count_table(labels, values, total):
    rows = ''.join(f'<tr><th scope="row">{escape(label)}</th><td>{count}</td><td>{100 * count / total if total else 0:.1f}%</td></tr>'
                   for label, count in zip(labels, values))
    return f'<table><thead><tr><th scope="col">Интервал</th><th scope="col">События</th><th scope="col">Доля</th></tr></thead><tbody>{rows}</tbody></table>'


def publish(data, root):
    with (root / 'summary.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(('group', 'bucket', 'count'))
        for group, counts in (('month_utc', data.monthly), ('magnitude', data.magnitude), ('depth_km', data.depth)):
            writer.writerows((group, bucket, count) for bucket, count in counts.items())
    monthly = data.monthly
    y23, y24 = (sum(count for month, count in monthly.items() if month.startswith(year)) for year in ('2023', '2024'))
    total = y23 + y24
    max_count = max(monthly.values())
    peaks = ', '.join(month for month, value in monthly.items() if value == max_count)
    month_names = ('Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь')
    table = ''.join(f'<tr><th scope="row">{name}</th><td>{monthly[f"2023-{i:02d}"]}</td><td>{monthly[f"2024-{i:02d}"]}</td></tr>'
                    for i, name in enumerate(month_names, 1))
    page = f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Землетрясения мира · USGS</title><style>{STYLE}</style></head>
<body><main><header><div class="eyebrow">02 / USGS · МИР · 2023–2024 UTC</div><h1>Сколько землетрясений M ≥ 5 учёл USGS</h1><p><strong>{total} событий:</strong> {y23} в 2023 году и {y24} в 2024-м. Максимум за месяц — {max_count} ({peaks}).</p></header>
<figure><figcaption>Число событий по месяцам (UTC)</figcaption>{bar_chart(monthly)}</figure>
<div class="split"><section class="sheet"><h2>По магнитуде</h2>{count_table(('5 ≤ M < 6', '6 ≤ M < 7', '7 ≤ M < 8', 'M ≥ 8'), data.magnitude.values(), total)}</section>
<section class="sheet"><h2>По глубине, км</h2>{count_table(('< 70', '70 ≤ глубина < 300', '≥ 300', 'Неизвестна'), data.depth.values(), total)}</section></div>
<section class="sheet"><h2>Месячные итоги</h2><table><thead><tr><th scope="col">Месяц</th><th scope="col">2023</th><th scope="col">2024</th></tr></thead><tbody>{table}</tbody><tfoot><tr><th scope="row">Всего</th><td>{y23}</td><td>{y24}</td></tr></tfoot></table></section>
<footer><p>Источник: <a href="{API}">USGS Earthquake Catalog, FDSN Event Web Service</a>. От 01.01.2023 00:00 UTC включительно до 01.01.2025 00:00 UTC исключительно; <code>eventtype=earthquake</code>. Магнитуды приведены как в каталоге, без унификации шкал. Глубины ниже нуля входят в группу &lt; 70 км.</p><p>Исключено по фильтрам: {data.excluded}. Повторных ID с совпадающими показателями: {data.duplicates}. Каталог обновляется; это сводка записей, не оценка сейсмического риска и не прогноз.</p><a href="summary.csv" download>Скачать агрегированный CSV</a></footer></main></body></html>'''
    (root / 'report.html').write_text(page, encoding='utf-8')
    return total, y23, y24, max_count, peaks


def main():
    filters = {'starttime': '2023-01-01', 'endtime': '2025-01-01', 'minmagnitude': 5, 'eventtype': 'earthquake'}
    with urlopen(f'{API}count?{urlencode(filters)}', timeout=60) as response:
        expected = int(response.read().decode('ascii').strip())
    if not 0 < expected <= 20_000:
        raise ValueError(f'Unexpected USGS count: {expected}; check source or split query')
    with urlopen(f'{API}query?{urlencode(dict(filters, format="csv"))}', timeout=60) as response:
        text = response.read().decode('utf-8-sig')
    data = aggregate(text)
    included = sum(data.monthly.values())
    if included + data.excluded + data.duplicates != expected:
        raise ValueError('USGS count and CSV differ; retry to avoid publishing a partial result')
    total, y23, y24, month_max, peaks = publish(data, ROOT)
    print(f'Total: {total}; 2023: {y23}; 2024: {y24}; peak: {month_max} ({peaks})')
    print(f'Magnitude: {data.magnitude}; depth: {data.depth}; excluded: {data.excluded}; duplicates: {data.duplicates}')


if __name__ == '__main__':
    main()
