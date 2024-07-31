import io
import sys
import json
import logging
import argparse
import multiprocessing as mp
import pandas as pd

from datetime import datetime
from collections import defaultdict
from pymongo import MongoClient, UpdateOne
from google.cloud import bigquery
from google.cloud.bigquery.job import ExtractJobConfig

from scripts import (
    MONGO_URL,
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
    download_gcp_blob_to_stream,
    check_bigquery_table_exists,
    get_bigquery_table_nrows,
    process_bigquery,
)
from scripts.github import get_repo_id, get_repo_n_stars_latest


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
    logging.info("Created centers %s", bigquery_task["output_table_id"])

    return get_bigquery_table_nrows(
        PROJECT_ID, DATASET_ID, bigquery_task["output_table_id"]
    )


def run_chunk(start_date: str, end_date: str):
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

    logging.info("Finished chunk %s_%s", start_date, end_date)


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
    logging.info("Created clusters %s", bigquery_task["output_table_id"])

    return get_bigquery_table_nrows(
        PROJECT_ID, DATASET_ID, bigquery_task["output_table_id"]
    )


def export_stargazer_graphs(start_date: str, end_date: str):
    client = bigquery.Client()
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    destination = f"gs://{GCP_BUCKET}/stargazers/{start_date}_{end_date}/*.json"
    extract_job = client.extract_table(
        source=dataset_ref.table(f"stargazers_{start_date}_{end_date}"),
        destination_uris=destination,
        job_config=ExtractJobConfig(
            destination_format=bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON,
        ),
    )
    extract_job.result()
    logging.info("Exported stargazers to %s", destination)


def export_copycatch_results(start_date: str, end_date: str):
    client = bigquery.Client()
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    destination = f"gs://{GCP_BUCKET}/clusters/{start_date}_{end_date}/*.json"
    extract_job = client.extract_table(
        source=dataset_ref.table(f"clusters_{start_date}_{end_date}"),
        destination_uris=destination,
        job_config=ExtractJobConfig(
            destination_format=bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON,
        ),
    )
    extract_job.result()
    logging.info("Exported clusters to %s", destination)


def extract_stargazer_mapping(blob_name: str) -> dict[tuple[str, str], str]:
    repo_user_to_time = defaultdict(datetime)
    with download_gcp_blob_to_stream(GCP_BUCKET, blob_name, io.BytesIO()) as f:
        for line in f:
            obj = json.loads(line)
            repo_user_to_time[(obj["repo_name"], obj["actor"])] = obj["starred_at"]
    return repo_user_to_time


def summarize_results(start_date: str, end_date: str) -> dict[str, set[str]]:
    logging.info("Summarizing results from %s to %s", start_date, end_date)

    repo_user_to_time = {}
    stargazer_blobs = []
    for b in list_gcp_blobs(GCP_BUCKET, f"stargazers/{start_date}_{end_date}"):
        stargazer_blobs.append(b.name)
    with mp.Pool(min(mp.cpu_count(), len(stargazer_blobs))) as pool:
        for chunk in pool.imap_unordered(extract_stargazer_mapping, stargazer_blobs):
            for k, v in chunk.items():
                repo_user_to_time[k] = v
    logging.info("Loaded %d stargazers", len(repo_user_to_time))

    repo_to_users = defaultdict(set)
    for blob in list_gcp_blobs(GCP_BUCKET, f"clusters/{start_date}_{end_date}"):
        logging.info("Blob: %s", blob.name)
        with download_gcp_blob_to_stream(GCP_BUCKET, blob.name, io.BytesIO()) as f:
            for line in f:
                obj = json.loads(line)
                logging.info("Cluster ID: %s", obj["repo_name"])

                for repo in obj["cluster"]:
                    star_times = []
                    for user in obj["actors"]:
                        if (repo, user) in repo_user_to_time:
                            star_times.append(repo_user_to_time[(repo, user)])
                    star_times = sorted(star_times)
                    if len(star_times) >= COPYCATCH_PARAMS.n * COPYCATCH_PARAMS.rho:
                        logging.info(
                            "Repo %s: %d stars out of %d users, star time %s - %s",
                            repo,
                            len(star_times),
                            len(obj["actors"]),
                            star_times[0],
                            star_times[-1],
                        )
                        repo_to_users[repo].update(obj["actors"])

    logging.info(
        "%d repos, top 10 repos: %s",
        len(repo_to_users),
        sorted([(k, len(v)) for k, v in repo_to_users.items()], key=lambda x: -x[1])[
            :10
        ],
    )

    return repo_to_users


