import argparse
import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import star_history


START = datetime(2026, 8, 2, tzinfo=timezone.utc)
AS_OF = (START + timedelta(days=34, hours=12)).isoformat()
METADATA = {
    "full_name": "example/repository",
    "stargazers_count": 450,
    "forks_count": 2,
    "created_at": START.isoformat(),
    "pushed_at": AS_OF,
    "archived": False,
    "html_url": "https://github.com/example/repository",
    "private": False,
}


def weeks(counts):
    assert len(counts) % 7 == 0
    result = []
    for index in range(0, len(counts), 7):
        days = counts[index:index + 7]
        result.append({
            "week": int((START + timedelta(days=index)).timestamp()),
            "days": days,
            "total": sum(days),
        })
    return list(reversed(result))


class FakeClient:
    authentication = "fixture"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, endpoint):
        self.calls.append(endpoint)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


class LiveAnalysisTests(unittest.TestCase):
    def analyze(self, responses, **kwargs):
        self.client = FakeClient(responses)
        return star_history.analyze(METADATA, AS_OF, client=self.client, **kwargs)

    def test_spike_counts_baseline_and_launch_exclusion(self):
        counts = [10] * 35
        counts[0], counts[29] = 1000, 200
        data = weeks(counts)
        report = self.analyze([
            (data[:2], {"link": '<unused>; rel="next"'}), (data[2:], {}),
        ])
        stats = report["statistics"]
        self.assertTrue(report["coverage_complete"])
        self.assertEqual(report["pages_read"], 2)
        self.assertEqual(stats["observed_stars"], sum(counts))
        self.assertEqual(stats["spike_days"], [{
            "date": "2026-08-31", "stars": 200,
            "previous_28_day_mean": 10, "multiple_of_baseline": 20,
        }])
        self.assertEqual(stats["top_days"][0]["stars"], 1000)
        self.assertEqual(stats["peak_7_day_window"]["stars"], 1060)
        self.assertEqual(report["outcome"], "temporal_spikes_for_review")

    def test_uniform_history_has_no_spikes(self):
        report = self.analyze([(weeks([10] * 35), {})])
        self.assertTrue(report["coverage_complete"])
        self.assertEqual(report["outcome"], "no_post_baseline_spikes_under_stated_rule")
        self.assertEqual(report["statistics"]["days_eligible_for_spike_rule"], 6)

    def test_new_repository_lacks_baseline_not_clean_verdict(self):
        report = star_history.analyze(
            METADATA, (START + timedelta(days=6)).isoformat(),
            client=FakeClient([(weeks([1] * 7), {})]),
        )
        self.assertTrue(report["coverage_complete"])
        self.assertEqual(report["outcome"], "insufficient_baseline_for_spike_analysis")

    def test_page_budget_retains_explicitly_partial_statistics(self):
        report = self.analyze(
            [(weeks([10] * 35)[:2], {"link": '<unused>; rel="next"'})],
            max_pages=1,
        )
        self.assertFalse(report["coverage_complete"])
        self.assertEqual(report["outcome"], "partial_live_history")
        self.assertEqual(report["statistics"]["observed_stars"], 140)
        self.assertIn("page budget", report["errors"][0])

    def test_restricted_and_rate_limited_are_not_empty_success(self):
        cases = (
            (403, {}), (404, {}), (429, {}),
            (403, {"x-ratelimit-remaining": "0"}),
        )
        for status, headers in cases:
            with self.subTest(status=status, headers=headers):
                report = self.analyze([star_history.GitHubAPIError(status, headers)])
                self.assertFalse(report["coverage_complete"])
                self.assertEqual(report["outcome"], "live_history_unavailable")
                self.assertEqual(len(self.client.calls), 1)
                self.assertNotIn("statistics", report)

    def test_failure_on_second_page_preserves_first(self):
        report = self.analyze([
            (weeks([10] * 35)[:2], {"link": '<unused>; rel="next"'}),
            star_history.GitHubAPIError(403, {}),
        ])
        self.assertEqual(report["outcome"], "partial_live_history")
        self.assertEqual(report["pages_read"], 1)
        self.assertEqual(report["statistics"]["observed_stars"], 140)

    def test_missing_creation_or_current_week_is_partial(self):
        data = weeks([10] * 35)
        for subset in (data[:-1], data[1:]):
            with self.subTest(subset=subset):
                report = self.analyze([(subset, {})])
                self.assertFalse(report["coverage_complete"])
                self.assertTrue(report["errors"])

    def test_empty_nonzero_history_is_unavailable(self):
        report = self.analyze([([], {})])
        self.assertFalse(report["coverage_complete"])
        self.assertIn("Empty history", report["errors"][0])

    def test_empty_history_is_not_coverage_even_when_current_count_is_zero(self):
        report = star_history.analyze(
            {**METADATA, "stargazers_count": 0}, AS_OF,
            client=FakeClient([([], {})]),
        )
        self.assertFalse(report["coverage_complete"])
        self.assertEqual(report["outcome"], "live_history_unavailable")

    def test_explicit_zero_weeks_are_valid_coverage(self):
        report = star_history.analyze(
            {**METADATA, "stargazers_count": 0}, AS_OF,
            client=FakeClient([(weeks([0] * 35), {})]),
        )
        self.assertTrue(report["coverage_complete"])
        self.assertEqual(report["outcome"], "no_stars_in_returned_history")

    def test_week_validation_and_gaps(self):
        base = weeks([10] * 35)
        invalid = [
            [{"week": True, "days": [1] * 7, "total": 7}],
            [{"week": 1, "days": [1] * 6, "total": 6}],
            [{"week": 1, "days": [1] * 7, "total": 8}],
            [{"week": 1, "days": [-1] * 7, "total": 0}],
            [base[0], base[0]],
            [base[0], base[2]],
        ]
        for data in invalid:
            with self.subTest(data=data):
                report = self.analyze([(data, {})])
                self.assertFalse(report["coverage_complete"])
                self.assertTrue(report["errors"])

    def test_private_target_does_not_request_history(self):
        client = FakeClient([])
        report = star_history.analyze(
            {**METADATA, "private": True}, AS_OF, client=client,
        )
        self.assertFalse(report["coverage_complete"])
        self.assertEqual(client.calls, [])

    def test_invalid_metadata_is_explicit_not_a_crash(self):
        invalid = (
            None, {}, {**METADATA, "full_name": "bad/name/"},
            {**METADATA, "stargazers_count": True},
            {**METADATA, "created_at": "2026-08-02"},
        )
        for metadata in invalid:
            with self.subTest(metadata=metadata):
                client = FakeClient([])
                report = star_history.analyze(metadata, AS_OF, client=client)
                self.assertFalse(report["coverage_complete"])
                self.assertTrue(report["errors"])
                self.assertEqual(client.calls, [])

    def test_zero_baseline_does_not_divide_by_zero(self):
        counts = [0] * 35
        counts[29] = 100
        stats = star_history.summarize(weeks(counts), METADATA["created_at"], AS_OF)
        self.assertIsNone(stats["spike_days"][0]["multiple_of_baseline"])

    def test_current_day_is_not_scored(self):
        counts = [1] * 35
        counts[-1] = 1000
        stats = star_history.summarize(weeks(counts), METADATA["created_at"], AS_OF)
        self.assertEqual(stats["spike_days"], [])
        self.assertEqual(stats["top_days"][0]["stars"], 1000)

    def test_future_nonzero_days_are_not_silently_dropped(self):
        report = star_history.analyze(
            METADATA, (START + timedelta(days=3)).isoformat(),
            client=FakeClient([(weeks([1] * 7), {})]),
        )
        self.assertFalse(report["coverage_complete"])
        self.assertIn("after the fetch date", report["errors"][-1])


