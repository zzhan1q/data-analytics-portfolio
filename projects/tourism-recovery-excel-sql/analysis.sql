WITH paired AS (
    SELECT a.economy, a.iso, a.value AS baseline, b.value AS comparison
    FROM observations AS a
    JOIN observations AS b ON b.iso = a.iso AND b.indicator = a.indicator AND b.year = 2023
    WHERE a.indicator = 'tour_occ_arnat' AND a.year = 2019
      AND a.value IS NOT NULL AND b.value IS NOT NULL
      AND a.value > 0
)
SELECT economy, iso, baseline, comparison, comparison / baseline * 100 AS metric
FROM paired ORDER BY metric DESC, iso;
