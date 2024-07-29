import sys
import logging
import multiprocessing as mp

from google.cloud import bigquery
from google.cloud.bigquery.job import ExtractJobConfig

from scripts import (
    MIN_STARS_COPYCATCH_SEED,
    COPYCATCH_NUM_ITERATIONS,
    COPYCATCH_PARAMS,
    COPYCATCH_DATE_CHUNKS,
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
    GOOGLE_CLOUD_BUCKET as GCP_BUCKET,
)
from scripts.gcp import (
    list_gcp_blobs,
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


def agg_results(start_date: str, end_date: str) -> int:
    bigquery_task = {
        "interactive": False,
        "query_file": "scripts/copycatch/queries/agg_results.sql",
        "output_table_id": f"clusters_{start_date}_{end_date}",
        "params": [
            bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
            bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
            bigquery.ScalarQueryParameter("m", "INT64", COPYCATCH_PARAMS.m),
            bigquery.ScalarQueryParameter("n", "INT64", COPYCATCH_PARAMS.n),
        ],
    }

    process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)
    logging.info("Created center mapping %s", bigquery_task["output_table_id"])

    return get_bigquery_table_nrows(
        PROJECT_ID, DATASET_ID, bigquery_task["output_table_id"]
    )


def dump_results(start_date: str, end_date: str):
    client = bigquery.Client()
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    destination = f"gs://{GCP_BUCKET}/clusters/{start_date}_{end_date}/*.json"
    extract_job = client.extract_table(
        source=dataset_ref.table(f"clusters_{start_date}_{end_date}"),
        destination_uris=destination,
        job_config=ExtractJobConfig(
            compression=bigquery.Compression.GZIP,
            destination_format=bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON,
        ),
    )
    extract_job.result()
    logging.info("Exported clusters to %s", destination)


def run_chunk(start_date: str, end_date: str):
    gcp_path = f"clusters/{start_date}_{end_date}"
    if len(list_gcp_blobs(GCP_BUCKET, gcp_path)) > 0:
        logging.info("Clusters %s_%s already exist, skipping", start_date, end_date)
        return

    logging.info("Processing dates %s to %s", start_date, end_date)

    get_stargazer_data(start_date, end_date)

    get_initial_centers(start_date, end_date)

    n_prev_users = -1
    for i in range(COPYCATCH_NUM_ITERATIONS):
        n_users = map_users(start_date, end_date)
        if n_users == n_prev_users:
            logging.info("No new users, stopping")
            break
        n_prev_users = n_users

        n_centers = reduce_centers(start_date, end_date)
        logging.info("Iteration %d (%d users, %d clusters)", i, n_users, n_centers)

    agg_results(start_date, end_date)

    dump_results(start_date, end_date)

    logging.info("Finished chunk %s_%s", start_date, end_date)


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    with mp.Pool(len(COPYCATCH_DATE_CHUNKS)) as pool:
        pool.starmap(run_chunk, COPYCATCH_DATE_CHUNKS)

    logging.info("All done!")


if __name__ == "__main__":
    main()
