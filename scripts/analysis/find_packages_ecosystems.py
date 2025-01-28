import sys
import random
import logging
import pymongo
import requests
import pandas as pd

from typing import Iterable
from pymongo.errors import DocumentTooLarge, DuplicateKeyError
from scripts import MONGO_URL
from scripts.analysis.data import get_fake_star_repos, get_repos_with_campaign


def collect_ecosystems(repo_names: Iterable[str]):
    logging.info("%d repos to collect", len(repo_names))

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.ecosystems_packages.create_index(
            ["name", "ecosystem"], unique=True
        )
        client.fake_stars.ecosystems_mapping.create_index("repo_name", unique=True)

    base_url = "https://packages.ecosyste.ms/api/v1/packages/lookup"
    for repo_name in repo_names:
        with pymongo.MongoClient(MONGO_URL) as client:
            mapping_db = client.fake_stars.ecosystems_mapping
            if mapping_db.find_one({"repo_name": repo_name}):
                logging.info("Already collected packages for %s", repo_name)
                continue

        logging.info("Collecting packages for %s", repo_name)

        req = requests.get(
            base_url, params={"repository_url": f"https://github.com/{repo_name}"}
        )
        if req.status_code != 200:
            logging.error("Failed to get data for %s: %s", repo_name, req)
            break  # stop because rate limit may have been reached
        with pymongo.MongoClient(MONGO_URL) as client:
            pkg_db = client.fake_stars.ecosystems_packages
            mapping_db = client.fake_stars.ecosystems_mapping

            mapping = {"repo_name": repo_name, "packages": []}
            for package in req.json():
                query = {"name": package["name"], "ecosystem": package["ecosystem"]}
                mapping["packages"].append(query)
                if pkg_db.find_one(query):
                    continue
                else:
                    try:
                        pkg_db.insert_one(package)
                    except DocumentTooLarge:
                        logging.error("Document too large for %s", package)
                        logging.info("Trying again with a smaller document")
                        del package["repo_metadata"]["tags"]
                        pkg_db.insert_one(package)

            mapping_db.insert_one(mapping)

            logging.info(
                "Mapping found: %s -> %s",
                repo_name,
                [(p["name"], p["ecosystem"]) for p in mapping["packages"]],
            )

    return


def summarize_ecosystems() -> pd.DataFrame:
    summary = []
    with pymongo.MongoClient(MONGO_URL) as client:
        for mapping in client.fake_stars.ecosystems_mapping.find():
            for m in mapping["packages"]:
                package, ecosystem = m["name"], m["ecosystem"]
                pkg_doc = client.fake_stars.ecosystems_packages.find_one(
                    {"name": package, "ecosystem": ecosystem}
                )
                summary.append(
                    {
                        "repo_name": mapping["repo_name"],
                        "package": package,
                        "ecosystem": ecosystem,
                        "description": pkg_doc["description"],
                        "created_at": pkg_doc["created_at"],
                        "n_versions": pkg_doc["versions_count"],
                        "n_dependent_packages": pkg_doc["dependent_packages_count"],
                        "n_dependent_repos": pkg_doc["dependent_repos_count"],
                        "n_downloads": pkg_doc["downloads"],
                        "downloads_period": pkg_doc["downloads_period"],
                    }
                )
                logging.info("Summarized %s -> %s", mapping["repo_name"], summary[-1])
    return pd.DataFrame(summary).sort_values(["ecosystem", "package"])


def sample_random_packages(n: int) -> pd.DataFrame:
    pypi_github = pd.read_csv(
        "data/pypi_github.csv", dtype={"name": str}, keep_default_na=False
    )
    npm_github = pd.read_csv(
        "data/npm_github.csv", dtype={"name": str}, keep_default_na=False
    )

    random.seed(114514)
    npm_pkgs = random.sample(sorted(set(pypi_github.name)), int(n))
    pypi_pkgs = random.sample(sorted(set(npm_github.name)), int(n))

    summary = []
    for pkg, ecosystem in zip(npm_pkgs + pypi_pkgs, ["npm"] * n + ["pypi"] * n):
        with pymongo.MongoClient(MONGO_URL) as client:
            query = {"name": pkg, "ecosystem": ecosystem}
            data = client.fake_stars.ecosystems_packages.find_one(query)
            if data:
                logging.info("Already collected data for %s", pkg)
            else:
                registry = "npmjs.org" if ecosystem == "npm" else "pypi.org"
                url = f"https://packages.ecosyste.ms/api/v1/registries/{registry}/packages/{pkg}"
                req = requests.get(url)
                if req.status_code != 200 or "error" in req.json():
                    logging.error("Req failed for %s: %s", pkg, req.json()["error"])
                    client.fake_stars.ecosystems_packages.insert_one(
                        {
                            "name": pkg,
                            "ecosystem": ecosystem,
                            "error": req.json()["error"],
                        }
                    )
                    continue
                data = req.json()
                try:
                    client.fake_stars.ecosystems_packages.insert_one(data)
                except DuplicateKeyError:
                    logging.error("Duplicate key for %s %s", pkg, ecosystem)
                    continue

    with pymongo.MongoClient(MONGO_URL) as client:
        for pkg_doc in client.fake_stars.ecosystems_packages.find(
            {
                "ecosystem": {"$in": ["npm", "pypi"]},
                "repo_metadata.stargazers_count": {"$gte": 50},
            }
        ):
            row = {
                "package": pkg_doc["name"],
                "ecosystem": pkg_doc["ecosystem"],
                "description": pkg_doc["description"],
                "n_versions": pkg_doc["versions_count"],
                "n_stars": pkg_doc["repo_metadata"]["stargazers_count"],
                "n_dependent_packages": pkg_doc["dependent_packages_count"],
                "n_dependent_repos": pkg_doc["dependent_repos_count"],
                "n_downloads": pkg_doc["downloads"],
                "downloads_period": pkg_doc["downloads_period"],
            }
            summary.append(row)
            logging.info("Sampled %s -> %s", pkg_doc["name"], row)

    # keep n for pypi and npm respectively
    summary = pd.DataFrame(summary)
    summary = pd.concat(
        [
            summary[summary.ecosystem == "npm"],
            summary[summary.ecosystem == "pypi"],
        ],
        ignore_index=True,
    )

    return summary.sort_values(["ecosystem", "package"])


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logging.info("Start!")

    repos = get_fake_star_repos()
    repos_with_campaign = get_repos_with_campaign()

    collect_ecosystems(repos_with_campaign)
    summary = summarize_ecosystems()
    summary.insert(
        5,
        "n_stars",
        summary["repo_name"].map(lambda n: repos[repos.repo_name == n].n_stars.iloc[0]),
    )
    summary.to_csv("data/packages_fake.csv", index=False)

    # For comparison (especially w. download data), sample packages from npm and PyPI
    random = sample_random_packages(10000)
    random = random[~random.package.isin(set(summary.package))]
    random.to_csv("data/packages_random.csv", index=False)

    logging.info("Done!")


if __name__ == "__main__":
    main()
