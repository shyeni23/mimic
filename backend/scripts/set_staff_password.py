"""
Generates the backend/.env lines for staff login (see app/services/auth.py).
Never prints or stores the plain password anywhere past this one run.

Run:
    python scripts/set_staff_password.py                         # prompts for a password
    python scripts/set_staff_password.py --password "..."        # non-interactive
    python scripts/set_staff_password.py --username manager --password "..."
"""
import argparse
import getpass
import secrets
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.services.auth import hash_password


def run(username: str, password: str):
    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)
    pw_hash = hash_password(password)
    login_secret = secrets.token_hex(32)
    print("\nAdd these lines to backend/.env (overwrite any existing STAFF_* lines):\n")
    print(f"STAFF_USERNAME={username}")
    print(f"STAFF_PASSWORD_HASH={pw_hash}")
    print(f"STAFF_LOGIN_SECRET={login_secret}")
    print("\nThen restart the backend. Staff sign in at /login with this "
          "username and the password you just typed -- it is not stored "
          "anywhere, only its hash above.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="staff")
    parser.add_argument("--password", default=None, help="Omit to be prompted (not echoed).")
    args = parser.parse_args()
    pw = args.password or getpass.getpass("New staff password: ")
    run(args.username, pw)
