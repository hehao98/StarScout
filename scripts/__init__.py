import yaml

from scripts.copycatch.iterative import CopyCatchParams


with open("secrets.yaml", "r") as f:
    SECRETS = yaml.safe_load(f)

# Secrets
MONGO_URL: str = SECRETS["mongo_url"]
GITHUB_TOKENS: list[str] = [x["token"] for x in SECRETS["github_tokens"]]
BIGQUERY_PROJECT: str = SECRETS["bigquery_project"]
BIGQUERY_DATASET: str = SECRETS["bigquery_dataset"]
GOOGLE_CLOUD_BUCKET: str = SECRETS["google_cloud_bucket"]
NPM_FOLLOWER_POSTGRES: str = SECRETS["npm_follower_postgres"]
VIRUS_TOTAL_API_KEY: str = SECRETS["virus_total_api_key"]

# Parameters for running experiments
START_DATE: str = "190701"
END_DATE: str = "240701"
MIN_STARS_LOW_ACTIVITY: int = 50
MIN_STARS_COPYCATCH_SEED: int = 50
COPYCATCH_NUM_ITERATIONS: int = 10
COPYCATCH_PARAMS = CopyCatchParams(
    delta_t=15 * 24 * 60 * 60,
    n=50,
    m=10,
    rho=0.5,
    beta=2,
)
COPYCATCH_DATE_CHUNKS = [
    ("190701", "200101"),
    ("191001", "200401"),
    ("200101", "200701"),
    ("200401", "201001"),
    ("200701", "210101"),
    ("201001", "210401"),
    ("210101", "210701"),
    ("210401", "211001"),
    ("210701", "220101"),
    ("211001", "220401"),
    ("220101", "220701"),
    ("220401", "221001"),
    ("220701", "230101"),
    ("221001", "230401"),
    ("230101", "230701"),
    ("230401", "231001"),
    ("230701", "240101"),
    ("231001", "240401"),
    ("240101", "240701"),
]
