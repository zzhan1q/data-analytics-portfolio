"""Generate portfolio pages from the five adjacent case.json files."""

import html
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
CASES = {
    "01-bike-demand": "#16665b",
    "02-shop-conversion": "#33467c",
    "03-email-experiment": "#913d43",
    "04-flight-reliability": "#245c7b",
    "05-electricity-access": "#755112",
}


def text(x):
    return html.escape(str(x), quote=True)


def bullets(seq):
    return "".join(f"<li>{text(x)}</li>" for x in seq)


def load_cases():
    out = {}
    for name in CASES:
        data = json.loads((ROOT / name / "case.json").read_text(encoding="utf-8-sig"))
        assert all(
            data[k]
            for k in (
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
            )
        ), name
        assert len(data["groups"]) >= 2 and len(
            {g["name"] for g in data["groups"]}
        ) == len(data["groups"]), name
        for g in data["groups"]:
            assert 2 <= len(g["kpis"]) <= 4 and 1 <= len(g["charts"]) <= 2, (
                name,
                g["name"],
            )
            for c in g["charts"]:
                assert c["type"] in {"bar", "line"} and 1 <= len(c["rows"]) <= 16, (
                    name,
                    c["title"],
                )
                assert all(
                    isinstance(r["value"], (float, int))
                    and math.isfinite(r["value"])
                    and r["label"]
                    for r in c["rows"]
                ), name
        assert all(
            urlsplit(s["url"]).scheme == "https" and urlsplit(s["url"]).hostname
            for s in data["sources"]
        ), name
        out[name] = data
    return out


def write(path, body):
    path.write_text(body + "\n", encoding="utf8")


def dashboard_groups(groups):
    def pick(item, *keys):
        return {key: item[key] for key in keys}

    return [
        {
            "name": group["name"],
            "kpis": [pick(kpi, "label", "value") for kpi in group["kpis"]],
            "charts": [
                {
                    **pick(chart, "title", "unit", "type"),
                    "rows": [pick(row, "label", "value") for row in chart["rows"]],
                }
                for chart in group["charts"]
            ],
        }
        for group in groups
    ]


def build():
    cases = load_cases()
    template = (ROOT / "dashboard.template.html").read_text(encoding="utf8")
    index = []
    listing = []
    for name, data in cases.items():
        base = ROOT / name
        src = data["sources"]
        txt = {
            key.upper(): text(data[key])
            for key in ("title", "eyebrow", "subtitle", "question", "action")
        }
        txt.update(
            {
                key.upper(): bullets(data[key])
                for key in ("findings", "limits", "method", "checks")
            }
        )
        txt["ACCENT"] = CASES[name]
        txt["GROUPS"] = json.dumps(
            dashboard_groups(data["groups"]),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).replace("<", r"\u003c")
        txt["SOURCES"] = " · ".join(
            f'<a href="{text(x["url"])}" rel="noreferrer">{text(x["name"])}</a>'
            for x in src
        )
        expanded = re.sub(
            r"__([A-Z]+)__", lambda match, values=txt: values[match[1]], template
        )
        write(base / "dashboard.html", expanded)
        cmd = (
            "uv run --with-requirements requirements.txt python analyze.py"
            if (base / "requirements.txt").is_file()
            else "python analyze.py"
        )

        def bullet(seq):
            return "\n".join("- " + x for x in seq)

        srcmd = "\n".join(f"- [{x['name']}]({x['url']})" for x in src)
        xlsx = (
            "\n- `Demand.xlsx` — Excel-отчёт с исходными дневными рядами, формулами и диаграммой."
            if (base / "Demand.xlsx").is_file()
            else ""
        )
        sql = (
            "\n- `analysis.sql` — SQL-логика формирования аналитических срезов."
            if (base / "analysis.sql").is_file()
            else ""
        )
        write(
            base / "README.md",
            f"""# {data["title"]}

{data["subtitle"]}

{data["question"]}

[Открыть отчёт](dashboard.html) · [Витрина CSV](summary.csv)

![Отчёт: {data["title"]}](dashboard.png)

## Выводы

{bullet(data["findings"])}

**Следующий шаг:** {data["action"]}

## Методика

{bullet(data["method"])}

## Ограничения

{bullet(data["limits"])}

## Контроль качества

{bullet(data["checks"])}

## Воспроизводимость

- `analyze.py` — загрузка источника, расчёт и сверки.
- `summary.csv` — агрегаты рассчитанных срезов.
- `case.json` — значения и текст отчёта.{sql}{xlsx}

Запустить из этой папки (Python 3.11+, для Excel также `uv`):

```bash
{cmd}
```

Первый запуск читает открытый источник; исходный кэш не предназначен для репозитория. Из корня портфолио запустите `python assemble.py`, чтобы обновить HTML по рассчитанным `case.json`. PNG — снимок HTML-отчёта.

## Источники

{srcmd}""",
        )
        index.append(
            f'<li><div class="label">{text(data["eyebrow"])}</div><h2><a href="{name}/dashboard.html">{text(data["title"])}</a></h2><p>{text(data["subtitle"])}</p><p class="q">{text(data["question"])}</p></li>'
        )
        listing.append(
            f"| {data['title']} | {data['eyebrow'].split(' / ')[-1]} | [Отчёт]({name}/dashboard.html) · [Методика]({name}/README.md) |"
        )
    write(
        ROOT / "index.html",
        f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Портфолио аналитика данных</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f3f1e9;color:#162b30;font:16px 'Segoe UI',Arial,sans-serif}}main{{max-width:860px;margin:auto;padding:32px clamp(16px,5vw,56px)}}header{{border-top:4px solid #16665b;padding:22px 0}}h1{{font:400 clamp(35px,6vw,60px)/1.04 Georgia,serif;letter-spacing:-.04em;margin:5px 0 10px}}p{{margin:0 0 5px;color:#385258}}ol{{padding:0;list-style:none;margin:0}}li{{border-top:1px solid #bccac0;padding:16px 0}}h2{{font-size:22px;margin:5px 0}}a{{color:#13594f}}.label{{letter-spacing:.1em;color:#13594f;font-size:12px;font-weight:700}}.q{{line-height:1.45;color:#162b30}}a:focus-visible{{outline:2px solid #13594f;outline-offset:4px}}
</style></head><body><main><header><div class="label">DATA ANALYTICS / CASE STUDIES</div><h1>Портфолио аналитика данных</h1><p>Пять отраслевых кейсов · исторические данные · воспроизводимые расчёты</p></header><ol>{"".join(index)}</ol></main></body></html>""",
    )
    write(
        ROOT / "README.md",
        """# Портфолио аналитика данных

Пять самостоятельных кейсов на открытых данных. Каждый содержит отчёт, агрегаты, методику, проверки и исходный код расчёта.

**Офлайн:** скачайте файлы целиком, распакуйте и откройте `index.html`. GitHub показывает README и снимки панелей прямо в браузере; для интерактивных фильтров откройте скачанный HTML.

| Кейс | Навык | Материалы |
|---|---|---|
"""
        + "\n".join(listing)
        + """

## Как пересобрать

Запустите `analyze.py` каждого кейса из его папки по инструкции в README. После расчётов выполните `python assemble.py` из корня портфолио; HTML обновится из `case.json`. Для обычного просмотра пересборка не нужна.

В репозитории нет сырых клиентских записей, локальных баз, журналов, учётных данных и конфигурации среды. В каждом кейсе указан источник и ограничения. Индивидуальные данные экспериментальных участников не распространяются.
""",
    )


if __name__ == "__main__":
    build()
