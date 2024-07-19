import io
import os
import sys
import json
import random
import logging
import argparse
import pandas as pd
import multiprocessing as mp

from pprint import pformat
from google.cloud import bigquery
from google.cloud.bigquery import ExtractJobConfig

from scripts import (
    BIGQUERY_PROJECT as PROJECT_ID,
    BIGQUERY_DATASET as DATASET_ID,
    GOOGLE_CLOUD_BUCKET as GCP_BUCKET,
    START_DATE,
    END_DATE,
)
from scripts.gcp import (
    check_gcp_blob_exists,
    download_gcp_blob_to_stream,
    process_bigquery,
)
from scripts.copycatch.iterative import (
    CopyCatch,
    CopyCatchParams,
)


def get_stargazer_data_dagster(start_date: str, end_date: str):
    stars = pd.read_csv("data/fake_stars_complex_users.csv")
    fake_stars = stars[stars.fake_acct != "unknown"]
    actors, fake_actors = set(stars.actor), set(fake_stars.actor)
    real_actors = random.sample(list(actors - fake_actors), len(fake_actors))
    logging.info(
        "%d stars (%d fake) from %d actors (%d fake)",
        len(stars),
        len(fake_stars),
        len(actors),
        len(fake_actors),
    )

    client = bigquery.Client()
    dataset_ref = bigquery.DatasetReference(PROJECT_ID, DATASET_ID)
    for actors, actor_type in zip([fake_actors, real_actors], ["fake", "real"]):
        output_file = f"test_dagster_stargazers_{actor_type}.json"
        if check_gcp_blob_exists(GCP_BUCKET, output_file):
            logging.info("Test data for %s actors already exists", actor_type)
            continue

        bigquery_task = {
            "interactive": True,
            "query_file": "scripts/copycatch/queries/stg_stargazers_by_names.sql",
            "output_table_id": f"test_dagster_stargazers_{actor_type}",
            "params": [
                bigquery.ScalarQueryParameter("start_date", "STRING", start_date),
                bigquery.ScalarQueryParameter("end_date", "STRING", end_date),
                bigquery.ArrayQueryParameter("actors", "STRING", actors),
            ],
        }
        process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)

        # Safe to export as a single file as the table is less than 1GB each
        extract_job = client.extract_table(
            source=dataset_ref.table(f"test_dagster_stargazers_{actor_type}"),
            destination_uris=f"gs://{GCP_BUCKET}/{output_file}",
            job_config=ExtractJobConfig(
                destination_format=(bigquery.DestinationFormat.NEWLINE_DELIMITED_JSON)
            ),
        )
        extract_job.result()

        events = []
        stream = download_gcp_blob_to_stream(GCP_BUCKET, output_file, io.BytesIO())
        for line in stream.readlines():
            events.append(json.loads(line))
        events = pd.DataFrame(events)
        events.to_csv(f"data/copycatch_test_stargazers_{actor_type}.csv", index=False)
        logging.info("Generated test data for %s actors", actor_type)


def test_iterative_synthetic():
    copycatch_params = CopyCatchParams(
        delta_t=180 * 24 * 60 * 60,
        n=1,
        m=1,
        rho=0.5,
        beta=2,
    )

    for i in range(1, 4):
        logging.info("Running synthetic test %d...", i)
        syn = pd.read_csv(f"data/copycatch_test/synthetic{i}.csv")
        copycatch = CopyCatch.from_df(copycatch_params, syn)
        copycatch.run_all()

    logging.info("Running synthetic test 3 with m = 2...")
    copycatch_params.m = 2
    copycatch = CopyCatch.from_df(copycatch_params, syn)
    copycatch.run_all()

    logging.info("Running synthetic test 3 with delta_t = 400 days...")
    copycatch_params.delta_t = 400 * 24 * 60 * 60
    copycatch = CopyCatch.from_df(copycatch_params, syn)
    copycatch.run_all()

    logging.info("Running synthetic test 3 with m = 3...")
    copycatch_params.m = 3
    copycatch = CopyCatch.from_df(copycatch_params, syn)
    copycatch.run_all()


