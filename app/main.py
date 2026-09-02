"""
Main FastAPI application.
Wires together: campaigns, image/caption generation, publishing (via
SocialPublisher adapters), durable scheduling, and webhook-verified
status tracking.
"""

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from app.db import get_connection, init_db
from app.scheduler import schedule_campaign_publish, start_scheduler, shutdown_scheduler
from app.services.caption_composer import generate_all_captions
from app.services.image_pipeline import generate_all_variants
from app.services.publish_service import publish_campaign
from app.services.webhook_verifier import verify_signature
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="FlyRank Social Campaign Publisher")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MEDIA_DIR = Path("media")

MEDIA_DIR.mkdir(exist_ok=True)
app.mount("/media", StaticFiles(directory="media"), name="media")


@app.on_event("startup")
def on_startup():
    init_db()
    MEDIA_DIR.mkdir(exist_ok=True)
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    shutdown_scheduler()


@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/dashboard")
def dashboard():
    return FileResponse("app/static/index.html")


@app.post("/campaigns")
def create_campaign(payload: dict):
    """Create a campaign from a blog post (title, body, url)."""
    campaign_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        """INSERT INTO campaigns (id, source_post_title, source_post_body, source_post_url)
           VALUES (?, ?, ?, ?)""",
        (campaign_id, payload["title"], payload["body"], payload.get("url", "")),
    )
    conn.commit()
    conn.close()
    return {"campaign_id": campaign_id, "status": "draft"}


@app.post("/campaigns/{campaign_id}/generate")
def generate_content(campaign_id: str, source_image_path: str):
    """
    Runs the image variant + caption pipeline for a campaign and stores
    a SocialPostEntry per platform.
    """
    conn = get_connection()
    campaign = conn.execute(
        "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    output_dir = MEDIA_DIR / campaign_id
    image_paths = generate_all_variants(source_image_path, str(output_dir))
    captions = generate_all_captions(
        campaign["source_post_title"], campaign["source_post_body"][:200]
    )

    for platform in image_paths:
        entry_id = str(uuid.uuid4())
        idempotency_key = f"{campaign_id}:{platform}"
        conn.execute(
            """INSERT OR IGNORE INTO social_post_entries
               (id, campaign_id, platform, image_path, caption, idempotency_key, status)
               VALUES (?, ?, ?, ?, ?, ?, 'queued')""",
            (entry_id, campaign_id, platform, image_paths[platform], captions[platform], idempotency_key),
        )

    conn.commit()
    conn.close()
    return {"campaign_id": campaign_id, "platforms": list(image_paths.keys())}


@app.post("/campaigns/{campaign_id}/publish-now")
async def publish_now(campaign_id: str):
    """
    Publishes all queued entries for a campaign immediately, using the
    same publish_campaign() logic the durable scheduler calls - so
    behavior is identical whether triggered live or by a scheduled job.
    """
    conn = get_connection()
    exists = conn.execute(
        "SELECT 1 FROM social_post_entries WHERE campaign_id = ?", (campaign_id,)
    ).fetchone()
    conn.close()
    if not exists:
        raise HTTPException(status_code=404, detail="No entries for this campaign")

    result = await publish_campaign(campaign_id)
    return result


@app.post("/campaigns/{campaign_id}/schedule")
def schedule_campaign(campaign_id: str, scheduled_at: str):
    """
    Schedules a campaign to be published later.

    scheduled_at: ISO 8601 datetime string, e.g. "2026-09-02T21:00:00".

    The job is durable: it's stored in jobs.db (via APScheduler's
    SQLAlchemyJobStore), so if this process crashes or restarts before
    the scheduled time, the job survives and still fires - and if the
    scheduled time already passed while the process was down, it fires
    on restart (within misfire_grace_time) instead of being lost.
    """
    conn = get_connection()
    campaign = conn.execute(
        "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        run_date = datetime.fromisoformat(scheduled_at)
    except ValueError:
        conn.close()
        raise HTTPException(status_code=422, detail="scheduled_at must be ISO 8601, e.g. 2026-09-02T21:00:00")

    conn.execute(
        "UPDATE campaigns SET status = 'scheduled', scheduled_at = ?, updated_at = ? WHERE id = ?",
        (scheduled_at, datetime.utcnow().isoformat(), campaign_id),
    )
    conn.commit()
    conn.close()

    schedule_campaign_publish(campaign_id, run_date)

    return {"campaign_id": campaign_id, "status": "scheduled", "scheduled_at": scheduled_at}


@app.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str):
    conn = get_connection()
    campaign = conn.execute(
        "SELECT * FROM campaigns WHERE id = ?", (campaign_id,)
    ).fetchone()
    if not campaign:
        conn.close()
        raise HTTPException(status_code=404, detail="Campaign not found")

    entries = conn.execute(
        "SELECT * FROM social_post_entries WHERE campaign_id = ?", (campaign_id,)
    ).fetchall()
    conn.close()

    return {
        "campaign": dict(campaign),
        "entries": [dict(e) for e in entries],
    }


@app.post("/webhook/social-delivery")
async def social_delivery_webhook(request: Request):
    """
    Receives delivery events from the fake platform.
    Verifies HMAC signature - forged/modified events get 400.
    Only a verified event may flip a SocialPostEntry to 'published'.

    Matches on idempotency_key rather than platform_post_id: the
    idempotency_key is written into social_post_entries during
    /generate, well before publish is ever called, so it is guaranteed
    to exist by the time any webhook can possibly arrive - even though
    the fake platform sends the webhook synchronously, before our own
    code has a chance to persist platform_post_id.

    After flipping an entry to 'published', also checks whether every
    entry belonging to that entry's campaign is now published, and if
    so rolls the parent campaign's own status up to 'published' too.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not verify_signature(raw_body, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = await request.json()
    platform_post_id = payload["platform_post_id"]
    idempotency_key = payload["idempotency_key"]

    conn = get_connection()
    conn.execute(
        """UPDATE social_post_entries
           SET status = 'published', platform_post_id = ?, updated_at = ?
           WHERE idempotency_key = ?""",
        (platform_post_id, datetime.utcnow().isoformat(), idempotency_key),
    )

    campaign_id = idempotency_key.split(":")[0]
    remaining = conn.execute(
        """SELECT COUNT(*) as cnt FROM social_post_entries
           WHERE campaign_id = ? AND status != 'published'""",
        (campaign_id,),
    ).fetchone()
    if remaining["cnt"] == 0:
        conn.execute(
            "UPDATE campaigns SET status = 'published', updated_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), campaign_id),
        )

    conn.commit()
    conn.close()

    return {"received": True}