"""Two-step sign-in primitives (ADR-0015): authenticator codes, secret encryption, backup codes.

Authenticator codes follow RFC 6238 (TOTP): HMAC-SHA1, 30-second steps, 6 digits, which every
free authenticator app supports. Secrets are stored encrypted with AES-GCM; backup codes are
stored only as keyed hashes.
"""

import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
import uuid
from urllib.parse import quote

import segno
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

STEP_SECONDS = 30
DIGITS = 6
# One step either side allows for a phone clock that is up to 30 seconds off.
DRIFT_STEPS = 1
BACKUP_CODE_COUNT = 10
# No 0/O, 1/I/L: codes are read off paper.
BACKUP_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
ISSUER = "Thodara"


def new_secret() -> str:
    """A 160-bit secret in base32, as authenticator apps expect."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii")


def code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**DIGITS).zfill(DIGITS)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // STEP_SECONDS)


def matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The time step the code belongs to, or None. The caller rejects steps already used."""
    code = code.strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - DRIFT_STEPS, step + DRIFT_STEPS + 1):
        if hmac.compare_digest(code_at(secret, candidate), code):
            return candidate
    return None


def _key() -> bytes:
    return base64.b64decode(get_settings().two_step_key)


def encrypt_secret(secret: str, user_id: uuid.UUID) -> str:
    nonce = secrets.token_bytes(12)
    sealed = AESGCM(_key()).encrypt(nonce, secret.encode("ascii"), user_id.bytes)
    return "v1:" + base64.b64encode(nonce + sealed).decode("ascii")


def decrypt_secret(stored: str, user_id: uuid.UUID) -> str:
    """Raises ValueError if the value was not sealed for this user with the current key."""
    version, _, payload = stored.partition(":")
    if version != "v1":
        raise ValueError("Unknown secret format")
    raw = base64.b64decode(payload)
    try:
        return AESGCM(_key()).decrypt(raw[:12], raw[12:], user_id.bytes).decode("ascii")
    except InvalidTag as exc:
        raise ValueError("Secret cannot be opened with the current key") from exc


def new_backup_codes() -> list[str]:
    codes = set()
    while len(codes) < BACKUP_CODE_COUNT:
        raw = "".join(secrets.choice(BACKUP_ALPHABET) for _ in range(10))
        codes.add(f"{raw[:5]}-{raw[5:]}")
    return sorted(codes)


def normalise_backup_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def backup_code_hash(code: str, user_id: uuid.UUID) -> str:
    message = user_id.bytes + normalise_backup_code(code).encode("ascii", "ignore")
    return hmac.new(_key(), message, hashlib.sha256).hexdigest()


def looks_like_backup_code(code: str) -> bool:
    return len(normalise_backup_code(code)) == 10


def otpauth_uri(secret: str, account: str) -> str:
    label = quote(f"{ISSUER}:{account}", safe=":")
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={ISSUER}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )


def qr_svg(uri: str) -> str:
    buffer = io.BytesIO()
    segno.make(uri, error="m").save(buffer, kind="svg", scale=5, border=2, xmldecl=False)
    return buffer.getvalue().decode("utf-8")
