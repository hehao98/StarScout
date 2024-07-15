WITH
  repo_low_activity_actors AS (
  SELECT
    repo_name,
    low_activity_actor
  FROM
    @project_id.@dataset_id.repos_with_low_activity_stars,
    UNNEST(low_activity_actors) AS low_activity_actor
  WITH
  OFFSET
    off )
SELECT DISTINCT
  actor.login AS actor,
  repo.name repo,
  created_at AS starred_at,
  actor.login IN (
  SELECT
    low_activity_actor
  FROM
    repo_low_activity_actors) AS low_activity
FROM
  `githubarchive.day.20*`
WHERE
  (_TABLE_SUFFIX BETWEEN @start_date
    AND @end_date)
  AND type = 'WatchEvent'
  AND CONTAINS_SUBSTR(payload, 'started')
  AND repo.name IN (
  SELECT
    repo_name
  FROM
    repo_low_activity_actors)