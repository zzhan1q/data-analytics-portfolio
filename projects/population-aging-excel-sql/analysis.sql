WITH paired AS (
    SELECT a.economy, a.iso, a.value AS baseline, b.value AS comparison
    FROM observations AS a
    JOIN observations AS b ON b.iso = a.iso AND b.indicator = a.indicator AND b.year = 2023
    WHERE a.indicator = 'SP.POP.65UP.TO.ZS' AND a.year = 2010
      AND a.value IS NOT NULL AND b.value IS NOT NULL
), ranks AS (
    SELECT economy, iso, RANK() OVER (ORDER BY baseline DESC) AS rank_start,
           RANK() OVER (ORDER BY comparison DESC) AS rank_end
    FROM paired
)
SELECT economy, iso, rank_start, rank_end, rank_start - rank_end AS rise
FROM ranks ORDER BY rise DESC, iso;
