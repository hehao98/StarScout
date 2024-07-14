import io
import sys
import json
import logging
import pandas as pd

from pprint import pformat
from google.cloud import bigquery
from google.cloud.bigquery import ExtractJobConfig

from scripts import (
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
    GOOGLE_CLOUD_BUCKET as GCP_BUCKET,
)
from scripts.gcp import process_bigquery, download_gcp_blob_to_stream


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    start_date, end_date = "190701", "240701"
    min_stars_low_activity = 50

    client = bigquery.Client()
    dataset = bigquery.Dataset(PROJECT_ID + "." + DATASET_ID)
    dataset = client.create_dataset(dataset, exists_ok=True, timeout=30)
    logging.info("Created dataset %s.%s", client.project, dataset.dataset_id)

    # This task can be very expensive, require user confirmation
    bigquery_task = {
        "interactive": True,
        "query_file": "scripts/dagster/queries/stg_all_repos_with_low_activity_stars.sql",
        "output_table_id": "repos_with_low_activity_stars",
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
            bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
            bigquery.ScalarQueryParameter(
                "min_stars_low_activity", "INT64", min_stars_low_activity
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

    repos = []
    stream = download_gcp_blob_to_stream(
        GCP_BUCKET, "repos_with_low_activity_stars.json", io.BytesIO()
    )
    for line in stream.readlines():
        repos.append(json.loads(line))
    repos = pd.DataFrame(repos)
    repos.n_stars_low_activity = repos.n_stars_low_activity.astype(int)
    repos.sort_values(by="n_stars_low_activity", ascending=False, inplace=True)

    all_actors = []
    for repo, actors in zip(repos.repo_name, repos.low_activity_actors):
        for actor in actors:
            all_actors.append({"repo": repo, "actors": actor})
    pd.DataFrame(all_actors).to_csv(f"data/low_activity_stars_actors.csv", index=False)

    repos.drop(columns=["low_activity_actors"], inplace=True)
    repos.rename(columns={"repo_name": "repo"}, inplace=True)
    repos.to_csv(f"data/low_activity_stars_repos.csv", index=False)
    client.close()
    logging.info("Done!")


if __name__ == "__main__":
    main()