class TransportAndCLITests(unittest.TestCase):
    def test_cli_transport_uses_only_github_get(self):
        client = star_history.GitHubClient(anonymous=True)
        client.gh = "/fixture/gh"
        result = subprocess.CompletedProcess(
            [], 0, b'HTTP/2.0 200 OK\r\nLink: <unused>; rel="next"\r\n\r\n[]', b"",
        )
        endpoint = "repos/example/repository/stargazers/history?per_page=30&page=1"
        with patch.object(star_history.subprocess, "run", return_value=result) as run:
            rows, headers = client.get(endpoint)
            args = run.call_args.args[0]
            self.assertEqual(args[args.index("--method") + 1], "GET")
            self.assertEqual(args[args.index("--hostname") + 1], "github.com")
            self.assertEqual(rows, [])
            self.assertIn("next", headers["link"])
            for invalid in ("https://outside.example/token", "repos/a/b/issues"):
                with self.assertRaises(ValueError):
                    client.get(invalid)
            self.assertEqual(run.call_count, 1)

    def test_anonymous_transport_is_bounded(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.headers = {"Content-Type": "application/json"}
        response.read.return_value = b"[]"
        client = star_history.GitHubClient(anonymous=True)
        with patch.object(star_history.urllib.request, "urlopen", return_value=response):
            rows, _ = client.get("repos/example/repository")
        self.assertEqual(rows, [])
        response.read.assert_called_once_with(star_history.MAX_RESPONSE_BYTES + 1)

    def test_invalid_repository_inputs(self):
        for value in (
            "https://github.com.evil/a/b", "https://enterprise.example/a/b",
            "a/..", "a/b;echo", "https://user@github.com/a/b",
        ):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                star_history.normalize_repo(value)
        self.assertEqual(star_history.normalize_repo("https://github.com/a/b.git/"), "a/b")

    def test_cli_metadata_error_is_json_and_nonzero(self):
        client = FakeClient([star_history.GitHubAPIError(404, {})])
        output = io.StringIO()
        with patch.object(star_history, "GitHubClient", return_value=client), \
                redirect_stdout(output):
            code = star_history.main(["example/repository"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertFalse(report["coverage_complete"])
        self.assertTrue(report["errors"])

    def test_cli_emits_complete_json_without_personal_profile_fields(self):
        client = FakeClient([
            ({**METADATA, "temp_clone_token": "fixture-not-to-emit"}, {}),
            (weeks([10] * 35), {}),
        ])
        output = io.StringIO()
        fixed = datetime.fromisoformat(AS_OF)
        with patch.object(star_history, "GitHubClient", return_value=client), \
                patch.object(star_history, "datetime", wraps=datetime) as clock, \
                redirect_stdout(output):
            clock.now.return_value = fixed
            code = star_history.main(["example/repository"])
        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertTrue(report["coverage_complete"])
        self.assertEqual(report["statistics"]["observed_stars"], 350)
        self.assertNotIn("fixture-not-to-emit", output.getvalue())
        self.assertEqual(report["individual_account_analysis"]["status"], "not_run")

    def test_page_budget_validation_before_network(self):
        with patch.object(star_history, "GitHubClient") as client, \
                patch("sys.stderr", new=io.StringIO()), \
                self.assertRaises(SystemExit):
            star_history.main(["example/repository", "--max-history-pages", "101"])
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
