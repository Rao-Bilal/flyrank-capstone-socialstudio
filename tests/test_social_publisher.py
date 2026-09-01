"""
Integration test for FakeInstagramPublisher against the live fake_platform
server. Requires: uvicorn fake_platform.main:app --port 9000 running.
"""

import pytest
from app.services.social_publisher import FakeInstagramPublisher


@pytest.mark.asyncio
async def test_publish_succeeds_and_returns_post_id():
    publisher = FakeInstagramPublisher()
    token = await publisher.get_access_token()
    assert token.startswith("fake-token-")

    result = await publisher.publish(
        idempotency_key="pytest-key-001",
        caption="Automated test caption",
        image_path="/fake/path/image.jpg",
        webhook_url="http://127.0.0.1:9000/does-not-matter",
        access_token=token,
    )

    assert result.status == "published"
    assert result.platform_post_id.startswith("post-")


@pytest.mark.asyncio
async def test_publish_is_idempotent():
    publisher = FakeInstagramPublisher()
    token = await publisher.get_access_token()

    result1 = await publisher.publish(
        idempotency_key="pytest-key-idempotent-check",
        caption="Same caption",
        image_path="/fake/path/image.jpg",
        webhook_url="http://127.0.0.1:9000/does-not-matter",
        access_token=token,
    )

    result2 = await publisher.publish(
        idempotency_key="pytest-key-idempotent-check",  # same key
        caption="Same caption",
        image_path="/fake/path/image.jpg",
        webhook_url="http://127.0.0.1:9000/does-not-matter",
        access_token=token,
    )

    # Same idempotency key must yield the SAME post id - no duplicate.
    assert result1.platform_post_id == result2.platform_post_id