"""
Read live aggregate star history for one public GitHub repository.

Usage:
    python scripts/local/star_history.py owner/repo
    python scripts/local/star_history.py https://github.com/owner/repo --anonymous

This describes temporal concentration, not fake-star probabilities. It does not
run the low-activity or CopyCatch detectors or collect stargazer identities.
"""

import argparse
import http.client
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


API = "https://api.github.com"
DOCS = "https://docs.github.com/en/rest/activity/starring#get-repository-star-history"
MAX_RESPONSE_BYTES = 1024 * 1024
READ_ERRORS = (
    OSError, ValueError, OverflowError, http.client.HTTPException,
    subprocess.TimeoutExpired,
)


def normalize_repo(value):
    value = value.strip()
    if "://" in value:
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != "github.com"
            or parsed.query
            or parsed.fragment
        ):
            raise argparse.ArgumentTypeError("Use https://github.com/owner/repo.")
        value = parsed.path.strip("/")
    if value.endswith(".git"):
        value = value[:-4]
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value)
        or value.split("/")[-1] in (".", "..")
    ):
        raise argparse.ArgumentTypeError("Expected a public GitHub owner/repo.")
    return value


class GitHubAPIError(ValueError):
    def __init__(self, status, headers):
        self.status = status
        self.rate_limited = status == 429 or (
            status == 403 and headers.get("x-ratelimit-remaining") == "0"
        )
        if self.rate_limited:
            detail = "rate limited"
        elif status in (401, 403, 404):
            detail = "unavailable or access restricted"
        else:
            detail = "request failed"
        super().__init__(
            f"GitHub HTTP {status}: {detail}; "
            f"retry-after={headers.get('retry-after', 'unspecified')}; "
            f"reset-epoch={headers.get('x-ratelimit-reset', 'unspecified')}"
        )


