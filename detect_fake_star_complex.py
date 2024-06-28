import sys
import yaml
import logging

from pprint import pformat
from google.cloud import bigquery


with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)

PROJECT_ID = SECRETS["bigquery_project"]
DATASET_ID = SECRETS["bigquery_dataset"]
BIGQUERY_TASKS = [
    {
        "query_file": "complex_detector/stg_all_actions_for_stargazers.sql",
        "output_table_id": "stg_all_actions",
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", "220101"),
            bigquery.ScalarQueryParameter("end_date", "STRING", "231231"),
            bigquery.ArrayQueryParameter(
                "repositories", "STRING", ["serverless-stack/sst"]
            ),
        ],
    },
    {
        "query_file": "complex_detector/stg_stargazer_overlap.sql",
        "output_table_id": "stg_stargazer_overlap",
    },
    {
        "query_file": "complex_detector/stg_stargazer_repo_clusters.sql",
        "output_table_id": "stg_stargazer_repo_clusters",
    },
    {
        "query_file": "complex_detector/stg_spammy_repos.sql",
        "output_table_id": "stg_spammy_repos",
    },
    {
        "query_file": "complex_detector/stargazer_summary.sql",
        "output_table_id": "stargazer_summary",
    },
    {
        "query_file": "complex_detector/stargazer_repo_summary.sql",
        "output_table_id": "stargazer_repo_summary",
    },
    {
        "query_file": "complex_detector/fake_star_stats.sql",
        "output_table_id": "fake_star_stats",
    },
]


def yes_or_no(question: str) -> bool:
    while True:
        reply = str(input(question + " (y/n): ")).lower().strip()
        if reply[0] == "y":
            return True
        if reply[0] == "n":
            return False


def process_bigquery(
    project_id: str,
    dataset_id: str,
    query_file: str,
    output_table_id: str,
    params: list[bigquery.ScalarQueryParameter] = [],
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

    if yes_or_no("Proceed?"):
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
    global BIGQUERY_TASKS

    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    client = bigquery.Client()
    dataset = bigquery.Dataset(PROJECT_ID + "." + DATASET_ID)
    dataset = client.create_dataset(dataset, exists_ok=True, timeout=30)
    logging.info("Created BigQuery dataset %s.%s", client.project, dataset.dataset_id)

    for bigquery_task in BIGQUERY_TASKS:
        logging.info("Current BigQuery task:\n%s", pformat(bigquery_task))
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)

    return


if __name__ == "__main__":
    main()
