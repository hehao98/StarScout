import sys
import time
import argparse
import pymongo
import logging
import pandas as pd
import stscraper as scraper

from multiprocessing import Pool

from scripts import MONGO_URL, GITHUB_TOKENS


def get_releases(repo: str):
    owner, name = repo.split("/")
    client = pymongo.MongoClient(MONGO_URL)
    db = client.fake_stars.releases

    strudel = scraper.GitHubAPIv4(",".join(GITHUB_TOKENS))
    try:
        limits = scraper.get_limits(",".join(GITHUB_TOKENS))
        for limit in limits:
            del limit["key"]
            logging.info(f"tokens: {limit}")

        result = strudel(
            """
        query($cursor: String, $owner: String!, $name: String!) {
            repository(owner: $owner, name: $name) {
                releases(first: 100,after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
                    nodes {
                        tagName
                        publishedAt
                    }
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                }
            }
        }""",
            ("repository", "releases"),
            owner=owner,
            name=name,
        )
        results = []

        for i, release in enumerate(result):
            data = {
                "github": repo,
                "tag": release["tagName"],
                "releasedAt": release["publishedAt"],
            }

            existing_check = db.find_one(
                {
                    "github": data["github"],
                    "tag": data["tag"],
                }
            )

            if existing_check:  # already in DB
                break
            else:
                results.append(data)
            if i % 100 == 0:
                logging.info(f"processed {i} releases")

        if len(results) == 0:
            logging.info("nothing to add for " + repo)
        else:
            db.insert_many(results)
            logging.info("finish updating for " + repo)
    except Exception as ex:
        logging.error(f"error fetching repo {repo}: {ex}")
        logging.info("Sleeping...")
        time.sleep(3600)
    finally:
        client.close()


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logging.info("Start!")

    df = pd.read_csv("data/samples.csv")

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.releases.create_index(
            [("github", 1), ("tag", 1)], unique=True
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("-j", help="Number of Jobs", type=int, default=1)
    arguments = parser.parse_args()

    if arguments.j > 1:
        with Pool(arguments.j) as pool:
            pool.map(get_releases, set(df["github"]))
    else:
        for repo in set(df["github"]):
            logging.info(f"start working on {repo}")
            get_releases(repo)

    logging.info("Done!")


if __name__ == "__main__":
    main()
