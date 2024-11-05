import sys
import json
import logging
import pymongo
import pymongo.errors
import itertools

from scripts import MONGO_URL


def main():
    logging.basicConfig(
        format="%(asctime)s (PID %(process)d) [%(levelname)s] %(filename)s:%(lineno)d %(message)s",
        level=logging.INFO,
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    client = pymongo.MongoClient(MONGO_URL)
    db = client["fake_stars"]

    with open("data/240701/fake_stars.clustered_stars.json", "r") as file:
        for lines in itertools.batched(file, 10000):
            data = [json.loads(line) for line in lines]
            data = [{k: v for k, v in d.items() if k != "_id"} for d in data]
            try:
                db["clustered_stars"].insert_many(data, ordered=False)
            except pymongo.errors.BulkWriteError as e:
                n_error, n_inserted = (
                    len(e.details["writeErrors"]),
                    e.details["nInserted"],
                )
                logging.info(f"Error in {n_error}, {n_inserted} inserted")


if __name__ == "__main__":

    main()
