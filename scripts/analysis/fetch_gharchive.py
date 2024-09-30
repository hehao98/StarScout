import sys
import logging
import pandas as pd

from google.cloud import bigquery

from scripts import (
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
    START_DATE,
    END_DATE,
    MIN_STARS_COPYCATCH_SEED,
)
from scripts.gcp import process_bigquery, check_bigquery_table_exists


SAMPLE_SIZE = 10000


def sample_repos():
    if check_bigquery_table_exists(PROJECT_ID, DATASET_ID, "sample_repos"):
        logging.info("sample_repos already exists, skipping")
        return
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
    logging.info("sample_repos created")


def sample_users():
    pass


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    sample_repos()

    logging.info("Finish!")


if __name__ == "__main__":
    main()
