import shared.auth as auth
from shared.auth import check_login, hash_password, locked_for, verify_password


def test_hash_roundtrip_and_salted():
    h1, h2 = hash_password("rahasia kita"), hash_password("rahasia kita")
    assert h1 != h2                       # different salts
    assert verify_password("rahasia kita", h1)
    assert not verify_password("rahasia  kita", h1)
    assert not verify_password("x", "garbage")


def test_check_login_and_lockout(monkeypatch):
    monkeypatch.setattr(auth, "_fails", {})
    users = {"0811": hash_password("benar")}
    assert check_login(" 0811 ", "benar", users)
    assert not check_login("0811", "salah", users)
    assert not check_login("tidakada", "benar", users)
    for _ in range(auth.MAX_FAILS - 1):
        check_login("0811", "salah", users)
    assert locked_for("0811") > 0
    assert locked_for("0811", now=10**12) == 0      # lockout expires


def test_real_accounts_file_holds_only_hashes():
    users = auth.load_users()
    assert len(users) >= 3
    assert all(v.startswith("pbkdf2_sha256$") for v in users.values())
