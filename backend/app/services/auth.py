"""
Staff authentication (Module 5's missing auth).

The "Start Your Shift" screen used to accept any email/password at all --
AdminLogin.js called login() unconditionally on submit, and no backend
endpoint existed to check anything. This is the real thing: a single shared
staff credential (this is a kiosk shift-start gate, not a multi-employee
account system -- matching what "Start Your Shift" actually means), hashed
with PBKDF2-HMAC and verified server-side, producing a signed, expiring
token the frontend must present on every staff-only request.

No new dependency: PBKDF2-HMAC and HMAC-SHA256 are both in the stdlib
(hashlib, hmac). That matters here specifically -- this project has already
been bitten once by a dependency upgrade quietly breaking an unrelated model
(see HANDOFF_MODULE3.md's gradio_client/huggingface-hub incident), so a new
auth library is not worth that risk for what is fundamentally a shift PIN.
"""
import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Header, HTTPException

from app.config import settings

PBKDF2_ITERATIONS = 200_000
# A token lasts one shift, matching the UI's own "Start Your Shift" framing
# -- long enough that a cashier isn't re-entering a password mid-shift,
# short enough that a token leaked once doesn't work forever.
TOKEN_LIFETIME_S = 12 * 3600


def hash_password(password: str, salt: bytes | None = None) -> str:
    """"salt_hex:digest_hex" -- what goes in STAFF_PASSWORD_HASH. Never store
    or compare the plain password anywhere past this call."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or ":" not in stored:
        return False
    salt_hex, digest_hex = stored.split(":", 1)
    try:
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    # constant-time compare -- a naive == leaks timing information about
    # how many leading hex characters matched.
    return hmac.compare_digest(candidate.hex(), digest_hex)


def _sign(payload: str) -> str:
    secret = settings.staff_login_secret.encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def make_token(username: str) -> tuple[str, int]:
    expires_at = int(time.time()) + TOKEN_LIFETIME_S
    payload = f"{username}:{expires_at}"
    token = base64.urlsafe_b64encode(payload.encode()).decode() + "." + _sign(payload)
    return token, expires_at


def verify_token(token: str | None) -> str | None:
    """The username if the token is validly signed and unexpired, else None.
    Never raises -- a malformed or absent token is just invalid, not a
    server error."""
    if not token:
        return None
    try:
        payload_b64, sig = token.split(".", 1)
        payload = base64.urlsafe_b64decode(payload_b64.encode()).decode()
        if not hmac.compare_digest(_sign(payload), sig):
            return None
        username, expires_at = payload.rsplit(":", 1)
        if int(expires_at) < time.time():
            return None
        return username
    except Exception:
        return None


def require_staff(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: protects every staff-only endpoint. Raises 401
    rather than letting the request through on a missing/bad/expired token --
    this is the actual security boundary; the frontend's own login screen is
    cosmetic without this."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Staff sign-in required.")
    return username
