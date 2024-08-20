import os
import sys
import base64
import shutil
import logging
import subprocess
import pandas as pd

from typing import Optional

from scripts.analysis.data import get_fake_star_repos_all, get_repo_with_compaign


def get_p2P(repos: set[str]) -> dict[str, str]:
    repos = {repo.replace("/", "_") for repo in repos}

    result = {}
    for repo in repos:
        proc = subprocess.Popen(
            f"echo {repo} |  ~/lookup/getValues p2P",
            shell=True,
            stdout=subprocess.PIPE,
            executable="/bin/bash",
        )
        for line in proc.stdout.readlines():
            line = line.decode("utf-8", "ignore").strip()
            if ";" in line:
                repo, repo_woc = line.split(";")
                logging.info(f"Found {repo} -> {repo_woc}")
                result[repo] = repo_woc
            else:
                logging.error(line)

    return result


def get_commit(commit: str) -> Optional[dict[str, str]]:
    proc = subprocess.Popen(
        f"echo {commit} | ~/lookup/showCnt commit",
        shell=True,
        stdout=subprocess.PIPE,
        executable="/bin/bash",
    )
    out = proc.stdout.read().decode("utf-8", "ignore").strip()
    if ";" in out:
        commit, tree, parent, author, committer, authored_at, committed_at = out.split(
            ";"
        )
        return {
            "commit": commit,
            "tree": tree,
            "parent": parent,
            "author": author,
            "committer": committer,
            "authored_at": authored_at,
            "committed_at": committed_at,
        }
    else:
        return None


def get_blob(blob: str) -> bytes:
    proc = subprocess.Popen(
        f"echo {blob} | ~/lookup/showCnt blob 1",
        stdout=subprocess.PIPE,
        shell=True,
        executable="/bin/bash",
    )

    for line in proc.stdout.readlines():
        return base64.b64decode(line.strip().split(";")[1])


def get_tree(tree: str) -> list[tuple[str, str]]:
    proc = subprocess.Popen(
        f"echo {tree} | ~/lookup/showCnt tree",
        stdout=subprocess.PIPE,
        shell=True,
        executable="/bin/bash",
    )
    return [
        line.decode("utf-8", "ignore").strip().split(";")[1:]
        for line in proc.stdout.readlines()
    ]


def get_repo_head_commit(repo: str) -> list[str]:
    proc = subprocess.Popen(
        f"echo {repo} | ~/lookup/getValues P2c",
        shell=True,
        stdout=subprocess.PIPE,
        executable="/bin/bash",
    )
    out = proc.stdout.read().decode("utf-8", "ignore").strip()
    if ";" in out:
        logging.info("Found %s -> %s", repo, out)
        head_commit, head_time = "", 0
        for commit_sha in out.split(";")[1:]:
            commit = get_commit(commit_sha)
            if commit is not None and int(commit["committed_at"]) > head_time:
                head_commit, head_time = commit["commit"], int(commit["committed_at"])
        logging.info("Head commit %s", head_commit)
        return head_commit
    else:
        logging.info("No commit found for repo %s", repo)
        return []


def save_tarball(repo: str, files: list[str], blobs: list[str]):
    os.path.makedirs("../repo_woc/" + repo, exist_ok=True)

    for blob, file in zip(blobs, files):
        path = f"../repo_woc/{repo}/{file}"
        with open(path, "wb") as f:
            f.write(get_blob(blob))

    prev_dir = os.getcwd()
    os.chdir("../repo_woc")
    subprocess.run(f"tar -czf {repo}.tar.gz {repo}")
    shutil.rmtree("../repo_woc/" + repo)
    os.chdir(prev_dir)

    logging.info(f"Saved {repo}.tar.gz")


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    repos = get_fake_star_repos_all()
    repos = repos[repos.repo_id.isna() & repos.repo_name.isin(get_repo_with_compaign())]

    os.makedirs("data/woc", exist_ok=True)
    os.makedirs("../repos_woc", exist_ok=True)

    if not os.path.exists("data/woc/p2P.csv"):
        p2P = get_p2P(set(repos.repo_name))
        p2P = [{"p": repo, "P": repo_woc} for repo, repo_woc in p2P.items()]
        p2P = pd.DataFrame(p2P)
        p2P.to_csv("data/woc/p2P.csv", index=False)
    else:
        p2P = pd.read_csv("data/woc/p2P.csv")

    if not os.path.exists("data/woc/P2fb.csv"):
        P2fb = []
        for P in p2P.P.unique():
            head_commit = get_repo_head_commit(P)
            if head_commit:
                tree = get_commit(head_commit).get("tree")
                blobs = get_tree(tree)
                logging.info("%s -> %s", P, blobs)
                P2fb.extend([{"P": P, "f": file, "b": blob} for blob, file in blobs])
        P2fb = pd.DataFrame(P2fb)
        P2fb.to_csv("data/woc/P2fb.csv", index=False)
    else:
        P2fb = pd.read_csv("data/woc/P2fb.csv")

    for P, df in P2fb.groupby("P"):
        files, blobs = df.f.tolist(), df.b.to_list()
        save_tarball(P, files, blobs)


if __name__ == "__main__":
    main()
