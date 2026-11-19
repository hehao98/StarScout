"""
Transform GitHub Archive JSON events to PyArrow tables.

Handles:
- Flattening nested JSON structure (actor.login -> actor_login)
- Computing derived fields (is_star)
- Schema evolution across GitHub Archive history
- Missing/null field handling
"""

from datetime import datetime
from typing import Iterator

import pyarrow as pa

from .schema import EVENTS_SCHEMA, MINIMAL_SCHEMA


def extract_event_fields(event: dict, hour_dt: datetime) -> dict | None:
    """
    Extract and flatten fields from a GitHub Archive event.

    Args:
        event: Raw event dictionary from GitHub Archive
        hour_dt: The hour this event belongs to (for partitioning)

    Returns:
        Flattened dictionary matching our schema, or None if event is malformed.
    """
    try:
        # Core fields
        event_type = event.get("type", "")
        created_at_str = event.get("created_at")

        if not event_type or not created_at_str:
            return None

        # Parse timestamp
        # GitHub Archive uses ISO format: 2024-01-15T12:34:56Z
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return None

        # Actor fields (with fallbacks for schema evolution)
        actor = event.get("actor") or {}

        # In pre-2015 (timeline API) events, actor is a plain login string
        # and the details live in actor_attributes. This must be checked
        # before calling .get() on actor, or the event is silently dropped.
        if isinstance(actor, str):
            actor_login = actor
            actor = event.get("actor_attributes") or {}
            actor_id = actor.get("id")
        else:
            actor_id = actor.get("id")
            actor_login = actor.get("login") or actor.get("display_login")

        if not actor_login:
            return None

        # Repo fields
        repo = event.get("repo", {}) or {}
        repo_id = repo.get("id")
        repo_name = repo.get("name")

        # Old format: repository.owner + repository.name
        if not repo_name:
            repository = event.get("repository", {}) or {}
            if repository:
                owner = repository.get("owner")
                name = repository.get("name")
                if owner and name:
                    repo_name = f"{owner}/{name}"
                repo_id = repository.get("id")

        if not repo_name:
            return None

        # Org fields (nullable)
        org = event.get("org", {}) or {}
        org_id = org.get("id")
        org_login = org.get("login")

        # Determine if this is a star event
        # WatchEvent with action="started" is a star
        is_star = False
        if event_type == "WatchEvent":
            payload = event.get("payload", {}) or {}
            action = payload.get("action", "")
            # "started" means star, empty or "started" in old format
            is_star = action in ("started", "")

        return {
            "id": str(event.get("id", "")),
            "type": event_type,
            "created_at": created_at,
            "actor_id": int(actor_id) if actor_id else None,
            "actor_login": actor_login,
            "actor_avatar_url": actor.get("avatar_url"),
            "repo_id": int(repo_id) if repo_id else None,
            "repo_name": repo_name,
            "org_id": int(org_id) if org_id else None,
            "org_login": org_login,
            "is_star": is_star,
            "year": hour_dt.year,
            "month": hour_dt.month,
            "day": hour_dt.day,
            "hour": hour_dt.hour,
        }

    except Exception:
        # Skip any malformed events
        return None


def events_to_arrow(
    events: Iterator[dict],
    hour_dt: datetime,
    minimal: bool = False,
) -> pa.Table:
    """
    Convert an iterator of GitHub Archive events to a PyArrow table.

    Args:
        events: Iterator of raw event dictionaries
        hour_dt: The hour these events belong to
        minimal: If True, use minimal schema (smaller files)

    Returns:
        PyArrow table with flattened event data
    """
    schema = MINIMAL_SCHEMA if minimal else EVENTS_SCHEMA

    # Collect rows
    rows = {field.name: [] for field in schema}

    for event in events:
        extracted = extract_event_fields(event, hour_dt)
        if extracted is None:
            continue

        for field in schema:
            value = extracted.get(field.name)
            rows[field.name].append(value)

    # Build arrays
    arrays = []
    for field in schema:
        arr = pa.array(rows[field.name], type=field.type)
        arrays.append(arr)

    return pa.Table.from_arrays(arrays, schema=schema)


def transform_hour(
    events: list[dict],
    hour_dt: datetime,
    minimal: bool = False,
) -> pa.Table:
    """
    Transform a list of events for a single hour into a PyArrow table.

    This is a convenience wrapper around events_to_arrow for batch processing.
    """
    return events_to_arrow(iter(events), hour_dt, minimal)
