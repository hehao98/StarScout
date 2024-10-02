import sys
import random
import logging
import pymongo

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
from scripts.analysis.data import get_fake_star_repos_all


SAMPLE_SIZE = 10000


def sample_repos():
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, "sample_repos"):
        logging.info("sample_repos already exists, skipping table creation")
    else:
        bigquery_task = {
            "interactive": True,
            "query_file": "scripts/analysis/queries/sample_repos.sql",
            "output_table_id": "sample_repos",
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
        logging.info("table sample_repos created")

    blobs = dump_bigquery_table(PROJECT_ID, DATASET_ID, "sample_repos", GCP_BUCKET)

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.sample_repos.drop()
        client.fake_stars.sample_repos.create_index("repo_name")
    for blob in blobs:
        load_gzipped_json_blob_to_mongodb(blob, MONGO_URL, "fake_stars", "sample_repos")
    return


def sample_users():
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, "sample_users"):
        logging.info("sample_users already exists, skipping table creation")
    else:
        bigquery_task = {
            "interactive": True,
            "query_file": "scripts/analysis/queries/sample_users.sql",
            "output_table_id": "sample_users",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", START_DATE),
                bigquery.ScalarQueryParameter("end_date", "STRING", END_DATE),
                bigquery.ScalarQueryParameter("sample_size", "INT64", SAMPLE_SIZE),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
        logging.info("table sample_users created")

    blobs = dump_bigquery_table(PROJECT_ID, DATASET_ID, "sample_users", GCP_BUCKET)

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.sample_actors.drop()
        client.fake_stars.sample_actors.create_index("actor")
    for blob in blobs:
        load_gzipped_json_blob_to_mongodb(
            blob, MONGO_URL, "fake_stars", "sample_actors"
        )
    return


def stg_all_events_from_fake_star_repos():
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, "all_events_repos"):
        logging.info("all_events_repos already exists, skipping table creation")
    else:
        fake_star_repos = list(get_fake_star_repos_all().repo_name)
        logging.info("Number of fake star repos: %d", len(fake_star_repos))
        bigquery_task = {
            "interactive": True,
            "query_file": "scripts/analysis/queries/stg_all_events_repos.sql",
            "output_table_id": "all_events_repos",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", START_DATE),
                bigquery.ScalarQueryParameter("end_date", "STRING", END_DATE),
                bigquery.ArrayQueryParameter("repos", "STRING", fake_star_repos),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
        logging.info("table all_events_repos created")

    blobs = dump_bigquery_table(PROJECT_ID, DATASET_ID, "all_events_repos", GCP_BUCKET)

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.all_events_repos.drop()
        client.fake_stars.all_events_repos.create_index("repo_name")
    for blob in blobs:
        load_gzipped_json_blob_to_mongodb(
            blob, MONGO_URL, "fake_stars", "all_events_repos"
        )
    return


def stg_all_events_from_fake_star_actors():
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, "all_events_actors"):
        logging.info("all_events_actors already exists, skipping table creation")
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
            "interactive": True,
            "query_file": "scripts/analysis/queries/stg_all_events_actors.sql",
            "output_table_id": "all_events_actors",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", START_DATE),
                bigquery.ScalarQueryParameter("end_date", "STRING", END_DATE),
                bigquery.ArrayQueryParameter("actors", "STRING", fake_star_actors),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
        logging.info("table all_events_actors created")

    blobs = dump_bigquery_table(PROJECT_ID, DATASET_ID, "all_events_actors", GCP_BUCKET)

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.all_events_actors.drop()
        client.fake_stars.all_events_actors.create_index("actor")
    for blob in blobs:
        load_gzipped_json_blob_to_mongodb(
            blob, MONGO_URL, "fake_stars", "all_events_actors"
        )
    return


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    sample_repos()
    sample_users()
    stg_all_events_from_fake_star_repos()
    stg_all_events_from_fake_star_actors()

    logging.info("Finish!")


if __name__ == "__main__":
    main()
