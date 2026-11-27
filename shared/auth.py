"""Login gate for the ChronoGaze app.

Accounts live in db/users.json as {username: "pbkdf2_sha256$<iter>$<salt>$<hash>"};
plain passwords are never stored. There is no sign-up page: add an account with

    .venv/Scripts/python.exe -m shared.auth add <username>

which asks for the password without echoing it.

Security level: salted PBKDF2-SHA256 hashes, constant-time comparison, one
generic error message, and a short lockout after repeated failures per
username. The login lasts for the browser session (a page refresh logs out).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from pathlib import Path

USERS_PATH = Path(__file__).resolve().parent.parent / "db" / "users.json"
ITERATIONS = 260_000
MAX_FAILS = 5          # failed attempts before a lockout
LOCK_SECONDS = 60      # lockout length

_fails: dict[str, list[float]] = {}   # username -> recent failure times (shared by all sessions)
_fails_lock = threading.Lock()


def hash_password(password: str, salt: str | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, _ = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        return hmac.compare_digest(hash_password(password, salt, int(iterations)), stored)
    except (ValueError, TypeError):
        return False


def load_users(path: Path = USERS_PATH) -> dict[str, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


_DUMMY = hash_password("not-a-real-password")


def locked_for(username: str, now: float | None = None) -> float:
    """Seconds left on this username's lockout (0 when it may try again)."""
    now = time.time() if now is None else now
    with _fails_lock:
        recent = [t for t in _fails.get(username, []) if now - t < LOCK_SECONDS]
        _fails[username] = recent
        if len(recent) >= MAX_FAILS:
            return LOCK_SECONDS - (now - recent[-MAX_FAILS])
    return 0.0


def check_login(username: str, password: str, users: dict[str, str] | None = None) -> bool:
    """True when the pair matches an account. Counts failures for the lockout."""
    users = load_users() if users is None else users
    username = username.strip()
    stored = users.get(username)
    # Hash even for unknown names so timing does not reveal which usernames exist.
    ok = verify_password(password, stored or _DUMMY) and stored is not None
    with _fails_lock:
        if ok:
            _fails.pop(username, None)
        else:
            _fails.setdefault(username, []).append(time.time())
    return ok


def add_user(username: str, password: str, path: Path = USERS_PATH) -> None:
    users = load_users(path)
    users[username.strip()] = hash_password(password)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, indent=2) + "\n", encoding="utf-8")


LOGIN_CSS = """<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stHeader"], [data-testid="stToolbar"] { display: none; }
.block-container { max-width: 380px; padding-top: 18vh; }
</style>"""


def require_login() -> str:
    """Show the login page and stop the script until the user signs in.

    Returns the signed-in username.
    """
    import streamlit as st

    user = st.session_state.get("auth_user")
    if user:
        return user

    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center'>ChronoGaze</h2>", unsafe_allow_html=True)
    with st.form("login", border=True):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Login", type="primary", width="stretch")

    if submitted:
        name = username.strip()
        wait = locked_for(name)
        if wait > 0:
            st.error(f"Terlalu banyak percobaan gagal. Coba lagi dalam {int(wait) + 1} detik.")
        elif name and password and check_login(name, password):
            st.session_state["auth_user"] = name
            st.rerun()
        else:
            st.error("Username atau password salah.")
    st.stop()


def logout() -> None:
    import streamlit as st

    st.session_state.pop("auth_user", None)


if __name__ == "__main__":
    import getpass
    import sys

    if len(sys.argv) != 3 or sys.argv[1] != "add":
        sys.exit("usage: python -m shared.auth add <username>")
    pw = getpass.getpass("Password: ")
    if pw != getpass.getpass("Ulangi password: "):
        sys.exit("Password tidak sama.")
    add_user(sys.argv[2], pw)
    print(f"Akun {sys.argv[2]} disimpan di {USERS_PATH}")
