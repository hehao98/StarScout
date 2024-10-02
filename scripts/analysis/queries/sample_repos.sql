WITH
  repo_samples AS (
  SELECT
    repo.name, COUNT(actor) AS n_stars,
  FROM
    `githubarchive.day.20*`
  WHERE
    (_TABLE_SUFFIX BETWEEN @start_date AND @end_date) 
    AND type = 'WatchEvent'
    --- AND CONTAINS_SUBSTR(payload, 'started') --- Save query costs
  GROUP BY
    repo.name
  HAVING
    n_stars >= @min_stars
  ORDER BY
    RAND()
  LIMIT
    @sample_size)
SELECT
  type,
  created_at,
  repo.name as repo,
  actor.login as actor,
FROM
  `githubarchive.day.20*`
WHERE
  (_TABLE_SUFFIX BETWEEN @start_date AND @end_date)
  AND repo.name IN (SELECT name FROM repo_samples)
ORDER BY 
  repo, created_at