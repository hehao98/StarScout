import sys
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
    load_gzipped_json_blob_to_mongodb
)


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

    files = dump_bigquery_table(PROJECT_ID, DATASET_ID, "sample_repos", GCP_BUCKET)

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.sample_repos.drop()
        client.fake_stars.sample_repos.create_index("repo_name")
    load_gzipped_json_blob_to_mongodb(files, MONGO_URL, "fake_stars", "sample_repos")
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
    load_gzipped_json_blob_to_mongodb(blobs, MONGO_URL, "fake_stars", "sample_actors")
    return


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    sample_repos()
    sample_users()

    logging.info("Finish!")


if __name__ == "__main__":
    main()
