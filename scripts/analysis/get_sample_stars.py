import sys
import yaml
import time
import argparse
import pymongo
import logging
import pandas as pd
import stscraper as scraper

from multiprocessing import Pool

from scripts import MONGO_URL, GITHUB_TOKENS


def get_stars(repo: str):
    owner, name = repo.split("/")
    client = pymongo.MongoClient(MONGO_URL)
    db = client.fake_stars.stars

    strudel = scraper.GitHubAPIv4(",".join(GITHUB_TOKENS))

    try:
        limits = scraper.get_limits(",".join(GITHUB_TOKENS))
        for limit in limits:
            del limit["key"]
            logging.info(f"tokens: {limit}")

        result = strudel(
            """
        query($cursor: String, $owner: String!, $name: String!) {
            repository(owner:$owner, name:$name){
            stargazers(first: 100, after: $cursor, orderBy: {field: STARRED_AT, direction: DESC}) {
                edges {
                node {
                    login,
                    createdAt
                    updatedAt
                    isHireable
                    bio
                    twitterUsername
                    followers{ totalCount }
                    following{ totalCount }
                    gists{ totalCount }
                    repositories{ totalCount }
                }
                starredAt
                }
                pageInfo {endCursor, hasNextPage}
            }
            }
        }""",
            ("repository", "stargazers"),
            owner=owner,
            name=name,
        )

        results = []
        for i, star in enumerate(result):
            starredAt = star["starredAt"]

            node = star["node"]
            data = {
                "github": repo,
                "stargazerName": node["login"],
                "starredAt": starredAt,
                "createdAt": node["createdAt"],
                "updatedAt": node["updatedAt"],
                # node["email"], requiring user:email scope and not particularly useful
                "email": "",
                "isHireable": node["isHireable"],
                "bio": node["bio"],
                "twitterUsername": node["twitterUsername"],
                "followers": node["followers"]["totalCount"],
                "following": node["following"]["totalCount"],
                "gists": node["gists"]["totalCount"],
                "repos": node["repositories"]["totalCount"],
            }

            existing_check = db.find_one(
                {
                    "github": data["github"],
                    "stargazerName": data["stargazerName"],
                    "starredAt": data["starredAt"],
                }
            )

            if existing_check:  # already in DB
                break
            else:
                results.append(data)
            if i % 100 == 0:
                logging.info(f"processed {i} stars")

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
    total_stars = sum(dict(zip(df["github"], df["stars"])).values())
    logging.info(f"{len(set(df['github']))} repos ({total_stars} stars) to collect")

    with pymongo.MongoClient(MONGO_URL) as client:
        client.fake_stars.stars.create_index(
            [("github", 1), ("stargazerName", 1), ("starredAt", 1)], unique=True
        )

    parser = argparse.ArgumentParser()
    parser.add_argument("-j", help="Number of Jobs", type=int, default=1)
    arguments = parser.parse_args()

    if arguments.j > 1:
        with Pool(arguments.j) as pool:
            pool.map(get_stars, set(df["github"]))
    else:
        for repo in set(df["github"]):
            logging.info(f"start working on {repo}")
            get_stars(repo)

    logging.info("Done!")


if __name__ == "__main__":
    main()
