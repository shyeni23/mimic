"""
POST /api/auth/staff-login -- the real check behind "Start Your Shift"
(replaces AdminLogin.js's old unconditional login()). See app/services/auth.py
for why this is a single shared kiosk credential rather than per-user
accounts, and scripts/set_staff_password.py to configure one.
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.services.auth import make_token, verify_password, verify_token

router = APIRouter(prefix="/api/auth", tags=["auth"])


class StaffLoginRequest(BaseModel):
    username: str
    password: str


@router.post("/staff-login")
def staff_login(req: StaffLoginRequest):
    if not settings.staff_password_hash or not settings.staff_login_secret:
        raise HTTPException(
            status_code=503,
            detail="Staff login isn't configured on this mirror -- run "
                   "scripts/set_staff_password.py and paste the printed lines "
                   "into backend/.env.")
    if req.username != settings.staff_username or not verify_password(req.password, settings.staff_password_hash):
        # Same message either way -- never reveal which half was wrong.
        raise HTTPException(status_code=401, detail="Wrong username or password.")
    token, expires_at = make_token(req.username)
    return {"token": token, "expires_at": expires_at}


@router.get("/verify")
def verify(authorization: str | None = Header(default=None)):
    """The frontend calls this once on load when it has a stored token, to
    confirm it's still valid -- catches expiry AND a backend restart with a
    freshly-generated secret, neither of which a purely client-side expiry
    check would catch."""
    token = (authorization or "").removeprefix("Bearer ").strip()
    username = verify_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Session expired -- please sign in again.")
    return {"username": username}
