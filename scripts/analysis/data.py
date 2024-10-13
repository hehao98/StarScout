import os
import sys
import logging
import pymongo
import psycopg
import numpy as np
import pandas as pd

from typing import Optional
from collections import defaultdict
from psycopg.rows import dict_row
from psycopg.types.composite import CompositeInfo, register_composite
from google.cloud import bigquery

from scripts import (
    END_DATE,
    MONGO_URL,
    NPM_FOLLOWER_POSTGRES,
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
)
from scripts.gcp import process_bigquery


END_DATES = ["240701", "241001"]


def _pad_missing_months(df: pd.DataFrame, key: str) -> pd.DataFrame:
    df.sort_values([key, "month"], inplace=True)
    metrics = set(df.columns) - {key, "month"}
    missing_values = []
    for index, sub_df in df.groupby(key):
        first, last, all = (
            sub_df.month.iloc[0],
            sub_df.month.iloc[-1],
            set(sub_df.month),
        )
        for month in pd.date_range(first, last, freq="MS"):
            if month.strftime("%Y-%m") not in all:
                missing_values.append(
                    {
                        key: index,
                        "month": month.strftime("%Y-%m"),
                        **{m: 0 for m in metrics},
                    }
                )
    return pd.concat([df, pd.DataFrame(missing_values)], ignore_index=True).sort_values(
        [key, "month"]
    )


def _get_stars_by_month_from_mongodb(end_date: str, fake_type: str) -> pd.DataFrame:
    assert end_date in END_DATES and fake_type in ["low_activity", "clustered"]

    output_path = f"data/{end_date}/fake_stars_{fake_type}_stars_by_month.csv"
    if os.path.exists(output_path):
        return pd.read_csv(output_path)

    client = pymongo.MongoClient(MONGO_URL)

    stars_by_month = list(
        client.fake_stars[f"{fake_type}_stars"].aggregate(
            [
                {
                    "$group": {
                        "_id": {
                            "repo": "$repo",
                            "month": {"$substr": ["$starred_at", 0, 7]},
                        },
                        "n_stars": {"$sum": 1},
                        f"n_stars_{fake_type}": {
                            "$sum": {
                                "$convert": {"input": f"${fake_type}", "to": "int"}
                            }
                        },
                    }
                }
            ]
        )
    )

    stars_by_month = [{**x["_id"], **x} for x in stars_by_month]
    stars_by_month = pd.DataFrame(stars_by_month).sort_values(["repo", "month"])
    stars_by_month.drop(columns=["_id"], inplace=True)
    stars_by_month.to_csv(output_path, index=False)
    return stars_by_month


def get_fake_star_repos() -> pd.DataFrame:
    all_repos = pd.DataFrame()
    for end_date in END_DATES:
        low_activity = pd.read_csv(f"data/{end_date}/fake_stars_low_activity_repos.csv")
        clustered = pd.read_csv(f"data/{end_date}/fake_stars_clustered_repos.csv")

        repos = pd.merge(
            low_activity, clustered, on=["repo_id", "repo_name"], how="outer"
        )

        repos.insert(
            2, "n_stars", repos.n_stars_x.fillna(0) + repos.n_stars_y.fillna(0)
        )
        repos.insert(
            3,
            "n_stars_latest",
            repos.n_stars_latest_x.fillna(0) + repos.n_stars_latest_y.fillna(0),
        )
        repos["n_stars_low_activity"] = repos.n_stars_low_activity.fillna(0)
        repos["n_stars_clustered"] = repos.n_stars_clustered.fillna(0)
        repos["p_stars_low_activity"] = repos.n_stars_low_activity / repos.n_stars
        repos["p_stars_clustered"] = repos.n_stars_clustered / repos.n_stars
        repos["p_stars_fake"] = repos.p_stars_low_activity + repos.p_stars_clustered
        repos.drop(
            columns=[
                "n_stars_x",
                "n_stars_y",
                "n_stars_latest_x",
                "n_stars_latest_y",
            ],
            inplace=True,
        )
        all_repos = pd.concat([all_repos, repos], ignore_index=True)
    all_repos.drop_duplicates(subset=["repo_name"], keep="last", inplace=True)
    all_repos.sort_values("p_stars_fake", ascending=False, inplace=True)
    all_repos.reset_index(drop=True, inplace=True)
    return all_repos


