import pandas as pd
import pymongo
import yaml

with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)
client = pymongo.MongoClient(SECRETS["mongo_url"])
stars_db = client.fake_stars.stars
downloads_db = client.fake_stars.downloads

obvious_repos = pd.read_csv("data/fake_stars_obvious_repos.csv")
filtered_repos = obvious_repos[(obvious_repos["fake_percentage"] >= 2) | (
    obvious_repos["fake_stars"] >= 100)]

obvious_users = pd.read_csv("data/fake_stars_obvious_users.csv")

filtered_users = obvious_users[obvious_users["github"].isin(
    filtered_repos["github"])]


filtered_repos.to_csv("data/filtered_repos.csv", index=False)
filtered_users.to_csv("data/filtered_repos_fake_users.csv", index=False)

unique_githubs = set(filtered_repos["github"].unique())

query = {"github": {"$in": list(unique_githubs)}}
stargazers = list(
    stars_db.find(query, {"github": 1, "stargazerName": 1,
                          "starredAt": 1, "_id": 0})
)

# Convert the documents to a DataFrame
df_star = pd.DataFrame(stargazers)
df_star.rename(
    {"stargazerName": "stargazer_name", "starredAt": "starred_at"},
    axis="columns",
    inplace=True,
)
df_star.to_csv("data/filtered_repos_total_users.csv", index=False)

download = list(downloads_db.find(query, {"github": 1, "month": 1,
                                          "downloads": 1, "_id": 0}))
df_download = pd.DataFrame(download).groupby(
    ['github', 'month'], as_index=False).sum()
df_download.to_csv("data/filtered_repos_downloads.csv", index=False)
