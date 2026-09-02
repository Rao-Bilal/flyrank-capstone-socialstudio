"""
Fake Social Platform Server.

Simulates a real social media platform's publishing API for local testing:
- OAuth-style token issuance
- Idempotency-Key support (same key = same result, no duplicate "post")
- Random rate limiting (429 + Retry-After)
- Signed delivery webhooks sent back to the caller's webhook URL

This is NOT a real social platform. Nothing here touches Instagram, X, etc.
Run with: uvicorn fake_platform.main:app --reload --port 9000
"""

import hashlib
import hmac
import json
import random
import time
import uuid
from typing import Optional
import os 

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="Fake Social Platform Server")

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "fake-platform-shared-secret-change-me")

ISSUED_TOKENS: dict[str, str] = {}
IDEMPOTENCY_STORE: dict[str, dict] = {}
RATE_LIMIT_HITS: dict[str, int] = {}


class TokenRequest(BaseModel):
    platform: str


class PublishRequest(BaseModel):
    caption: str
    image_url: Optional[str] = None
    webhook_url: str


@app.post("/oauth/token")
def issue_token(req: TokenRequest):
    token = f"fake-token-{uuid.uuid4()}"
    ISSUED_TOKENS[token] = req.platform
    return {"access_token": token, "platform": req.platform, "expires_in": 3600}


@app.post("/publish")
async def publish(
    req: PublishRequest,
    request: Request,
    authorization: str = Header(...),
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
):
    token = authorization.replace("Bearer ", "")
    if token not in ISSUED_TOKENS:
        raise HTTPException(status_code=401, detail="Invalid token")

    if idempotency_key in IDEMPOTENCY_STORE:
        return IDEMPOTENCY_STORE[idempotency_key]

    if random.random() < 0.2:
        raise HTTPException(
            status_code=429,
            detail="Rate limited",
            headers={"Retry-After": "5"},
        )

    platform_post_id = f"post-{uuid.uuid4()}"
    result = {
        "platform_post_id": platform_post_id,
        "status": "accepted",
        "idempotency_key": idempotency_key,
    }
    IDEMPOTENCY_STORE[idempotency_key] = result

    await _send_delivery_webhook(req.webhook_url, platform_post_id, idempotency_key)

    return result


async def _send_delivery_webhook(webhook_url: str, platform_post_id: str, idempotency_key: str):
    """
    Sends a signed delivery webhook back to the caller.

    IMPORTANT: we serialize the payload to JSON exactly once with
    json.dumps, sign THOSE EXACT BYTES, and send THOSE EXACT BYTES via
    content=body. We deliberately do NOT use httpx's json=payload
    shortcut, because that would let httpx re-serialize the payload
    independently -- and if its serialization differs even slightly
    from what we signed (key order, spacing, quoting), the receiver's
    signature check would fail even though the payload is legitimate.
    Signing and sending must operate on the same bytes.
    """
    payload = {
        "platform_post_id": platform_post_id,
        "idempotency_key": idempotency_key,
        "status": "published",
        "timestamp": int(time.time()),
    }
    body = json.dumps(payload).encode()
    signature = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()

    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                webhook_url,
                content=body,
                headers={
                    "X-Signature": signature,
                    "Content-Type": "application/json",
                },
                timeout=5.0,
            )
        except Exception as e:
            print(f"[fake_platform] webhook delivery failed: {e}")