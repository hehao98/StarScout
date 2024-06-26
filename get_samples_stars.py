import sys
import yaml
import pymongo
import logging
import pandas as pd
import multiprocessing as mp
import stscraper as scraper


with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)


def get_stars(repo: str):
    global SECRETS
    owner, name = repo.split("/")
    tokens = ",".join(x["token"] for x in SECRETS["github_tokens"])
    strudel = scraper.GitHubAPIv4(tokens)
    db = pymongo.MongoClient(SECRETS["mongo_url"]).fakestars.stars

    logging.info(f"start working on {repo}, tokens: {scraper.get_limits(tokens)}")

    try:
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
                email
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
    except Exception as ex:
        logging.error(f"Error processing {repo}: {ex}")
        return

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
            "email": node["email"],
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


def main():
    global SECRETS

    df = pd.read_csv("samples.csv")

    db = pymongo.MongoClient(SECRETS["mongo_url"]).fakestars.stars
    db.create_index(
        [("github", 1), ("stargazerName", 1), ("starredAt", 1)], unique=True
    )

    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    logging.info("Start!")

    with mp.pool(len(SECRETS["github_tokens"]) * 5) as pool:
        pool.map(get_stars, df["github"].tolist())

    logging.info("Done!")


if __name__ == "__main__":
    main()
