-- "Table with 1 row per repo, summarizing similarity to other repos actors touched"

SELECT
    *,
    CASE
        WHEN repo IN (SELECT repo FROM @project_id.@dataset_id.stg_spammy_repos)
        THEN 'suspected-activity_cluster'
        ELSE 'unknown'
    END as fake_acct
FROM @project_id.@dataset_id.stg_stargazer_repo_clusters