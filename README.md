# JobSpy

Self-hosted job swiper. Scans Indeed/LinkedIn hourly, you swipe at `/`, apply from `/saved`.

## Run (Ubuntu 24.04, no Docker)
```bash
sudo apt install -y python3-venv
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock
cp .env.example .env && $EDITOR .env          # set APP_PASSWORD (else one is generated and printed on first start)
sed -e "s|__USER__|$USER|g" -e "s|__DIR__|$PWD|g" deploy/jobfinder.service | sudo tee /etc/systemd/system/jobfinder.service
sudo systemctl daemon-reload && sudo systemctl enable --now jobfinder
```
Listens on `127.0.0.1:48213`. Point Nginx / cloudflared at it, e.g. `cloudflared tunnel --url http://localhost:48213`.
Serve over HTTPS (session cookie is Secure). For plain-http local testing set `SECURE_COOKIES=0`.

See `.env.example`. Discord alerts: set `DISCORD_WEBHOOK_URL` (Server Settings > Integrations > Webhooks); new jobs at `DISCORD_MIN_MATCH`% or better (default 70) are posted once after each scan. It also posts a daily reminder of how many saved applications are pending, at `REMINDER_TIMES` (default 18:30 and 20:30) in `REMINDER_TZ` (default Asia/Kolkata); nothing is sent when the queue is empty.

Env: `PORT`, `HOST`, `APP_USER` (default admin), `APP_PASSWORD`, `DATA_DIR` (default `./data`), `SINKS` (e.g. `jsonl`).
Data (SQLite, secrets) lives in `data/`. Back it up by copying that folder.

## Layout
`jobfinder/web` routes + templates + scheduler, `scan.py` scraping, `store.py` SQLite, `skills.py`/`experience.py`/`matching.py` analysis, `sinks/` export plugins (Google Sheets stub in `sinks/sheets.py`).

## Security
Built for a single user on a public URL. What is in place:
- **Login:** scrypt-hashed password supported (`python -m jobfinder hash-password`, put the output in `.env` as `APP_PASSWORD_HASH`). Five failed attempts per client per 10 minutes locks that client out; a bot cannot lock you out.
- **Bots and scrapers:** everything except `/login`, `/healthz` and `/robots.txt` needs a session. Anonymous clients are rate limited (40 requests/min), `robots.txt` disallows all, and responses carry `noindex`.
- **Browser protections:** strict CSP with per-request nonces (no inline script without it), cross-site POSTs refused, `SameSite=Lax` + `HttpOnly` + `Secure` cookie, HSTS, `no-store`, no framing.
- **Input:** all SQL is parameterized, scraped text is escaped and links are scheme-checked, uploads are capped (5MB, 25 pages) and must start with `%PDF`, webhook URLs must be real Discord hosts, and the app never fetches user-supplied URLs.
- **Process:** runs as an unprivileged user in a systemd sandbox that can only write `data/`. It binds to loopback only; expose it through Cloudflare Tunnel or Nginx.
- **Dependencies:** `requirements.lock` pins exact versions. CI runs the tests and `pip-audit` on every push and every Monday, and Dependabot opens update PRs. Locally: `.venv/bin/pip install pip-audit && .venv/bin/pip-audit -r requirements.lock`.

Strongly recommended on top: put **Cloudflare Access** (free) in front so strangers never reach the login page at all. With Nginx, set `proxy_set_header Host $host;` and `PUBLIC_URL` so the cross-site check works behind the proxy. Keep the OS patched (`unattended-upgrades`).

## Tests
```bash
.venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q
```

## License
MIT, see [LICENSE](LICENSE).

## Built with
| Project | License | Used for |
|---|---|---|
| [JobSpy](https://github.com/speedyapply/JobSpy) (`python-jobspy`) | MIT | scraping job boards |
| [FastAPI](https://github.com/fastapi/fastapi), [Starlette](https://github.com/encode/starlette), [Uvicorn](https://github.com/encode/uvicorn) | MIT / BSD-3 | web app and server |
| [Jinja2](https://github.com/pallets/jinja), [itsdangerous](https://github.com/pallets/itsdangerous) | BSD-3 | templates, signed session cookie |
| [python-multipart](https://github.com/Kludex/python-multipart) | Apache-2.0 | form and file uploads |
| [pypdf](https://github.com/py-pdf/pypdf) | BSD-3 | resume parsing |
| [pandas](https://github.com/pandas-dev/pandas) | BSD-3 | data handling |
| [Lucide](https://lucide.dev) | ISC | UI icons (inlined SVG) |

## Disclaimer
This tool scrapes public job listings through JobSpy. Scraping may violate the terms of service of the sites involved (LinkedIn and Indeed in particular). It is meant for personal use at low volume; you are responsible for how you use it. Not affiliated with any job board.

---
Vibecoded with disdain