def test_iterative_one_repo(test_repo: str, actor_type: str) -> tuple[int, int]:
    copycatch_params = CopyCatchParams(
        delta_t=180 * 24 * 60 * 60,
        n=20,
        m=5,
        rho=0.6,
        beta=2,
    )

    if actor_type == "fake":
        df = pd.read_csv("data/fake_stars_complex_repos.csv")
        n_cluster = df[df.repo_names.str.contains(test_repo)].n_activity_cluster.iloc[0]
    else:
        n_cluster = 0

    logging.info("Searching Dagster's %s stars for %s...", actor_type, test_repo)
    stargazers = pd.read_csv(f"data/copycatch_test/stargazers_{actor_type}.csv")
    actors = set(stargazers[stargazers.repo_name == test_repo].actor)
    stargazers = stargazers[stargazers.actor.isin(actors)]
    logging.info(
        "%d edges, %d repos, %d stargazers",
        len(stargazers),
        len(stargazers.repo_name.unique()),
        len(actors),
    )

    copycatch = CopyCatch.from_df(copycatch_params, stargazers)
    fake_users = set()
    users, _ = copycatch.run_once(
        copycatch.find_closest_repos(copycatch.repo2id[test_repo], copycatch.m)
    )
    if len(users) > copycatch_params.n:
        fake_users.update(users)
    logging.info("Found %d/%d fakes in one search", len(fake_users), n_cluster)

    for users, _ in copycatch.run_around_one_repo(test_repo, n_rounds=10):
        fake_users.update(users)
    logging.info("Found %d/%d fakes in 10 searches", len(fake_users), n_cluster)

    # for users, repos in copycatch.run_all(n_jobs=8):
    #    logging.info("Found %d user cluster among %s", len(users), repos)
    #    if test_repo in repos:
    #        fake_users.update(users)
    # logging.info("Found %d/%d fakes in exhaustive search", len(fake_users), n_cluster)

    return len(fake_users), n_cluster


def test_iterative_all_repos(actor_type: str):
    stargazers = pd.read_csv(f"data/copycatch_test/stargazers_{actor_type}.csv")
    logging.info(
        "%d edges, %d repos, %d stargazers",
        len(stargazers),
        len(stargazers.repo_name.unique()),
        len(stargazers.actor.unique()),
    )

    copycatch_params = CopyCatchParams(
        delta_t=180 * 24 * 60 * 60,
        n=20,
        m=5,
        rho=0.6,
        beta=2,
    )
    copycatch = CopyCatch.from_df(copycatch_params, stargazers)
    fake_results = {}
    with mp.Pool(mp.cpu_count()) as pool:
        for results in pool.imap_unordered(
            copycatch.run_around_one_repo,
            stargazers.repo_name.unique(),
            chunksize=1,
        ):
            actors = set()
            repos = set(stargazers.repo_name.unique())
            for users, repo_chunks in results:
                actors.update(users)
                repos = repos.intersection(repo_chunks)
            assert len(repos) == 1
            repo = list(repos)[0]
            fake_results[repo] = len(actors)
            logging.info("Found %d fake stars for %s", len(actors), repo)
    return fake_results


def main():
    parser = argparse.ArgumentParser(description="Run CopyCatch tests")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
        default=False,
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate test data",
        default=False,
    )
    parser.add_argument(
        "--test-synthetic",
        action="store_true",
        help="Run CopyCatch tests on simple synthetic data",
        default=False,
    )
    parser.add_argument(
        "--test-real",
        action="store_true",
        help="Run CopyCatch tests on real data",
        default=False,
    )
    parser.add_argument(
        "--test-real-all",
        action="store_true",
        help="Run CopyCatch tests on all repos in real data",
        default=False,
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO if not args.debug else logging.DEBUG,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    if args.generate:
        if not os.path.exists("data/copycatch_test/stargazers_fake.csv"):
            get_stargazer_data_dagster(start_date=START_DATE, end_date=END_DATE)
        else:
            logging.info("Test data already exists")

    if args.test_synthetic:
        test_iterative_synthetic()

    if args.test_real:
        fake_results, real_results = {}, {}
        suspicious_repos = [
            "holochain/holochain-client-js",
            "Bitcoin-ABC/bitcoin-abc",
            "Joystream/joystream",
            "subquery/subql",
            "etherspot/etherspot-sdk",
            "tatumio/tatum-js",
            "streamr-dev/network",
            "paraswap/paraswap-sdk",
        ]
        for repo in suspicious_repos:
            fake_results[repo] = test_iterative_one_repo(repo, "fake")
            real_results[repo] = test_iterative_one_repo(repo, "real")
        logging.info("Fake results:\n%s", pformat(fake_results))
        logging.info("Real results:\n%s", pformat(real_results))

    if args.test_real_all:
        fake_results = test_iterative_all_repos("fake")
        real_results = test_iterative_all_repos("real")
        logging.info("Fake results:\n%s", pformat(fake_results))
        logging.info("Real results:\n%s", pformat(real_results))

    logging.info("Done!")


if __name__ == "__main__":
    main()
