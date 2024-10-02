SELECT
  type,
  created_at,
  repo.name as repo,
  actor.login as actor,
FROM
  `githubarchive.day.20*`
WHERE
  (_TABLE_SUFFIX BETWEEN @start_date AND @end_date)
  AND actor.login IN (
  SELECT
    DISTINCT actor
  FROM
    fake-star-detection.data.sample_repo_events
  ORDER BY
    RAND()
  LIMIT
    @sample_size)