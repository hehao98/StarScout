import sys
import yaml
import time
import argparse
import pymongo
import logging
import pandas as pd
import stscraper as scraper

from multiprocessing import Pool


with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)


def get_repo_id(repo: str):
    global SECRETS

    owner, name = repo.split("/")
    client = pymongo.MongoClient(SECRETS["mongo_url"])

    tokens = ",".join(x["token"] for x in SECRETS["github_tokens"])
    strudel = scraper.GitHubAPIv4(tokens)

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
        print(result)
        return result
    except Exception as ex:
        logging.error(f"error fetching repo {repo}: {ex}")
        logging.info("Sleeping...")
        time.sleep(3600)
    finally:
        client.close()


def main():
    global SECRETS

    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logging.info("Start!")

    df = pd.read_csv("data/samples.csv")
    githubs = set(df['github'])
    repos = set()
    for git in githubs:
        id = get_repo_id(git)
        repos.add(id)
        if len(repos) % 100 == 0:
            print(f"Collect {len(repos)} ids")
    print(len(repos))


if __name__ == "__main__":
    main()
