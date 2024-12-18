import os
import sys
import pymongo
import logging
import itertools
import pandas as pd
import multiprocessing as mp

from scripts import END_DATE, MONGO_URL
from scripts.github import get_user_info


def get_user_sets() -> tuple[set[str], set[str]]:
    client = pymongo.MongoClient(MONGO_URL)
    collection = client.fake_stars.low_activity_stars
    users_low_activity = list(
        collection.aggregate(
            [{"$match": {"low_activity": True}}, {"$group": {"_id": "$actor"}}]
        )
    )
    users_low_activity = set(x["_id"] for x in users_low_activity)

    collection = client.fake_stars.clustered_stars
    users_clustered = list(
        collection.aggregate(
            [{"$match": {"clustered": True}}, {"$group": {"_id": "$actor"}}]
        )
    )
    users_clustered = set(x["_id"] for x in users_clustered)

    client.close()
    return users_low_activity, users_clustered


def fetch_user_info(users: list[str]):
    client = pymongo.MongoClient(MONGO_URL)
    db = client.fake_stars
    for user in users:
        if db.actors.find_one({"actor": user}) is not None:
            logging.info("Skipping user %s", user)
            continue
        info = get_user_info(user)

        stars = list(db.clustered_stars.find({"actor": user}))
        stars.extend(list(db.low_activity_stars.find({"actor": user})))
        stars = sorted(
            [{"repo": x["repo"], "starred_at": x["starred_at"]} for x in stars],
            key=lambda x: x["starred_at"],
        )
        if "error" in info and "404" in info["error"]:
            db.actors.insert_one(
                {
                    "actor": user,
                    "error": True,
                    "stars": stars,
                    "info": None,
                }
            )
            logging.info("Fetched info for user %s", user)
        elif "error" not in info:
            db.actors.insert_one(
                {
                    "actor": user,
                    "error": False,
                    "stars": stars,
                    "info": info,
                }
            )
            logging.info("Fetched info for user %s", user)
        else:
            logging.error("No action for user %s, info = %s", user, info)
    client.close()


def get_fake_star_users() -> pd.DataFrame:
    client = pymongo.MongoClient(MONGO_URL)

    users_low_activity, users_clustered = get_user_sets()

    results = []
    for doc in client.fake_stars.actors.find():
        results.append(
            {
                "actor": doc["actor"],
                "n_repos_starred": set(x["repo"] for x in doc["stars"]),
                "low_activity": doc["actor"] in users_low_activity,
                "clustered": doc["actor"] in users_clustered,
                "deleted": doc["error"],
                "first_active": doc["stars"][0]["starred_at"],
                "last_active": doc["stars"][-1]["starred_at"],
            }
        )

    results = pd.DataFrame(results)
    results.to_csv(f"data/{END_DATE}/fake_stars_users.csv", index=False)
    return results


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.actors.create_index("actor", unique=True)
        client.fake_stars.clustered_stars.create_index("actor")
        client.fake_stars.low_activity_stars.create_index("actor")

    users_low_activity, users_clustered = get_fake_star_users()
    users = users_low_activity.union(users_clustered)
    logging.info("Fetched %d users", len(users))

    with mp.Pool(8) as pool:
        pool.map(fetch_user_info, itertools.batched(users, 100))

    get_fake_star_users()

    logging.info("Done!")


if __name__ == "__main__":
    main()
