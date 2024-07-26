import sys
import logging

from google.cloud import bigquery

from scripts import (
    MIN_STARS_COPYCATCH_SEED,
    COPYCATCH_NUM_ITERATIONS,
    COPYCATCH_PARAMS,
    COPYCATCH_DATE_CHUNKS,
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
)
from scripts.gcp import (
    check_bigquery_table_exists,
    get_bigquery_table_nrows,
    process_bigquery,
)


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
        "output_table_id": f"centers_{start_date}_{end_date}",
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


def map_users(start_date: str, end_date: str) -> int:
    bigquery_task = {
        "interactive": False,
        "query_file": "scripts/copycatch/queries/map_users.sql",
        "output_table_id": f"users_{start_date}_{end_date}",
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
            bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
            bigquery.ScalarQueryParameter("delta_t", "INT64", COPYCATCH_PARAMS.delta_t),
            bigquery.ScalarQueryParameter("rho", "FLOAT64", COPYCATCH_PARAMS.rho),
        ],
    }

    process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
    logging.info("Created user mapping %s", bigquery_task["output_table_id"])

    return get_bigquery_table_nrows(
        PROJECT_ID, DATASET_ID, bigquery_task["output_table_id"]
    )


def reduce_centers(start_date: str, end_date: str) -> int:
    bigquery_task = {
        "interactive": False,
        "query_file": "scripts/copycatch/queries/reduce_centers.sql",
        "output_table_id": f"centers_{start_date}_{end_date}",
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
            bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
            bigquery.ScalarQueryParameter("delta_t", "INT64", COPYCATCH_PARAMS.delta_t),
            bigquery.ScalarQueryParameter("m", "INT64", COPYCATCH_PARAMS.m),
            bigquery.ScalarQueryParameter(
                "relaxed_m", "INT64", 20 * COPYCATCH_PARAMS.m
            ),
        ],
    }

    process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
    logging.info("Created center mapping %s", bigquery_task["output_table_id"])

    return get_bigquery_table_nrows(
        PROJECT_ID, DATASET_ID, bigquery_task["output_table_id"]
    )


def cleanup_results():
    pass


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    for start_date, end_date in COPYCATCH_DATE_CHUNKS[:1]:
        logging.info("Processing dates %s to %s", start_date, end_date)

        get_stargazer_data(start_date, end_date)

        get_initial_centers(start_date, end_date)

        n_prev_users = -1
        for i in range(COPYCATCH_NUM_ITERATIONS):
            n_users = map_users(start_date, end_date)
            n_centers = reduce_centers(start_date, end_date)

            logging.info("Iteration %d (%d users, %d clusters)", i, n_users, n_centers)
            if n_users == n_prev_users:
                break
            n_prev_users = n_users

    cleanup_results()

    logging.info("All done!")


if __name__ == "__main__":
    main()
