-- SQLite. Inputs: economies(code, region), years(year),
-- access(code, year, value), population(code, year, value). Keys are unique.
-- Denominators include all eligible economies with reported positive population,
-- even if their electricity data is missing or they are outside the fixed panel.
WITH grid AS (
    SELECT e.code, e.region, y.year, a.value AS access_pct, p.value AS pop
    FROM economies AS e
    CROSS JOIN years AS y
    LEFT JOIN access AS a ON a.code = e.code AND a.year = y.year
    LEFT JOIN population AS p ON p.code = e.code AND p.year = y.year
), fixed_panel AS (
    SELECT code
    FROM grid
    WHERE access_pct IS NOT NULL AND pop > 0
    GROUP BY code
    HAVING COUNT(*) = (SELECT COUNT(*) FROM years)
), tagged AS (
    SELECT g.*, f.code IS NOT NULL AS in_panel
    FROM grid AS g
    LEFT JOIN fixed_panel AS f USING (code)
), scoped AS (
    SELECT 'ALL' AS scope, * FROM tagged
    UNION ALL
    SELECT region AS scope, * FROM tagged
)
SELECT scope, year,
       COUNT(*) AS metadata_economies,
       COUNT(CASE WHEN pop > 0 THEN 1 END) AS pop_economies,
       SUM(in_panel) AS panel_economies,
       SUM(CASE WHEN pop > 0 THEN pop ELSE 0 END) AS known_population,
       SUM(CASE WHEN in_panel THEN pop ELSE 0 END) AS covered_population,
       100.0 * SUM(CASE WHEN in_panel THEN pop ELSE 0 END)
           / NULLIF(SUM(CASE WHEN pop > 0 THEN pop ELSE 0 END), 0) AS population_coverage_pct,
       SUM(CASE WHEN in_panel THEN pop * access_pct END)
           / NULLIF(SUM(CASE WHEN in_panel THEN pop ELSE 0 END), 0) AS weighted_pct,
       AVG(CASE WHEN in_panel THEN access_pct END) AS unweighted_pct
FROM scoped
GROUP BY scope, year
ORDER BY scope, year;
