"""
SocialPublisher interface + Fake Instagram / Fake X adapters.

Rule: the rest of the application depends ONLY on the SocialPublisher
interface, never on a concrete adapter. Adding a new platform means
adding a new adapter class here - nothing above this layer changes.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

FAKE_PLATFORM_BASE_URL = "http://127.0.0.1:9000"


@dataclass
class PublishResult:
    platform_post_id: str
    status: str  # "published" | "failed"


class SocialPublisher(ABC):
    """Every platform adapter must implement this interface."""

    platform: str

    @abstractmethod
    async def publish(
        self,
        idempotency_key: str,
        caption: str,
        image_path: str,
        webhook_url: str,
        access_token: str,
    ) -> PublishResult:
        ...

    @abstractmethod
    async def get_access_token(self) -> str:
        ...


class _FakePlatformAdapterBase(SocialPublisher):
    """
    Shared logic for adapters that talk to our fake_platform server.
    Handles idempotency-key passthrough and 429/Retry-After backoff -
    both FakeInstagramPublisher and FakeXPublisher reuse this, so the
    retry/backoff logic isn't duplicated per platform.
    """

    MAX_RETRIES = 3

    async def get_access_token(self) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{FAKE_PLATFORM_BASE_URL}/oauth/token",
                json={"platform": self.platform},
            )
            resp.raise_for_status()
            return resp.json()["access_token"]

    async def publish(
        self,
        idempotency_key: str,
        caption: str,
        image_path: str,
        webhook_url: str,
        access_token: str,
    ) -> PublishResult:
        attempt = 0
        async with httpx.AsyncClient() as client:
            while attempt < self.MAX_RETRIES:
                attempt += 1
                resp = await client.post(
                    f"{FAKE_PLATFORM_BASE_URL}/publish",
                    json={
                        "caption": caption,
                        "image_url": image_path,
                        "webhook_url": webhook_url,
                    },
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Idempotency-Key": idempotency_key,
                    },
                )

                if resp.status_code == 429:
                    retry_after = int(resp.headers.get("Retry-After", "1"))
                    await asyncio.sleep(retry_after)
                    continue  # retry - safe because idempotency key is unchanged

                resp.raise_for_status()
                data = resp.json()
                return PublishResult(
                    platform_post_id=data["platform_post_id"],
                    status="published",
                )

        return PublishResult(platform_post_id="", status="failed")


class FakeInstagramPublisher(_FakePlatformAdapterBase):
    platform = "instagram"


class FakeXPublisher(_FakePlatformAdapterBase):
    platform = "x"