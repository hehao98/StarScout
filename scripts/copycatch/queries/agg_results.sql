WITH
  users AS (
  SELECT
    repo_name,
    ARRAY_AGG(actor) AS actors,
  FROM
    `@project_id.@dataset_id.users_*`
  WHERE
    ENDS_WITH(_TABLE_SUFFIX, CONCAT(@start_date, '_', @end_date))
  GROUP BY
    repo_name)
SELECT
  c.repo_name,
  c.cluster,
  users.actors
FROM
  `@project_id.@dataset_id.centers_*` c
JOIN
  users
ON
  users.repo_name = c.repo_name
WHERE
  ENDS_WITH(_TABLE_SUFFIX, CONCAT(@start_date, '_', @end_date))
  AND ARRAY_LENGTH(users.actors) >= @n
  AND ARRAY_LENGTH(c.cluster) >= @m