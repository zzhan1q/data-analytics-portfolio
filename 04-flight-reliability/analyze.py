"""Пересоздать summary.csv и case.json: python analyze.py [--cache].

Python 3.11+, только стандартная библиотека. Без --cache CSV не сохраняется.
"""

import argparse
import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import NamedTuple
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
CSV_URL = "https://vincentarelbundock.github.io/Rdatasets/csv/nycflights13/flights.csv"
CSV_SHA256 = "b791a2590c9167aa0bd3cb45af3f64101180878cf088c183eae4011e3a654f42"
SOURCES = [
    {
        "name": "nycflights13 / tidyverse: документация flights",
        "url": "https://nycflights13.tidyverse.org/reference/flights.html",
    },
    {
        "name": "Bureau of Transportation Statistics (BTS): On-Time Performance",
        "url": "https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ",
    },
    {"name": "Rdatasets: CSV-зеркало nycflights13::flights", "url": CSV_URL},
]
ORIGINS = ("EWR", "JFK", "LGA")
MONTHS = (
    "янв",
    "фев",
    "мар",
    "апр",
    "май",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)


class Metrics(NamedTuple):
    flights: int
    observed: int
    missing: int
    delayed_15: int
    delayed_pct: float | None
    p90_min: int | None

    @property
    def missing_pct(self):
        return 100 * self.missing / self.flights


def summarize(flights, histogram):
    observed = sum(histogram.values())
    delayed = sum(count for delay, count in histogram.items() if delay >= 15)
    rank = (9 * observed + 9) // 10  # ceil(0.9 * n), индексация с 1
    cumulative = 0
    p90 = None
    for delay in sorted(histogram):
        cumulative += histogram[delay]
        if cumulative >= rank:
            p90 = delay
            break
    return Metrics(
        flights,
        observed,
        flights - observed,
        delayed,
        100 * delayed / observed if observed else None,
        p90,
    )


def aggregate(lines):
    total = Counter()
    histograms = defaultdict(Counter)
    reader = csv.DictReader(lines)
    if not {"year", "month", "origin", "arr_delay"} <= set(reader.fieldnames or ()):
        raise ValueError("В CSV нет обязательных полей.")
    for row in reader:
        year, month, origin = int(row["year"]), int(row["month"]), row["origin"]
        if year != 2013 or not 1 <= month <= 12 or origin not in ORIGINS:
            raise ValueError(
                f"Строка {reader.line_num}: неожиданный год, месяц или аэропорт."
            )
        period = f"{year}-{month:02d}"
        raw_delay = row["arr_delay"].strip()
        delay = None if raw_delay in ("", "NA") else int(raw_delay)
        for key in (
            ("all", "NYC"),
            ("month", period),
            ("origin", origin),
            ("month_origin", f"{period}/{origin}"),
        ):
            total[key] += 1
            if delay is not None:
                histograms[key][delay] += 1
    return {key: summarize(total[key], histograms[key]) for key in sorted(total)}


def self_test():
    sample = "year,month,origin,arr_delay\n2013,1,EWR,14\n2013,1,EWR,15\n2013,1,JFK,NA\n2013,2,JFK,-4\n2013,2,JFK,99\n2013,2,EWR,\n"
    metrics = aggregate(sample.splitlines())
    assert metrics.get(("all", "NYC")) == (6, 4, 2, 2, 50.0, 99), (
        "Итог: пропуски, порог 15 и p90"
    )
    assert metrics.get(("month", "2013-01")) == (3, 2, 1, 1, 50.0, 15), (
        "Знаменатель месяца"
    )
    assert metrics.get(("origin", "EWR")) == (3, 2, 1, 1, 50.0, 15), (
        "Знаменатель аэропорта"
    )
    assert metrics.get(("month_origin", "2013-01/JFK")) == (1, 0, 1, 0, None, None), (
        "Пустой знаменатель"
    )
    ranks = [
        "year,month,origin,arr_delay",
        *(f"2013,1,LGA,{d}" for d in range(10, 0, -1)),
    ]
    assert aggregate(ranks).get(("all", "NYC"))[-1] == 9, (
        "p90: 9-я позиция из 10, без интерполяции"
    )


def load_source(use_cache):
    cached = ROOT / ".cache" / "flights.csv"
    from_cache = use_cache and cached.is_file()
    if from_cache:
        payload = cached.read_bytes()
    else:
        with urlopen(CSV_URL, timeout=60) as response:
            payload = response.read()
    if hashlib.sha256(payload).hexdigest() != CSV_SHA256:
        raise ValueError(
            "SHA-256 исходного CSV не совпадает: проверьте версию данных или удалите повреждённый кэш."
        )
    if use_cache and not from_cache:
        cached.parent.mkdir(exist_ok=True)
        cached.write_bytes(payload)
    return io.StringIO(payload.decode("utf-8-sig"), newline="")


