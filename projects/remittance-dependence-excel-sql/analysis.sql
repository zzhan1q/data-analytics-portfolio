SELECT economy, iso, MIN(value), MAX(value), MAX(value) - MIN(value) AS spread
FROM observations
WHERE indicator = 'BX.TRF.PWKR.DT.GD.ZS' AND year BETWEEN 2019 AND 2023 AND value IS NOT NULL
GROUP BY iso, economy
HAVING COUNT(*) = 5 AND AVG(value) >= 5
ORDER BY spread DESC, iso;
