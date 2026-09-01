import hashlib
import hmac

from app.services.webhook_verifier import verify_signature, WEBHOOK_SECRET


def test_valid_signature_is_accepted():
    body = b'{"platform_post_id": "post-123", "status": "published"}'
    correct_signature = hmac.new(
        WEBHOOK_SECRET.encode(), body, hashlib.sha256
    ).hexdigest()

    assert verify_signature(body, correct_signature) is True


def test_forged_signature_is_rejected():
    body = b'{"platform_post_id": "post-123", "status": "published"}'
    forged_signature = "0000000000000000000000000000000000000000000000000000000000000000"

    assert verify_signature(body, forged_signature) is False


def test_modified_body_with_old_signature_is_rejected():
    original_body = b'{"platform_post_id": "post-123", "status": "published"}'
    signature_for_original = hmac.new(
        WEBHOOK_SECRET.encode(), original_body, hashlib.sha256
    ).hexdigest()

    # Attacker modifies the body but reuses the old signature
    tampered_body = b'{"platform_post_id": "post-123", "status": "failed"}'

    assert verify_signature(tampered_body, signature_for_original) is False