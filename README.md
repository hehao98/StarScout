# Fake-Star-Detector

This is a project to detect fake stars in popular github repos

## Dev Setup

These scripts have only been tested in Ubuntu.

1. Setup Python env. For example (using Anaconda):

    ```shell
    conda create -n fake-star python=3.12
    conda activate fake-star
    pip install -r requirements.txt
    ```

2. Configure Secrets in `secrets.yaml`:

    ```yaml
    mongo_url: your_mongo_url
    github_tokens:
      - token: your_github_token
        name: your_github_username
      - token: your_github_token
        name: your_github_username
    # The Google Bigquery dataset to write to for complex detector
    bigquery_project: your_project_name
    bigquery_dataset: your_table_name
    google_cloud_bucket: your_google_cloud_bucket_name
    ```

3. Configure Google BigQuery [credentials](https://cloud.google.com/bigquery/docs/authentication#client-libs).

## Getting Data

1. Get stargazer metadata from GitHub:

    ```shell
    mkdir logs
    nohup python -m scripts.get_samples_stars -j 32 > logs/get_samples_stars.log & 
    ```

    This script will read from `data/samples.csv` and write to `fake_stars.stars` collection in MongoDB. It is idempotent and can incrementally collect new data based on existing data in the collection. Use the `-j [number of jobs]` option to enable multiprocessing.

2. Get obvious fake stars (using the [Dagster.io](https://dagster.io/blog/fake-stars) approach):

    ```shell
    nohup python -m scripts.dagster.simple_detector > logs/simple_detector.log &
    ```

    The script will read from `fake_stars.stars` collection in MongoDB and write to `data/fake_stars_obvious_users.csv` and `data/fake_stars_obvious_repos.csv`.

3. Get non-obvious fake stars (using the [Dagster.io](https://dagster.io/blog/fake-stars) approach):

    ```shell
    python -m scripts.dagster.complex_detector --init
    ```

    As Google BigQuery can read a huge amount of data and cost you money, this script is designed to run interactively and you will need to confirm the cost before the most expensive bulk query is sent. Then, the script will compute fake stars per repo and write results to `gs://{{google_cloud_bucket}}/fake-stars/{{repo}}/{{table}}*.json`. Finally, it will collect all the Google Cloud Storage files and aggreggate fake star info into local files.
