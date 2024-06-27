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

2. Configuring Secrets in `secrets.yaml`

    ```yaml
    mongo_url: "your_mongo_url"
    github_tokens:
      - token: "your_github_token"
        name: "your_github_username"
      - token: "your_github_token"
        name: "your_github_username"
    ```

## Getting Data

1. Get stargazer metadata from GitHub:

    ```shell
    mkdir logs
    nohup python get_samples_stars.py > logs/get_samples_stars.log &
    ```

    This script will read from `data/samples.csv` and write to `fake_stars.stars` collection in MongoDB. It is idempotent and can incrementally collect new data based on existing data in the collection.

2. Get obvious fake stars (using the [Dagster.io](https://dagster.io/blog/fake-stars) approach):

    ```shell
    nohup python detect_fake_star_simple.py > logs/detect_fake_star_simple.log &
    ```

    The script will read from `fake_stars.stars` collection in MongoDB and write to `data/fake_stars_obvious.csv`.

3. Get non-obvious fake stars (using the [Dagster.io](https://dagster.io/blog/fake-stars) approach):

    ```shell
    nohup python detect_fake_star_complex.py > logs/detect_fake_star_complex.log &
    ```
