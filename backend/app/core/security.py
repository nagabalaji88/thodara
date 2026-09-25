import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()
_dummy_password_hash = password_hash.hash("invalid-account-dummy-password")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, encoded_hash: str | None) -> bool:
    return password_hash.verify(password, encoded_hash or _dummy_password_hash)


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_token_match(candidate: str, expected_digest: str) -> bool:
    return secrets.compare_digest(token_digest(candidate), expected_digest)


def session_expiry(hours: int) -> datetime:
    return datetime.now(UTC) + timedelta(hours=hours)
