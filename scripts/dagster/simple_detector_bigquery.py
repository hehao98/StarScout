import io
import os
import sys
import json
import logging
import pymongo
import pandas as pd

from pprint import pformat
from google.cloud import bigquery
from google.cloud.bigquery import ExtractJobConfig

from scripts import (
    MONGO_URL,
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
    GOOGLE_CLOUD_BUCKET as GCP_BUCKET,
    START_DATE,
    END_DATE,
    MIN_STARS_LOW_ACTIVITY,
)
from scripts.gcp import process_bigquery, download_gcp_blob_to_stream, list_gcp_blobs
from scripts.github import get_repo_id, get_repo_n_stars_latest


def get_repos_with_low_activity_stars():
    client = bigquery.Client()
    dataset = bigquery.Dataset(PROJECT_ID + "." + DATASET_ID)
    dataset = client.create_dataset(dataset, exists_ok=True, timeout=30)
    logging.info("Created dataset %s.%s", client.project, dataset.dataset_id)

    # This task can be very expensive, require user confirmation
    bigquery_task = {
        "interactive": False,
        "query_file": "scripts/dagster/queries/stg_all_repos_with_low_activity_stars.sql",
        "output_table_id": "repos_with_low_activity_stars",
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", START_DATE),
            bigquery.ScalarQueryParameter("end_date", "STRING", END_DATE),
            bigquery.ScalarQueryParameter(
                "min_stars_low_activity", "INT64", MIN_STARS_LOW_ACTIVITY
            ),
        ],
    }
    logging.info("Current BigQuery task:\n%s", pformat(bigquery_task))
    process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)

    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    extract_job = client.extract_table(
        source=dataset_ref.table(f"repos_with_low_activity_stars"),
        destination_uris=f"gs://{GCP_BUCKET}/repos_with_low_activity_stars.json",
        job_config=ExtractJobConfig(
            destination_format=(bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON)
        ),
    )
    extract_job.result()

    client.close()


def get_low_activity_stars_users():
    client = bigquery.Client()

    # This task can be very expensive, require user confirmation
    bigquery_task = {
        "interactive": False,
        "query_file": "scripts/dagster/queries/stg_low_activity_stargazers.sql",
        "output_table_id": "low_activity_stars",
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", START_DATE),
            bigquery.ScalarQueryParameter("end_date", "STRING", END_DATE),
        ],
    }
    logging.info("Current BigQuery task:\n%s", pformat(bigquery_task))
    process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)

    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    extract_job = client.extract_table(
        source=dataset_ref.table(f"low_activity_stars"),
        destination_uris=f"gs://{GCP_BUCKET}/low_activity_stars/*.json",
        job_config=ExtractJobConfig(
            destination_format=(bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON)
        ),
    )
    extract_job.result()

    client.close()


def dump_repos_with_low_activity_stars():
    stream = download_gcp_blob_to_stream(
        GCP_BUCKET, "repos_with_low_activity_stars.json", io.BytesIO()
    )

    repos = pd.DataFrame([json.loads(line) for line in stream.readlines()])
    repos.n_stars = repos.n_stars.astype(int)
    repos["n_stars_low_activity"] = repos.low_activity_actors.apply(
        lambda x: len(set(x))
    )

    # sum stars for duplicate repo ids, keeping those without repo id
    repos.insert(0, "repo_id", repos.repo_name.apply(get_repo_id))
    repos["n_stars_latest"] = repos.repo_name.apply(get_repo_n_stars_latest)
    repos["p_stars_low_activity"] = repos.n_stars_low_activity / repos.n_stars

    repos.sort_values(by="p_stars_low_activity", ascending=False, inplace=True)
    repos.drop(columns=["low_activity_actors"], inplace=True)

    repos.to_csv(f"data/{END_DATE}/fake_stars_low_activity_repos.csv", index=False)


def dump_low_activity_stars_users():
    client = pymongo.MongoClient(MONGO_URL)
    db = client.get_database("fake_stars")
    db.low_activity_stars.drop()
    db.low_activity_stars.create_index(["repo", "actor", "starred_at"], unique=True)

    existing = set()
    for blob in list_gcp_blobs(GCP_BUCKET, "low_activity_stars"):
        stars = []
        stream = download_gcp_blob_to_stream(GCP_BUCKET, blob.name, io.BytesIO())
        for line in stream.readlines():
            star = json.loads(line)
            if "repo" not in star or "actor" not in star or "starred_at" not in star:
                logging.error("Invalid star: %s", star)
                continue
            if star["repo"] + star["actor"] + star["starred_at"] in existing:
                logging.error("Duplicated star: %s", star)
                continue
            stars.append(star)
            existing.add(star["repo"] + star["actor"] + star["starred_at"])
        db.low_activity_stars.insert_many(stars)

    client.close()


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    os.makedirs(f"data/{END_DATE}", exist_ok=True)

    get_repos_with_low_activity_stars()

    get_low_activity_stars_users()

    dump_repos_with_low_activity_stars()

    dump_low_activity_stars_users()

    logging.info("Done!")


if __name__ == "__main__":
    main()
