"""Credential primitives: no plaintext password/token persistence."""
import base64
import hashlib
import hmac
import secrets


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return "600000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(hashed).decode()


def verify_password(password: str, stored: str) -> bool:
    rounds, salt, expected = stored.split("$")
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(rounds))
    return hmac.compare_digest(actual, base64.b64decode(expected))
