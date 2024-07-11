SELECT
  actor.login AS actor,
  repo.name repo,
  created_at AS starred_at,
FROM
  `githubarchive.day.20*`
WHERE
  (_TABLE_SUFFIX BETWEEN @start_date AND @end_date) 
  AND type = 'WatchEvent'
  AND CONTAINS_SUBSTR(payload, 'started')
