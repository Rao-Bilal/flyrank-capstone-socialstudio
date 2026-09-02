"""
Shared publish logic used by BOTH the immediate /publish-now endpoint
and the durable scheduler's background job. Keeping this in one place
means "publish this campaign" behaves identically whether triggered
by a live API call or by a scheduled job waking up later.
"""

from datetime import datetime

from app.db import get_connection
from app.services.social_publisher import FakeInstagramPublisher, FakeXPublisher

PUBLISHERS = {
    "instagram": FakeInstagramPublisher(),
    "x": FakeXPublisher(),
}

WEBHOOK_URL = "http://127.0.0.1:8000/webhook/social-delivery"


async def publish_campaign(campaign_id: str) -> dict:
    """
    Publishes all queued entries for a campaign.

    Safe to call multiple times for the same campaign (e.g. a crashed
    worker restarting and re-running a job): each entry's idempotency_key
    is stable, so the fake platform (and our own DB checks) prevent
    duplicate posts. Entries already 'published' are skipped entirely -
    this is what makes crash-recovery safe (Probe 3): a restarted worker
    re-running this function does not re-publish anything already done.
    """
    conn = get_connection()
    entries = conn.execute(
        "SELECT * FROM social_post_entries WHERE campaign_id = ?", (campaign_id,)
    ).fetchall()

    if not entries:
        conn.close()
        return {"campaign_id": campaign_id, "results": [], "skipped": True}

    conn.execute(
        "UPDATE campaigns SET status = 'publishing', updated_at = ? WHERE id = ?",
        (datetime.utcnow().isoformat(), campaign_id),
    )
    conn.commit()

    results = []
    for entry in entries:
        if entry["status"] == "published":
            # Already done in a previous run (e.g. before a crash) - skip.
            results.append({
                "platform": entry["platform"],
                "platform_post_id": entry["platform_post_id"],
                "skipped_already_published": True,
            })
            continue

        publisher = PUBLISHERS[entry["platform"]]
        token = await publisher.get_access_token()

        result = await publisher.publish(
            idempotency_key=entry["idempotency_key"],
            caption=entry["caption"],
            image_path=entry["image_path"],
            webhook_url=WEBHOOK_URL,
            access_token=token,
        )

        # Guarded updates - never stomp a row the webhook already
        # flipped to 'published' while we were awaiting publish().
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