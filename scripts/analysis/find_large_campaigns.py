import io
import sys
import json
import logging

from collections import defaultdict

from scripts import COPYCATCH_DATE_CHUNKS, GOOGLE_CLOUD_BUCKET as GCP_BUCKET
from scripts.gcp import download_gcp_blob_to_stream, list_gcp_blobs


def find_large_clusters(start_date: str, end_date: str):
    cluster_id_to_repo = defaultdict(set)
    repo_to_cluster_id = defaultdict(set)

    for blob in list_gcp_blobs(GCP_BUCKET, f"clusters/{start_date}_{end_date}"):
        logging.info("Blob: %s", blob.name)
        with download_gcp_blob_to_stream(GCP_BUCKET, blob.name, io.BytesIO()) as f:
            for line in f:
                obj = json.loads(line)
                cluster_id = obj["repo_name"]
                cluster_id_to_repo[cluster_id].update(obj["cluster"])
                for repo in obj["cluster"]:
                    repo_to_cluster_id[repo].add(cluster_id)

    for repo, cluster_ids in sorted(
        repo_to_cluster_id.items(), key=lambda x: len(x[1]), reverse=True
    )[0:10]:
        if len(cluster_ids) > 1:
            logging.info("Repo: %s, Clusters: %s", repo, len(cluster_ids))


if __name__ == "__main__":
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    for start_date, end_date in COPYCATCH_DATE_CHUNKS:
        find_large_clusters(start_date, end_date)
