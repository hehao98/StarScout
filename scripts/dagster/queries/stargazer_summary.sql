-- "All activities for users who starred repo in time period"

-- ### suspicious activity cluster definition ###
-- # suspicious actors (based on suspicious repos identified above)
-- {% set n_spammy_repo_overlap_gte = 2 %} -- user interacted with at least x suspicious repos in set AND
-- {% set p_spammy_repo_overlap_gt = 0.5 %} -- more than y% of actos' repos are suspicious AND
-- {% set actions_per_repo_lt = 2 %} -- user has on average less than 2 actions per repo they interacted with
-- ### suspicious low activity definition ###
-- # this is an approximation of the heuristic we use with the GH API data
-- {% set actor_dates = 1 %} -- user has activity on x dates
-- {% set actor_repos = 1 %} -- user has activity on x repos
-- {% set actor_orgs = 1 %} -- user has activity on x orgs
-- {% set actor_actions_lte = 2 %} -- user has no more than x total actions

-- identify suspicious users (activity cluster heuristic & low activity heuristic)
SELECT
    *,
    ARRAY_LENGTH(spammy_repo_overlap) AS n_spammy_repo_overlap,
    ARRAY_LENGTH(spammy_repo_overlap) / n_repos AS p_spammy_repo_overlap,
    CASE # run fake star detection heuristics:
    WHEN 1=1 -- activity cluster heuristic
        -- user interacted with at least x suspicious repos in set
        AND ARRAY_LENGTH(spammy_repo_overlap) >= 2
        -- more than y% of actos' repos are suspicious
        AND ARRAY_LENGTH(spammy_repo_overlap) / n_repos > 0.5
        -- user has on average less than z actions per repo they interacted with
        AND actions_per_repo < 2
    THEN 'suspected-activity_cluster'
    WHEN 1=1 -- low activity heuristic
        AND n_dates = 1 -- user has activity on 1 date
        AND n_repos = 1 -- user has activity on 1 repo (the target repo)
        AND n_orgs = 1 -- user has activity on 1 org
        AND n <= 2 -- user has no more than 2 total actions
    THEN 'suspected-low_activity'
    ELSE 'unknown'
    END as fake_acct,
FROM ( -- cross join actor table with spammy repo array, to calculate overlap
    SELECT
    a.*,
    ARRAY(
        SELECT * FROM a.repos
        INTERSECT DISTINCT
        SELECT * FROM b.repos
    ) AS spammy_repo_overlap
    FROM @project_id.@dataset_id.stg_stargazer_overlap a
        CROSS JOIN (
            SELECT ARRAY_AGG(repo) repos FROM @project_id.@dataset_id.stg_spammy_repos
        ) b
 )