def get_fake_stars_by_month(anomaly_detection: bool = False) -> pd.DataFrame:
    all_stars = pd.DataFrame()
    for end_date in END_DATES:
        low_activity = _get_stars_by_month_from_mongodb(end_date, "low_activity")
        clustered = _get_stars_by_month_from_mongodb(end_date, "clustered")
        stars = pd.merge(low_activity, clustered, on=["repo", "month"], how="outer")
        stars.insert(
            2, "n_stars", stars.n_stars_x.fillna(0) + stars.n_stars_y.fillna(0)
        )
        stars["n_stars_low_activity"] = stars.n_stars_low_activity.fillna(0)
        stars["n_stars_clustered"] = stars.n_stars_clustered.fillna(0)
        stars["n_stars_other"] = (
            stars["n_stars"]
            - stars["n_stars_low_activity"]
            - stars["n_stars_clustered"]
        )
        stars["n_stars_fake"] = (
            stars["n_stars_low_activity"] + stars["n_stars_clustered"]
        )
        stars.drop(columns=["n_stars_x", "n_stars_y"], inplace=True)
        stars.sort_values(["repo", "month"], inplace=True)
        all_stars = pd.concat([all_stars, stars], ignore_index=True)
    all_stars.drop_duplicates(subset=["repo", "month"], keep="last", inplace=True)
    all_stars = _pad_missing_months(all_stars, "repo")
    all_stars.sort_values(["repo", "month"], inplace=True)
    all_stars.reset_index(drop=True, inplace=True)

    if anomaly_detection:
        WINDOW_SIZE = 4
        THRESHOLD = 50
        all_stars["past_median"], all_stars["past_mad"] = 0.0, 0.0
        for _, df in all_stars.groupby("repo"):
            for i, _ in enumerate(df["month"]):
                past_values = [df["n_stars"].iloc[j] for j in range(i)][-WINDOW_SIZE:]
                if len(past_values) > 0:
                    past_median = np.median(past_values)
                    past_mad = np.median([abs(x - past_median) for x in past_values])
                else:
                    past_median, past_mad = 0, 0
                all_stars.loc[df.index[i], "past_median"] = past_median
                all_stars.loc[df.index[i], "past_mad"] = past_mad
        all_stars["threshold"] = (
            all_stars.past_median + all_stars.past_mad + np.maximum(all_stars.past_mad, THRESHOLD)
        )
        all_stars["anomaly"] = (
            (all_stars.n_stars >= all_stars.threshold)
            & (all_stars.n_stars_fake >= 50)
            & (all_stars.n_stars_fake >= 0.5 * all_stars.n_stars)
        )

    return all_stars


def get_sample_stars_by_month() -> pd.DataFrame:
    stars = pd.read_csv(f"data/{END_DATE}/sample_repo_stars_by_month.csv")
    stars = _pad_missing_months(stars, "repo")
    stars.sort_values(["repo", "month"], inplace=True)
    stars.reset_index(drop=True, inplace=True)
    return stars


def get_stars_from_repo(repo: str) -> Optional[pd.DataFrame]:
    client = pymongo.MongoClient(MONGO_URL)

    low_activity = client.fake_stars.low_activity_stars.find({"repo": repo})
    cluster = client.fake_stars.clustered_stars.find({"repo": repo})

    low_activity = pd.DataFrame(list(low_activity))
    cluster = pd.DataFrame(list(cluster))

    if len(low_activity) == 0 and len(cluster) == 0:
        return None

    if len(low_activity) == 0:
        cluster["low_activity"] = False
        return cluster

    if len(cluster) == 0:
        low_activity["clustered"] = False
        return low_activity

    merged = pd.merge(
        low_activity, cluster, on=["repo", "actor", "starred_at"], how="outer"
    ).drop(columns=["_id_x", "_id_y"])
    merged["low_activity"] = merged.low_activity.astype(bool).fillna(False)
    merged["clustered"] = merged.clustered.astype(bool).fillna(False)
    return merged


