import sys
import logging

from pprint import pformat
from google.cloud import bigquery


QUERY_STG_ALL_ACTIONS = (
    "complex_detector/stg_all_actions_for_actors_who_starred_repo.sql"
)


def yes_or_no(question: str) -> bool:
    while True:
        reply = str(input(question + " (y/n): ")).lower().strip()
        if reply[0] == "y":
            return True
        if reply[0] == "n":
            return False


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    client = bigquery.Client()

    with open(QUERY_STG_ALL_ACTIONS, "r") as f:
        query = f.read()

    params = [
        bigquery.ScalarQueryParameter("start_date", "STRING", "231225"),
        bigquery.ScalarQueryParameter("end_date", "STRING", "231231"),
        bigquery.ArrayQueryParameter(
            "repositories", "STRING", ["hydro-dev/Hydro", "discordjs/discord.js"]
        ),
    ]
    job_config = bigquery.QueryJobConfig(dry_run=True, query_parameters=params)

    logging.info("Sending query:\n%s\nwith params:\n%s", query, pformat(params))
    dry_run_job = client.query(query, job_config=job_config)
    logging.info("Query cost: %f GB", dry_run_job.total_bytes_processed / 1024**3)

    if yes_or_no("Proceed?"):
        job_config.dry_run = False
        actual_job = client.query(query, job_config=job_config)
        rows = actual_job.result()
        for row in rows:
            logging.info(row)

    return


if __name__ == "__main__":
    main()
