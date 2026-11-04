"""Request hardening: rate limits, CSRF origin check, body size cap, security headers."""
import secrets
import time
from collections import defaultdict, deque
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import PlainTextResponse

from .. import settings

LOOPBACK = {"127.0.0.1", "::1"}
MAX_BODY = 6 * 1024 * 1024
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def client_ip(request: Request) -> str:
    """Real client behind a local proxy. uvicorn already applies X-Forwarded-For from loopback;
    cloudflared sends CF-Connecting-IP instead."""
    peer = request.client.host if request.client else "unknown"
    return (request.headers.get("cf-connecting-ip") or peer) if peer in LOOPBACK else peer


class Limiter:
    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window, self.hits = limit, window, defaultdict(deque)

    def allow(self, key: str) -> bool:
        now, q = time.monotonic(), self.hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        if len(self.hits) > 10_000:  # bound memory under a flood of distinct addresses
            for k in [k for k, v in self.hits.items() if not v or v[-1] <= now - self.window]:
                del self.hits[k]
        return True


anon_limiter, user_limiter = Limiter(40), Limiter(300)


def origin_ok(request: Request) -> bool:
    """State-changing requests must come from this site. Requests with no Origin (curl, old browsers)
    are covered by the SameSite cookie."""
    origin = request.headers.get("origin")
    if origin is None:
        return True
    allowed = {request.headers.get("host", "")}
    if settings.PUBLIC_URL:
        allowed.add(urlparse(settings.PUBLIC_URL).netloc)
    return urlparse(origin).netloc in allowed


def add_headers(response, nonce: str | None = None):
    csp = ("default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
           "form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
    if nonce:
        csp += f"; script-src 'nonce-{nonce}'"
    h = response.headers
    h["Content-Security-Policy"] = csp
    h["X-Content-Type-Options"] = "nosniff"
    h["X-Frame-Options"] = "DENY"
    h["Referrer-Policy"] = "same-origin"
    h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    h["Cross-Origin-Opener-Policy"] = "same-origin"
    h["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    h["Cache-Control"] = "no-store"
    if settings.SECURE_COOKIES:
        h["Strict-Transport-Security"] = "max-age=31536000"
    return response


async def harden(request: Request, call_next):
    nonce = request.state.nonce = secrets.token_urlsafe(16)
    limiter = user_limiter if request.session.get("user") else anon_limiter
    if not limiter.allow(client_ip(request)):
        return add_headers(PlainTextResponse("Too many requests", 429, {"Retry-After": "60"}))
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return add_headers(PlainTextResponse("Request too large", 413))
    if request.method in UNSAFE and not origin_ok(request):
        return add_headers(PlainTextResponse("Cross-site request blocked", 403))
    return add_headers(await call_next(request), nonce)
