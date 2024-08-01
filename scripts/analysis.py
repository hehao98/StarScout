import os
import pymongo
import pandas as pd


from scripts import MONGO_URL


def get_stars_by_month(fake_type: str) -> pd.DataFrame:
    assert fake_type in ["low_activity", "clustered"]

    output_path = f"data/fake_stars_{fake_type}_stars_by_month.csv"
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


def get_fake_star_repos_all() -> pd.DataFrame:
    low_activity = pd.read_csv("data/fake_stars_low_activity_repos.csv")
    clustered = pd.read_csv("data/fake_stars_clustered_repos.csv")

    repos = pd.merge(low_activity, clustered, on=["repo_id", "repo_name"], how="outer")

    repos.insert(2, "n_stars", repos.n_stars_x.fillna(0) + repos.n_stars_y.fillna(0))
    
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
        columns=["n_stars_x", "n_stars_y", "n_stars_latest_x", "n_stars_latest_y"],
        inplace=True,
    )

    repos.sort_values("p_stars_fake", ascending=False, inplace=True)

    repos.reset_index(drop=True, inplace=True)

    return repos


def get_stars_by_month_all() -> pd.DataFrame:
    low_activity = get_stars_by_month("low_activity")
    clustered = get_stars_by_month("clustered")
    stars = pd.merge(low_activity, clustered, on=["repo", "month"], how="outer")
    stars.insert(2, "n_stars", stars.n_stars_x.fillna(0) + stars.n_stars_y.fillna(0))
    stars["n_stars_low_activity"] = stars.n_stars_low_activity.fillna(0)
    stars["n_stars_clustered"] = stars.n_stars_clustered.fillna(0)
    stars["n_stars_other"] = (
        stars["n_stars"] - stars["n_stars_low_activity"] - stars["n_stars_clustered"]
    )
    stars.drop(columns=["n_stars_x", "n_stars_y"], inplace=True)
    stars.sort_values(["repo", "month"], inplace=True)
    return stars


def main():
    get_stars_by_month("low_activity")
    get_stars_by_month("clustered")


if __name__ == "__main__":
    main()
