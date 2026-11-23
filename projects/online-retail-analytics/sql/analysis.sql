-- SQLite. Money is stored in 1/100000 GBP to avoid float aggregation.
-- Month window declared in build.py: [2009-12, 2011-12).
CREATE VIEW classified AS
SELECT *, substr(sold_at, 1, 7) AS month,
       CASE
         WHEN invoice = '' OR stock = '' OR sold_at IS NULL OR qty IS NULL OR price IS NULL THEN 'invalid'
         WHEN qty = 0 OR price <= 0 THEN 'non_positive_value'
         WHEN invoice LIKE 'C%' AND qty > 0 THEN 'cancel_positive'
         WHEN qty < 0 THEN 'adjustment'
         ELSE 'sale'
       END AS kind,
       qty * price AS amount
FROM lines;

CREATE TABLE ledger AS
SELECT DISTINCT invoice, stock, description, qty, sold_at, price, customer,
                country, month, kind, amount
FROM classified
WHERE kind IN ('sale','adjustment');
CREATE INDEX ledger_month ON ledger(month,stock);

CREATE TABLE month_summary AS
SELECT m.month,
       coalesce(sum(l.amount) FILTER(WHERE kind='sale'),0) AS sales,
       -coalesce(sum(l.amount) FILTER(WHERE kind='adjustment'),0) AS adjustments,
       coalesce(sum(l.amount),0) AS net,
       count(DISTINCT l.invoice) FILTER(WHERE kind='sale') AS orders,
       count(DISTINCT l.customer) FILTER(WHERE kind='sale') AS known_customers
FROM months AS m LEFT JOIN ledger AS l USING(month)
GROUP BY m.month;

CREATE TABLE monthly_export AS
WITH prev AS (
  SELECT *, lag(net) OVER (ORDER BY month) AS previous_net
  FROM month_summary
)
SELECT *, net-previous_net AS net_change,
       1.0*(net-previous_net)/nullif(previous_net,0) AS net_growth
FROM prev;

CREATE TABLE sku_month AS
SELECT l.month, stock, sum(amount) AS net
FROM ledger AS l JOIN months USING(month)
GROUP BY l.month, stock;
CREATE UNIQUE INDEX sku_key ON sku_month(month,stock);

CREATE TABLE product_delta AS
WITH names AS (
  SELECT stock, description, count(*) AS n
  FROM ledger JOIN months USING(month)
  WHERE kind='sale' AND description<>''
  GROUP BY stock,description
), name_rank AS (
  SELECT *, row_number() OVER(PARTITION BY stock ORDER BY n DESC,description) AS rn
  FROM names
), pairs AS (
  SELECT month, lag(month) OVER(ORDER BY month) AS prev FROM months
), keys AS (
  SELECT p.month, p.prev, s.stock FROM pairs p JOIN sku_month s ON s.month=p.month WHERE p.prev IS NOT NULL
  UNION
  SELECT p.month, p.prev, s.stock FROM pairs p JOIN sku_month s ON s.month=p.prev
)
SELECT k.month, k.prev AS previous_month, k.stock, coalesce(n.description,k.stock) AS product,
       coalesce(a.net,0) AS current_net, coalesce(b.net,0) AS prior_net,
       coalesce(a.net,0)-coalesce(b.net,0) AS contribution
FROM keys k
LEFT JOIN sku_month a ON a.month=k.month AND a.stock=k.stock
LEFT JOIN sku_month b ON b.month=k.prev AND b.stock=k.stock
LEFT JOIN name_rank n ON n.stock=k.stock AND n.rn=1;

CREATE TABLE customers AS
SELECT customer, count(DISTINCT invoice) AS orders
FROM ledger JOIN months USING(month)
WHERE kind='sale' AND customer IS NOT NULL
GROUP BY customer;

CREATE TABLE quality AS
SELECT kind AS rule, count(*) AS source_rows, sum(customer IS NULL) AS missing_customer
FROM classified GROUP BY kind;
