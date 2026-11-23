# Сборка отчёта в Power BI Desktop

Этот комплект содержит витрины и меры, а не готовый `.pbix`. Для просмотра готового отчёта без Power BI откройте `../dashboard.html`.

1. Импортируйте `Monthly.csv`, `Products.csv`, `Overview.csv`, `Quality.csv` как Text/CSV (UTF-8, разделитель запятая). В Power Query задайте `month`, `previous_month`, `stock`, `product` как Text. Денежные поля и `net_growth`/`repeat_rate` — Decimal Number; при чтении используйте локаль English (United Kingdom), чтобы десятичная точка распознавалась правильно. `orders`, `known_customers`, `repeat_customers`, `source_rows`, `missing_customer` — Whole Number.
2. Свяжите `Monthly[month]` (1) → `Products[month]` (*), Active, Single. `Overview` и `Quality` оставьте без связей. Официальное руководство: https://learn.microsoft.com/en-us/power-bi/transform-model/desktop-create-and-manage-relationships
3. Создайте меры из `Measures.dax` по одной. Денежные меры форматируйте как GBP, доли как проценты.
4. Соберите страницу по `../dashboard.png`: карточки нетто, заказов, среднего чека и изменения м/м; линия нетто по `Monthly[month]`; таблица `Products[stock]`, `Products[product]`, `[Product Contribution GBP]` с условным цветом; карточка доли повторных покупок за весь период. Добавьте одиночный срез `Monthly[month]`: через Edit interactions отключите его влияние на график 24 месяцев и на блок повторных покупок.
5. Сверьте значения выбранного месяца по `Monthly.csv`, а результат клиентской карточки — по `Overview.csv`. Откройте декабрь 2009: м/м и вклад отсутствуют, это ожидаемо. Строка `Quality` относится к исходным данным до дедупликации и фильтра периода.

**Зерно:** Monthly — месяц; Products — сравниваемый месяц × SKU; Overview — весь 24-месячный период; Quality — правило классификации. Число уникальных клиентов по месяцам нельзя суммировать. Процент м/м имеет смысл только при выбранном одном месяце.
