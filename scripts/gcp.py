# Wrappers of Google Cloud Platform APIs

import io
import logging

from pprint import pformat
from google.cloud import storage
from google.cloud import bigquery


def yes_or_no(question: str) -> bool:
    while True:
        reply = str(input(question + " (y/n): ")).lower().strip()
        if reply[0] == "y":
            return True
        if reply[0] == "n":
            return False


def check_gcp_blob_exists(bucket_name: str, path: str) -> bool:
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    return storage.Blob(bucket=bucket, name=path).exists()


def list_gcp_blobs(buckt_name: str, path: str) -> list[storage.Blob]:
    client = storage.Client()
    return list(client.list_blobs(buckt_name, prefix=path))


def download_gcp_blob_to_stream(
    bucket_name: str, path: str, file_obj: io.BytesIO
) -> io.BytesIO:
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = storage.Blob(bucket=bucket, name=path)
    blob.download_to_file(file_obj)
    file_obj.seek(0)
    logging.info("Downloaded %s to file-like object", path)
    return file_obj


def check_bigquery_table_exists(
    project_id: str, dataset_id: str, table_id: str
) -> bool:
    client = bigquery.Client()
    dataset_ref = client.dataset(dataset_id, project=project_id)
    table_ref = dataset_ref.table(table_id)
    try:
        client.get_table(table_ref)
        return True
    except:
        return False


def process_bigquery(
    project_id: str,
    dataset_id: str,
    interactive: bool,
    query_file: str,
    output_table_id: str,
    params: list = [],
):
    with open(query_file, "r") as f:
        query = f.read()
        # This is an unfortunate workaround because Google BigQuery does
        # not accept parameters in table names. Do not use in production
        query = query.replace("@project_id", project_id)
        query = query.replace("@dataset_id", dataset_id)

    client = bigquery.Client()
    job_config = bigquery.QueryJobConfig(dry_run=True, query_parameters=params)
    logging.info("Sending query:\n%s\nwith params:\n%s", query, pformat(params))

    dry_run_job = client.query(query, job_config=job_config)
    logging.info("Query cost: %f GB", dry_run_job.total_bytes_processed / 1024**3)

    if not interactive or yes_or_no("Proceed?"):
        job_config.dry_run = False
        job_config.write_disposition = bigquery.WriteDisposition.WRITE_TRUNCATE
        job_config.destination = ".".join([project_id, dataset_id, output_table_id])
        actual_job = client.query(query, job_config=job_config)
        actual_job.result()
        logging.info("Results written to destination %s", job_config.destination)
    else:
        logging.info("Aborting")
