"""Hillstrom 2008. Run `python analyze.py` (Python 3.11+; standard library).
Fetches the pinned original into memory and writes only summary.csv and case.json.
"""

import csv
import hashlib
import io
import json
import math
from decimal import Decimal
from pathlib import Path
from statistics import NormalDist
from urllib.request import urlopen

BLOG = (
    "https://blog.minethatdata.com/2008/03/minethatdata-e-mail-analytics-and-data.html"
)
CSV_URL = (
    "http://www.minethatdata.com/"
    "Kevin_Hillstrom_MineThatData_E-MailAnalytics_DataMiningChallenge_2008.03.20.csv"
)
SHA256 = "0e5893329d8b93cefecc571777672028290ab69865718020c78c7284f291aece"
ARMS = {
    "No E-Mail": ("control", "Без письма", 21306),
    "Mens E-Mail": ("mens", "Мужской ассортимент", 21307),
    "Womens E-Mail": ("womens", "Женский ассортимент", 21387),
}
HEADER = [
    "recency",
    "history_segment",
    "history",
    "mens",
    "womens",
    "zip_code",
    "newbie",
    "channel",
    "segment",
    "visit",
    "conversion",
    "spend",
]


def aggregate(raw):
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("Original CSV does not match its pinned SHA-256")
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8"), newline=""))
    assert reader.fieldnames == HEADER, "Unexpected original CSV schema"
    counts = {s: [0, 0, 0, Decimal("0.00")] for s in ARMS}
    for row in reader:
        segment = row["segment"]
        assert segment in counts, "Unknown assignment arm"
        v, c = int(row["visit"]), int(row["conversion"])
        s = Decimal(row["spend"])
        assert 0 <= c <= v <= 1, "Visit/conversion outside the binary funnel"
        assert s.is_finite() and s >= 0 and (s > 0) == bool(c), (
            "Spend and conversion disagree"
        )
        a = counts[segment]
        a[0] += 1
        a[1] += v
        a[2] += c
        a[3] += s
    assert sum(a[0] for a in counts.values()) == 64000, "Unexpected experiment size"
    assert all(counts[s][0] == spec[2] for s, spec in ARMS.items()), (
        "Unexpected allocation counts"
    )
    return counts


def summarize(counts):
    n0, v0, c0, s0 = counts["No E-Mail"]
    p0 = c0 / n0
    z = NormalDist().inv_cdf(1 - 0.05 / (2 * (len(ARMS) - 1)))
    rows = []
    for segment, (arm, _, _) in ARMS.items():
        n, v, c, s = counts[segment]
        p = c / n
        diff = p - p0
        # Difference of independent proportions; control-vs-itself is a reference, not a test.
        width = (
            z * math.sqrt(p * (1 - p) / n + p0 * (1 - p0) / n0)
            if arm != "control"
            else 0
        )
        lo, hi = diff - width, diff + width
        assert lo <= diff <= hi, "Invalid interval ordering"
        rows.append(
            {
                "arm": arm,
                "n": n,
                "visits": v,
                "conversions": c,
                "spend_total_usd": s,
                "visit_pct": 100 * v / n,
                "conversion_pct": 100 * p,
                "spend_usd_per_customer": float(s / n),
                "conversion_lift_pp": 100 * diff,
                "conversion_ci_low_pp": None if arm == "control" else 100 * lo,
                "conversion_ci_high_pp": None if arm == "control" else 100 * hi,
                "visit_lift_pp": 100 * (v / n - v0 / n0),
                "spend_lift_usd_per_customer": float(s / n - s0 / n0),
            }
        )
    return rows


