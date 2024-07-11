import yaml

with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)

MONGO_URL: str = SECRETS["mongo_url"]
GITHUB_TOKENS: list[str] = [x["token"] for x in SECRETS["github_tokens"]]
BIGQUERY_PROJECT: str = SECRETS["bigquery_project"]
BIGQUERY_DATASET: str = SECRETS["bigquery_dataset"]
GOOGLE_CLOUD_BUCKET: str = SECRETS["google_cloud_bucket"]
