# Портфолио аналитика данных

Проекты на открытых данных: продажи, продуктовые метрики, эксперименты, операционная аналитика и показатели стран. В кейсах есть исходный код или SQL, методика расчёта, результаты и ограничения. Инструменты: SQL (SQLite), Excel, Python и материалы для Power BI.

## Три кейса для знакомства

| Кейс | Вопрос и результат | Материалы |
|---|---|---|
| **Online Retail II** · SQL, дашборд | Что стояло за ростом нетто-выручки в ноябре 2011 года? Она выросла на 36,2% к октябрю. Крупнейшая товарная позиция объясняет около 5,7% прироста. | [Методика и превью](projects/online-retail-analytics/README.md) · [SQL](projects/online-retail-analytics/sql/analysis.sql) |
| **A/B-тест email-рассылки** · эксперименты | Увеличивали ли письма долю покупателей? Относительно контроля прирост составил 0,681 и 0,311 п. п. для двух вариантов. Сравнение писем между собой не проводилось. | [Методика и превью](03-email-experiment/README.md) · [Результаты CSV](03-email-experiment/summary.csv) |
| **Конверсия интернет-магазина** · SQL | Как объем трафика меняет вывод о конверсии? Новые посетители покупали чаще на сессию (24,91% против 13,93%), но вернувшиеся принесли больше покупок: 1 470 против 422. | [Методика и превью](02-shop-conversion/README.md) · [Результаты CSV](02-shop-conversion/summary.csv) |

## Все проекты

### Бизнес и операционная аналитика

- [Online Retail II: продажи и повторные покупки](projects/online-retail-analytics/README.md)
- [Конверсия интернет-магазина](02-shop-conversion/README.md)
- [A/B-тест email-рассылки](03-email-experiment/README.md)
- [Спрос на велопрокат](01-bike-demand/README.md)
- [Задержки рейсов из Нью-Йорка](04-flight-reliability/README.md)
- [Сроки закрытия обращений NYC 311](projects/nyc-311-response/README.md)
- [Цифровые выдачи библиотеки Сиэтла](projects/seattle-library-checkouts/README.md)

### Экономика и открытые данные

- [Доступ к электричеству](05-electricity-access/README.md)
- [Компоненты потребительской инфляции в США](projects/us-cpi-comparison/README.md)
- [Землетрясения M ≥ 5 по каталогу USGS](projects/usgs-earthquake-catalog/README.md)

### Excel + SQL: показатели стран

- [Урбанизация](projects/urbanization-excel-sql/README.md)
- [Распространение интернета](projects/internet-adoption-excel-sql/README.md)
- [Продолжительность жизни](projects/life-expectancy-excel-sql/README.md)
- [Возобновляемая электроэнергия](projects/renewable-electricity-excel-sql/README.md)
- [Внешняя торговля](projects/trade-openness-excel-sql/README.md)
- [Молодёжная безработица](projects/youth-unemployment-excel-sql/README.md)
- [Старение населения](projects/population-aging-excel-sql/README.md)
- [Расходы на здравоохранение](projects/health-spending-excel-sql/README.md)
- [Восстановление туризма](projects/tourism-recovery-excel-sql/README.md)
- [Денежные переводы](projects/remittance-dependence-excel-sql/README.md)

Отдельная заметка: [Численность заключённых в Казахстане](notes/kazakhstan-prison-population.md).

## Как открыть отчёты

Превью видны в README кейсов. Чтобы пользоваться фильтрами, скачайте репозиторий через **Code → Download ZIP**, распакуйте и откройте HTML из нужной папки. [Офлайн-оглавление первых пяти кейсов](index.html) тоже работает после распаковки. В десяти кейсах Excel + SQL готовые книги `report.xlsx` открываются отдельно. Команды пересборки и источники указаны в README каждого проекта.
