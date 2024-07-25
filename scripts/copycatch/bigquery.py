import sys
import logging

from google.cloud import bigquery

from scripts import (
    MIN_STARS_COPYCATCH_SEED,
    COPYCATCH_PARAMS,
    COPYCATCH_DATE_CHUNKS,
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
)
from scripts.gcp import check_bigquery_table_exists, process_bigquery


def get_stargazer_data(start_date: str, end_date: str):
    table_id = f"stargazers_{start_date}_{end_date}"
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, table_id):
        logging.info("Table %s already exists, skipping", table_id)
        return

    bigquery_task = {
        "interactive": False,
        "query_file": "scripts/copycatch/queries/stg_stargazers_all.sql",
        "output_table_id": table_id,
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
            bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
        ],
    }
    process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
    logging.info("Created table %s", table_id)


def get_initial_centers(start_date: str, end_date: str):

    table_id = f"stargazers_{start_date}_{end_date}"
    if not check_bigquery_table_exists(PROJECT_ID, DATASET_ID, table_id):
        logging.info("Table %s does not exist, skipping", table_id)
        return

    bigquery_task = {
        "interactive": False,
        "query_file": "scripts/copycatch/queries/stg_initial_centers.sql",
        "output_table_id": f"initial_centers_{start_date}_{end_date}",
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
            bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
            bigquery.ScalarQueryParameter(
                "min_stars_copycatch_seed", "INT64", MIN_STARS_COPYCATCH_SEED
            ),
        ],
    }
    process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
    logging.info("Created table %s", bigquery_task["output_table_id"])


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    for start_date, end_date in COPYCATCH_DATE_CHUNKS[:1]:
        get_stargazer_data(start_date, end_date)
        get_initial_centers(start_date, end_date)

    logging.info("All done!")


if __name__ == "__main__":
    main()
