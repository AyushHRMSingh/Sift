"""Runtime settings: environment variables, data dir, persisted secrets."""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> None:
    """Minimal .env reader (KEY=value lines); real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.split(" #")[0].strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_env(ROOT / ".env")
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", 48213))
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "1") != "0"  # set 0 only for plain-http testing
USERNAME = os.environ.get("APP_USER", "admin")
PASSWORD_HASH = os.environ.get("APP_PASSWORD_HASH", "")   # preferred over APP_PASSWORD; make one with: python -m jobfinder hash-password
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")            # used for links in alerts
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
DISCORD_MIN_MATCH = int(os.environ.get("DISCORD_MIN_MATCH", 70))
REMINDER_TIMES = [t.strip() for t in os.environ.get("REMINDER_TIMES", "18:30,20:30").split(",") if t.strip()]
REMINDER_TZ = os.environ.get("REMINDER_TZ", "Asia/Kolkata")
STALE_DAYS = int(os.environ.get("STALE_DAYS", 30))                    # hide swipe/alert candidates posted longer ago
PROXIES = [p.strip() for p in os.environ.get("SCRAPE_PROXIES", "").split(",") if p.strip()]  # user:pass@host:port


def _persisted(name: str, make) -> str:
    path = DATA_DIR / name
    if not path.exists():
        path.write_text(make())
        path.chmod(0o600)
    return path.read_text().strip()


SECRET_KEY = os.environ.get("SECRET_KEY") or _persisted(".secret", lambda: secrets.token_hex(32))


def password() -> str:
    """APP_PASSWORD, or a random one generated on first run and kept in data/.password."""
    if os.environ.get("APP_PASSWORD"):
        return os.environ["APP_PASSWORD"]
    path = DATA_DIR / ".password"
    fresh = not path.exists()
    pw = _persisted(".password", lambda: secrets.token_urlsafe(12))
    if fresh:
        print(f"[jobfinder] generated login -> user: {USERNAME}  password: {pw}  (stored in {path})", flush=True)
    return pw


DEFAULT_SCAN = {
    "enabled": True,
    "interval_hours": 1,
    "queries": ["software engineer fresher", "software developer", "SDE 1", "junior developer",
                "full stack developer", "python developer"],
    "cities": ["Bangalore", "Mumbai", "Pune"],
    "sites": ["indeed", "linkedin"],
    "results": 30,
    "days": 7,          # lookback for the first/manual scan; scheduled runs only look back since the last scan
    "full_descriptions": True,
}
