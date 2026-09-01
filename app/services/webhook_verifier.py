"""
Webhook signature verification.
The fake_platform server signs delivery events with HMAC-SHA256 using a
shared secret. We MUST verify this signature before trusting any status
update - forged or modified events get rejected with 400.
"""

import hashlib
import hmac

# Must match WEBHOOK_SECRET in fake_platform/main.py
WEBHOOK_SECRET = "fake-platform-shared-secret-change-me"


def verify_signature(raw_body: bytes, provided_signature: str) -> bool:
    """
    Recomputes the HMAC signature over raw_body and compares it to
    provided_signature using a constant-time comparison (hmac.compare_digest)
    to avoid timing attacks.
    """
    expected_signature = hmac.new(
        WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected_signature, provided_signature)