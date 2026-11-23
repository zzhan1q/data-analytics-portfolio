# Разрыв между молодёжной и общей безработицей

В Джибути в 2023 году безработица среди 15–24-летних составила 76,39% против 26,07% по рабочей силе в целом. Разрыв в 50,32 п. п. оказался наибольшим среди 184 экономик с обеими оценками.

[Книга Excel](report.xlsx) · [Запрос SQLite](analysis.sql) · [Результаты CSV](summary.csv)

Две оценки МОТ соединены по экономике и году. Excel вычитает общую ставку из молодёжной. Лист «Сверка» показывает пропуски по году и расхождения между формулами и SQL.

Обе серии — моделируемые оценки МОТ за 2023 год. Знаменатель каждой ставки — рабочая сила соответствующей группы, а не всё население.

**Источник.** Всемирный банк, World Development Indicators: [`SL.UEM.TOTL.ZS`](https://data.worldbank.org/indicator/SL.UEM.TOTL.ZS), [`SL.UEM.1524.ZS`](https://data.worldbank.org/indicator/SL.UEM.1524.ZS). В `source.csv` оставлены национальные ряды за 2010–2023 годы; региональные и глобальные агрегаты исключены. [Лицензия набора](https://datacatalog.worldbank.org/infrastructure-data/search/dataset/0037712/world-development-indicators). Дата выгрузки: 23 ноября 2026 года. Пустая ячейка означает отсутствие наблюдения.

Готовая книга открывается без установки Python. Чтобы пересобрать её из `source.csv` и проверить результат:

```sh
uv run --with-requirements requirements.txt python build.py
uv run --with-requirements requirements.txt python -m unittest -v
```
