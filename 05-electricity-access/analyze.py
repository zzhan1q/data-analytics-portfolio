"""World Bank WDI case: python analyze.py [--cache | --offline].

Run by script path from any working directory; requires only Python 3 stdlib.
Default: fetch live without writing raw inputs. --cache: fetch live and save a
local snapshot in .cache/. --offline: use that snapshot; no network calls.
"""

import argparse
import csv
import json
import math
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
SNAPSHOT = ROOT / ".cache" / "wdi-2015-2022.json"
YEARS = tuple(range(2015, 2023))
ACCESS, POP = "EG.ELC.ACCS.ZS", "SP.POP.TOTL"
API = "https://api.worldbank.org/v2/"
REGIONS = {
    "EAS": "Восточная Азия и Тихоокеанский регион",
    "ECS": "Европа и Центральная Азия",
    "LCN": "Латинская Америка и Карибский бассейн",
    "MEA": "Ближний Восток, Северная Африка, Афганистан и Пакистан",
    "NAC": "Северная Америка",
    "SAS": "Южная Азия",
    "SSF": "Африка к югу от Сахары",
}
SOURCES = [
    {
        "name": "Всемирный банк — доступ к электроэнергии (EG.ELC.ACCS.ZS)",
        "url": "https://data.worldbank.org/indicator/EG.ELC.ACCS.ZS",
    },
    {
        "name": "Всемирный банк — численность населения (SP.POP.TOTL)",
        "url": "https://data.worldbank.org/indicator/SP.POP.TOTL",
    },
    {
        "name": "Всемирный банк — метаданные экономик и регионов",
        "url": "https://api.worldbank.org/v2/country?format=json&per_page=400",
    },
]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def fetch_page(resource, **params):
    url = API + resource + "?" + urlencode({"format": "json", **params})
    for attempt in range(3):
        try:
            with urlopen(url, timeout=30) as response:
                payload = json.load(response)
            break
        except (URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 2:
                raise
            time.sleep(2**attempt)
    if not (
        isinstance(payload, list)
        and len(payload) == 2
        and isinstance(payload[0], dict)
        and isinstance(payload[1], list)
    ):
        raise ValueError(f"Неожиданный ответ API: {resource}")
    return payload


def fetch_all(resource, **params):
    first, rows = fetch_page(resource, page=1, **params)
    pages = int(first["pages"])
    require(int(first["page"]) == 1 and pages >= 1, f"Первая страница: {resource}")
    for page in range(2, pages + 1):
        meta, part = fetch_page(resource, page=page, **params)
        require(
            int(meta["page"]) == page
            and all(
                meta.get(key) == first.get(key)
                for key in ("pages", "total", "sourceid", "lastupdated")
            ),
            f"API изменился при пагинации: {resource}",
        )
        rows.extend(part)
    require(len(rows) == int(first["total"]), f"Неполная выгрузка: {resource}")
    return first, rows


def retrieve():
    _, countries = fetch_all("country", per_page=400)
    snapshot = {"countries": countries, "series": {}}
    for indicator in (ACCESS, POP):
        meta, rows = fetch_all(
            f"country/all/indicator/{indicator}",
            source=2,
            date=f"{YEARS[0]}:{YEARS[-1]}",
            per_page=1000,
        )
        require(str(meta.get("sourceid")) == "2", f"Ожидался источник WDI: {indicator}")
        snapshot["series"][indicator] = {"updated": meta["lastupdated"], "rows": rows}
    return snapshot


def normalize(snapshot):
    countries = snapshot["countries"]
    require(
        len({r["id"] for r in countries}) == len(countries), "Повтор кода в метаданных"
    )
    economies = {
        r["id"]: r["region"]["id"] for r in countries if r["region"]["id"] != "NA"
    }
    require(set(economies.values()) == set(REGIONS), "Неожиданный состав регионов")
    series = {}
    for indicator in (ACCESS, POP):
        known = {}
        seen = set()
        for row in snapshot["series"][indicator]["rows"]:
            require(
                row["indicator"]["id"] == indicator, f"Неверный индикатор: {indicator}"
            )
            code, year, value = row["countryiso3code"], int(row["date"]), row["value"]
            require(year in YEARS, f"Год за пределами периода: {year}")
            if code not in economies:
                continue
            key = (code, year)
            require(key not in seen, f"Повтор наблюдения: {indicator} {key}")
            seen.add(key)
            if value is None:
                continue
            if indicator == ACCESS:
                require(
                    type(value) in (float, int) and 0 <= value <= 100,
                    f"Доля доступа вне диапазона: {key}",
                )
            else:
                require(type(value) is int and value >= 0, f"Неверное население: {key}")
                if value == 0:
                    continue
            known[key] = value
        series[indicator] = known
    return economies, series[ACCESS], series[POP]


def analyze(economies, access, population):
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE economies(code TEXT PRIMARY KEY, region TEXT NOT NULL);
            CREATE TABLE years(year INTEGER PRIMARY KEY);
            CREATE TABLE access(code TEXT, year INTEGER, value REAL NOT NULL, PRIMARY KEY(code, year));
            CREATE TABLE population(code TEXT, year INTEGER, value INTEGER NOT NULL, PRIMARY KEY(code, year));
        """)
        db.executemany("INSERT INTO economies VALUES (?, ?)", sorted(economies.items()))
        db.executemany("INSERT INTO years VALUES (?)", [(year,) for year in YEARS])
        db.executemany(
            "INSERT INTO access VALUES (?, ?, ?)",
            [(code, year, value) for (code, year), value in sorted(access.items())],
        )
        db.executemany(
            "INSERT INTO population VALUES (?, ?, ?)",
            [(code, year, value) for (code, year), value in sorted(population.items())],
        )
        return [
            dict(row)
            for row in db.execute((ROOT / "analysis.sql").read_text(encoding="utf-8"))
        ]


def verify(rows, economies, access, population):
    """Independent cross-check of SQL, using Python sets and math.fsum."""
    checks = []
    scopes = ("ALL", *REGIONS)
    observed = {(row["scope"], row["year"]): row for row in rows}
    require(
        len(rows) == len(observed)
        and set(observed) == {(s, y) for s in scopes for y in YEARS},
        "Неполные или повторные строки сводки",
    )
    checks.append(
        f"Проверены уникальность и полнота сводки: {len(rows)} строк, 8 лет и 8 географических срезов."
    )
    pairs = access.keys() & population.keys()
    panel = {code for code in economies if all((code, y) in pairs for y in YEARS)}
    inputs = []
    for scope in scopes:
        eligible = {
            code for code, region in economies.items() if scope in ("ALL", region)
        }
        members = panel & eligible
        require(bool(members), f"Пустая панель: {scope}")
        for year in YEARS:
            row = observed[scope, year]
            known_pops = [
                population[code, year]
                for code in eligible
                if (code, year) in population
            ]
            weights = [population[code, year] for code in members]
            require(
                (
                    row["metadata_economies"],
                    row["pop_economies"],
                    row["panel_economies"],
                )
                == (len(eligible), len(known_pops), len(members)),
                f"Состав панели: {scope}/{year}",
            )
            inputs.append((scope, year, row, members, known_pops, weights))
    checks.append(
        f"По пересечению исходных рядов подтверждена постоянная панель: {len(panel)} из {len(economies)} экономик, без агрегатов API."
    )
    for scope, year, row, _, known_pops, weights in inputs:
        known, covered = sum(known_pops), sum(weights)
        require(
            0 < covered <= known
            and (row["known_population"], row["covered_population"]) == (known, covered)
            and math.isclose(
                row["population_coverage_pct"], 100 * covered / known, abs_tol=1e-9
            ),
            f"Охват населения: {scope}/{year}",
        )
    checks.append(
        "Для каждой строки независимо пересчитаны обе суммы населения и доля покрытия."
    )
    for scope, year, row, members, _, weights in inputs:
        expected = {
            "weighted_pct": math.fsum(
                access[c, year] * population[c, year] for c in members
            )
            / sum(weights),
            "unweighted_pct": math.fsum(access[c, year] for c in members)
            / len(members),
        }
        for metric, value in expected.items():
            require(
                0 <= row[metric] <= 100
                and math.isclose(row[metric], value, rel_tol=0, abs_tol=1e-9),
                f"Проверка {metric}: {scope}/{year}",
            )
    checks.append(
        "Взвешенная и невзвешенная оценки независимо пересчитаны и совпали с SQL во всех строках."
    )
    return checks


def russian(value, digits=2):
    return f"{value:.{digits}f}".replace(".", ",")


def build_case(rows, checks, snapshot):
    table = {(row["scope"], row["year"]): row for row in rows}
    first, last = YEARS[0], YEARS[-1]
    start, end = table["ALL", first], table["ALL", last]
    region_levels = {code: table[code, last]["weighted_pct"] for code in REGIONS}
    region_delta = {
        code: region_levels[code] - table[code, first]["weighted_pct"]
        for code in REGIONS
    }
    lowest, highest = (
        min(region_levels, key=region_levels.get),
        max(region_levels, key=region_levels.get),
    )
    fastest = max(region_delta, key=region_delta.get)
    coverage = [table["ALL", year]["population_coverage_pct"] for year in YEARS]
    update_dates = ", ".join(
        sorted(
            {snapshot["series"][indicator]["updated"] for indicator in (ACCESS, POP)}
        )
    )
    gap = end["unweighted_pct"] - end["weighted_pct"]

    def kpi(label, value):
        return {"label": label, "value": value}

    def chart(title, unit, kind, items):
        return {
            "title": title,
            "unit": unit,
            "type": kind,
            "rows": [
                {"label": label, "value": round(value, 4)} for label, value in items
            ],
        }

    def trend(metric):
        return [(str(year), table["ALL", year][metric]) for year in YEARS]

    def ranked(values):
        return [
            (REGIONS[code], values[code])
            for code in sorted(values, key=lambda c: (-values[c], c))
        ]

    return {
        "title": "Доступ к электроэнергии в 2015–2022 годах",
        "eyebrow": "Аналитический кейс · Всемирный банк",
        "subtitle": "Динамика доступа, разница между двумя способами усреднения и сравнение регионов.",
        "question": "Как менялся доступ к электроэнергии и что меняется в выводах, если учитывать население каждой экономики?",
        "method": [
            f"Данные World Development Indicators: доступ к электроэнергии в процентах населения [1] и общая численность населения [2]. Дата обновления в ответе API: {update_dates}.",
            "Используем состав регионов из метаданных Всемирного банка [3]. Исключаем готовые агрегаты и соединяем два ряда по коду экономики и году.",
            "Берём только экономики с долей доступа и положительной численностью населения во всех восьми годах. Одного пропуска достаточно для исключения экономики из панели на весь период; пропуски не заполняем.",
            "Взвешенная оценка: сумма произведений доли доступа на население, делённая на население панели в том же году. В невзвешенной оценке каждая экономика имеет одинаковый вес.",
            "Охват населения: численность жителей панели в данном году, делённая на известную численность населения всех экономик соответствующей географии. В CSV также приведено число экономик по метаданным, с известным населением и в панели. ALL — итог по панели; прочие коды — регионы Всемирного банка.",
        ],
        "findings": [
            f"Доступ с весами по населению вырос с {russian(start['weighted_pct'])} % в {first} году до {russian(end['weighted_pct'])} % в {last} году ({russian(end['weighted_pct'] - start['weighted_pct'])} п. п.). [1][2][3]",
            f"Без взвешивания среднее изменилось с {russian(start['unweighted_pct'])} % до {russian(end['unweighted_pct'])} %. В {last} году разность «без весов минус с весами» составила {russian(gap)} п. п. [1][2][3]",
            f"Минимум среди регионов в {last} году — {REGIONS[lowest]} ({russian(region_levels[lowest])} %); максимум — {REGIONS[highest]} ({russian(region_levels[highest])} %). Наибольший прирост: {REGIONS[fastest]}, {russian(region_delta[fastest])} п. п. [1][2][3]",
            f"Панель включает {end['panel_economies']} из {end['metadata_economies']} экономик; за восемь лет её охват составлял {russian(min(coverage), 4)}–{russian(max(coverage), 4)} % известного населения. [1][2][3]",
        ],
        "limits": [
            "Это расчёт по панели, а не готовый мировой агрегат Всемирного банка. Экономики с пропусками могут отличаться по уровню доступа, а население без оценки не входит в знаменатель охвата.",
            "Население пересчитывается каждый год: взвешенная динамика отражает и изменения доступа, и изменения относительной численности населения. Показатель не измеряет надёжность или стоимость электроснабжения.",
            "Всемирный банк может пересматривать исторические ряды. Повторная загрузка воспроизводит метод, а запуск из сохранённого снимка — исходные значения.",
        ],
        "action": f"Начать детальный разбор с региона «{REGIONS[lowest]}»: проверить охват и разложить оценку по экономикам, прежде чем определять приоритеты электрификации.",
        "sources": SOURCES,
        "groups": [
            {
                "name": "Общая динамика и охват",
                "kpis": [
                    kpi(
                        f"С весами по населению, {last}",
                        f"{russian(end['weighted_pct'])} %",
                    ),
                    kpi(f"Без весов, {last}", f"{russian(end['unweighted_pct'])} %"),
                    kpi(
                        "Экономик в панели",
                        f"{end['panel_economies']} из {end['metadata_economies']}",
                    ),
                    kpi(
                        f"Охват известного населения, {last}",
                        f"{russian(end['population_coverage_pct'], 4)} %",
                    ),
                ],
                "charts": [
                    chart(
                        "Доступ с весами по населению",
                        "%",
                        "line",
                        trend("weighted_pct"),
                    ),
                    chart(
                        "Средний доступ без весов", "%", "line", trend("unweighted_pct")
                    ),
                ],
            },
            {
                "name": "Различия между регионами",
                "kpis": [
                    kpi(
                        f"Минимальный доступ, {last}",
                        f"{russian(region_levels[lowest])} % · {REGIONS[lowest]}",
                    ),
                    kpi(
                        f"Наибольший прирост, {first}–{last}",
                        f"{russian(region_delta[fastest])} п. п. · {REGIONS[fastest]}",
                    ),
                ],
                "charts": [
                    chart(
                        f"Доступ с весами по населению, {last}",
                        "%",
                        "bar",
                        ranked(region_levels),
                    ),
                    chart(
                        f"Изменение взвешенного доступа, {first}–{last}",
                        "п. п.",
                        "bar",
                        ranked(region_delta),
                    ),
                ],
            },
        ],
        "checks": checks,
    }


def write_json(path, data, indent=None):
    temp = path.with_suffix(".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, ensure_ascii=False, allow_nan=False, indent=indent)
        stream.write("\n")
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(
        description="Сводка доступа к электроэнергии по данным WDI, 2015–2022."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--cache",
        action="store_true",
        help="Загрузить данные и сохранить снимок в .cache.",
    )
    mode.add_argument(
        "--offline",
        action="store_true",
        help="Использовать сохранённый снимок без сети.",
    )
    args = parser.parse_args()
    if args.offline:
        if not SNAPSHOT.is_file():
            parser.error("Снимок отсутствует: сначала запустите скрипт с --cache.")
        snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    else:
        snapshot = retrieve()
    inputs = normalize(snapshot)
    rows = analyze(*inputs)
    checks = verify(rows, *inputs)
    case = build_case(rows, checks, snapshot)
    if args.cache:
        SNAPSHOT.parent.mkdir(exist_ok=True)
        write_json(SNAPSHOT, snapshot)
    temp = ROOT / "summary.tmp"
    with temp.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: f"{value:.10f}" if isinstance(value, float) else value
                    for key, value in row.items()
                }
            )
    temp.replace(ROOT / "summary.csv")
    write_json(ROOT / "case.json", case, indent=2)
    for check in checks:
        print(f"PASS: {check}")
    print("OK: summary.csv, case.json")


if __name__ == "__main__":
    main()
