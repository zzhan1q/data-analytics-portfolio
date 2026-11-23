-- Reads in-memory requests(borough, created_us, closed_us, closed_missing).
-- Integer microseconds avoid floating timestamp error at exactly seven days.
WITH classified AS (
    SELECT borough,
           CASE
               WHEN closed_missing THEN 'missing'
               WHEN closed_us IS NULL OR closed_us < created_us THEN 'invalid'
               WHEN closed_us - created_us <= 604800000000 THEN 'within'
               ELSE 'after'
           END AS outcome
    FROM requests
)
SELECT borough,
       COUNT(*) AS total_requests,
       SUM(outcome = 'within') AS closed_within_7_days,
       SUM(outcome = 'after') AS closed_after_7_days,
       SUM(outcome = 'missing') AS missing_closed_date,
       SUM(outcome = 'invalid') AS invalid_closed_date,
       ROUND(100.0 * SUM(outcome = 'within') / COUNT(*), 2) AS pct_closed_within_7_days
FROM classified
GROUP BY borough
ORDER BY 1.0 * SUM(outcome = 'within') / COUNT(*) DESC, borough;
