<p align="center"><img src="jobfinder/web/logo.svg" width="96" alt="Sift logo"></p>

<h1 align="center">Sift</h1>
<p align="center">Self-hosted job finder. Scans job boards on a schedule, ranks the freshest postings by how well they fit you, and lets you swipe through them. No accounts, no cloud, no LLMs.</p>

## What it does
- **Swipe** through new postings, freshest first, best match first within a day. Save, pass, or save for research. Arrow keys on desktop, swipe on a phone browser.
- **Match** each posting against your resume skills and experience, and hide roles that ask for far more than you have.
- **Resume check** reads your PDF the way a basic applicant tracking system does, shows what it could extract, flags what is likely to go wrong, and compares your skills with what scanned postings ask for.
- **Analysis** of the postings you have collected: demand by skill, what is rising, pay, and which skill to learn next.
- **Scans** run hourly on a schedule you control (cities, search terms, sites).
- **Discord digest** twice a day: how many jobs are waiting to apply and how many are left in the swipe queue. Nothing per job.

## Try it locally
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock
cp .env.example .env
SECURE_COOKIES=0 .venv/bin/python -m jobfinder
```
Open <http://localhost:48213>. If `APP_PASSWORD` is not set in `.env`, a password is generated and printed once on first start. The default user is `admin`. Upload your resume under **Resume** or **Profile**, then run a scan from **Scan**.

## Run on a server (Ubuntu 24.04, no Docker)
```bash
sudo apt install -y python3-venv
python3 -m venv .venv && .venv/bin/pip install -r requirements.lock
cp .env.example .env && $EDITOR .env          # set APP_PASSWORD and PUBLIC_URL
sed -e "s|__USER__|$USER|g" -e "s|__DIR__|$PWD|g" deploy/jobfinder.service | sudo tee /etc/systemd/system/jobfinder.service
sudo systemctl daemon-reload && sudo systemctl enable --now jobfinder
```
Sift listens on `127.0.0.1:48213` only. Put Nginx or a Cloudflare Tunnel in front of it, for example `cloudflared tunnel --url http://localhost:48213`, and serve it over HTTPS (the session cookie is `Secure`).

## Configuration
Everything is in `.env` (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `APP_USER`, `APP_PASSWORD` | `admin`, generated | Login. `APP_PASSWORD_HASH` is supported (`python -m jobfinder hash-password`). |
| `PORT`, `HOST` | `48213`, `127.0.0.1` | Where it listens |
| `PUBLIC_URL` | unset | Your real address. Enables the forged-Host check and links in Discord messages. |
| `DATA_DIR` | `./data` | SQLite database and secrets. Back it up by copying the folder. |
| `DISCORD_WEBHOOK_URL` | unset | Server Settings > Integrations > Webhooks |
| `REMINDER_TIMES`, `REMINDER_TZ` | `18:30,20:30`, `Asia/Kolkata` | When the Discord digest goes out |
| `SECURE_COOKIES` | `1` | Set `0` only for plain-http local testing |
| `SINKS` | unset | Export plugins, for example `jsonl` |

## Reset
Stop the service, then `python -m jobfinder reset` (type `wipe` to confirm). It deletes jobs, scans and your profile, keeps the login, and leaves a copy in `data/backups/`. Add `--purge` to delete the backups too.

## Security
Built for a single user on a public URL.
- **Login:** scrypt-hashed passwords supported. Five failed attempts per client per 10 minutes locks that client out, so a bot cannot lock you out.
- **Bots and scrapers:** everything except `/login`, `/healthz` and `/robots.txt` needs a session. Anonymous clients are rate limited, `robots.txt` disallows all, and responses carry `noindex`.
- **Requests:** bodies are capped by bytes received (chunked uploads included), and with `PUBLIC_URL` set, requests with a forged `Host` header are refused.
- **Browser protections:** strict CSP with per-request nonces, cross-site POSTs refused, `SameSite=Lax`, `HttpOnly` and `Secure` cookie, HSTS, `no-store`, no framing.
- **Input:** all SQL is parameterized, scraped text is escaped and links are scheme-checked, uploads are capped (5MB, 25 pages) and must start with `%PDF`, webhook URLs must be real Discord hosts, and the app never fetches user-supplied URLs.
- **Process:** runs as an unprivileged user in a systemd sandbox that can only write `data/`, bound to loopback.
- **Dependencies:** `requirements.lock` pins exact versions. CI runs the tests and `pip-audit` on every push and every Monday, and Dependabot opens update PRs.

Strongly recommended on top: put **Cloudflare Access** (free) in front so strangers never reach the login page. With Nginx, set `proxy_set_header Host $host;` and `PUBLIC_URL`. Keep the OS patched (`unattended-upgrades`).

## Development
```bash
.venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest -q
```
`jobfinder/web` holds routes, templates and the scheduler. `scan.py` does the scraping, `store.py` the SQLite storage, `skills.py`, `experience.py`, `matching.py` and `resume_check.py` the analysis, and `sinks/` the export plugins.

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

## License
MIT, see [LICENSE](LICENSE).

## Disclaimer
Sift scrapes public job listings through JobSpy. Scraping may violate the terms of service of the sites involved (LinkedIn and Indeed in particular). It is meant for personal use at low volume; you are responsible for how you use it. Not affiliated with any job board.
