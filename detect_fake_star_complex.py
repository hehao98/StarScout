import sys
import yaml
import logging

from pprint import pformat
from google.cloud import storage
from google.cloud import bigquery
from google.cloud.bigquery.job import ExtractJobConfig


with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)
PROJECT_ID = SECRETS["bigquery_project"]
DATASET_ID = SECRETS["bigquery_dataset"]
GCP_BUCKET = SECRETS["google_cloud_bucket"]


def yes_or_no(question: str) -> bool:
    while True:
        reply = str(input(question + " (y/n): ")).lower().strip()
        if reply[0] == "y":
            return True
        if reply[0] == "n":
            return False


def check_gcp_blob_exists(bucket_name: str, path: str) -> bool:
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    return storage.Blob(bucket=bucket, name=path).exists()


def process_bigquery(
    project_id: str,
    dataset_id: str,
    interactive: bool,
    query_file: str,
    output_table_id: str,
    params: list = [],
):
    with open(query_file, "r") as f:
        query = f.read()
        # This is an unfortunate workaround because Google BigQuery does
        # not accept parameters in table names. Do not use in production
        query = query.replace("@project_id", project_id)
        query = query.replace("@dataset_id", dataset_id)

    client = bigquery.Client()
    job_config = bigquery.QueryJobConfig(dry_run=True, query_parameters=params)
    logging.info("Sending query:\n%s\nwith params:\n%s", query, pformat(params))

    dry_run_job = client.query(query, job_config=job_config)
    logging.info("Query cost: %f GB", dry_run_job.total_bytes_processed / 1024**3)

    if not interactive or yes_or_no("Proceed?"):
        job_config.dry_run = False
        job_config.write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE
        job_config.destination = ".".join([project_id, dataset_id, output_table_id])
        actual_job = client.query(query, job_config=job_config)
        actual_job.result()
        logging.info("Results written to destination %s", job_config.destination)
    else:
        logging.info("Aborting")


def main():
    global PROJECT_ID, DATASET_ID

    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    start_date, end_date = "220101", "231231"
    repos = [
        "serverless-stack/sst",
        "animate-css/animate.css",
        "facebook/docusaurus",
        "rails/rails",
    ]

    client = bigquery.Client()
    dataset = bigquery.Dataset(PROJECT_ID + "." + DATASET_ID)
    dataset = client.create_dataset(dataset, exists_ok=True, timeout=30)
    logging.info("Created BigQuery dataset %s.%s", client.project, dataset.dataset_id)

    # This task can be very expensive, require user confirmation
    bigquery_bulk_task = {
        "interactive": True,
        "query_file": "complex_detector/stg_all_actions_for_stargazers.sql",
        "output_table_id": "stg_all_actions",
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
            bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
            bigquery.ArrayQueryParameter("repositories", "STRING", repos),
        ],
    }
    logging.info("Current BigQuery task:\n%s", pformat(bigquery_bulk_task))
    process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_bulk_task)

    for repo in repos:
        gcp_dest_path = f"fake-stars/{repo.replace('/', '_')}"
        if check_gcp_blob_exists(GCP_BUCKET, gcp_dest_path + "/fake_star_stats.json"):
            logging.info("Repo %s results already exists, skipping", repo)
            continue

        logging.info("Processing repo: %s", repo)
        bigquery_per_repo_tasks = [
            "stg_stargazer_overlap",
            "stg_stargazer_repo_clusters",
            "stg_spammy_repos",
            "stargazer_summary",
            "stargazer_repo_summary",
            "fake_star_stats",
        ]
        for task in bigquery_per_repo_tasks:
            logging.info("Current BigQuery task: %s", task)
            process_bigquery(
                PROJECT_ID,
                DATASET_ID,
                interactive=False,
                query_file=f"complex_detector/{task}.sql",
                output_table_id=task,
                params=[bigquery.ScalarQueryParameter("repo", "STRING", repo)],
            )

        logging.info("Writing results to Google Cloud Storage")
        dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)

        for table in bigquery_per_repo_tasks:
            logging.info("Writing table %s", table)
            extract_job = client.extract_table(
                source=dataset_ref.table(table),
                destination_uris=f"gs://{GCP_BUCKET}/{gcp_dest_path}/{table}.json",
                job_config=ExtractJobConfig(
                    destination_format=(
                        bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON
                    )
                ),
            )
            extract_job.result()

    return


if __name__ == "__main__":
    main()
