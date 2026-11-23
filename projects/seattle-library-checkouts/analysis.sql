-- SQLite. analyze.py creates these TEMP inputs and loads only Socrata aggregates:
-- source_monthly(checkoutyear INTEGER, checkoutmonth INTEGER, usageclass TEXT, n INTEGER)
-- source_annual(checkoutyear INTEGER, n INTEGER)

CREATE TEMP VIEW monthly AS
SELECT checkoutyear, checkoutmonth,
       SUM(CASE WHEN usageclass = 'Digital' THEN n ELSE 0 END) AS digital,
       SUM(CASE WHEN usageclass = 'Physical' THEN n ELSE 0 END) AS physical,
       SUM(n) AS total,
       100.0 * SUM(CASE WHEN usageclass = 'Digital' THEN n ELSE 0 END)
             / NULLIF(SUM(n), 0) AS digital_share_pct
FROM source_monthly
GROUP BY checkoutyear, checkoutmonth;

CREATE TEMP VIEW annual AS
SELECT checkoutyear, SUM(digital) AS digital, SUM(physical) AS physical,
       SUM(total) AS total,
       100.0 * SUM(digital) / NULLIF(SUM(total), 0) AS digital_share_pct
FROM monthly
GROUP BY checkoutyear;

-- A clean run returns no rows in issues. Expected grid is generated independently.
CREATE TEMP VIEW issues AS
WITH RECURSIVE years(y) AS (VALUES (2022) UNION ALL SELECT y+1 FROM years WHERE y<2024),
months(m) AS (VALUES (1) UNION ALL SELECT m+1 FROM months WHERE m<12),
classes(c) AS (VALUES ('Digital'), ('Physical')),
expected AS (SELECT y, m, c FROM years CROSS JOIN months CROSS JOIN classes)
SELECT 'missing group' AS issue, y AS year, m AS month, c AS usageclass
FROM expected
WHERE NOT EXISTS (SELECT 1 FROM source_monthly WHERE checkoutyear=y AND checkoutmonth=m AND usageclass=c)
UNION ALL
SELECT 'unexpected group / invalid count', checkoutyear, checkoutmonth, usageclass
FROM source_monthly
WHERE NOT EXISTS (SELECT 1 FROM expected WHERE checkoutyear=y AND checkoutmonth=m AND usageclass=c)
   OR typeof(n) != 'integer' OR n < 0
UNION ALL
SELECT 'duplicate group', checkoutyear, checkoutmonth, usageclass
FROM source_monthly GROUP BY checkoutyear, checkoutmonth, usageclass HAVING COUNT(*) > 1
UNION ALL
SELECT 'invalid control year / count', checkoutyear, NULL, NULL
FROM source_annual
WHERE checkoutyear IS NULL OR checkoutyear NOT BETWEEN 2022 AND 2024 OR typeof(n) != 'integer' OR n < 0
UNION ALL
SELECT 'annual reconciliation', y, NULL, NULL FROM years
WHERE (SELECT COUNT(*) FROM source_annual WHERE checkoutyear=y) <> 1
   OR NOT EXISTS (SELECT 1 FROM annual a JOIN source_annual s USING (checkoutyear)
                  WHERE a.checkoutyear=y AND a.total=s.n AND a.digital+a.physical=a.total);