def get_repo_with_compaign() -> set[str]:
    repos = get_fake_star_repos()
    stars = get_fake_stars_by_month()

    stars["seems_like_compaign"] = (
        stars["n_stars_low_activity"] + stars["n_stars_clustered"] >= 50
    ) & (
        (stars["n_stars_low_activity"] + stars["n_stars_clustered"]) / stars["n_stars"]
        >= 0.5
    )

    repos_burst = set(stars[stars.seems_like_compaign].repo)
    # If lower than 10%, I choose to not trust the algorithm.
    # It may be producing false alerts for a legitimate repo.
    repos_high_pert = set(repos[repos["p_stars_fake"] >= 0.1].repo_name)
    return repos_burst & repos_high_pert


def get_pypi_pkgs_and_downloads() -> tuple[pd.DataFrame, pd.DataFrame]:
    repos_with_compaign = get_repo_with_compaign()
    pypi_github = pd.read_csv("data/pypi_github.csv")
    pypi_downloads = pd.read_csv("data/pypi_downloads.csv")
    pypi_pkg_repos = set(pypi_github.github) & repos_with_compaign

    pypi_github = (
        pypi_github[pypi_github.github.isin(pypi_pkg_repos)]
        .drop(columns=["version"])
        .drop_duplicates()
        .reset_index(drop=True)
    )

    pypi_downloads = pypi_downloads[pypi_downloads.name.isin(set(pypi_github.name))]

    return pypi_github, pypi_downloads


def get_npm_pkg_github() -> pd.DataFrame:
    if os.path.exists("data/npm_github.csv"):
        return pd.read_csv("data/npm_github.csv")
    npm_github = []
    with psycopg.connect(NPM_FOLLOWER_POSTGRES) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT 
                    packages.name, 
                    ((versions.repository_parsed).github_bitbucket_gitlab_user 
                    || '/' || (versions.repository_parsed).github_bitbucket_gitlab_repo)
                    AS github
                FROM versions 
                JOIN packages ON versions.package_id = packages.id
                WHERE (versions.repository_parsed).host = 'github'
                ORDER BY packages.name ASC
                """
            )
            for name, github in cur.fetchall():
                npm_github.append({"name": name, "github": github})
    npm_github = pd.DataFrame(npm_github)
    npm_github.to_csv("data/npm_github.csv", index=False)
    return npm_github


def get_npm_downloads() -> pd.DataFrame:
    if os.path.exists("data/npm_downloads.csv"):
        return pd.read_csv("data/npm_downloads.csv")

    npm_github = get_npm_pkg_github()
    repos = get_fake_star_repos()
    pkgs = set(npm_github[npm_github.github.isin(set(repos.repo_name))].name)

    npm_downloads = []
    with psycopg.connect(NPM_FOLLOWER_POSTGRES, row_factory=dict_row) as conn:
        t_info = CompositeInfo.fetch(conn, "download_count_struct")
        register_composite(t_info, conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT packages.name, download_counts FROM download_metrics
                JOIN packages ON packages.id = download_metrics.package_id
                WHERE packages.name = ANY(%(pkgs)s)
                ORDER BY packages.name ASC
                """,
                {"pkgs": list(pkgs)},
            )
            for row in cur.fetchall():
                for download in row["download_counts"]:
                    npm_downloads.append(
                        {
                            "name": row["name"],
                            "date": download.time.strftime("%Y-%m-%d"),
                            "download_count": download.counter,
                        }
                    )
    npm_downloads = pd.DataFrame(npm_downloads)
    npm_downloads.to_csv("data/npm_downloads.csv", index=False)


def get_npm_pkgs_and_downloads() -> tuple[pd.DataFrame, pd.DataFrame]:
    npm_github = get_npm_pkg_github()
    npm_downloads = get_npm_downloads()
    repos = get_repo_with_compaign()

    npm_github = npm_github[npm_github.github.isin(repos)]
    npm_downloads = npm_downloads[npm_downloads.name.isin(set(npm_github.name))]
    npm_downloads.insert(1, "month", npm_downloads.date.map(lambda x: x[:7]))
    npm_downloads = (
        npm_downloads.drop(columns=["date"])
        .groupby(["name", "month"])
        .sum()
        .reset_index()
    )

    return npm_github, npm_downloads


