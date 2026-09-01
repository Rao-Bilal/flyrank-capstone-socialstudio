"""
Token encryption utilities.
Uses AES-GCM with a random IV per encryption - required so OAuth tokens
are never stored in plaintext (Definition of Done: "Grep the database and
logs -> no plaintext token anywhere").
"""

import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# In production this key would come from an env var / secret manager.
# For local dev, we generate one and store it in an env var if not present.
_KEY_ENV_VAR = "TOKEN_ENCRYPTION_KEY"


def _get_key() -> bytes:
    key_b64 = os.environ.get(_KEY_ENV_VAR)
    if not key_b64:
        # Dev fallback: generate a key for this process only.
        # In real deployment, set TOKEN_ENCRYPTION_KEY in .env and never commit it.
        key = AESGCM.generate_key(bit_length=256)
        os.environ[_KEY_ENV_VAR] = base64.b64encode(key).decode()
        return key
    return base64.b64decode(key_b64)


def encrypt_token(plaintext_token: str) -> tuple[bytes, bytes]:
    """
    Encrypts a token. Returns (ciphertext, iv).
    A fresh random IV is generated every call - required, reusing an IV
    with AES-GCM breaks the encryption's security guarantees.
    """
    key = _get_key()
    aesgcm = AESGCM(key)
    iv = os.urandom(12)  # 96-bit IV, standard for GCM
    ciphertext = aesgcm.encrypt(iv, plaintext_token.encode(), None)
    return ciphertext, iv


def decrypt_token(ciphertext: bytes, iv: bytes) -> str:
    """Decrypts a token given its ciphertext and the IV used to encrypt it."""
    key = _get_key()
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(iv, ciphertext, None)
    return plaintext.decode()