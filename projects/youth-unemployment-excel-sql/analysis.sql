SELECT a.economy, a.iso, a.value, b.value, b.value - a.value AS metric
FROM observations AS a
JOIN observations AS b ON b.iso = a.iso AND b.year = a.year AND b.indicator = 'SL.UEM.1524.ZS'
WHERE a.indicator = 'SL.UEM.TOTL.ZS' AND a.year = 2023
  AND a.value IS NOT NULL AND b.value IS NOT NULL
ORDER BY metric DESC, a.iso;
