import stscraper as scraper
import pymongo
import sys
import logging
import pandas as pd
import time

file_path = 'tokens.txt'
tokens = []
# Read the tokens from the file and join them into one string
with open(file_path, 'r') as file:
    for line in file:
        # Split the line into parts based on the colon and space
        parts = line.strip().split(': ')
        if len(parts) == 2:
            tokens.append(parts[1])

# Join the tokens into one string without any separator
combined_tokens = ','.join(tokens)
print(combined_tokens)
gh_api4 = scraper.GitHubAPIv4(combined_tokens)


def get_star(git):
    github = git.split('/')
    logging.info(f"start working on {git}")
    name = github[1]
    owner = github[0]

    try:
        result = gh_api4(
            """
      query($cursor: String, $owner: String!, $name: String!) {
        repository(owner:$owner, name:$name){
          stargazers(first: 100, after: $cursor, orderBy: {field: STARRED_AT, direction: DESC}) {
            edges {

              node{
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
      }""", ('repository', 'stargazers'), owner=owner, name=name
        )
    except Exception as ex:
        logging.error(f"Error processing {git}: {ex}")
        sys.exit(1)
    results = []
    for star in result:
        starredAt = star["starredAt"]

        node = star["node"]
        data = {
            "github": git,
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
        try:
            existing_check = stars.find_one(
                {"github": data["github"], "stargazerName": data["stargazerName"], "starredAt": data["starredAt"]})
        except Exception as ex:
            logging.error(f"Error checking {git}: {ex}")
            sys.exit(1)
        if existing_check:  # already in DB
            break
        else:
            results.append(data)

    if len(results) == 0:
        logging.info("nothing to add for " + git)
    else:
        stars.insert_many(results)
        logging.info("finish updating for " + git)


df = pd.read_csv("samples.csv")
githubs = set(df['github'])

DbClient = pymongo.MongoClient("mongodb://localhost:27020")
db = DbClient.fake_stars
stars = db.stars
stars.create_index([("github", 1), ("stargazerName", 1), ("starredAt", 1)])

logging.basicConfig(
    format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)],


)
logging.info("Start!")

for git in githubs:
    tokens = scraper.get_limits(combined_tokens)
    for token in tokens:
        logging.info(token)
    get_star(git)

logging.info("Done!")