def make_case(rows):
    control, mens, womens = rows
    treatments = rows[1:]
    labels = [label for _, label, _ in ARMS.values()]

    def ru(x, signed=False):
        return format(x, "+.3f" if signed else ".3f").replace(".", ",")

    def interval(r):
        return f"[{ru(r['conversion_ci_low_pp'], True)}; {ru(r['conversion_ci_high_pp'], True)}]"

    def kpi(label, value):
        return {"label": label, "value": value}

    def chart(title, unit, key):
        return {
            "title": title,
            "unit": unit,
            "type": "bar",
            "rows": [
                {"label": name, "value": round(r[key], 6)}
                for name, r in zip(labels, rows, strict=True)
            ],
        }

    return {
        "title": "Повысила ли email-рассылка долю покупателей?",
        "eyebrow": "Рандомизированный эксперимент · Hillstrom, 2008",
        "subtitle": "Две рассылки, контроль без письма и две недели наблюдения за 64 000 клиентами.",
        "question": "Насколько письмо с мужским или женским ассортиментом повышает вероятность покупки по сравнению с отсутствием письма? Что происходит с посещениями сайта и тратами?",
        "method": [
            "По описанию Кевина Хиллстрома, клиентов случайно распределили примерно поровну между двумя рассылками и контролем без письма. В течение двух недель после рассылки фиксировали посещения, покупки и траты. Названия писем обозначают ассортимент, а не пол клиентов.",
            "Сравниваем по назначенной группе (intention-to-treat): знаменатель — все клиенты группы, а не только посетившие сайт. Основная метрика — доля клиентов с покупкой. Эффект — доля в варианте минус доля в контроле, в процентных пунктах (п. п.).",
            "Для двух сравнений с общим контролем строим двусторонние интервалы Вальда для разности долей с раздельными оценками дисперсии. Поправка Бонферрони: уровень доверия 97,5% у каждого интервала, номинально не менее 95% для обоих одновременно.",
            "Посещения — доля клиентов, посетивших сайт. Траты — сумма покупок в долларах США на каждого назначенного клиента, включая нули. Для этих двух метрик приводим только описательные оценки, без проверки значимости.",
        ],
        "findings": [
            f"В контроле купили {control['conversions']} из 21 306 клиентов ({ru(control['conversion_pct'])}%).",
            *[
                f"{label}: конверсия {ru(r['conversion_pct'])}%; прирост к контролю {ru(r['conversion_lift_pp'], True)} п. п., интервал {interval(r)} п. п."
                for label, r in zip(labels[1:], treatments, strict=True)
            ],
            "Оба интервала выше нуля: у каждого письма прирост конверсии относительно контроля статистически значим после поправки. У письма с мужским ассортиментом точечный прирост больше, но прямое сравнение писем здесь не тестировали.",
            f"Посещения: {ru(mens['visit_lift_pp'], True)} и {ru(womens['visit_lift_pp'], True)} п. п. к контролю для мужского и женского ассортимента соответственно. Траты: {ru(mens['spend_lift_usd_per_customer'], True)} и {ru(womens['spend_lift_usd_per_customer'], True)} долл. США на клиента соответственно. Это прирост трат, а не прибыли.",
        ],
        "limits": [
            "Две недели наблюдения в одном историческом эксперименте: результаты нельзя автоматически переносить на другие аудитории, сезоны или частоту рассылок.",
            "Нет данных о марже, стоимости рассылки и долгосрочных последствиях, включая отписки. Значимый рост доли покупателей не доказывает окупаемость.",
        ],
        "action": "В новом тесте сохранить контроль без письма и проверить оба варианта на актуальной аудитории. До запуска задать минимальный полезный прирост конверсии и порог дополнительной маржинальной прибыли на клиента с учётом затрат; масштабировать только при подтверждённой окупаемости.",
        "sources": [
            {
                "name": "Кевин Хиллстром, MineThatData — E-Mail Analytics And Data Mining Challenge (20 марта 2008)",
                "url": BLOG,
            },
        ],
        "groups": [
            {
                "name": "Конверсия в покупку",
                "kpis": [
                    kpi("Без письма", f"{ru(control['conversion_pct'])}%"),
                    *[
                        kpi(
                            f"{label}: прирост",
                            f"{ru(r['conversion_lift_pp'], True)} п. п. · ДИ {interval(r)} п. п.",
                        )
                        for label, r in zip(labels[1:], treatments, strict=True)
                    ],
                ],
                "charts": [chart("Доля клиентов с покупкой", "%", "conversion_pct")],
            },
            {
                "name": "Посещения и траты",
                "kpis": [
                    *[
                        kpi(
                            label,
                            f"Посещения {ru(r['visit_lift_pp'], True)} п. п. · траты {ru(r['spend_lift_usd_per_customer'], True)} долл. США/клиента к контролю",
                        )
                        for label, r in zip(labels[1:], treatments, strict=True)
                    ],
                ],
                "charts": [
                    chart("Доля клиентов с посещением", "%", "visit_pct"),
                    chart(
                        "Траты на одного назначенного клиента",
                        "долл. США/клиента",
                        "spend_usd_per_customer",
                    ),
                ],
            },
        ],
        "checks": [
            "SHA-256 исходного CSV совпал с зафиксированным хешем; заголовок соответствует исходной схеме.",
            "Ровно 64 000 строк в трёх группах: 21 306, 21 307 и 21 387 клиентов.",
            "Посещение и покупка в каждой строке — бинарные признаки; покупок без посещения нет.",
            "Все траты конечны и неотрицательны; положительная сумма есть только у купивших, и у каждого купившего она положительна.",
        ],
    }


def main():
    if not __debug__:
        raise RuntimeError("Run without -O so that assertions are executed")
    with urlopen(CSV_URL, timeout=30) as response:
        raw = response.read(5_000_001)
    rows = summarize(aggregate(raw))
    case = make_case(rows)
    here = Path(__file__).resolve().parent
    with (here / "summary.csv").open("w", newline="", encoding="utf-8") as f:
        # The control has no estimated confidence interval against itself.
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {k: f"{v:.9f}" if isinstance(v, float) else v for k, v in row.items()}
            for row in rows
        )
    (here / "case.json").write_text(
        json.dumps(case, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Checked {sum(r['n'] for r in rows):,} assignments; wrote summary.csv and case.json."
    )


if __name__ == "__main__":
    main()
