# StarScout

This repository contains the source code of StarScout, a tool to find suspicious (and possibly faked) GitHub stars at-scale. It also contains data and scripts to replicate results from the following paper:

> Hao He, Haoqin Yang, Philipp Burckhardt, Alexandros Kapravelos, Bogdan
Vasilescu, and Christian Kästner. 2026. Six Million (Suspected) Fake Stars
on GitHub: A Growing Spiral of Popularity Contests, Spam, and Malware.
In 2026 IEEE/ACM 48th International Conference on Software Engineering
(ICSE ’26), April 12–18, 2026, Rio de Janeiro, Brazil. ACM, New York, NY,
USA, 13 pages. https://doi.org/10.1145/3744916.3764531

```bibtex
@inproceedings{he2026six,
    title={Six Million (Suspected) Fake Stars on GitHub: A Growing Spiral of Popularity Contests, Spam, and Malware},
    author={He, Hao and Yang, Haoqin and Burckhardt, Philipp and Kapravelos, Alexandros and Vasilescu, Bogdan and K\"{a}stner, Christian},
    booktitle={2026 IEEE/ACM 48th International Conference on Software Engineering (ICSE '26)},
    year={2026},
    doi={10.1145/3744916.3764531},
    url={https://doi.org/10.1145/3744916.3764531}
    publisher={{ACM}},
}
```

## Setup

The scripts works with Python 3.12 and has only been tested on Ubuntu 22.04.

1. Setup Python env. For example (using Anaconda):

    ```shell
    conda create -n fake-star python=3.12
    conda activate fake-star
    pip install -r requirements.txt
    ```

2. Configure secrets in `secrets.yaml`:

    ```yaml
    mongo_url: your_mongo_url
    github_tokens:
      - token: your_github_token
        name: your_github_username
      - token: your_github_token
        name: your_github_username
    bigquery_project: your_project_name
    bigquery_dataset: your_table_name
    google_cloud_bucket: your_google_cloud_bucket_name
    npm_follower_postgres: your_postgresql_that_stores_npm_follower_dataset
    virus_total_api_key: your_virus_total_api_key
    ```

    If you only want to replicate the Jupyter Notebooks, you only need to setup the MongoDB URL.

    If you only want to run fake star detector, you only need to setup the MongoDB URL and Google Cloud related fields (remember to configure Google Cloud [credentials](https://cloud.google.com/bigquery/docs/authentication#client-libs)). The remaining configurations are for experimental and research scripts.

## Inspecting Current Repositories

For a lightweight look at a repository created after the published dataset
cutoffs, use the live aggregate star-history tool:

```shell
python3 scripts/local/star_history.py owner/repo
```

This standalone command uses only the Python standard library and GitHub's
public aggregate-history API; it does not require the setup above, MongoDB,
BigQuery, DuckDB, or a GitHub Archive download. It reports temporal concentration
and explicit coverage limits, **not a fake-star verdict**, and does not execute
the low-activity or lockstep heuristics. See
[live star-history usage and limitations](scripts/local/README.md#live-repository-star-history)
for details.

## Running the Detector

The detector employs two heuristics: a low-activity heuristic and a lockstep heuristic. Their parameters are defined in [scripts/__init__.py](scripts/__init__.py). Notably, you may want to change the `END_DATE` and `COPYCATCH_DATE_CHUNKS` to include latest data. The CopyCatch algorithm for the lockstep heuristic works on half-year chunks as specified in `COPYCATCH_DATE_CHUNKS` and a new chunk should be manually added on a quarterly basis (e.g., add `("240401", "241001")` after Oct 2024).

### Local Execution (Alternative)

For cost-effective local execution without Google Cloud, see **[scripts/local/README.md](scripts/local/README.md)**. This approach uses DuckDB to query Parquet files directly, eliminating BigQuery costs and avoiding the 6-hour query timeout limit. Significant local storage is needed, however.

### BigQuery Execution (Original)

To run the low-activity heuristic, use:

```shell
python -m scripts.dagster.simple_detector_bigquery
```

It will run the low-activity heuristic starting from `scripts.START_DATE` to `scripts.END_DATE` on Google BigQuery, and write the results to MongoDB. Expect it to read >= 20TB of data ($6.25/TB on the default billing). The BigQuery quries won't take more than a few minutes, but the script will also fetch GitHub API to collect certain information. Expect it to be slower and output a lot of error messages (because many of the fake star repositories have been deleted). Once this script finishes, you should be able to see several CSV files in `data/[END_DATE]` and a new collection `fake_stars.low_activity_stars` in the MongoDB instance as specificed my `scripts.MONGODB_URL`.

To run the lockstep heuristic, first use:

```shell
python -m scripts.copycatch.bigquery --run
```

Allow it a week to finish all iterations and expect it to read >= 40TB of data. You can use `nohup` to put it as a background process. After a week, you can run the following command to collect the results into MongoDB and local CSV files:

```shell
# Write BigQuery Tables to Google Cloud Storage
# Then, export from Google Cloud Storage to MongoDB and local CSV files
python -m scripts.copycatch.bigquery --export
```

After they finish, you should be able to see CSV files in the `data/{END_DATE}` folder.

## The (Suspected) Fake Stars Dataset

StarScout was executed in three different time cutoffs: 240701, 241001, 250101. The results from each run are available in the `data/{240701, 241001, 250101}` folders. Since the tool itself have evolved significantly between the runs, it is generally tricky to merge the data from three quarters, so we provide a bunch of data loading utilities in the `scripts/analysis/data.py` module. The Jupyter Notebooks from the measurement study could also serve as examples regarding how to consume and repurpose the dataset in our study.

**Disclaimer.** *As we discussed in Section 3.4 and 3.5 in our paper, the resulting dataset are only repositories and users with suspected fake stars. The individual repositories and users in our dataset may be false positives. The main purpose of our dataset is for statistical analyses (which tolerates noises reasonably well), not for publicly shaming individual repositories. If you intend to publish subsequent work based on our dataset, please be aware of this limitation and its ethical implications.*

## The Measurement Study

All the scripts and results from our measurement study can be found in the Jupyter Notebooks. The notebook names should be mostly self-explanatory. It is worth noting that some of the notebook needs a MongoDB database with all the detailed detection results from StarScout, in order to correctly execute. The dataset dump is available at [Zenodo](https://doi.org/10.5281/zenodo.17009694) as gzip files and can be recovered using the `mongorestore` tool like this:

```
mongorestore --gzip --db fake_stars [your-downloaded-file-path]/mongodb/fake_stars/
```