def get_pypi_pkgs_and_downloads() -> tuple[pd.DataFrame, pd.DataFrame]:
    repos = get_fake_star_repos()
    pypi_github = pd.read_csv("data/pypi_github.csv")
    if os.path.exists("data/pypi_downloads.csv"):
        pypi_downloads = pd.read_csv("data/pypi_downloads.csv")
    else:
        pypi_fake_repos = pypi_github[pypi_github["github"].isin(set(repos.repo_name))]
        all_fake_pkgs = set(pypi_fake_repos.name)
        all_fake_pkgs = sorted([x.lower() for x in all_fake_pkgs])
        logging.info(f"Total {len(all_fake_pkgs)} fake packages in PyPI")

        bigquery_task = {
            "interactive": True,
            "query_file": "scripts/analysis/queries/stg_pypi_downloads.sql",
            "output_table_id": "test_pypi_downloads",
            "params": [
                bigquery.ArrayQueryParameter("packages", "STRING", all_fake_pkgs),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)

        logging.info("Done!")
    return pypi_github, pypi_downloads


def get_modeling_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    path_stars, path_downloads = "data/model_stars.csv", "data/model_downloads.csv"
    if os.path.exists(path_stars) and os.path.exists(path_downloads):
        return pd.read_csv(path_stars), pd.read_csv(path_downloads)

    npm_github, npm_downloads = get_npm_pkgs_and_downloads()
    pypi_github, pypi_downloads = get_pypi_pkgs_and_downloads()
    stars = get_fake_stars_by_month()
    repos_with_campaign = sorted(get_repo_with_compaign())

    model_stars, model_downloads = defaultdict(dict), defaultdict(dict)

    for repo in repos_with_campaign:
        if repo in set(npm_github.github):
            pkgs = set(npm_github[npm_github.github == repo].name)
            df = (
                npm_downloads[npm_downloads.name.isin(pkgs)]
                .groupby("month")
                .sum()
                .reset_index()
            )
            for month, count in zip(df.month, df.download_count):
                model_downloads[repo][month] = count
        if repo in set(pypi_github.github):
            pkgs = set(pypi_github[pypi_github.github == repo].name)
            df = (
                pypi_downloads[pypi_downloads.name.isin(pkgs)]
                .groupby("month")
                .sum()
                .reset_index()
            )
            for month, count in zip(df.month, df.download_count):
                model_downloads[repo][month] = count
        df = stars[stars.repo == repo]
        for row in df.itertuples():
            model_stars[repo][row.month] = {
                "n_stars_all": row.n_stars,
                "n_stars_fake": row.n_stars_low_activity + row.n_stars_clustered,
                "n_stars_real": row.n_stars_other,
            }

    model_downloads_df = []
    for repo, months in model_downloads.items():
        for month, count in months.items():
            if month in model_stars[repo]:
                n_stars_all = model_stars[repo][month]["n_stars_all"]
                n_stars_fake = model_stars[repo][month]["n_stars_fake"]
                n_stars_real = model_stars[repo][month]["n_stars_real"]
            else:
                n_stars_all = n_stars_fake = n_stars_real = 0
            model_downloads_df.append(
                {
                    "repo": repo,
                    "month": month,
                    "platform": "npm" if repo in set(npm_github.github) else "PyPI",
                    "download_count": count,
                    "n_stars_all": n_stars_all,
                    "n_stars_fake": n_stars_fake,
                    "n_stars_real": n_stars_real,
                }
            )
    model_stars_df = [
        {"repo": repo, "month": month, **data}
        for repo, months in model_stars.items()
        for month, data in months.items()
    ]

    model_stars_df = pd.DataFrame(model_stars_df)
    model_downloads_df = pd.DataFrame(model_downloads_df)
    model_stars_df.to_csv("data/model_stars.csv", index=False)
    model_downloads_df.to_csv("data/model_downloads.csv", index=False)
    return model_stars_df, model_downloads_df


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logging.info("Collecting stars by month...")
    for end_date in END_DATES:
        _get_stars_by_month_from_mongodb(end_date, "low_activity")
        _get_stars_by_month_from_mongodb(end_date, "clustered")
    get_fake_stars_by_month()

    logging.info("Collecting downloads...")
    get_npm_pkg_github()
    get_npm_downloads()
    get_pypi_pkgs_and_downloads()

    logging.info("Collecting modeling data...")
    get_modeling_data()


if __name__ == "__main__":
    main()
