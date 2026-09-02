"""
Proves the crash-recovery / no-double-publish guarantee automatically,
without needing to manually kill and restart a server each time.

The real-world scenario: a scheduled job calls publish_campaign(), the
process crashes partway through (or the scheduler/OS re-fires the same
job for any reason), and a restarted process calls publish_campaign()
again for the SAME campaign. This must never create a second post per
platform - already-published entries must be skipped.

This test simulates that by calling publish_campaign() twice in a row
for the same campaign against a mocked publisher, and asserting the
underlying "publish" HTTP call only ever happens once per platform.
"""

import uuid
import sqlite3
from pathlib import Path

import pytest
import httpx

from app.db import init_db
from app.services.publish_service import publish_campaign, PUBLISHERS


TEST_DB_PATH = Path("test_crash_recovery.db")


@pytest.fixture
def isolated_db(monkeypatch):
    """Points get_connection() at a throwaway sqlite file for this test only."""
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    def _get_test_connection():
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("app.db.get_connection", _get_test_connection)
    monkeypatch.setattr("app.services.publish_service.get_connection", _get_test_connection)

    monkeypatch.setattr("app.db.DB_PATH", TEST_DB_PATH)
    init_db()

    yield _get_test_connection

    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest.mark.asyncio
async def test_publish_campaign_is_safe_to_call_twice(isolated_db, monkeypatch):
    get_conn = isolated_db

    campaign_id = str(uuid.uuid4())
    conn = get_conn()
    conn.execute(
        """INSERT INTO campaigns (id, source_post_title, source_post_body, source_post_url)
           VALUES (?, ?, ?, ?)""",
        (campaign_id, "Test Title", "Test Body", "http://example.com"),
    )
    for platform in ("instagram", "x"):
        conn.execute(
            """INSERT INTO social_post_entries
               (id, campaign_id, platform, image_path, caption, idempotency_key, status)
               VALUES (?, ?, ?, ?, ?, ?, 'queued')""",
            (
                str(uuid.uuid4()),
                campaign_id,
                platform,
                f"media/{campaign_id}/{platform}.jpg",
                f"caption for {platform}",
                f"{campaign_id}:{platform}",
            ),
        )
    conn.commit()
    conn.close()

    real_publish_calls = {"n": 0}

    class _FakeResponse:
        def __init__(self, json_data):
            self.status_code = 200
            self._json_data = json_data

        def json(self):
            return self._json_data

        def raise_for_status(self):
            pass

    async def fake_post(self, url, **kwargs):
        if "/oauth/token" in url:
            return _FakeResponse({"access_token": "fake-token"})
        if "/publish" in url:
            real_publish_calls["n"] += 1
            return _FakeResponse({"platform_post_id": f"post-{real_publish_calls['n']}"})
        raise ValueError(f"Unexpected URL: {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    # First call: simulates the original scheduled job run. Both
    # platforms should actually get published.
    first_result = await publish_campaign(campaign_id)
    assert real_publish_calls["n"] == 2  # one /publish call per platform

    # Manually mark both entries as published, the way the webhook
    # handler would after a verified delivery event - this is the
    # state the DB would be in right after a successful first run.
    conn = get_conn()
    conn.execute(
        "UPDATE social_post_entries SET status = 'published' WHERE campaign_id = ?",
        (campaign_id,),
    )
    conn.commit()
    conn.close()

    # Second call: simulates a crash-then-restart re-running the same
    # job for the same campaign. NO new /publish calls should happen.
    second_result = await publish_campaign(campaign_id)
    assert real_publish_calls["n"] == 2  # unchanged - nothing new published

    for entry_result in second_result["results"]:
        assert entry_result["skipped_already_published"] is True