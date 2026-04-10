from app.services.storage.crypto import DpapiCipher


def test_dpapi_cipher_roundtrip() -> None:
    cipher = DpapiCipher(b"test-entropy")
    payload = b"secret payload"

    encrypted = cipher.encrypt(payload)
    decrypted = cipher.decrypt(encrypted)

    assert encrypted != payload
    assert decrypted == payload
