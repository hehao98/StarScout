import io
import os
import sys
import json
import logging
import pymongo
import networkx as nx

from collections import defaultdict
from tqdm import tqdm

from scripts import MONGO_URL, COPYCATCH_DATE_CHUNKS, GOOGLE_CLOUD_BUCKET as GCP_BUCKET
from scripts.gcp import download_gcp_blob_to_stream, list_gcp_blobs
from scripts.analysis.data import get_repos_with_campaign


def find_large_clusters():
    cluster_id_to_repo = defaultdict(set)
    repo_to_cluster_id = defaultdict(set)
    repos_with_campaign = get_repos_with_campaign()

    for start_date, end_date in COPYCATCH_DATE_CHUNKS:
        for blob in list_gcp_blobs(GCP_BUCKET, f"clusters/{start_date}_{end_date}"):
            logging.info("Blob: %s", blob.name)
            with download_gcp_blob_to_stream(GCP_BUCKET, blob.name, io.BytesIO()) as f:
                for line in f:
                    obj = json.loads(line)
                    cluster_id = obj["repo_name"]
                    for repo in obj["cluster"]:
                        if repo in repos_with_campaign:
                            repo_to_cluster_id[repo].add(cluster_id)
                            cluster_id_to_repo[cluster_id].add(repo)

    for repo, cluster_ids in sorted(
        repo_to_cluster_id.items(), key=lambda x: len(x[1]), reverse=True
    )[0:10]:
        if len(cluster_ids) > 1:
            logging.info("Repo: %s, Clusters: %s", repo, len(cluster_ids))
            all_repos = set()
            for cluster_id in cluster_ids:
                all_repos.update(cluster_id_to_repo[cluster_id])
            logging.info("All %d repos: %s", len(all_repos), sorted(all_repos)[0:100])


def generate_repository_network() -> nx.Graph:
    if os.path.exists("data/repo_network.csv"):
        return nx.read_edgelist("data/repo_network.csv")

    G = nx.Graph()

    repo_to_actors = defaultdict(set)
    actors_to_repo = defaultdict(set)
    repos_with_campaign = get_repos_with_campaign()

    for repo in tqdm(repos_with_campaign):
        with pymongo.MongoClient(MONGO_URL) as client:
            stars = list(
                client.fake_stars.low_activity_stars.find(
                    {"repo": repo, "low_activity": True}
                )
            )
            stars.extend(
                list(
                    client.fake_stars.clustered_stars.find(
                        {"repo": repo, "clustered": True}
                    )
                )
            )
        repo_to_actors[repo] = set([star["actor"] for star in stars])
        for star in stars:
            actors_to_repo[star["actor"]].add(repo)

    for repo in tqdm(repos_with_campaign):
        for other_repo in repos_with_campaign:
            overlap = len(repo_to_actors[repo] & repo_to_actors[other_repo])
            if repo != other_repo and overlap > 0:
                G.add_edge(repo, other_repo, weight=overlap)

    nx.to_pandas_edgelist(G).to_csv("data/repo_network.csv", index=False)
    return G


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # find_large_clusters()

    generate_repository_network()
