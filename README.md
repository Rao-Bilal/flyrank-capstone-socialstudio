\# FlyRank Capstone — Multi-Platform Social Campaign Publisher



Turn one blog post into a fully-tracked, multi-platform social media campaign — with

idempotent publishing, rate-limit backoff, durable crash-safe scheduling, and

signature-verified webhook status tracking. Built against a provided fake social

platform server; no real Instagram/X account is ever touched.



\## What this system does



1\. Takes a blog post (title + body + URL) and creates a \*\*campaign\*\*.

2\. Generates platform-correct \*\*image variants\*\* (1080×1080 for Instagram, 1600×900

&#x20;  for X) and \*\*platform-tailored captions\*\* from a shared brand voice.

3\. Publishes each platform's post through a common `SocialPublisher` interface —

&#x20;  the app never knows or cares which concrete platform it's talking to.

4\. Publishing is \*\*idempotent\*\* (a retried request never creates a duplicate post),

&#x20;  \*\*rate-limit aware\*\* (respects `429` + `Retry-After`, backs off, retries safely),

&#x20;  and can be run \*\*immediately\*\* or \*\*scheduled for later\*\* via a durable

&#x20;  background job that survives a process crash.

5\. A post's status only ever flips to `published` after a \*\*signature-verified\*\*

&#x20;  delivery webhook confirms it — forged or tampered webhooks are rejected with `400`.



\## Architecture



```

Blog Post (title, body, url)

&#x20;       │

&#x20;       ▼

&#x20;  POST /campaigns  ──────────────────────────► campaigns table (status: draft)

&#x20;       │

&#x20;       ▼

POST /campaigns/{id}/generate

&#x20;       │

&#x20;       ├──► Image Variant Pipeline (Pillow) ──► media/{id}/instagram.jpg (1080x1080)

&#x20;       │                                    └──► media/{id}/x.jpg (1600x900)

&#x20;       │

&#x20;       └──► Caption Composer (shared voice + platform fragments)

&#x20;       │

&#x20;       ▼

social\_post\_entries table (one row per platform, status: queued)

&#x20;       │

&#x20;       ├── POST /campaigns/{id}/publish-now  ──┐

&#x20;       │                                        │

&#x20;       └── POST /campaigns/{id}/schedule  ──►  APScheduler (jobs.db,           │

&#x20;            (durable — survives a crash;         SQLAlchemyJobStore)           │

&#x20;             missed jobs fire on restart)         │                             │

&#x20;                                                   ▼                             │

&#x20;                                         run\_publish\_job(campaign\_id) ◄──────────┘

&#x20;                                                   │

&#x20;                                                   ▼

&#x20;                                   publish\_service.publish\_campaign()

&#x20;                                   (shared by BOTH the live endpoint and

&#x20;                                    the scheduler — one code path, one

&#x20;                                    set of guarantees, for every trigger)

&#x20;                                                   │

&#x20;                                                   ▼

&#x20;                                     SocialPublisher interface

&#x20;                                     ┌─────────────┴─────────────┐

&#x20;                                     ▼                           ▼

&#x20;                         FakeInstagramPublisher          FakeXPublisher

&#x20;                         (idempotency key, 429/Retry-After backoff,

&#x20;                          encrypted OAuth token via AES-GCM)

&#x20;                                     │                           │

&#x20;                                     └─────────────┬─────────────┘

&#x20;                                                   ▼

&#x20;                                   Fake Social Platform Server (port 9000)

&#x20;                                   - OAuth token issuance

&#x20;                                   - Idempotency-Key store (dedupe)

&#x20;                                   - Random 429 + Retry-After simulation

&#x20;                                   - Sends signed delivery webhook back

&#x20;                                                   │

&#x20;                                                   ▼

&#x20;                         POST /webhook/social-delivery (this app, port 8000)

&#x20;                         - Verifies HMAC-SHA256 signature (X-Signature header)

&#x20;                         - Forged/tampered signature → 400, no status change

&#x20;                         - Valid signature → matches entry by idempotency\_key,

&#x20;                           flips status to "published", stores platform\_post\_id

&#x20;                         - Once every entry for a campaign is published, rolls

&#x20;                           the parent campaign's own status up to "published"

```



\### Why match webhooks on `idempotency\_key`, not `platform\_post\_id`?



The fake platform sends its delivery webhook \*\*synchronously\*\*, inside its own

`/publish` handler, before that handler even returns to us. That means the webhook

can arrive and be processed \*\*before\*\* our own code has had a chance to write

`platform\_post\_id` into the database. `idempotency\_key`, on the other hand, is

written into `social\_post\_entries` during `/generate` — long before `/publish-now`

or the scheduler ever runs — so it's guaranteed to already exist by the time any

webhook could possibly arrive. Matching on it eliminates a real race condition we

hit and fixed during development (see `BUILDLOG.md`).



\## Data model



\*\*`campaigns`\*\*

| column | type | notes |

|---|---|---|

| id | TEXT PK | UUID |

| source\_post\_title / source\_post\_body / source\_post\_url | TEXT | the input blog post |

| status | TEXT | draft → scheduled → publishing → published |

| scheduled\_at | TEXT | ISO 8601, set when scheduled |

| created\_at / updated\_at | TEXT | |



\*\*`social\_post\_entries`\*\*

| column | type | notes |

|---|---|---|

| id | TEXT PK | UUID |

| campaign\_id | TEXT FK | → campaigns.id |

| platform | TEXT | "instagram" \\| "x" |

| image\_path | TEXT | generated variant path |

| caption | TEXT | platform-tailored caption |

| idempotency\_key | TEXT | `{campaign\_id}:{platform}`, UNIQUE with (campaign\_id, platform) |

| platform\_post\_id | TEXT | set once the fake platform accepts the post |

| status | TEXT | queued → publishing → published \\| failed |

| last\_error / retry\_count | | |



Indexes on `campaign\_id` and `idempotency\_key`. Jobs live in a \*\*separate\*\* SQLite

file, `jobs.db`, managed entirely by APScheduler's `SQLAlchemyJobStore` — kept apart

from `campaigns.db` to avoid lock contention between the two.



\## Setup — run on a clean machine



\### Prerequisites

\- Python 3.11+

\- No credit card, no external services — everything runs locally.



\### Install



```powershell

python -m venv venv

.\\venv\\Scripts\\activate

pip install -r requirements.txt

```



\*(If you don't have a `requirements.txt` yet, generate one with

`pip freeze > requirements.txt` before submitting.)\*



\### Run — two servers, two terminals



\*\*Terminal 1 — fake social platform (port 9000):\*\*

```powershell

uvicorn fake\_platform.main:app --reload --port 9000

```



\*\*Terminal 2 — main application (port 8000):\*\*

```powershell

uvicorn app.main:app --reload --port 8000

```



Both must be running for publishing/webhooks to work end-to-end.



\### Seed a demo campaign



```powershell

\# Create a placeholder source image

python -c "from PIL import Image; Image.new('RGB', (1200, 1200), color=(70, 130, 180)).save('media/source.jpg')"



\# Create a campaign

$body = @{

&#x20;   title = "10 Tips for Remote Work"

&#x20;   body  = "Remote work is here to stay. Here are ten tips..."

&#x20;   url   = "https://flyrank.example.com/blog/remote-work-tips"

} | ConvertTo-Json

$response = Invoke-RestMethod -Uri "http://127.0.0.1:8000/campaigns" -Method Post -Body $body -ContentType "application/json"

$campaignId = $response.campaign\_id



\# Generate platform content

Invoke-RestMethod -Uri "http://127.0.0.1:8000/campaigns/$campaignId/generate?source\_image\_path=media/source.jpg" -Method Post



\# Publish immediately

Invoke-RestMethod -Uri "http://127.0.0.1:8000/campaigns/$campaignId/publish-now" -Method Post



\# ...or schedule for later instead:

\# $scheduledAt = (Get-Date).AddMinutes(1).ToString("yyyy-MM-ddTHH:mm:ss")

\# Invoke-RestMethod -Uri "http://127.0.0.1:8000/campaigns/$campaignId/schedule?scheduled\_at=$scheduledAt" -Method Post



\# Check status

Invoke-RestMethod -Uri "http://127.0.0.1:8000/campaigns/$campaignId" -Method Get | ConvertTo-Json -Depth 5

```



\### Run tests



```powershell

pytest -v

```



\## API surface



| Method | Path | Purpose |

|---|---|---|

| GET | `/health` | liveness check |

| POST | `/campaigns` | create a campaign from a blog post |

| POST | `/campaigns/{id}/generate` | run image + caption pipeline, queue entries |

| POST | `/campaigns/{id}/publish-now` | publish all queued entries immediately |

| POST | `/campaigns/{id}/schedule` | schedule a durable publish job for later |

| GET | `/campaigns/{id}` | fetch campaign + all its entries |

| POST | `/webhook/social-delivery` | receives signed delivery events from the fake platform |



\## Reliability guarantees, and how each is proven



| Guarantee | Where it's enforced | Automated proof |

|---|---|---|

| Idempotent publishing | stable `idempotency\_key`, fake platform's `IDEMPOTENCY\_STORE` | `tests/test\_social\_publisher.py` |

| Rate-limit backoff | `\_FakePlatformAdapterBase.publish()` retries on 429, honors `Retry-After` | `tests/test\_rate\_limit\_backoff.py` |

| Encrypted tokens at rest | AES-GCM, random IV per encryption | `tests/test\_crypto\_utils.py` |

| Durable scheduling | APScheduler + `SQLAlchemyJobStore` (`jobs.db`), `misfire\_grace\_time=3600` | manual crash test in `EVIDENCE.md`; `tests/test\_crash\_recovery.py` |

| No double-publish on restart | `publish\_campaign()` skips entries already `published` | `tests/test\_crash\_recovery.py` |

| Signed webhook trust boundary | HMAC-SHA256 verification, `hmac.compare\_digest` | `tests/test\_webhook\_security.py` |

| Correct image variants | Pillow resize/crop pipeline | manual proof in `EVIDENCE.md` (dimensions checked) |



\## Known limitations



\- Uses SQLite for both the app database and the job store — fine for a single-process

&#x20; local demo, but a real multi-worker deployment would need PostgreSQL + a shared

&#x20; job store (e.g. Redis-backed) so multiple worker processes don't double-fire jobs.

\- The image pipeline currently resizes/crops a placeholder rather than doing

&#x20; content-aware subject detection for the "safe zone" — acceptable per the brief's

&#x20; realistic-scope guidance (§7: "Image generation can be a resize/crop of a

&#x20; placeholder... graded, not artistry").

\- Only two platforms are implemented (Instagram, X), per the brief's realistic-scope

&#x20; guidance (§7: "Two platforms are enough").

\- `@app.on\_event("startup"/"shutdown")` is used for simplicity; FastAPI's newer

&#x20; `lifespan` context manager is the currently-recommended replacement and would be

&#x20; a natural next refactor.

\- The fake platform server's idempotency store and rate-limiter are in-memory and

&#x20; reset whenever that process restarts — this only affects the fake test harness,

&#x20; not the real application's own durability guarantees.



\## Project structure



```

app/

&#x20; main.py                    # FastAPI app: campaigns, generate, publish, schedule, webhook

&#x20; db.py                      # SQLite schema + connection helper

&#x20; scheduler.py               # APScheduler durable job scheduling

&#x20; services/

&#x20;   caption\_composer.py      # platform-tailored caption generation

&#x20;   image\_pipeline.py        # platform image variant generation

&#x20;   social\_publisher.py      # SocialPublisher interface + fake adapters

&#x20;   publish\_service.py       # shared publish logic (used by API + scheduler)

&#x20;   crypto\_utils.py           # AES-GCM token encryption

&#x20;   webhook\_verifier.py       # HMAC signature verification

fake\_platform/

&#x20; main.py                    # simulated social platform (OAuth, publish, webhooks)

tests/

&#x20; test\_db.py

&#x20; test\_crypto\_utils.py

&#x20; test\_social\_publisher.py

&#x20; test\_rate\_limit\_backoff.py

&#x20; test\_crash\_recovery.py

&#x20; test\_webhook\_security.py

media/                       # generated image variants (gitignored per-campaign output)

EVIDENCE.md                  # pasted proof for every Definition-of-Done checkbox

BUILDLOG.md                  # AI-usage log

capstone.yaml                # evaluator manifest

```

