"""
Staff authentication (app/services/auth.py) -- the real check behind
"Start Your Shift", which previously accepted any email/password at all
(AdminLogin.js called login() unconditionally, no backend check existed).
"""
import time

import pytest
from fastapi import HTTPException

from app.services import auth


class TestPasswordHashing:
    def test_correct_password_verifies(self):
        stored = auth.hash_password("correct horse battery staple")
        assert auth.verify_password("correct horse battery staple", stored)

    def test_wrong_password_fails(self):
        stored = auth.hash_password("correct horse battery staple")
        assert not auth.verify_password("wrong password", stored)

    def test_same_password_hashes_differently_each_time(self):
        """Random salt per call -- two staff members with the same password
        (or the same password set twice) must not produce identical hashes,
        which would otherwise leak that fact to anyone with DB/.env access."""
        a = auth.hash_password("same password here")
        b = auth.hash_password("same password here")
        assert a != b
        assert auth.verify_password("same password here", a)
        assert auth.verify_password("same password here", b)

    def test_empty_or_malformed_stored_hash_never_verifies(self):
        assert not auth.verify_password("anything", "")
        assert not auth.verify_password("anything", "not-a-valid-hash")
        assert not auth.verify_password("anything", "zz:zz")  # not valid hex

    def test_plain_password_is_never_in_the_stored_value(self):
        stored = auth.hash_password("supersecretpassword")
        assert "supersecretpassword" not in stored


class TestTokens:
    def test_token_roundtrip(self, monkeypatch):
        monkeypatch.setattr(auth.settings, "staff_login_secret", "test-secret")
        token, expires_at = auth.make_token("staff")
        assert auth.verify_token(token) == "staff"
        assert expires_at > time.time()

    def test_tampered_signature_is_rejected(self, monkeypatch):
        monkeypatch.setattr(auth.settings, "staff_login_secret", "test-secret")
        token, _ = auth.make_token("staff")
        payload_b64, sig = token.split(".", 1)
        tampered = payload_b64 + "." + ("0" if sig[0] != "0" else "1") + sig[1:]
        assert auth.verify_token(tampered) is None

    def test_token_signed_with_different_secret_is_rejected(self, monkeypatch):
        """Simulates a backend restart generating a fresh secret (if the
        user never pinned STAFF_LOGIN_SECRET in .env) -- old tokens must not
        silently keep working."""
        monkeypatch.setattr(auth.settings, "staff_login_secret", "secret-a")
        token, _ = auth.make_token("staff")
        monkeypatch.setattr(auth.settings, "staff_login_secret", "secret-b")
        assert auth.verify_token(token) is None

    def test_expired_token_is_rejected(self, monkeypatch):
        monkeypatch.setattr(auth.settings, "staff_login_secret", "test-secret")
        monkeypatch.setattr(auth, "TOKEN_LIFETIME_S", -1)  # already expired on creation
        token, _ = auth.make_token("staff")
        assert auth.verify_token(token) is None

    @pytest.mark.parametrize("bad", [None, "", "garbage", "no-dot-here", "a.b.c", "a." + "z" * 64])
    def test_malformed_tokens_never_raise(self, bad, monkeypatch):
        monkeypatch.setattr(auth.settings, "staff_login_secret", "test-secret")
        assert auth.verify_token(bad) is None


class TestRequireStaffDependency:
    def test_missing_header_raises_401(self):
        with pytest.raises(HTTPException) as exc:
            auth.require_staff(authorization=None)
        assert exc.value.status_code == 401

    def test_valid_bearer_token_passes(self, monkeypatch):
        monkeypatch.setattr(auth.settings, "staff_login_secret", "test-secret")
        token, _ = auth.make_token("staff")
        assert auth.require_staff(authorization=f"Bearer {token}") == "staff"

    def test_invalid_token_raises_401(self, monkeypatch):
        monkeypatch.setattr(auth.settings, "staff_login_secret", "test-secret")
        with pytest.raises(HTTPException) as exc:
            auth.require_staff(authorization="Bearer not-a-real-token")
        assert exc.value.status_code == 401
