import os
import requests
import time
import yaml
import pandas as pd
import urllib.request
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta
import pymongo
import logging
import sys
from multiprocessing import Pool, cpu_count

with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)


def get_downloads(pkg, sampleDf, startDate):
    global SECRETS
    result = []
    try:
        url = "https://registry.npmjs.org/" + pkg
        with urllib.request.urlopen(url) as response:
            data = json.load(response)
            create_time = data['time']['created']
        dt = datetime.strptime(create_time, "%Y-%m-%dT%H:%M:%S.%fZ")

        now = datetime.now()
        current_month = now.strftime("%Y-%m")

        dates = []
        current = max(dt, startDate)

        while current.strftime("%Y-%m") < current_month:
            dates.append(current.strftime("%Y-%m"))
            current += relativedelta(months=1)

        for date in dates:
            start_date = date + "-01"
            end_date = (datetime.strptime(start_date, "%Y-%m-%d") +
                        relativedelta(months=1) - relativedelta(days=1)).strftime("%Y-%m-%d")
            query = f"https://api.npmjs.org/downloads/point/{start_date}:{end_date}/{pkg}"
            response = requests.get(query).json()
            package = response["package"]
            month = datetime.strptime(response["start"], "%Y-%m-%d")
            downloads = response["downloads"]
            github = sampleDf.loc[sampleDf['package']
                                  == package, 'github'].values[0]
            result.append(
                {
                    "package": package,
                    "month": month,
                    "downloads": downloads,
                    "github": github
                }
            )
        return result
    except Exception as ex:
        logging.error(f"Error processing package {pkg}: {ex}")
        logging.info(f"Sleeping...")
        time.sleep(60)
        return ["skip"]


def process_pkg(pkg):
    global SECRETS
    client = pymongo.MongoClient(SECRETS["mongo_url"])
    downloads = client.fake_stars.downloads

    df = pd.read_csv("data/samples.csv")

    latest_record = downloads.find_one(
        {"package": pkg}, sort=[("month", pymongo.DESCENDING)]
    )

    if latest_record:
        startDate = latest_record["month"] + relativedelta(months=1)
    else:
        startDate = datetime(2015, 1, 1)

    result = get_downloads(pkg, df, startDate)
    if result == []:
        logging.info("nothing to add for " + pkg)
    elif result[0] == "skip":
        logging.info("skip " + pkg + " due to exception")
    else:
        downloads.insert_many(result)
        logging.info("finish updating for " + pkg)
    client.close()


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logging.info("Start!")
    df = pd.read_csv("data/samples.csv")
    pkg_names = set(df['package'])

    pkgs_nonscoped, pkgs_scoped = [], []
    for pkg in pkg_names:
        if pkg is None:
            continue
        if pkg.startswith("@") and "/" in pkg:
            continue
        else:
            pkgs_nonscoped.append(pkg)

    # Combine scoped and nonscoped packages
    all_pkgs = pkgs_scoped + pkgs_nonscoped

    with Pool(8) as pool:
        pool.map(process_pkg, reversed(all_pkgs))

    logging.info("Done!")


if __name__ == "__main__":
    main()
