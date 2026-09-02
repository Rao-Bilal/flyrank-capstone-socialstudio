"""
Proves the adapter respects 429 + Retry-After and retries safely,
without depending on the fake platform's random 20% rate-limit chance.
"""

import pytest
import httpx

from app.services.social_publisher import FakeInstagramPublisher


class _FakeResponse:
    def __init__(self, status_code, json_data=None, headers=None):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)


@pytest.mark.asyncio
async def test_publish_retries_after_429_and_succeeds(monkeypatch):
    call_count = {"n": 0}

    async def fake_post(self, url, **kwargs):
        call_count["n"] += 1
        if "/oauth/token" in url:
            return _FakeResponse(200, {"access_token": "fake-token-abc"})
        if "/publish" in url:
            if call_count["n"] == 2:
                # first /publish call (2nd overall call) -> rate limited
                return _FakeResponse(429, headers={"Retry-After": "0"})
            # second /publish call (3rd overall call) -> succeeds
            return _FakeResponse(200, {"platform_post_id": "post-test-123"})
        raise ValueError(f"Unexpected URL: {url}")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    publisher = FakeInstagramPublisher()
    token = await publisher.get_access_token()
    result = await publisher.publish(
        idempotency_key="test-campaign:instagram",
        caption="Test caption",
        image_path="media/test.jpg",
        webhook_url="http://127.0.0.1:8000/webhook/social-delivery",
        access_token=token,
    )

    assert result.status == "published"
    assert result.platform_post_id == "post-test-123"
    # 1 oauth call + 1 rate-limited /publish + 1 successful /publish = 3
    assert call_count["n"] == 3


@pytest.mark.asyncio
async def test_publish_gives_up_after_max_retries(monkeypatch):
    async def always_rate_limited(self, url, **kwargs):
        if "/oauth/token" in url:
            return _FakeResponse(200, {"access_token": "fake-token-abc"})
        return _FakeResponse(429, headers={"Retry-After": "0"})

    monkeypatch.setattr(httpx.AsyncClient, "post", always_rate_limited)

    publisher = FakeInstagramPublisher()
    token = await publisher.get_access_token()
    result = await publisher.publish(
        idempotency_key="test-campaign:instagram-gives-up",
        caption="Test caption",
        image_path="media/test.jpg",
        webhook_url="http://127.0.0.1:8000/webhook/social-delivery",
        access_token=token,
    )

    assert result.status == "failed"
    assert result.platform_post_id == ""