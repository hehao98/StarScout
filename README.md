# StarScout

Find suspicious (and possibly faked) GitHub stars at-scale. Please refer to [this paper preprint](https://arxiv.org/abs/2412.13459) for technical details and our findings:

```
@misc{he202445millionsuspectedfake,
      title={4.5 Million (Suspected) Fake Stars in GitHub: A Growing Spiral of Popularity Contests, Scams, and Malware}, 
      author={Hao He and Haoqin Yang and Philipp Burckhardt and Alexandros Kapravelos and Bogdan Vasilescu and Christian Kästner},
      year={2024},
      eprint={2412.13459},
      archivePrefix={arXiv},
      primaryClass={cs.CR},
      url={https://arxiv.org/abs/2412.13459}, 
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

    If you only want to run fake star detector, you only need to setup the MongoDB URL and Google Cloud related fields (remember to configure Google Cloud [credentials](https://cloud.google.com/bigquery/docs/authentication#client-libs)). The remaining configurations are for experimental and research scripts.

## Running the Detector

The detector employs two heuristics: a low-activity heuristic and a lockstep heuristic. Their parameters are defined in [scripts/__init__.py](scripts/__init__.py). Notably, you may wnat to change the `END_DATE` and `COPYCATCH_DATE_CHUNKS` to include latest data. The CopyCatch algorithm for the lockstep heuristic works on half-year chunks as specified in `COPYCATCH_DATE_CHUNKS` and a new chunk should be manually added on a quarterly basis (e.g., add `("240401", "241001")` after Oct 2024).

To run the low-acivity heuristic, use:

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

Currently, StarScout runs on a quarterly basis and we dump the data from each quarter into `data/{END_DATE}`. We have a few utility code to generate combined data and repositories with suspected fake star campaigns in `scripts/analysis/data.py`. Other data files in the `data/` folder are updated on-demand by the paper authors.

**Disclaimer.** *As we discussed in Section 3.4 and 3.5 in our paper, the resulting dataset are only repositories and users with suspected fake stars. The individual repositories and users in our dataset may be false positives. The main purpose of our dataset is for statistical analyses (which tolerates noises reasonably well), not for publicly shaming individual repositories. If you intend to publish subsequent work based on our dataset, please be aware of this limitation and its ethical implications.*

## The Measurement Study

All the scripts and results from our measurement study can be found in the Jupyter Notebooks. Currently, the notebook depends on a MongoDB database which stores a large amount of data. We are actively working on it and release a public version in the future.
