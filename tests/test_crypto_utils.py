from app.services.crypto_utils import encrypt_token, decrypt_token


def test_encrypt_decrypt_roundtrip():
    original = "fake-token-super-secret-12345"
    ciphertext, iv = encrypt_token(original)

    assert original.encode() not in ciphertext

    decrypted = decrypt_token(ciphertext, iv)
    assert decrypted == original


def test_random_iv_each_time():
    token = "same-token-encrypted-twice"
    ciphertext1, iv1 = encrypt_token(token)
    ciphertext2, iv2 = encrypt_token(token)

    assert iv1 != iv2
    assert ciphertext1 != ciphertext2