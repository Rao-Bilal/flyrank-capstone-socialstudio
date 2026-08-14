# Design Doc — Multi-Platform Social Campaign Publisher

## 1. Problem
Turn one published blog post into a scheduled, multi-platform social campaign
(image variant + tailored caption per platform), published through a reliable,
idempotent, rate-limit-aware adapter layer against a fake social platform server.
Storage of blog content already exists at FlyRank; the publishing system does not.

## 2. Non-goal (explicit)
This project will NOT integrate with any real social media API (Instagram, X,
LinkedIn) in the core build. All publishing happens against the provided fake
platform server. Real publishing is an opt-in stretch goal only, out of scope
for the core.

## 3. Platform specs

| Platform  | Image size  | Aspect ratio | Caption max length (assumed) | Voice notes            |
|-----------|-------------|--------------|-------------------------------|-------------------------|
| Instagram | 1080x1080   | 1:1          | 2200 chars                    | casual, emoji-friendly  |
| X         | 1600x900    | 16:9         | 280 chars                     | punchy, concise         |

## 4. Data model

### Campaign
- id (uuid, pk)
- source_post_title (string)
- source_post_body (text)
- source_post_url (string)
- status (enum: draft | scheduled | publishing | completed | failed)
- scheduled_at (timestamp, nullable)
- created_at, updated_at

### SocialPostEntry (per platform, per campaign)
- id (uuid, pk)
- campaign_id (fk -> Campaign)
- platform (enum: instagram | x)
- image_path (string)
- caption (text)
- idempotency_key (string, unique per campaign+platform)
- platform_post_id (string, nullable — set once platform confirms)
- status (enum: queued | publishing | published | failed)
- last_error (text, nullable)
- retry_count (int, default 0)
- created_at, updated_at

### PlatformToken
- id (uuid, pk)
- platform (enum: instagram | x)
- encrypted_token (bytes)
- iv (bytes, random per row)
- created_at

### WebhookEvent (audit log)
- id (uuid, pk)
- social_post_entry_id (fk)
- raw_payload (text)
- signature_valid (bool)
- received_at (timestamp)

## 5. API surface (core endpoints)

- `POST /campaigns` — create campaign from a blog post (title, body, url)
- `POST /campaigns/:id/generate` — run image variant + caption pipeline
- `POST /campaigns/:id/schedule` — set scheduled_at, enqueue durable job
- `POST /campaigns/:id/publish-now` — immediate publish (idempotent, testable via probe 1)
- `GET /campaigns/:id` — campaign + all SocialPostEntry statuses
- `POST /webhook/social-delivery` — receives signed delivery events from fake platform
- `GET /health` — liveness check

## 6. Layer sketch
​```
HTTP layer (routes/controllers)
-> validates input, maps to DTOs, never touches DB directly
Service layer (CampaignService, PublishService, SchedulerService)
-> business logic, idempotency checks, orchestrates adapters
Adapter layer (SocialPublisher interface)
-> FakeInstagramPublisher, FakeXPublisher
-> only layer that knows about the fake platform's HTTP shape
Data layer (repositories)
-> Campaign repo, SocialPostEntry repo, Token repo (Postgres/SQLite)
Background layer
-> durable scheduler/worker (BullMQ+Redis or APScheduler)
​```

Rule: Service layer depends on the `SocialPublisher` interface, never on a
concrete adapter. Adding a platform = new adapter class, zero changes above it.

## 7. SocialPublisher interface signature

```typescript
interface PublishResult {
  platformPostId: string;
  status: "published" | "failed";
}

interface SocialPublisher {
  platform: "instagram" | "x";

  publish(params: {
    campaignId: string;
    idempotencyKey: string;
    imagePath: string;
    caption: string;
  }): Promise<PublishResult>;

  handleRateLimit(retryAfterSeconds: number): Promise<void>;
}
```

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class PublishResult:
    platform_post_id: str
    status: str  # "published" | "failed"

class SocialPublisher(ABC):
    platform: str

    @abstractmethod
    async def publish(
        self,
        campaign_id: str,
        idempotency_key: str,
        image_path: str,
        caption: str,
    ) -> PublishResult:
        ...

    @abstractmethod
    async def handle_rate_limit(self, retry_after_seconds: int) -> None:
        ...
```

## 8. Frontend (planned stretch, not in graded core)
A thin dashboard on top of the API: campaign creation form, image/caption
preview, schedule picker, and a status table driven by polling `GET /campaigns/:id`.
Built only after all §6 Definition of Done boxes are green.
