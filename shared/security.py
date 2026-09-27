"""Password hashing (stdlib PBKDF2) and JWT helpers."""

import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt

_ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    salt_hex, _, digest_hex = stored.partition("$")
    candidate = hash_password(password, bytes.fromhex(salt_hex)).partition("$")[2]
    return hmac.compare_digest(candidate, digest_hex)


def create_token(user_id: int, secret: str, ttl_minutes: int, scope: str = "shop") -> str:
    """scope separates identities: "shop" = ShopBot customer, "lab" = AI Testing Lab user."""
    now = datetime.now(UTC)
    payload = {"sub": str(user_id), "scope": scope, "iat": now,
               "exp": now + timedelta(minutes=ttl_minutes)}
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_token(token: str, secret: str, scope: str = "shop") -> int | None:
    """Return the user id, or None for a missing/invalid/expired token or one of another scope
    (a lab user id must never be read as a customer id). Pre-scope tokens count as "shop"."""
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
        if payload.get("scope", "shop") != scope:
            return None
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
