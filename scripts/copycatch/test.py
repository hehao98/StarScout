import io
import os
import sys
import json
import random
import logging
import pandas as pd

from google.cloud import bigquery
from google.cloud.bigquery import ExtractJobConfig

from scripts import (
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
    GOOGLE_CLOUD_BUCKET as GCP_BUCKET,
    START_DATE,
    END_DATE,
)
from scripts.gcp import (
    check_gcp_blob_exists,
    download_gcp_blob_to_stream,
    process_bigquery,
)


def get_stargazer_data_dagster(start_date: str, end_date: str):
    stars = pd.read_csv("data/fake_stars_complex_users.csv")
    fake_stars = stars[stars.fake_acct != "unknown"]
    actors, fake_actors = set(stars.actor), set(fake_stars.actor)
    real_actors = random.sample(list(actors - fake_actors), len(fake_actors))
    logging.info(
        "%d stars (%d fake) from %d actors (%d fake)",
        len(stars),
        len(fake_stars),
        len(actors),
        len(fake_actors),
    )

    client = bigquery.Client()
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    for actors, actor_type in zip([fake_actors, real_actors], ["fake", "real"]):
        output_file = f"test_dagster_stargazers_{actor_type}.json"
        if check_gcp_blob_exists(GCP_BUCKET, output_file):
            logging.info("Test data for %s actors already exists", actor_type)
            continue

        bigquery_task = {
            "interactive": True,
            "query_file": "scripts/copycatch/queries/stg_stargazers_by_names.sql",
            "output_table_id": f"test_dagster_stargazers_{actor_type}",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
                bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
                bigquery.ArrayQueryParameter("actors", "STRING", actors),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)

        # Safe to export as a single file as the table is less than 1GB each
        extract_job = client.extract_table(
            source=dataset_ref.table(f"test_dagster_stargazers_{actor_type}"),
            destination_uris=f"gs://{GCP_BUCKET}/{output_file}",
            job_config=ExtractJobConfig(
                destination_format=(bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON)
            ),
        )
        extract_job.result()

        events = []
        stream = download_gcp_blob_to_stream(GCP_BUCKET, output_file, io.BytesIO())
        for line in stream.readlines():
            events.append(json.loads(line))
        events = pd.DataFrame(events)
        events.to_csv(f"data/copycatch_test_stargazers_{actor_type}.csv", index=False)
        logging.info("Generated test data for %s actors", actor_type)


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logging.info("Generating test data...")
    if not os.path.exists("data/copycatch_test_stargazers_fake.csv"):
        get_stargazer_data_dagster(start_date=START_DATE, end_date=END_DATE)

    # TODO: Run and compare the two CopyCatch implementations

    logging.info("Done!")


if __name__ == "__main__":
    main()
