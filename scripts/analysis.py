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
                        f"n_{fake_type}_stars": {
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


def main():
    get_stars_by_month("low_activity")
    get_stars_by_month("clustered")


if __name__ == "__main__":
    main()
