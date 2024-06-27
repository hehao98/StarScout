import yaml
import pymongo
import pandas as pd
import datetime as dt
from datetime import datetime


def _validate_star(user):
    # Returns True if this matches a fake profile.
    if (
        (user["followers"] < 2)
        and (user["following"] < 2)
        and (user["gists"] == 0)
        and (user["repos"] < 5)
        and (user["createdAt"] > dt.datetime(2022, 1, 1))
        and (user["email"] == "")
        and (user["bio"] is None or user["bio"] == "")
        and (
            user["starredAt"].date()
            == user["updatedAt"].date()
            == user["createdAt"].date()
        )
    ):
        return True
    else:
        return False


def read_from_mongo(uri, dbname, collection_name):
    client = pymongo.MongoClient(uri)
    db = client[dbname]
    collection = db[collection_name]

    fake_count = 0
    github_dict = {}
    total_stars = {}
    user_info = []

    # Process and validate users
    for user in collection.find():
        user["createdAt"] = datetime.strptime(user["createdAt"], "%Y-%m-%dT%H:%M:%SZ")
        user["updatedAt"] = datetime.strptime(user["updatedAt"], "%Y-%m-%dT%H:%M:%SZ")
        user["starredAt"] = datetime.strptime(user["starredAt"], "%Y-%m-%dT%H:%M:%SZ")

        repo_name = user["github"]

        if _validate_star(user):
            user_info.append({"github": user["github"], "name": user["stargazerName"]})
            fake_count += 1
            if repo_name not in github_dict:
                github_dict[repo_name] = {"fake_stars": 0, "total_stars": 0}
            github_dict[repo_name]["fake_stars"] += 1

        if repo_name not in total_stars:
            total_stars[repo_name] = 0
        total_stars[repo_name] += 1

    results = pd.DataFrame(user_info)
    results.sort_values(by="github").to_csv("data/fake_users.csv", index=False)

    # Merge the total stars into the github_dict
    for repo_name in github_dict:
        github_dict[repo_name]["total_stars"] = total_stars[repo_name]
        github_dict[repo_name]["fake_percentage"] = (
            github_dict[repo_name]["fake_stars"] / github_dict[repo_name]["total_stars"]
        ) * 100

    # Sort by fake percentage
    sorted_github_dict = dict(
        sorted(
            github_dict.items(),
            key=lambda item: item[1]["fake_percentage"],
            reverse=True,
        )
    )

    # Display the results
    for key, value in sorted_github_dict.items():
        print(
            f"{key}: {value['fake_stars']} fake stars, {value['fake_percentage']:.2f}% fake stars"
        )

    print("Number of suspicious repos: " + str(len(sorted_github_dict)))
    client.close()
    return fake_count


def main():
    with open("secrets.yaml", "r") as f:
        SECRETS = yaml.safe_load(f)

    uri = SECRETS["mongo_url"]
    db_name = "fake_stars"
    collection_name = "stars"
    count = read_from_mongo(uri, db_name, collection_name)
    print("Total fake stars count:", count)


if __name__ == "__main__":
    main()
