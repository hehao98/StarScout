import io
import sys
import json
import logging
import argparse
import pandas as pd
import stscraper as scraper

from pprint import pformat
from typing import Optional
from google.cloud import bigquery
from google.cloud.bigquery import ExtractJobConfig

from scripts import (
    GITHUB_TOKENS,
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
    GOOGLE_CLOUD_BUCKET as GCP_BUCKET,
)
from scripts.gcp import (
    check_gcp_blob_exists,
    list_gcp_blobs,
    download_gcp_blob_to_stream,
    process_bigquery,
)


def read_gcp_stargazer_summary_blob(
    repo: str, bucket_name: str, stargazer_blob_path: str
) -> list[dict]:
    stargazer_stats = []
    stream = download_gcp_blob_to_stream(bucket_name, stargazer_blob_path, io.BytesIO())
    for line in stream.readlines():
        line = json.loads(line)
        stargazer_stats.append(
            {
                "repo_name": repo,
                "actor": line["actor"],
                "starred_at": line["star_time"],
                "fake_acct": line["fake_acct"],
            }
        )
    return stargazer_stats


def process_fake_star_detection(repo: str) -> list[dict]:
    client = bigquery.Client()
    gcp_dest_path = f"fake-stars/{repo.replace('/', '_')}"
    stargazer_blob_path = gcp_dest_path + "/stargazer_summary.json"

    if not check_gcp_blob_exists(GCP_BUCKET, stargazer_blob_path) and all(
        "stargazer_summary" not in b.name
        for b in list_gcp_blobs(GCP_BUCKET, gcp_dest_path)
    ):
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
                query_file=f"scripts/dagster/queries/{task}.sql",
                output_table_id=task,
                params=[bigquery.ScalarQueryParameter("repo", "STRING", repo)],
            )

        logging.info("Writing results to Google Cloud Storage")
        dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)

        for table in bigquery_per_repo_tasks:
            try:
                logging.info("Writing table %s", table)
                extract_job = client.extract_table(
                    source=dataset_ref.table(table),
                    destination_uris=f"gs://{GCP_BUCKET}/{gcp_dest_path}/{table}*.json",
                    job_config=ExtractJobConfig(
                        destination_format=(
                            bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON
                        )
                    ),
                )
                extract_job.result()
            except Exception as ex:
                logging.error("Error writing table %s: %s", table, ex)
    else:
        logging.info("Repo %s results already exists, skipping BigQuery tasks", repo)
    client.close()

    stargazer_stats = []

    if check_gcp_blob_exists(GCP_BUCKET, stargazer_blob_path):
        chunk = read_gcp_stargazer_summary_blob(repo, GCP_BUCKET, stargazer_blob_path)
        stargazer_stats.extend(chunk)
    else:
        for blob in list_gcp_blobs(GCP_BUCKET, gcp_dest_path):
            if "stargazer_summary" not in blob.name:
                continue
            chunk = read_gcp_stargazer_summary_blob(repo, GCP_BUCKET, blob.name)
            stargazer_stats.extend(chunk)

    return stargazer_stats


def get_repo_id(repo: str) -> Optional[str]:
    owner, name = repo.split("/")
    strudel = scraper.GitHubAPIv4(",".join(GITHUB_TOKENS))

    try:
        result = strudel(
            """
            query ($owner: String!, $name: String!) {
                repository(owner: $owner, name: $name) {
                    id
                }
            }
            """,
            owner=owner,
            name=name,
        )
        return result
    except Exception as ex:
        logging.error(f"Error fetching repo {repo}: {ex}")
        return None


def dump_fake_star_data(fake_star_users: list[dict]):
    fake_star_users = pd.DataFrame(fake_star_users)
    repo_to_id = {r: get_repo_id(r) for r in set(fake_star_users.repo_name)}
    repo_id_series = fake_star_users.repo_name.map(lambda n: repo_to_id[n])
    fake_star_users.insert(0, column="repo_id", value=repo_id_series)
    fake_star_users.sort_values(by=["repo_id", "starred_at"], inplace=True)

    fake_star_repos = []
    for repo_id, df in fake_star_users.groupby(by="repo_id"):
        if len(df) == 0:
            continue
        fake_star_repos.append(
            {
                "repo_id": repo_id,
                "repo_names": ",".join(sorted(set(df.repo_name))),
                "total_stars": len(df),
                "p_fake_stars": len(df[df.fake_acct != "unknown"]) / len(df),
                "n_fake_stars": len(df[df.fake_acct != "unknown"]),
                "n_low_activity": len(df[df.fake_acct == "suspected-low_activity"]),
                "n_activity_cluster": len(
                    df[df.fake_acct == "suspected-activity_cluster"]
                ),
            }
        )
    fake_star_repos = pd.DataFrame(fake_star_repos)

    fake_star_repos.sort_values(by="repo_id", inplace=True)

    fake_star_users.drop("repo_id", axis=1, inplace=True)
    fake_star_users.to_csv("data/fake_stars_complex_users.csv", index=False)
    fake_star_repos.to_csv("data/fake_stars_complex_repos.csv", index=False)
    return


def main():
    global PROJECT_ID, DATASET_ID

    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("--init", action="store_true", default=False)
    args = parser.parse_args()

    start_date, end_date = "190701", "240701"
    df = pd.read_csv("data/fake_stars_obvious_repos.csv")
    df_filtered = df[(df["fake_percentage"] >= 2) | (df["fake_stars"] >= 100)]
    repos = list(set(df_filtered.github))
    logging.info("%d repos to scan", len(repos))

    if args.init:
        with bigquery.Client() as cli:
            dataset = bigquery.Dataset(PROJECT_ID + "." + DATASET_ID)
            dataset = cli.create_dataset(dataset, exists_ok=True, timeout=30)
            logging.info("Created dataset %s.%s", cli.project, dataset.dataset_id)

            # This task can be very expensive, require user confirmation
            bigquery_bulk_task = {
                "interactive": True,
                "query_file": "scripts/dagster/queries/stg_all_actions_for_stargazers.sql",
                "output_table_id": "stg_all_actions",
                "params": [
                    bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
                    bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
                    bigquery.ArrayQueryParameter("repositories", "STRING", repos),
                ],
            }
            logging.info("Current BigQuery task:\n%s", pformat(bigquery_bulk_task))
            process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_bulk_task)

    fake_star_users = []
    for repo in repos:
        try:
            fake_star_users.extend(process_fake_star_detection(repo))
        except Exception as ex:
            logging.error("Error while detecting fake stars for %s: %s", repo, ex)

    dump_fake_star_data(fake_star_users)

    logging.info("Done!")
    return


if __name__ == "__main__":
    main()
