import sys
import logging
import pandas as pd

from google.cloud import bigquery

from scripts import BIGQUERY_PROJECT as PROJECT_ID, BIGQUERY_DATASET as DATASET_ID
from scripts.gcp import process_bigquery
from scripts.analysis.data import get_fake_star_repos_all


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    repos = get_fake_star_repos_all()
    pypi_github = pd.read_csv("data/pypi_github.csv")
    pypi_fake_repos = pypi_github[pypi_github["github"].isin(set(repos.repo_name))]
    all_fake_pkgs = set(pypi_fake_repos.name)
    all_fake_pkgs = sorted([x.lower() for x in all_fake_pkgs])
    logging.info(f"Total {len(all_fake_pkgs)} fake packages in PyPI")

    bigquery_task = {
        "interactive": True,
        "query_file": "scripts/analysis/queries/stg_pypi_downloads.sql",
        "output_table_id": "test_pypi_downloads",
        "params": [
            bigquery.ArrayQueryParameter("packages", "STRING", all_fake_pkgs),
        ],
    }
    process_bigquery(PROJECT_ID, DATASET_ID, **bigquery_task)

    logging.info("Done!")


if __name__ == "__main__":
    main()
