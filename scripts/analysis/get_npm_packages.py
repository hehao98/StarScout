import psycopg
import pandas as pd

from tqdm import tqdm
from scripts import NPM_FOLLOWER_POSTGRES


def main():
    npm_github = []
    with psycopg.connect(NPM_FOLLOWER_POSTGRES) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT 
                    packages.name, 
                    ((versions.repository_parsed).github_bitbucket_gitlab_user 
                    || '/' || (versions.repository_parsed).github_bitbucket_gitlab_repo)
                    AS github
                FROM versions 
                JOIN packages ON versions.package_id = packages.id
                WHERE (versions.repository_parsed).host = 'github'
                ORDER BY packages.name ASC
                """
            )
            for name, github in tqdm(cur.fetchall()):
                npm_github.append({"name": name, "github": github})
    npm_github = pd.DataFrame(npm_github)
    npm_github.to_csv("data/npm_github.csv", index=False)


if __name__ == "__main__":
    main()