def validate(data):
    months = {f"2013-{m:02d}" for m in range(1, 13)}
    expected = {("all", "NYC")}
    expected.update(("month", m) for m in months)
    expected.update(("origin", o) for o in ORIGINS)
    expected.update(("month_origin", f"{m}/{o}") for m in months for o in ORIGINS)
    assert set(data) == expected, (
        "Ожидались все 12 месяцев, 3 аэропорта и 36 пересечений."
    )
    grand = data["all", "NYC"]
    assert grand[:4] == (336776, 327346, 9430, 80100), (
        "Контрольные суммы исходной выборки."
    )
    assert all(
        0 < m.observed <= m.flights == m.observed + m.missing
        and 0 <= m.delayed_15 <= m.observed
        for m in data.values()
    ), "Баланс в каждом срезе."
    for dimension in ("month", "origin", "month_origin"):
        assert (
            tuple(
                sum(m[i] for (dim, _), m in data.items() if dim == dimension)
                for i in range(4)
            )
            == grand[:4]
        ), f"Аддитивные метрики: {dimension}."
    for dim, label in sorted(expected):
        if dim in ("month", "origin"):
            part = 0 if dim == "month" else 1
            children = [
                m
                for (d, k), m in data.items()
                if d == "month_origin" and k.split("/")[part] == label
            ]
            assert (
                tuple(sum(m[i] for m in children) for i in range(4))
                == data[dim, label][:4]
            ), (dim, label)


def write_summary(data):
    with (ROOT / "summary.csv").open("w", encoding="utf-8", newline="") as output:
        out = csv.writer(output, lineterminator="\n")
        out.writerow(("dimension", "segment", *Metrics._fields, "missing_pct"))
        for (dim, label), m in data.items():
            out.writerow(
                (
                    dim,
                    label,
                    *m[:4],
                    f"{m.delayed_pct:.6f}",
                    m.p90_min,
                    f"{m.missing_pct:.6f}",
                )
            )


