WITH
  clusters AS (
  SELECT
    repo_name,
    cluster_repo_name,
    t1.centers[cluster_repo_name] AS cluster_repo_center,
    ARRAY_LENGTH(t1.cluster) as cluster_size
  FROM
    `socket-research.fake_stars.centers_*` t1
  CROSS JOIN
    UNNEST(t1.cluster) AS cluster_repo_name
  WHERE
    ENDS_WITH(_TABLE_SUFFIX, CONCAT(@start_date, '_', @end_date))),
  cluster_id_to_actor AS (
  SELECT
    clusters.repo_name,
    clusters.cluster_size,
    t2.actor,
  FROM
    clusters
  CROSS JOIN
    `socket-research.fake_stars.stargazers_*` t2
  WHERE
    ENDS_WITH(_TABLE_SUFFIX, CONCAT(@start_date, '_', @end_date))
    AND clusters.cluster_repo_name = t2.repo_name
    AND ABS(FLOAT64(clusters.cluster_repo_center) - UNIX_SECONDS(t2.starred_at)) <= @delta_t
    )
SELECT
  repo_name,
  actor,
FROM
  cluster_id_to_actor
GROUP BY
  repo_name,
  actor,
  cluster_size
HAVING
  COUNT(*) >= @rho * cluster_size - 0.001 -- handle numerical imprecision