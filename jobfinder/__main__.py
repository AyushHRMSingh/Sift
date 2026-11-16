import getpass
import sys

import uvicorn

from . import settings


def reset(purge: bool, yes: bool) -> None:
    """Wipe jobs, swipe history, scans and profile. Login and secrets are kept.
    A copy is left in data/backups/ unless --purge is given."""
    from datetime import datetime
    from . import store
    if not yes and input('This deletes every job, scan and your profile. Type "wipe" to continue: ') != "wipe":
        sys.exit("Aborted")
    if store.DB_PATH.exists() and not purge:
        print("Backup:", store.backup(tag=f"before-reset-{datetime.now():%Y%m%d-%H%M%S}"))
    for suffix in ("", "-wal", "-shm"):
        store.DB_PATH.with_name(store.DB_PATH.name + suffix).unlink(missing_ok=True)
    if purge:
        for f in (settings.DATA_DIR / "backups").glob("jobs-*.db"):
            f.unlink()
    print("Wiped. Start the service; the first scan runs within a minute and sends no alerts for the backlog.")


def main() -> None:
    if sys.argv[1:] == ["hash-password"]:
        from .web.auth import hash_password
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Again: "):
            sys.exit("Passwords differ")
        print("Put this in .env:\nAPP_PASSWORD_HASH=" + hash_password(pw))
        return
    if sys.argv[1:2] == ["reset"]:
        reset(purge="--purge" in sys.argv, yes="--yes" in sys.argv)
        return
    uvicorn.run("jobfinder.web.app:app", host=settings.HOST, port=settings.PORT, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1", server_header=False, log_level="info")


if __name__ == "__main__":
    main()
