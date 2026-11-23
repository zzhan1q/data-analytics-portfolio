WITH observed AS (
    SELECT economy, iso, year, value,
           LAG(year) OVER history AS previous_year,
           LAG(value) OVER history AS previous_value,
           FIRST_VALUE(value) OVER history AS initial_value
    FROM observations
    WHERE indicator = 'IT.NET.USER.ZS' AND value IS NOT NULL
    WINDOW history AS (PARTITION BY iso ORDER BY year)
), crossings AS (
    SELECT economy, iso, previous_year, year,
           ROW_NUMBER() OVER (PARTITION BY iso ORDER BY year) AS crossing
    FROM observed
    WHERE initial_value < 50 AND previous_value < 50 AND value >= 50
)
SELECT economy, iso, previous_year, year, year - previous_year
FROM crossings WHERE crossing = 1
ORDER BY year, iso;
