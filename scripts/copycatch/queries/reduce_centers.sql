WITH
  center_with_actor AS (
  SELECT
    c.repo_name,
    c.repo_center,
    c.centers,
    u.actor,
  FROM
    `@project_id.@dataset_id.centers_*` c
  JOIN --sample to keep this join efficient
    `@project_id.@dataset_id.users_*` u TABLESAMPLE SYSTEM (10 PERCENT)
  ON
    c.repo_name = u.repo_name
  WHERE
    ENDS_WITH(c._TABLE_SUFFIX, CONCAT(@start_date, '_', @end_date))
    AND ENDS_WITH(u._TABLE_SUFFIX, CONCAT(@start_date, '_', @end_date))),
  new_centers AS (
  SELECT
    c.repo_name,
    c.repo_center,
    c.actor,
    s.repo_name AS center_repo_name,
    UNIX_SECONDS(s.starred_at) AS starred_at
  FROM
    center_with_actor c
  JOIN
    `@project_id.@dataset_id.stargazers_*` s
  ON
    c.actor = s.actor
    AND ABS(UNIX_SECONDS(s.starred_at) -
    IF
      (c.centers[s.repo_name] IS NULL, c.repo_center, FLOAT64(c.centers[s.repo_name]))) <= @delta_t
  WHERE
    ENDS_WITH(s._TABLE_SUFFIX, CONCAT(@start_date, '_', @end_date))),
  new_center2 AS (
  SELECT
    repo_name,
    repo_center,
    STRUCT(center_repo_name AS r,
      AVG(starred_at) AS c,
      COUNT(starred_at) AS p,
      VARIANCE(starred_at) AS v) AS centers,
  FROM
    new_centers
  GROUP BY
    repo_name,
    repo_center,
    center_repo_name),
  new_center3 AS (
  SELECT
    repo_name,
    repo_center,
    ARRAY_AGG(centers ORDER BY
      centers.p DESC, centers.v ASC
    LIMIT @relaxed_m) AS centers
  FROM
    new_center2
  GROUP BY
    repo_name,
    repo_center)
SELECT
  repo_name,
  repo_center,
  JSON_OBJECT(
    ARRAY(SELECT r FROM UNNEST(centers)), 
    ARRAY(SELECT c FROM UNNEST(centers))) AS centers,
  ARRAY((SELECT r FROM UNNEST(centers) LIMIT @m)) as cluster,
FROM
  new_center3