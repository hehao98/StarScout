import os
import sys
import logging
import subprocess

from typing import Optional
from github import Github, Auth
from pymongo import MongoClient

from scripts import MONGO_URL, GITHUB_TOKENS
from scripts.analysis.data import get_fake_star_repos_all


def get_github_readme(repo: str) -> Optional[str]:
    try:
        github = Github(auth=Auth.Token(GITHUB_TOKENS[0]))
        content = github.get_repo(repo).get_readme().content
        return content
    except Exception as ex:
        logging.error(f"Error getting README repo {repo}: {ex}")
        return None


def clone_github_repo(repo: str) -> None:
    logging.info(f"Cloning {repo}...")
    prev_dir = os.getcwd()
    os.chdir("../repos")
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


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    repos = get_fake_star_repos_all()

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

    for repo in repos[repos.repo_id.notna()].repo_name:
        clone_github_repo(repo)

    for repo in repos.repo_name:
        pass  # TODO: world of code

    logging.info("Done!")


if __name__ == "__main__":
    main()
