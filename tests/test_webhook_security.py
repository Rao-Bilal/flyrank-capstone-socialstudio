"""
Proves the webhook trust boundary automatically (Probe 4):
- A forged/modified delivery event -> rejected with 400, no status change.
- A correctly signed event -> accepted, status flips to 'published'.
"""

import hashlib
import hmac
import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.webhook_verifier import WEBHOOK_SECRET

TEST_DB_PATH = Path("test_webhook_security.db")


@pytest.fixture
def client_with_isolated_db(monkeypatch):
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    def _get_test_connection():
        conn = sqlite3.connect(TEST_DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr("app.db.get_connection", _get_test_connection)
    monkeypatch.setattr("app.main.get_connection", _get_test_connection)

    from app.db import init_db
    monkeypatch.setattr("app.db.DB_PATH", TEST_DB_PATH)
    init_db()

    campaign_id = str(uuid.uuid4())
    idempotency_key = f"{campaign_id}:instagram"
    conn = _get_test_connection()
    conn.execute(
        """INSERT INTO campaigns (id, source_post_title, source_post_body, source_post_url)
           VALUES (?, ?, ?, ?)""",
        (campaign_id, "Test", "Body", "http://example.com"),
    )
    conn.execute(
        """INSERT INTO social_post_entries
           (id, campaign_id, platform, image_path, caption, idempotency_key, status)
           VALUES (?, ?, 'instagram', 'media/test.jpg', 'caption', ?, 'publishing')""",
        (str(uuid.uuid4()), campaign_id, idempotency_key),
    )
    conn.commit()
    conn.close()

    with TestClient(app) as test_client:
        yield test_client, campaign_id, idempotency_key, _get_test_connection

    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


def _sign(body_bytes: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body_bytes, hashlib.sha256).hexdigest()


def test_forged_webhook_is_rejected_with_400(client_with_isolated_db):
    client, campaign_id, idempotency_key, get_conn = client_with_isolated_db

    payload = {
        "platform_post_id": "post-forged-123",
        "idempotency_key": idempotency_key,
        "status": "published",
        "timestamp": 1234567890,
    }
    body = json.dumps(payload).encode()

    response = client.post(
        "/webhook/social-delivery",
        content=body,
        headers={"X-Signature": "0" * 64, "Content-Type": "application/json"},
    )

    assert response.status_code == 400

    conn = get_conn()
    row = conn.execute(
        "SELECT status FROM social_post_entries WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    conn.close()
    assert row["status"] == "publishing"  # unchanged - forged event had no effect


def test_modified_body_with_stale_signature_is_rejected(client_with_isolated_db):
    client, campaign_id, idempotency_key, get_conn = client_with_isolated_db

    original_payload = {
        "platform_post_id": "post-original-123",
        "idempotency_key": idempotency_key,
        "status": "published",
        "timestamp": 1234567890,
    }
    original_body = json.dumps(original_payload).encode()
    valid_signature_for_original = _sign(original_body)

    # Attacker tampers with the payload after the signature was computed.
    tampered_payload = dict(original_payload)
    tampered_payload["platform_post_id"] = "post-attacker-injected"
    tampered_body = json.dumps(tampered_payload).encode()

    response = client.post(
        "/webhook/social-delivery",
        content=tampered_body,
        headers={"X-Signature": valid_signature_for_original, "Content-Type": "application/json"},
    )

    assert response.status_code == 400


def test_valid_signed_webhook_is_accepted_and_updates_status(client_with_isolated_db):
    client, campaign_id, idempotency_key, get_conn = client_with_isolated_db

    payload = {
        "platform_post_id": "post-valid-456",
        "idempotency_key": idempotency_key,
        "status": "published",
        "timestamp": 1234567890,
    }
    body = json.dumps(payload).encode()
    valid_signature = _sign(body)

    response = client.post(
        "/webhook/social-delivery",
        content=body,
        headers={"X-Signature": valid_signature, "Content-Type": "application/json"},
    )

    assert response.status_code == 200

    conn = get_conn()
    row = conn.execute(
        "SELECT status, platform_post_id FROM social_post_entries WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    conn.close()
    assert row["status"] == "published"
    assert row["platform_post_id"] == "post-valid-456"