import base64
import hashlib
import hmac
import os
import time
from collections import defaultdict

from .. import settings

WINDOW, MAX_FAILS = 600, 5      # 5 bad logins per client per 10 minutes
FAIL_DELAY = 0.4                # slows down guessing on every failure
_failures: dict[str, list[float]] = defaultdict(list)


def hash_password(password: str) -> str:
    """scrypt hash for APP_PASSWORD_HASH, so the plaintext never sits in .env."""
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return "scrypt:" + base64.urlsafe_b64encode(salt).decode() + ":" + base64.urlsafe_b64encode(digest).decode()


def verify(password: str) -> bool:
    stored = settings.PASSWORD_HASH
    if not stored:
        return hmac.compare_digest(password.encode(), settings.password().encode())
    try:
        _, salt, digest = stored.split(":")
        got = hashlib.scrypt(password.encode(), salt=base64.urlsafe_b64decode(salt), n=2**14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got, base64.urlsafe_b64decode(digest))
    except Exception:
        return False


def locked(ip: str) -> bool:
    cutoff = time.time() - WINDOW
    _failures[ip] = [t for t in _failures[ip] if t > cutoff]
    if not _failures[ip]:
        _failures.pop(ip, None)
    return len(_failures.get(ip, ())) >= MAX_FAILS


def check(username: str, password: str, ip: str) -> bool:
    ok_user = hmac.compare_digest(username.encode(), settings.USERNAME.encode())
    ok_pw = verify(password)  # always evaluated, so timing doesn't reveal which half was wrong
    if ok_user and ok_pw:
        _failures.pop(ip, None)
        return True
    _failures[ip].append(time.time())
    time.sleep(FAIL_DELAY)
    return False
