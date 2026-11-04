import getpass
import sys

import uvicorn

from . import settings


def main() -> None:
    if sys.argv[1:] == ["hash-password"]:
        from .web.auth import hash_password
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Again: "):
            sys.exit("Passwords differ")
        print("Put this in .env:\nAPP_PASSWORD_HASH=" + hash_password(pw))
        return
    uvicorn.run("jobfinder.web.app:app", host=settings.HOST, port=settings.PORT, proxy_headers=True,
                forwarded_allow_ips="127.0.0.1", server_header=False, log_level="info")


if __name__ == "__main__":
    main()