def case_payload(data):
    def count(n):
        return f"{n:,}".replace(",", "\u00a0")

    def pct(n):
        return f"{n:.2f}".replace(".", ",") + "\u00a0%"

    def fraction(m):
        return f"{count(m.delayed_15)} из {count(m.observed)}"

    def kpi(label, value):
        return {"label": label, "value": value}

    def chart(title, unit, kind, entries, field):
        return {
            "title": title,
            "unit": unit,
            "type": kind,
            "rows": [
                {"label": label, "value": round(getattr(m, field), 2)}
                for label, m in entries
            ],
        }

    def month_name(key):
        return MONTHS[int(key[-2:]) - 1]

    grand = data["all", "NYC"]
    months = [(k, m) for (d, k), m in data.items() if d == "month"]
    origins = sorted(
        ((k, m) for (d, k), m in data.items() if d == "origin"),
        key=lambda x: -x[1].delayed_pct,
    )
    high_key, high = max(months, key=lambda x: x[1].delayed_pct)
    low_key, low = min(months, key=lambda x: x[1].delayed_pct)
    tail_key, tail = max(months, key=lambda x: x[1].p90_min)
    hotspot_key, hotspot = max(
        ((k, m) for (d, k), m in data.items() if d == "month_origin"),
        key=lambda x: x[1].delayed_pct,
    )
    hot_month, hot_origin = hotspot_key.split("/")
    full_month = {"2013-07": "июль", "2013-09": "сентябрь", "2013-12": "декабрь"}

    def pretty_month(key):
        return full_month.get(key, month_name(key))

    return {
        "title": "Надёжность прилёта рейсов из Нью-Йорка",
        "eyebrow": "Транспортная аналитика · 2013",
        "subtitle": "Рейсы из EWR, JFK и LGA: как часто самолёты прибывали с опозданием и насколько велики были задержки.",
        "question": "В каких месяцах и аэропортах вылета опоздания на 15 минут и более встречались чаще всего?",
        "method": [
            "Данные `nycflights13::flights` из пакета tidyverse [1] основаны на статистике BTS [2]. Для расчёта использована CSV-копия Rdatasets [3].",
            "Месяц определяется по дате вылета; аэропорт — по коду `origin`. Опоздание: `arr_delay ≥ 15` минут, включая ровно 15 минут. Знаменатель — число записей с известным `arr_delay` в соответствующей группе.",
            "Доля пропусков: число записей без `arr_delay` делится на все записи группы. Ранние прилёты (отрицательные значения) входят в выборку, но не считаются опозданиями.",
            "p90: значение на позиции ⌈0,90 × n⌉ в отсортированных по возрастанию известных задержках; позиции считаются с 1, интерполяции нет.",
        ],
        "findings": [
            f"За год {pct(grand.delayed_pct)} рейсов с известной задержкой прилетели на 15 минут или позже ({fraction(grand)}). У {count(grand.missing)} из {count(grand.flights)} записей задержка неизвестна ({pct(grand.missing_pct)}).",
            f"Среди рейсов с известной задержкой максимум по доле опозданий — {pretty_month(high_key)}: {pct(high.delayed_pct)} ({fraction(high)}); минимум — {pretty_month(low_key)}: {pct(low.delayed_pct)} ({fraction(low)}). Максимум по p90 пришёлся на другой месяц: {pretty_month(tail_key)}, {tail.p90_min} мин против {high.p90_min} мин в месяце с наибольшей долей опозданий.",
            "По аэропортам вылета: "
            + "; ".join(
                f"{o} — {pct(m.delayed_pct)} ({fraction(m)})" for o, m in origins
            )
            + ".",
            f"Среди 36 сочетаний месяца и аэропорта максимальная доля опозданий — {hot_origin}, {pretty_month(hot_month)}: {pct(hotspot.delayed_pct)} ({fraction(hotspot)}).",
        ],
        "limits": [
            "В наборе нет отдельного признака отмены. Пропуск `arr_delay` не равен подтверждённой отмене; причины пропусков здесь не установлены.",
            "Это сравнение за один год без поправок на маршруты, перевозчиков и условия вылета. Оно не позволяет судить о причинах или переносить рейтинг на другие годы.",
        ],
        "action": f"Начать разбор с {hot_origin} за месяц {hot_month}: проверить отмены и отклонения от маршрута по флагам BTS и сравнить задержки по перевозчикам и направлениям. Для планирования стыковок отдельно смотреть p90: месяц с частыми опозданиями не обязательно даёт самые длинные задержки.",
        "sources": SOURCES,
        "groups": [
            {
                "name": "По месяцам вылета",
                "kpis": [
                    kpi("Рейсы с известной задержкой", count(grand.observed)),
                    kpi(
                        f"Макс. доля опозданий · {month_name(high_key)}",
                        pct(high.delayed_pct),
                    ),
                    kpi(
                        f"Мин. доля опозданий · {month_name(low_key)}",
                        pct(low.delayed_pct),
                    ),
                    kpi(f"Макс. p90 · {month_name(tail_key)}", f"{tail.p90_min} мин"),
                ],
                "charts": [
                    chart(
                        "Опоздания от 15 минут среди наблюдаемых прилётов",
                        "%",
                        "line",
                        [(month_name(k), m) for k, m in months],
                        "delayed_pct",
                    ),
                    chart(
                        "90-й перцентиль задержки прилёта",
                        "мин",
                        "line",
                        [(month_name(k), m) for k, m in months],
                        "p90_min",
                    ),
                ],
            },
            {
                "name": "По аэропортам вылета",
                "kpis": [
                    kpi(f"{o} · рейсы с известной задержкой", count(m.observed))
                    for o, m in origins
                ],
                "charts": [
                    chart(
                        "Опоздания от 15 минут среди наблюдаемых прилётов",
                        "%",
                        "bar",
                        origins,
                        "delayed_pct",
                    ),
                    chart(
                        "Записи без данных о задержке среди всех рейсов",
                        "%",
                        "bar",
                        origins,
                        "missing_pct",
                    ),
                ],
            },
        ],
        "checks": [
            "SHA-256 подтверждает совпадение исходного CSV с использованной версией.",
            "Контрольный набор проверяет порог 15 минут, отрицательные задержки, пропуски, пустой знаменатель и p90 без интерполяции.",
            "Найдены все 12 месяцев, 3 аэропорта и 36 сочетаний; суммы по каждому разрезу сходятся с итогом.",
            f"Баланс исходных записей: {count(grand.observed)} с известной задержкой + {count(grand.missing)} без неё = {count(grand.flights)}.",
        ],
    }


def main():
    if not __debug__:
        raise RuntimeError("Запускайте без -O: иначе проверки assert отключены.")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache", action="store_true", help="Сохранять входной CSV в локальной .cache."
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Выполнить контрольные проверки без сети.",
    )
    args = parser.parse_args()
    self_test()
    if args.self_test:
        print("OK: 5 self-test assertions")
        return
    with load_source(args.cache) as source:
        data = aggregate(source)
    validate(data)
    case_json = (
        json.dumps(case_payload(data), ensure_ascii=False, allow_nan=False, indent=2)
        + "\n"
    )
    write_summary(data)
    with (ROOT / "case.json").open("w", encoding="utf-8", newline="\n") as output:
        output.write(case_json)
    grand = data["all", "NYC"]
    print(
        f"OK: {len(data)} aggregates; flights={grand.flights}, observed={grand.observed}, "
        f"missing={grand.missing}, delayed_15={grand.delayed_15}, p90={grand.p90_min}; summary.csv, case.json"
    )


if __name__ == "__main__":
    main()
