import pandas as pd
import pymongo
import yaml

with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)
client = pymongo.MongoClient(SECRETS["mongo_url"])
db = client.fake_stars.stars

file_path1 = 'data/fake_stars_obvious_percentage.csv'
df1 = pd.read_csv(file_path1)
filtered_df1 = df1[(df1['fake_percentage'] >= 2) | (df1['fake_stars'] >= 100)]


file_path2 = 'data/fake_stars_obvious_users.csv'
df2 = pd.read_csv(file_path2)

filtered_df2 = df2[df2['github'].isin(filtered_df1['github'])]


filtered_df1.to_csv('data/filtered_repos_percentage.csv', index=False)
filtered_df2.to_csv('data/filtered_repos_fake_users.csv', index=False)

unique_githubs = set(filtered_df1['github'].unique())

query = {"github": {"$in": list(unique_githubs)}}
documents = list(
    db.find(query, {"github": 1, "stargazerName": 1, "starredAt": 1, "_id": 0}))

# Convert the documents to a DataFrame
df_mongo = pd.DataFrame(documents)
df_mongo.to_csv('data/filtered_repos_total_users.csv', index=False)
