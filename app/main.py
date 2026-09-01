"""
Main FastAPI application.
Wires together: campaigns, image/caption generation, publishing (via
SocialPublisher adapters), and webhook-verified status tracking.
"""

import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from app.db import get_connection, init_db
from app.services.caption_composer import generate_all_captions
from app.services.image_pipeline import generate_all_variants
from app.services.social_publisher import FakeInstagramPublisher, FakeXPublisher
from app.services.webhook_verifier import verify_signature

app = FastAPI(title="FlyRank Social Campaign Publisher")

PUBLISHERS = {
    "instagram": FakeInstagramPublisher(),
    "x": FakeXPublisher(),
}

MEDIA_DIR = Path("media")
WEBHOOK_URL = "http://127.0.0.1:8000/webhook/social-delivery"


@app.on_event("startup")
def on_startup():
    init_db()
    MEDIA_DIR.mkdir(exist_ok=True)


@app.get("/health")
def health():
    return {"status": "ok"}


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
    Publishes all queued entries for a campaign immediately.
    Idempotent: calling this twice for the same campaign does not create
    duplicate posts, because each entry's idempotency_key is stable and
    the adapter/fake-platform layer enforces one-post-per-key.
    """
    conn = get_connection()
    entries = conn.execute(
        "SELECT * FROM social_post_entries WHERE campaign_id = ?", (campaign_id,)
    ).fetchall()
    if not entries:
        conn.close()
        raise HTTPException(status_code=404, detail="No entries for this campaign")

    conn.execute(
        "UPDATE campaigns SET status = 'publishing', updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), campaign_id),
    )
    conn.commit()

    results = []
    for entry in entries:
        publisher = PUBLISHERS[entry["platform"]]
        token = await publisher.get_access_token()

        result = await publisher.publish(
            idempotency_key=entry["idempotency_key"],
            caption=entry["caption"],
            image_path=entry["image_path"],
            webhook_url=WEBHOOK_URL,
            access_token=token,
        )

        conn.execute(
            """UPDATE social_post_entries
               SET platform_post_id = ?, updated_at = ?
               WHERE id = ? AND status != 'published'""",
            (result.platform_post_id, datetime.utcnow().isoformat(), entry["id"]),
        )
        conn.execute(
            """UPDATE social_post_entries
               SET status = 'publishing'
               WHERE id = ? AND status = 'queued'""",
            (entry["id"],),
        )
        conn.commit()
        results.append({"platform": entry["platform"], "platform_post_id": result.platform_post_id})

    conn.close()
    return {"campaign_id": campaign_id, "results": results}


@app.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: str):
    """Fetch a campaign and its associated social platform entries."""
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
        "entries": [dict(entry) for entry in entries]
    }


@app.post("/webhook/social-delivery")
async def social_delivery_webhook(request: Request):
    """
    Receives delivery status from the fake platform.
    Updates the specific entry and rolls up the status to the campaign.
    """
    data = await request.json()
    
    x_signature = request.headers.get("X-Signature")
    verify_signature(await request.body(), x_signature) 
    
    idempotency_key = data.get("idempotency_key")
    platform_post_id = data.get("platform_post_id")
    
    if not idempotency_key or not platform_post_id:
        raise HTTPException(status_code=400, detail="Missing fields in webhook payload")

    conn = get_connection()
    
    conn.execute(
        """UPDATE social_post_entries 
           SET status = 'published', platform_post_id = ?, updated_at = ? 
           WHERE idempotency_key = ?""",
        (platform_post_id, datetime.utcnow().isoformat(), idempotency_key),
    )

    campaign_id = idempotency_key.split(":")[0]
    remaining = conn.execute(
        "SELECT COUNT(*) as cnt FROM social_post_entries WHERE campaign_id = ? AND status != 'published'",
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