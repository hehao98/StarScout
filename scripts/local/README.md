# Local Execution

This module provides a local alternative to the BigQuery-based detection pipeline. It uses [DuckDB](https://duckdb.org/) to query Parquet files directly, eliminating the need for Google Cloud services.

## Live Repository Star History

To inspect a current public repository without downloading GitHub Archive data:

```bash
python3 scripts/local/star_history.py owner/repo
python3 scripts/local/star_history.py https://github.com/owner/repo --anonymous
python3 scripts/local/star_history.py owner/repo --max-history-pages 4
```

This standalone command needs only Python 3.10+ and its standard library.
Invoke it by file path, rather than `python -m scripts.local.star_history`, to
avoid importing the existing pipeline's optional dependencies. It uses an
existing authenticated GitHub CLI (`gh`) session when available, or anonymous
public API access otherwise. `--anonymous` disables GitHub CLI use. It never
prints or saves tokens, queries stargazer identities, or requests extra scopes.

The JSON output contains current repository metadata, source URLs, weekly
history, peak days, the densest seven-day window, and descriptive temporal
spike flags. Pagination defaults to 12 pages of at most 30 weeks each; the
configurable limit is 1-100 pages. Exit code `0` means the returned history
covers the creation week through the retrieval week; `2` means unavailable,
invalid, restricted, rate-limited, or partial data. Partial results remain in
the JSON with errors. This coverage indicator is not an authenticity verdict.

The temporal rule flags a complete observed day with at least 100 stars and
at least five times its preceding 28-calendar-day mean. This is a descriptive
screening threshold, **not a validated fraud classifier**. The first 28 observed
days have no prior baseline, and the current incomplete day is not scored.
Launch-period peaks are still reported. Missing weeks are never filled with
zeros, and a page limit is never presented as a complete history.

Interpretation limitations:

- Publicity, launches, and releases can cause legitimate concentration.
- GitHub's calendar boundaries need not align with UTC; date labels are approximate.
- The API history and current star count are not assumed to have identical semantics.
- Account age, low activity, and cross-repository lockstep are not evaluated.
  This tool does not replace either detector or reproduce the paper's findings.
- GitHub restricts individual stargazer access; an unavailable endpoint is
  reported, not bypassed.

Sources: [GitHub aggregate-history API](https://docs.github.com/en/rest/activity/starring#get-repository-star-history)
and [stargazer access restrictions](https://github.blog/changelog/2026-06-30-upcoming-access-restrictions-to-public-api-endpoints-and-ui-views/).

Run its deterministic offline tests without pipeline dependencies:

```bash
python3 -B -m unittest discover -s scripts/local -p test_star_history.py -v
```

## Quick Start

The fastest way to run the detection pipeline locally:

```bash
# Run detection on new data since last run (handles everything automatically)
./scripts/local/example_run.sh new

# Or choose a specific mode:
./scripts/local/example_run.sh quick     # 1 week test (~11 GB total)
./scripts/local/example_run.sh month     # 1 month validation (~45 GB total)
./scripts/local/example_run.sh year      # 1 year production (~300 GB total)
./scripts/local/example_run.sh research  # Replicate original paper (~700 GB total)
./scripts/local/example_run.sh full      # All data to today (~750+ GB total)
```

The script automatically:
- Creates a Python virtual environment
- Installs dependencies
- Downloads and converts GitHub Archive data to Parquet
- Runs the low-activity detector
- Runs the CopyCatch/lockstep detector (except in `quick` mode)
- Cleans up temp files

## Motivation

The original BigQuery approach has limitations:
- **Cost**: ~$6.25/TB, requiring ~$125-375+ per full execution
- **Time limits**: BigQuery has a 6-hour query timeout that large datasets can exceed
- **Dependencies**: Requires Google Cloud account, credentials, and billing

Local execution trades cloud costs for disk space and compute time, allowing the project to be more reproducible. 

## Requirements

- **Python 3.12+**
- **Disk space**: ~6 TB for full GitHub Archive (2011-present), or less for partial ranges
- **Temp space**: 200-500 GB for DuckDB spill files during large queries (see below)
- **RAM**: 16+ GB recommended (DuckDB spills to disk for larger-than-memory queries)
- **No cloud credentials required**

### Temp Space for Large Queries

DuckDB requires significant temporary disk space for aggregation queries on large datasets. Even with query optimizations, expect:

| Mode | Data Size | Temp Space Needed |
|------|-----------|-------------------|
| quick | ~1 GB | ~10 GB |
| month | ~5 GB | ~40 GB |
| year | ~47 GB | ~200-300 GB |
| research/full | ~200+ GB | ~500+ GB |

If your primary disk lacks space, symlink `data/_duckdb_temp` to external storage:

```bash
# Example: Use an external SSD/M.2 drive (faster than NAS)
mkdir -p /Volumes/MyExternalDrive/duckdb_temp
rm -rf data/_duckdb_temp
ln -sf /Volumes/MyExternalDrive/duckdb_temp data/_duckdb_temp

# Or use NAS if speed is less critical
ln -sf /Volumes/nas/duckdb_temp data/_duckdb_temp
```

An external M.2/SSD drive is recommended over NAS for temp storage due to the random I/O patterns of database spill files.

### GitHub API Enrichment (Optional)

To match the original paper's output, you can enable GitHub API enrichment which adds:
- `repo_id`: GitHub's GraphQL node ID for each repository
- `n_stars_latest`: Current star count (to compare against detected fake stars)

**Setup:**

1. Create a GitHub Personal Access Token at https://github.com/settings/tokens
   - Select scope: `public_repo` (read-only access)
   - Copy the token (starts with `ghp_`)

2. Create `secrets.yaml` in the project root:
   ```yaml
   github_tokens:
     - token: ghp_your_token_here
     # Add more tokens for rate limit rotation (5000 req/hr each)
     # - token: ghp_another_token
   ```

3. Enable enrichment when running:
   ```bash
   ENRICH_GITHUB=true ./scripts/local/example_run.sh year
   ```

## Data Flow

```
GitHub Archive (gharchive.org)
    ↓ download hourly .json.gz files
Parquet files with Zstd compression
    /data/gharchive/year=YYYY/month=MM/day=DD/HH.parquet
    ↓ DuckDB queries with partition pruning
Detection results
    /data/_checkpoints/*.parquet (intermediate)
    /data/{YYMMDD}/*.csv (final output)
```

## Setup

### Local Dependencies

The local execution module has its own minimal requirements file at `scripts/local/requirements.txt`. This avoids installing heavy dependencies (Dagster, Google Cloud libraries, etc.) that are only needed for the BigQuery pipeline.

**Option 1: Using the example script (recommended)**

The `example_run.sh` script automatically creates a virtual environment and installs dependencies:

```bash
./scripts/local/example_run.sh quick
```

**Option 2: Manual installation**

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install local-only dependencies (minimal)
pip install -r scripts/local/requirements.txt
```

The local requirements include:
- `pandas`, `pyyaml`, `tqdm`, `requests` - Core utilities
- `duckdb`, `pyarrow` - Local query engine and Parquet support
- `pymongo` - MongoDB export (optional, fails gracefully)
- `strudel.scraper` - GitHub API enrichment (optional, fails gracefully)

### Optional: secrets.yaml

Create `secrets.yaml` in the project root (can be empty if only using local execution):

```yaml
# Empty file is fine for local-only execution
```

### Ingest GitHub Archive Data

```bash
# Backfill a date range (downloads and converts to Parquet)
python -m scripts.local.ingest.pipeline --backfill 2025-01-01 2025-01-18

# Or incremental update (fetches recent missing hours)
python -m scripts.local.ingest.pipeline --incremental
```

Data is stored in `data/gharchive/` by default (~50 MB/hour compressed).

## Running the Detectors

### Low-Activity Heuristic

Identifies accounts with minimal GitHub activity (single-day activity, ≤2 actions):

```bash
python -m scripts.local.simple_detector \
    --start-date 250101 \
    --end-date 260118 \
    --data-path data/gharchive \
    --skip-mongodb
```

Output: `data/{end_date}/fake_stars_low_activity_repos.csv`

### Lockstep Heuristic (CopyCatch)

Detects coordinated starring behavior using clustering:

```bash
# Run the detection
python -m scripts.local.copycatch --run \
    --data-path data/gharchive \
    --skip-mongodb

# Export results after completion
python -m scripts.local.copycatch --export \
    --skip-mongodb
```

Output: `data/{end_date}/fake_stars_clustered_repos.csv`

## Configuration

### DuckDB Settings

Environment variables (or edit `scripts/local/__init__.py`):

| Variable | Default | Description |
|----------|---------|-------------|
| `DUCKDB_MEMORY_LIMIT` | `16GB` | Max RAM for DuckDB |
| `DUCKDB_TEMP_DIRECTORY` | auto | Spill-to-disk location |
| `DUCKDB_THREADS` | `4` | Parallel threads |

For large datasets, ensure temp directory has sufficient space (can exceed 500 GB for full scans).

### Date Chunks

CopyCatch processes data in 6-month overlapping chunks defined in `scripts/__init__.py`. Add new chunks as data becomes available:

```python
COPYCATCH_DATE_CHUNKS = [
    # ... existing chunks ...
    ("250101", "250701"),
    ("250401", "251001"),
]
```

## Storage Location

For large datasets, you may want to store data on external/network storage:

```bash
# Symlink to external storage
ln -sf /path/to/external/storage/gharchive data/gharchive
```

## Performance Notes

- **First run**: Expect several hours for the low-activity heuristic on a full year of data
- **CopyCatch**: May take days for full historical analysis (processes each chunk iteratively)
- **Disk I/O**: SSD recommended; NAS/SMB works but is slower
- **Temp I/O**: External M.2/SSD strongly recommended for `data/_duckdb_temp` - random I/O patterns make NAS significantly slower
- **Memory**: DuckDB efficiently spills to disk, but more RAM = faster queries

## Comparison with BigQuery

| Aspect | BigQuery | Local |
|--------|----------|-------|
| Cost | $125-375+ per run | Electricity only |
| Speed | Minutes (parallel) | Hours (sequential) |
| Data freshness | Real-time | Manual ingestion |
| Setup | Cloud credentials | Disk space |
| Query limits | 6-hour timeout | None |

## Custom Queries

You can run ad-hoc queries against the local Parquet files using DuckDB's CLI or Python.

### DuckDB CLI

```bash
# Install DuckDB CLI
brew install duckdb          # macOS
# apt install duckdb         # Debian/Ubuntu
# choco install duckdb       # Windows
# Or download from: https://duckdb.org/docs/installation/

# Start interactive session (from project root)
cd /path/to/StarScout
duckdb
```

Once in the DuckDB shell, you can run SQL queries directly:

```sql
-- Find most starred repos in January 2025
SELECT
    repo_name,
    COUNT(*) as star_count
FROM read_parquet('data/gharchive/**/*.parquet', hive_partitioning=true)
WHERE is_star = true
  AND created_at >= '2025-01-01'
  AND created_at < '2025-02-01'
GROUP BY repo_name
ORDER BY star_count DESC
LIMIT 20;

-- Find users who starred the most repos
SELECT
    actor_login,
    COUNT(DISTINCT repo_name) as repos_starred
FROM read_parquet('data/gharchive/**/*.parquet', hive_partitioning=true)
WHERE is_star = true
GROUP BY actor_login
ORDER BY repos_starred DESC
LIMIT 20;

-- Export results to CSV
COPY (
    SELECT repo_name, COUNT(*) as stars
    FROM read_parquet('data/gharchive/**/*.parquet', hive_partitioning=true)
    WHERE is_star = true
    GROUP BY repo_name
    HAVING COUNT(*) >= 100
) TO 'my_results.csv' (HEADER, DELIMITER ',');
```

One-liner queries from the command line:

```bash
# Quick query without entering interactive mode
duckdb -c "SELECT COUNT(*) FROM read_parquet('data/gharchive/**/*.parquet', hive_partitioning=true) WHERE is_star"

# Output to CSV directly
duckdb -csv -c "SELECT repo_name, COUNT(*) as stars FROM read_parquet('data/gharchive/**/*.parquet', hive_partitioning=true) WHERE is_star GROUP BY 1 ORDER BY 2 DESC LIMIT 100" > top_repos.csv

# For large queries, increase memory and set temp directory
duckdb -c "SET memory_limit='8GB'; SET temp_directory='data/_duckdb_temp'; SELECT ..."
```

### Python

```python
import duckdb

con = duckdb.connect()
con.execute("SET memory_limit = '8GB'")
con.execute("SET temp_directory = 'data/_duckdb_temp'")

# Find most starred repos in January 2025
df = con.execute("""
    SELECT
        repo_name,
        COUNT(*) as star_count,
        COUNT(DISTINCT actor_login) as unique_stargazers
    FROM read_parquet('data/gharchive/**/*.parquet', hive_partitioning=true)
    WHERE is_star = true
      AND created_at >= '2025-01-01'
      AND created_at < '2025-02-01'
    GROUP BY repo_name
    ORDER BY star_count DESC
    LIMIT 100
""").fetchdf()

print(df)
```

### Parquet Schema

The ingested Parquet files have this schema:

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGINT | GitHub event ID |
| `type` | VARCHAR | Event type (WatchEvent, PushEvent, etc.) |
| `created_at` | TIMESTAMP | Event timestamp |
| `actor_id` | BIGINT | User's GitHub ID |
| `actor_login` | VARCHAR | Username |
| `repo_id` | BIGINT | Repository's GitHub ID |
| `repo_name` | VARCHAR | Repository name (owner/repo) |
| `org_id` | BIGINT | Organization ID (nullable) |
| `org_login` | VARCHAR | Organization name (nullable) |
| `is_star` | BOOLEAN | True if WatchEvent with action=started |

### Partition Structure

Files are organized using Hive-style partitioning:
```
data/gharchive/
  year=2025/
    month=01/
      day=15/
        00.parquet
        01.parquet
        ...
        23.parquet
```

DuckDB automatically prunes partitions when filtering on `created_at`, making date-range queries efficient.
