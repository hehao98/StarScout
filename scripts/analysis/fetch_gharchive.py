import sys
import random
import logging
import pymongo
import pandas as pd

from google.cloud import bigquery

from scripts import (
    MONGO_URL,
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
    GOOGLE_CLOUD_BUCKET as GCP_BUCKET,
    START_DATE,
    END_DATE,
    MIN_STARS_COPYCATCH_SEED,
)
from scripts.gcp import (
    process_bigquery,
    check_bigquery_table_exists,
    dump_bigquery_table,
    load_gzipped_json_blob_to_mongodb,
)
from scripts.analysis.data import get_fake_star_repos
from scripts.github import get_repo_id, get_user_info


SAMPLE_SIZE = 10000


def sample_repo_events():
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, "sample_repo_events"):
        logging.info("sample_repo_events already exists, skipping table creation")
    else:
        bigquery_task = {
            "interactive": False,
            "query_file": "scripts/analysis/queries/sample_repos.sql",
            "output_table_id": "sample_repo_events",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", START_DATE),
                bigquery.ScalarQueryParameter("end_date", "STRING", END_DATE),
                bigquery.ScalarQueryParameter("sample_size", "INT64", SAMPLE_SIZE),
                bigquery.ScalarQueryParameter(
                    "min_stars", "INT64", MIN_STARS_COPYCATCH_SEED
                ),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
        logging.info("table sample_repo_events created")

    blobs = dump_bigquery_table(
        PROJECT_ID, DATASET_ID, "sample_repo_events", GCP_BUCKET
    )

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.sample_repo_events.drop()
        client.fake_stars.sample_repo_events.create_index("repo")
    for blob in blobs:
        load_gzipped_json_blob_to_mongodb(
            blob, MONGO_URL, "fake_stars", "sample_repo_events"
        )
    return


def sample_user_events():
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, "sample_actor_events"):
        logging.info("sample_actor_events already exists, skipping table creation")
    else:
        bigquery_task = {
            "interactive": False,
            "query_file": "scripts/analysis/queries/sample_users.sql",
            "output_table_id": "sample_actor_events",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", START_DATE),
                bigquery.ScalarQueryParameter("end_date", "STRING", END_DATE),
                bigquery.ScalarQueryParameter("sample_size", "INT64", SAMPLE_SIZE),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
        logging.info("table sample_actor_events created")

    blobs = dump_bigquery_table(
        PROJECT_ID, DATASET_ID, "sample_actor_events", GCP_BUCKET
    )

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.sample_actor_events.drop()
        client.fake_stars.sample_actor_events.create_index("actor")
    for blob in blobs:
        load_gzipped_json_blob_to_mongodb(
            blob, MONGO_URL, "fake_stars", "sample_actor_events"
        )
    return


def stg_all_events_from_fake_star_repos():
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, "fake_repo_events"):
        logging.info("fake_repo_events already exists, skipping table creation")
    else:
        fake_star_repos = list(get_fake_star_repos().repo_name)
        logging.info("Number of fake star repos: %d", len(fake_star_repos))
        bigquery_task = {
            "interactive": False,
            "query_file": "scripts/analysis/queries/stg_all_events_repos.sql",
            "output_table_id": "fake_repo_events",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", START_DATE),
                bigquery.ScalarQueryParameter("end_date", "STRING", END_DATE),
                bigquery.ArrayQueryParameter("repos", "STRING", fake_star_repos),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
        logging.info("table fake_repo_events created")

    blobs = dump_bigquery_table(PROJECT_ID, DATASET_ID, "fake_repo_events", GCP_BUCKET)

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.fake_repo_events.drop()
        client.fake_stars.fake_repo_events.create_index("repo")
    for blob in blobs:
        load_gzipped_json_blob_to_mongodb(
            blob, MONGO_URL, "fake_stars", "fake_repo_events"
        )
    return


def stg_all_events_from_fake_star_actors():
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, "fake_actor_events"):
        logging.info("fake_actor_events already exists, skipping table creation")
    else:
        with pymongo.MongoClient(MONGO_URL) as client:
            fake_star_actors = list(
                map(
                    lambda x: x["_id"],
                    client.fake_stars.actors.aggregate([{"$group": {"_id": "$actor"}}]),
                )
            )
            motivating_example_actors = []
            for doc in client.fake_stars.low_activity_stars.find(
                {"repo": "gqylpy/funccache", "low_activity": True}
            ):
                motivating_example_actors.append(doc["actor"])
            for doc in client.fake_stars.clustered_stars.find(
                {"repo": "gqylpy/funccache", "clustered": True}
            ):
                motivating_example_actors.append(doc["actor"])
        logging.info("# of fake star actors: %d", len(fake_star_actors))
        logging.info("# in motivating example: %d", len(motivating_example_actors))

        fake_star_actors = random.sample(fake_star_actors, SAMPLE_SIZE)
        fake_star_actors += motivating_example_actors

        bigquery_task = {
            "interactive": False,
            "query_file": "scripts/analysis/queries/stg_all_events_actors.sql",
            "output_table_id": "fake_actor_events",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", START_DATE),
                bigquery.ScalarQueryParameter("end_date", "STRING", END_DATE),
                bigquery.ArrayQueryParameter("actors", "STRING", fake_star_actors),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
        logging.info("table fake_actor_events created")

    blobs = dump_bigquery_table(PROJECT_ID, DATASET_ID, "fake_actor_events", GCP_BUCKET)

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.fake_actor_events.drop()
        client.fake_stars.fake_actor_events.create_index("actor")
    for blob in blobs:
        load_gzipped_json_blob_to_mongodb(
            blob, MONGO_URL, "fake_stars", "fake_actor_events"
        )
    return


def aggregate_csvs():
    with pymongo.MongoClient(MONGO_URL) as client:
        results = (
            pd.DataFrame(
                list(
                    map(
                        lambda x: {
                            "repo": x["_id"]["repo"],
                            "month": x["_id"]["month"],
                            "n_stars": x["n_stars"],
                        },
                        client.fake_stars.sample_repo_events.aggregate(
                            [
                                {"$match": {"type": "WatchEvent"}},
                                {
                                    "$group": {
                                        "_id": {
                                            "repo": "$repo",
                                            "month": {"$substr": ["$created_at", 0, 7]},
                                        },
                                        "n_stars": {"$sum": 1},
                                    }
                                },
                            ]
                        ),
                    )
                )
            )
            .sort_values(by=["repo", "month"])
            .reset_index(drop=True)
        )
    results.to_csv(f"data/{END_DATE}/sample_repo_stars_by_month.csv", index=False)

    collections_and_pivots = [
        ("sample_repo_events", "repo"),
        ("sample_actor_events", "actor"),
        ("fake_repo_events", "repo"),
        ("fake_actor_events", "actor"),
    ]
    for collection, pivot in collections_and_pivots:
        with pymongo.MongoClient(MONGO_URL) as client:
            results = (
                pd.DataFrame(
                    list(
                        map(
                            lambda x: {
                                pivot: x["_id"][pivot],
                                "type": x["_id"]["type"],
                                "count": x["count"],
                            },
                            client.fake_stars[collection].aggregate(
                                [
                                    {
                                        "$group": {
                                            "_id": {
                                                pivot: f"${pivot}",
                                                "type": "$type",
                                            },
                                            "count": {"$sum": 1},
                                        }
                                    },
                                ]
                            ),
                        )
                    )
                )
                .pivot(index=pivot, columns="type", values="count")
                .fillna(0)
                .sort_values(by=pivot)
                .reset_index()
            )
        results.to_csv(f"data/{END_DATE}/{collection}.csv", index=False)


def check_deletion_status():
    sample_repos = pd.read_csv(f"data/{END_DATE}/sample_repo_events.csv")
    sample_actors = pd.read_csv(f"data/{END_DATE}/sample_actor_events.csv")
    fake_actors = pd.read_csv(f"data/{END_DATE}/fake_actor_events.csv")

    logging.info("Matching %d sample repos to GitHub IDs", len(sample_repos))
    sample_repo_ids = []
    for repo in sample_repos.repo:
        repo_id = get_repo_id(repo)
        sample_repo_ids.append({"repo": repo, "id": repo_id})
        logging.info("Repo: %s, ID: %s", repo, repo_id)

    sample_user_info = []
    for actor in sample_actors.actor:
        user_info = get_user_info(actor)
        if "error" in user_info:
            sample_user_info.append({"actor": actor, "error": user_info["error"]})
            logging.error("Actor: %s, Error: %s", actor, user_info["error"])
        else:   
            user_info = {k: v for k, v in user_info.items() if "url" not in k}
            user_info = {k: v for k, v in user_info.items() if "node_id" not in k}
            sample_user_info.append({"actor": actor, **user_info})
            logging.info("Actor: %s, Info: %s", actor, user_info)

    fake_user_info = []
    for actor in fake_actors.actor:
        user_info = get_user_info(actor)
        if "error" in user_info:
            fake_user_info.append({"actor": actor, "error": user_info["error"]})
            logging.error("Actor: %s, Error: %s", actor, user_info["error"])
        else:   
            user_info = {k: v for k, v in user_info.items() if "url" not in k}
            user_info = {k: v for k, v in user_info.items() if "node_id" not in k}
            fake_user_info.append({"actor": actor, **user_info})
            logging.info("Actor: %s, Info: %s", actor, user_info)


    pd.DataFrame(sample_repo_ids).to_csv(
        f"data/{END_DATE}/sample_repo_ids.csv", index=False
    )
    pd.DataFrame(sample_user_info).to_csv(
        f"data/{END_DATE}/sample_user_info.csv", index=False
    )
    pd.DataFrame(fake_user_info).to_csv(
        f"data/{END_DATE}/fake_user_info.csv", index=False
    )


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    sample_repo_events()
    sample_user_events()

    stg_all_events_from_fake_star_repos()
    stg_all_events_from_fake_star_actors()

    aggregate_csvs()

    check_deletion_status()

    logging.info("Finish!")


if __name__ == "__main__":
    main()
