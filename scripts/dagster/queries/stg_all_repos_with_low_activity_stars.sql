WITH
  low_activity_users AS (
  SELECT
    actor.login AS actor,
    DATE(MIN(created_at)) AS first_active,
    DATE(MAX(created_at)) AS last_active,
    COUNT(created_at) AS n_actions,
    COUNT(DISTINCT repo.name) AS n_repos,
    COUNT(DISTINCT org.login) AS n_orgs,
  FROM
    `githubarchive.day.20*`
  WHERE
    (_TABLE_SUFFIX BETWEEN @start_date
      AND @end_date)
  GROUP BY
    actor
  HAVING
    first_active = last_active
    AND n_actions <= 2
    AND n_repos <= 1
    AND n_orgs <= 1 ),
  stars AS (
  SELECT
    actor.login AS actor,
    repo.id AS repo_id,
    repo.name AS repo_name,
    (actor.login IN (
      SELECT
        actor
      FROM
        low_activity_users)) AS low_activity
  FROM
    `githubarchive.day.20*`
  WHERE
    (_TABLE_SUFFIX BETWEEN @start_date
      AND @end_date)
    AND type = "WatchEvent" )
SELECT
  repo_name,
  COUNT(DISTINCT actor) AS n_stars,
  COUNTIF(low_activity = TRUE) AS n_stars_low_activity,
  ARRAY_AGG(DISTINCT
  IF
    (low_activity = FALSE, actor, NULL) IGNORE NULLS) AS low_activity_actors
FROM
  stars
GROUP BY
  repo_name
HAVING
  n_stars_low_activity >= @min_stars_low_activity
ORDER BY
  n_stars_low_activity DESC