def export_mongodb(repo_to_fakes: dict[str, set[str]]):
    client = MongoClient(MONGO_URL)
    collection = client.fake_stars.clustered_stars
    collection.drop()
    collection.create_index(["repo", "actor", "starred_at"], unique=True)

    # Export all real stars first
    chunk = []
    for start_date, end_date in COPYCATCH_DATE_CHUNKS:
        for b in list_gcp_blobs(GCP_BUCKET, f"stargazers/{start_date}_{end_date}"):
            for (repo, actor), time in extract_stargazer_mapping(b.name).items():
                if repo in repo_to_fakes:
                    key = {"repo": repo, "actor": actor, "starred_at": time}
                    chunk.append(
                        UpdateOne(
                            filter={**key},
                            update={
                                "$set": {
                                    **key,
                                    "clustered": False,
                                }
                            },
                            upsert=True,
                        )
                    )
                if len(chunk) >= 100000:
                    logging.info("Inserting %d records", len(chunk))
                    collection.bulk_write(chunk)
                    chunk.clear()
    if len(chunk) >= 0:
        logging.info("Inserting %d records", len(chunk))
        collection.bulk_write(chunk)
        chunk.clear()

    # And then export all fake stars to overwrite older ones
    chunk = []
    for start_date, end_date in COPYCATCH_DATE_CHUNKS:
        for b in list_gcp_blobs(GCP_BUCKET, f"stargazers/{start_date}_{end_date}"):
            for (repo, actor), time in extract_stargazer_mapping(b.name).items():
                if repo in repo_to_fakes and actor in repo_to_fakes[repo]:
                    key = {"repo": repo, "actor": actor, "starred_at": time}
                    chunk.append(
                        UpdateOne(
                            filter={**key},
                            update={
                                "$set": {
                                    **key,
                                    "clustered": True,
                                }
                            },
                            upsert=True,
                        )
                    )
                if len(chunk) >= 100000:
                    logging.info("Inserting %d records", len(chunk))
                    collection.bulk_write(chunk)
                    chunk.clear()
    if len(chunk) >= 0:
        logging.info("Inserting %d records", len(chunk))
        collection.bulk_write(chunk)
        chunk.clear()

    logging.info("Finish exporting to MongoDB")
    client.close()


def summarize_mongodb():
    client = MongoClient(MONGO_URL)
    collection = client.fake_stars.clustered_stars

    results = []
    for repo in collection.distinct("repo"):
        n_stars = collection.count_documents({"repo": repo})
        n_fakes = collection.count_documents({"repo": repo, "clustered": True})
        logging.info("Repo %s: %d stars, %d fakes", repo, n_stars, n_fakes)
        results.append(
            {
                "repo_name": repo,
                "n_stars": n_stars,
                "n_stars_clustered": n_fakes,
            }
        )
    results = pd.DataFrame(results)

    results.insert(0, "repo_id", results["repo_name"].apply(get_repo_id))
    results["n_stars_latest"] = results["repo_id"].apply(get_repo_n_stars_latest)

    results = (
        results.groupby("repo_id")
        .agg(
            repo_id="first",
            repo_names=("repo_name", "unique"),
            n_stars="sum",
            n_stars_clustered="sum",
        )
        .reset_index()
    )

    results["p_stars_clustered"] = results["n_stars_clustered"] / results["n_stars"]

    results.sort_values(by="p_stars_clustered", ascending=False, inplace=True)
    results.to_csv("data/fake_stars_clustered_repos.csv", index=False)


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    parser = argparse.ArgumentParser(description="Run CopyCatch on BigQuery")
    parser.add_argument("--run", action="store_true", help="Run CopyCatch on BigQuery")
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export CopyCatch clusters and stargazer results to Google Cloud Storage",
    )
    parser.add_argument(
        "--summarize",
        action="store_true",
        help="Summarize results from Google Cloud Storage",
    )
    parser.add_argument(
        "--summarize-mongodb",
        action="store_true",
        help="Summarize results from MongoDB",
    )
    args = parser.parse_args()

    if args.run:
        with mp.Pool(len(COPYCATCH_DATE_CHUNKS)) as pool:
            pool.starmap(run_chunk, COPYCATCH_DATE_CHUNKS)
    if args.export:
        with mp.Pool(len(COPYCATCH_DATE_CHUNKS)) as pool:
            pool.starmap(export_stargazer_graphs, COPYCATCH_DATE_CHUNKS)
            pool.starmap(agg_results, COPYCATCH_DATE_CHUNKS)
            pool.starmap(export_copycatch_results, COPYCATCH_DATE_CHUNKS)
    if args.summarize:
        repo_to_fakes = defaultdict(set)
        for start_date, end_date in COPYCATCH_DATE_CHUNKS:
            repo_to_fakes = summarize_results(start_date, end_date)
            for k, v in repo_to_fakes.items():
                repo_to_fakes[k].update(v)
        logging.info(
            "%d repos, %d fakes",
            len(repo_to_fakes),
            sum(map(len, repo_to_fakes.values())),
        )
        export_mongodb(repo_to_fakes)
    if args.summarize_mongodb:
        summarize_mongodb()

    logging.info("All done!")


if __name__ == "__main__":
    main()
