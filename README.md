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
    mongo_url: "your_mongo_url"
    github_tokens:
      - token: "your_github_token"
        name: "your_github_username"
      - token: "your_github_token"
        name: "your_github_username"
    ```

3. Configure Google BigQuery [credentials](https://cloud.google.com/bigquery/docs/authentication#client-libs).

## Getting Data

1. Get stargazer metadata from GitHub:

    ```shell
    mkdir logs
    # Determine number of jobs based on your tokens
    nohup python get_samples_stars.py -j 32 > logs/get_samples_stars.log & 
    ```

    This script will read from `data/samples.csv` and write to `fake_stars.stars` collection in MongoDB. It is idempotent and can incrementally collect new data based on existing data in the collection. Use the `-j [number of jobs]` option to enable multiprocessing.

2. Get obvious fake stars (using the [Dagster.io](https://dagster.io/blog/fake-stars) approach):

    ```shell
    nohup python detect_fake_star_simple.py > logs/detect_fake_star_simple.log &
    ```

    The script will read from `fake_stars.stars` collection in MongoDB and write to `data/fake_stars_obvious.csv`.

3. Get non-obvious fake stars (using the [Dagster.io](https://dagster.io/blog/fake-stars) approach):

    ```shell
    nohup python detect_fake_star_complex.py > logs/detect_fake_star_complex.log &
    ```
