SELECT
  type,
  created_at,
  repo.name as repo_name,
  actor.login as actor,
FROM
  `githubarchive.day.20*`
WHERE
  (_TABLE_SUFFIX BETWEEN @start_date AND @end_date)
  AND repo.name IN UNNEST(@repos)
ORDER BY 
  repo_name, created_at