class GitHubClient:
    def __init__(self, anonymous=False):
        self.gh = None if anonymous else shutil.which("gh")
        if self.gh:
            status = subprocess.run(
                [self.gh, "auth", "status", "--hostname", "github.com"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            if status.returncode:
                self.gh = None

    @property
    def authentication(self):
        return "existing_github_cli_session" if self.gh else "anonymous"

    def get(self, endpoint):
        if not re.fullmatch(
            r"repos/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+"
            r"(/stargazers/history\?per_page=30&page=\d+)?",
            endpoint,
        ):
            raise ValueError("Only repository metadata and star-history GETs are allowed.")
        if self.gh:
            result = subprocess.run(
                [
                    self.gh, "api", "--hostname", "github.com", "--method", "GET",
                    "--include", "-H", "Accept: application/vnd.github+json", endpoint,
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=45,
                env={**os.environ, "GH_PROMPT_DISABLED": "1", "GH_PAGER": "cat"},
            )
            if len(result.stdout) > MAX_RESPONSE_BYTES:
                raise ValueError("GitHub response exceeds 1 MiB.")
            text = result.stdout.decode("utf-8").replace("\r\n", "\n")
            header_text, separator, body = text.partition("\n\n")
            status = re.match(r"HTTP/\S+\s+(\d{3})", header_text)
            if not status or not separator:
                raise ValueError(
                    f"GitHub CLI returned no HTTP response (exit {result.returncode})."
                )
            headers = {
                key.lower(): value.strip()
                for line in header_text.splitlines()[1:] if ":" in line
                for key, value in [line.split(":", 1)]
            }
            code = int(status.group(1))
            if code != 200:
                raise GitHubAPIError(code, headers)
            if result.returncode:
                raise ValueError(
                    f"GitHub CLI failed despite HTTP 200 (exit {result.returncode})."
                )
        else:
            request = urllib.request.Request(
                f"{API}/{endpoint}",
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "StarScout-star-history",
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=40) as response:
                    headers = {
                        key.lower(): value for key, value in response.headers.items()
                    }
                    content = response.read(MAX_RESPONSE_BYTES + 1)
            except urllib.error.HTTPError as exc:
                raise GitHubAPIError(
                    exc.code, {key.lower(): value for key, value in exc.headers.items()}
                ) from exc
            if len(content) > MAX_RESPONSE_BYTES:
                raise ValueError("GitHub response exceeds 1 MiB.")
            body = content.decode("utf-8")
        return json.loads(body), headers


def validate_metadata(metadata):
    fields = (
        "full_name", "private", "created_at", "stargazers_count", "forks_count",
        "pushed_at", "archived", "html_url",
    )
    if not isinstance(metadata, dict) or any(key not in metadata for key in fields):
        raise ValueError("GitHub repository metadata is incomplete.")
    if metadata["private"] is not False:
        raise ValueError("Only public repositories are supported.")
    if not isinstance(metadata["full_name"], str):
        raise ValueError("Invalid canonical repository name.")
    try:
        normalize_repo(metadata["full_name"])
    except argparse.ArgumentTypeError as exc:
        raise ValueError("Invalid canonical repository name.") from exc
    created = metadata["created_at"]
    if not isinstance(created, str):
        raise ValueError("Invalid repository creation date.")
    if datetime.fromisoformat(created.replace("Z", "+00:00")).tzinfo is None:
        raise ValueError("Repository creation date must include a timezone.")
    for key in ("stargazers_count", "forks_count"):
        if type(metadata[key]) is not int or metadata[key] < 0:
            raise ValueError(f"Invalid repository {key}.")
    return {key: metadata[key] for key in fields}


def validate_week(row):
    if not isinstance(row, dict) or not {"week", "total", "days"} <= row.keys():
        raise ValueError("Invalid aggregate-history row.")
    if type(row["week"]) is not int or not 0 <= row["week"] <= 253402300799:
        raise ValueError("Invalid aggregate-history week timestamp.")
    if type(row["total"]) is not int or row["total"] < 0:
        raise ValueError("Invalid weekly star count.")
    days = row["days"]
    if not isinstance(days, list) or len(days) != 7:
        raise ValueError("Aggregate-history weeks must contain seven daily counts.")
    if any(type(count) is not int or count < 0 for count in days):
        raise ValueError("Invalid daily star count.")
    if sum(days) != row["total"]:
        raise ValueError("Daily counts do not reconcile with the weekly total.")
    return {"week": row["week"], "total": row["total"], "days": days}


def summarize(weeks, created_at, as_of):
    created = datetime.fromisoformat(created_at.replace("Z", "+00:00")).date()
    fetched = datetime.fromisoformat(as_of.replace("Z", "+00:00")).date()
    daily = []
    for row in sorted(weeks, key=lambda value: value["week"]):
        start = datetime.fromtimestamp(row["week"], timezone.utc).date()
        for offset, count in enumerate(row["days"]):
            day = start + timedelta(days=offset)
            if day > fetched:
                if count:
                    raise ValueError("Nonzero stars reported after the fetch date.")
                continue
            # Calendar boundaries are source-defined; retain nonzero boundary days.
            if day >= created or count:
                daily.append({"date": day.isoformat(), "stars": count})
    if not daily:
        return {
            "observed_stars": 0, "days_observed": 0, "top_days": [], "spike_days": [],
            "days_eligible_for_spike_rule": 0,
        }
    counts = [day["stars"] for day in daily]
    total = sum(counts)
    top_days = sorted(daily, key=lambda row: (-row["stars"], row["date"]))[:10]
    spikes = []
    eligible = 0
    for index in range(28, len(daily)):
        # Exclude the current incomplete day; require a contiguous 28-day baseline.
        end = datetime.fromisoformat(daily[index]["date"]).date()
        begin = datetime.fromisoformat(daily[index - 28]["date"]).date()
        if end >= fetched or (end - begin).days != 28:
            continue
        eligible += 1
        baseline = statistics.mean(counts[index - 28:index])
        if counts[index] >= max(100, 5 * baseline):
            spikes.append({
                **daily[index],
                "previous_28_day_mean": round(baseline, 3),
                "multiple_of_baseline": (
                    round(counts[index] / baseline, 3) if baseline else None
                ),
            })
    windows = []
    for index in range(6, len(daily)):
        start, end = daily[index - 6]["date"], daily[index]["date"]
        if (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days == 6:
            windows.append({
                "start": start, "end": end, "stars": sum(counts[index - 6:index + 1]),
            })
    peak = max(windows, key=lambda row: row["stars"]) if windows else None
    if peak:
        peak["share_of_observed_history"] = (
            round(peak["stars"] / total, 6) if total else None
        )
    return {
        "observed_stars": total,
        "days_observed": len(daily),
        "start_date_label": daily[0]["date"],
        "end_date_label": daily[-1]["date"],
        "median_daily_stars": statistics.median(counts),
        "top_days": top_days,
        "peak_7_day_window": peak,
        "spike_rule": "At least 100 stars AND 5x prior 28-calendar-day mean; complete days only.",
        "spike_days": spikes,
        "days_eligible_for_spike_rule": eligible,
        "launch_period_note": "First 28 observed days lack a prior baseline and are not scored.",
    }


def analyze(metadata, as_of, max_pages=12, client=None):
    if not 1 <= max_pages <= 100:
        raise ValueError("History page budget must be between 1 and 100.")
    report = {
        "method": "github_aggregate_history_not_low_activity_or_copycatch",
        "outcome": "live_history_unavailable",
        "coverage_complete": False,
        "pages_read": 0,
        "page_budget": max_pages,
        "sources": [],
        "errors": [],
        "individual_account_analysis": {
            "status": "not_run",
            "reason": "This mode uses public aggregates, not restricted stargazer identities.",
            "unavailable": ["account_age", "low_activity", "cross_repository_lockstep"],
        },
        "limitations": [
            "Temporal concentration is descriptive, not proof of purchased or fake stars.",
            "Launches, releases, and publicity can cause legitimate bursts.",
            "Only returned weeks are analyzed; missing weeks are not filled with zeros.",
            "API calendar boundaries need not align with UTC; date labels are approximate.",
            "History totals and current star counts are not assumed to have identical semantics.",
            "No personal stargazer data collected and no original detector executed.",
        ],
        "documentation": DOCS,
    }
    weeks = []
    terminal = False
    try:
        metadata = validate_metadata(metadata)
        fetched = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            raise ValueError("Fetch time must include a timezone.")
        client = client or GitHubClient()
        report["authentication"] = client.authentication
        for page in range(1, max_pages + 1):
            endpoint = (
                f"repos/{metadata['full_name']}/stargazers/history?per_page=30&page={page}"
            )
            report["sources"].append(f"{API}/{endpoint}")
            rows, headers = client.get(endpoint)
            if not isinstance(rows, list) or len(rows) > 30:
                raise ValueError("Expected a history page with at most 30 weeks.")
            page_weeks = [validate_week(row) for row in rows]
            previous = weeks[-1]["week"] if weeks else None
            for row in page_weeks:
                if previous is not None and not 601200 <= previous - row["week"] <= 608400:
                    raise ValueError("Duplicate, missing, or out-of-order history weeks.")
                previous = row["week"]
            weeks.extend(page_weeks)
            report["pages_read"] += 1
            has_next = bool(re.search(r'rel=["\']?next\b', headers.get("link", ""), re.I))
            if not has_next:
                terminal = True
                break
            if not rows:
                raise ValueError("Empty history page unexpectedly advertised a next page.")
        if not terminal:
            report["errors"].append("History page budget reached; older weeks were not read.")
        if weeks:
            oldest = datetime.fromtimestamp(weeks[-1]["week"], timezone.utc)
            newest = datetime.fromtimestamp(weeks[0]["week"], timezone.utc)
            created = datetime.fromisoformat(metadata["created_at"].replace("Z", "+00:00"))
            # One-day tolerance accommodates the API's unspecified calendar timezone.
            spans_creation = oldest - timedelta(days=1) <= created < oldest + timedelta(days=8)
            reaches_present = newest - timedelta(days=1) <= fetched < newest + timedelta(days=8)
            if terminal and not spans_creation:
                report["errors"].append("History does not reach the repository's creation week.")
            if not reaches_present:
                report["errors"].append("History does not reach the fetch week.")
        else:
            report["errors"].append(
                "Empty history cannot establish coverage; unavailable/restricted, not zero activity."
            )
    except READ_ERRORS as exc:
        report["errors"].append(str(exc))
    report["weekly_history"] = weeks
    if weeks:
        try:
            report["statistics"] = summarize(weeks, metadata["created_at"], as_of)
        except (ValueError, OverflowError) as exc:
            report["errors"].append(str(exc))
        if "statistics" in report:
            if not report["statistics"]["observed_stars"]:
                report["outcome"] = "no_stars_in_returned_history"
            elif report["statistics"]["spike_days"]:
                report["outcome"] = "temporal_spikes_for_review"
            elif not report["statistics"]["days_eligible_for_spike_rule"]:
                report["outcome"] = "insufficient_baseline_for_spike_analysis"
            else:
                report["outcome"] = "no_post_baseline_spikes_under_stated_rule"
    report["coverage_complete"] = terminal and not report["errors"]
    if report["errors"] and weeks:
        report["outcome"] = "partial_live_history"
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=normalize_repo)
    parser.add_argument("--max-history-pages", type=int, default=12)
    parser.add_argument(
        "--anonymous", action="store_true",
        help="Do not use existing GitHub CLI authentication.",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.max_history_pages <= 100:
        parser.error("--max-history-pages must be between 1 and 100.")
    as_of = datetime.now(timezone.utc).isoformat()
    report = {
        "requested_repository": args.repository,
        "fetched_at": as_of,
        "metadata": None,
        "coverage_complete": False,
        "outcome": "repository_metadata_unavailable",
        "sources": [f"{API}/repos/{args.repository}"],
        "errors": [],
    }
    try:
        client = GitHubClient(anonymous=args.anonymous)
        metadata, _ = client.get(f"repos/{args.repository}")
        report["metadata"] = validate_metadata(metadata)
        analysis = analyze(report["metadata"], as_of, args.max_history_pages, client)
        analysis["sources"] = report["sources"] + analysis["sources"]
        report.update(analysis)
    except READ_ERRORS as exc:
        report["errors"].append(str(exc))
    print(json.dumps(report, indent=2))
    return 0 if report["coverage_complete"] else 2


if __name__ == "__main__":
    sys.exit(main())
