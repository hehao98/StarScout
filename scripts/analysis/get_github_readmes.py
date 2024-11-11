import os
import sys
import base64
import logging
import subprocess
import pandas as pd

from typing import Optional
from github import Github, Auth
from pymongo import MongoClient

from scripts import MONGO_URL, GITHUB_TOKENS
from scripts.analysis.data import get_fake_star_repos, get_repos_with_campaign


def get_github_readme(repo: str) -> Optional[str]:
    try:
        github = Github(auth=Auth.Token(GITHUB_TOKENS[0]))
        content = github.get_repo(repo).get_readme().content
        return content
    except Exception as ex:
        logging.error(f"Error getting README repo {repo}: {ex}")
        return None


def get_repo_size(repo: str) -> Optional[int]:
    try:
        github = Github(auth=Auth.Token(GITHUB_TOKENS[0]))
        size = github.get_repo(repo).size
        return size
    except Exception as ex:
        logging.error(f"Error getting size for repo {repo}: {ex}")
        return None


def clone_github_repo(repo: str) -> None:
    prev_dir = os.getcwd()
    os.chdir("../fake-star-repos")

    # clone repo
    if os.path.exists(f"../fake-star-repos/{repo.replace('/', '_')}"):
        logging.info(f"Skipping {repo} because it is already cloned")
    else:
        logging.info(f"Cloning {repo}...")
        result = subprocess.run(
            [
                "git",
                "clone",
                f"https://github.com/{repo}.git",
                repo.replace("/", "_"),
                "--depth",
                "1",
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            logging.error(f"Failed to clone {repo}")
            os.chdir(prev_dir)
            return

    # compress into tarball
    result = subprocess.run(
        [
            "tar",
            "-czf",
            f"{repo.replace('/', '_')}.tar.gz",
            repo.replace("/", "_"),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        logging.error(f"Failed to compress {repo}")
    else:
        logging.info(f"Compressed {repo}")
        subprocess.run(["rm", "-rf", repo.replace("/", "_")])

    os.chdir(prev_dir)


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    repos = get_fake_star_repos()
    repos = repos[repos.repo_name.isin(get_repos_with_campaign())]

    with MongoClient(MONGO_URL) as client:
        github_readmes = client.fake_stars.github_readmes

        for repo in repos[repos.repo_id.notna()].repo_name:
            if github_readmes.find_one({"repo": repo}):
                logging.info(f"Skipping {repo}")
                continue
            readme = get_github_readme(repo)
            if readme:
                github_readmes.insert_one({"repo": repo, "readme": readme})
                logging.info(f"Inserted {repo}")
            else:
                logging.info(f"Failed to get README for {repo}")

        summary = []
        os.makedirs("data/readmes", exist_ok=True)
        for repo in repos[repos.repo_id.notna()].repo_name:
            readme = github_readmes.find_one({"repo": repo})

            if readme:
                path = f"data/readmes/{repo.replace('/', '_')}.md"
                with open(path, "w") as f:
                    content = base64.b64decode(readme["readme"])
                    f.write(content.decode("utf-8", "ignore"))
                    summary.append({"repo": repo, "readme": path, "type": None})
        pd.DataFrame(summary).to_csv("data/readmes/summary.csv", index=False)

    
    for repo in repos[repos.repo_id.notna()].repo_name:
        size = get_repo_size(repo)
        if size is None:
            logging.info(f"Failed to get size for {repo}")
            continue
        if size >= 1024 * 1024:  # 1024MB
            logging.info(f"Skipping {repo} because it is too large ({size} Kb)")
            continue
        clone_github_repo(repo)

    logging.info("Done!")


if __name__ == "__main__":
    main()
