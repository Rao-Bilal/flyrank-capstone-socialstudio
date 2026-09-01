"""
SQLite persistence layer.
Real persistence with proper schema, as required by the shared
requirements (#4: "Real persistence - schema as migrations, right indexes").
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("campaigns.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            source_post_title TEXT NOT NULL,
            source_post_body TEXT NOT NULL,
            source_post_url TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            scheduled_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS social_post_entries (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            image_path TEXT,
            caption TEXT,
            idempotency_key TEXT NOT NULL,
            platform_post_id TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            last_error TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
            UNIQUE (campaign_id, platform)
        );

        CREATE INDEX IF NOT EXISTS idx_entries_campaign
            ON social_post_entries(campaign_id);

        CREATE INDEX IF NOT EXISTS idx_entries_idempotency_key
            ON social_post_entries(idempotency_key);
    """)
    conn.commit()
    conn.close()