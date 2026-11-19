"""Tests for scripts.local.ingest.transform (GitHub Archive event flattening)."""

from datetime import datetime, timezone

from scripts.local.ingest.transform import events_to_arrow, extract_event_fields

HOUR = datetime(2024, 1, 15, 12)


def modern_event(**overrides):
    event = {
        "id": "123",
        "type": "WatchEvent",
        "created_at": "2024-01-15T12:34:56Z",
        "actor": {"id": 5, "login": "alice", "avatar_url": "https://a/x.png"},
        "repo": {"id": 9, "name": "owner/repo"},
        "org": {"id": 7, "login": "acme"},
        "payload": {"action": "started"},
    }
    event.update(overrides)
    return event


def legacy_event(**overrides):
    """Pre-2015 timeline-API format: actor is a string, repo is `repository`."""
    event = {
        "type": "WatchEvent",
        "created_at": "2012-03-10T07:56:30-08:00",
        "actor": "octocat",
        "actor_attributes": {"login": "octocat", "gravatar_id": "abc"},
        "repository": {"owner": "rails", "name": "rails", "id": 8514},
        "payload": {"action": "started"},
    }
    event.update(overrides)
    return event


def test_modern_star_event():
    row = extract_event_fields(modern_event(), HOUR)
    assert row["actor_login"] == "alice"
    assert row["actor_id"] == 5
    assert row["repo_name"] == "owner/repo"
    assert row["repo_id"] == 9
    assert row["org_login"] == "acme"
    assert row["is_star"] is True
    assert row["created_at"] == datetime(2024, 1, 15, 12, 34, 56, tzinfo=timezone.utc)
    assert (row["year"], row["month"], row["day"], row["hour"]) == (2024, 1, 15, 12)


def test_display_login_fallback():
    row = extract_event_fields(modern_event(actor={"id": 5, "display_login": "bob"}), HOUR)
    assert row["actor_login"] == "bob"


def test_non_star_event():
    row = extract_event_fields(modern_event(type="PushEvent", payload={}), HOUR)
    assert row["is_star"] is False


def test_legacy_string_actor_is_not_dropped():
    row = extract_event_fields(legacy_event(), datetime(2012, 3, 10, 15))
    assert row is not None
    assert row["actor_login"] == "octocat"
    assert row["actor_id"] is None
    assert row["repo_name"] == "rails/rails"
    assert row["repo_id"] == 8514
    assert row["is_star"] is True


def test_legacy_actor_attributes_id_used_when_present():
    row = extract_event_fields(
        legacy_event(actor_attributes={"login": "octocat", "id": 583231}),
        datetime(2012, 3, 10, 15),
    )
    assert row["actor_id"] == 583231


def test_malformed_events_are_skipped():
    assert extract_event_fields({}, HOUR) is None
    assert extract_event_fields(modern_event(created_at="not-a-date"), HOUR) is None
    assert extract_event_fields(modern_event(actor={}), HOUR) is None
    assert extract_event_fields(modern_event(repo={}), HOUR) is None


def test_events_to_arrow_keeps_legacy_rows():
    table = events_to_arrow(iter([modern_event(), legacy_event(), {}]), HOUR)
    assert table.num_rows == 2
    assert table.column("actor_login").to_pylist() == ["alice", "octocat"]
