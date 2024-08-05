SELECT
  LOWER(file_downloads.project) AS name,
  FORMAT_TIMESTAMP("%Y-%m", file_downloads.timestamp) AS month,
  COUNT(file_downloads.timestamp) AS download_count
FROM
  `bigquery-public-data.pypi.file_downloads` AS file_downloads
WHERE
  LOWER(file_downloads.project) IN UNNEST(@packages)
GROUP BY
  1,
  2
ORDER BY
  1,
  2,
  3