-- Staging: Pull ALL activity for users who starred the suspicious repos in a time period
WITH
  watch_event_actors AS (
  SELECT
    DISTINCT actor.login AS actor
  FROM
    `githubarchive.day.20*`
  WHERE
    (_TABLE_SUFFIX BETWEEN @start_date
      AND @end_date)
    AND type = 'WatchEvent' -- starred
    AND repo.name IN UNNEST(@repositories)
    AND actor.login NOT LIKE '%[bot]'-- reduce table size
    )
SELECT
  actor.login AS actor,
  CONCAT(type, IFNULL(JSON_EXTRACT(payload, '$.action'), '')) AS event,
  DATE(created_at) date,
  created_at,
  actor.avatar_url,
  repo.name repo,
  org.login org,
  payload,
IF
  (repo.name IN UNNEST(@repositories), TRUE, FALSE) AS is_target_repo,
IF
  (type = 'WatchEvent', TRUE, FALSE) AS is_star,
FROM
  `githubarchive.day.20*`
WHERE
  (_TABLE_SUFFIX BETWEEN @start_date
    AND @start_date)
  AND actor.login IN (
  SELECT
    actor
  FROM
    watch_event_actors)