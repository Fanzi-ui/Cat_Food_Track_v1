# Cat Feeder App

FastAPI app to log cat feedings, track daily stats, and manage pet profiles.

## Features

- Mobile-friendly dashboard with status and stats
- Pet profiles with photos and feeding logs
- Per-pet daily limits (count and grams)
- Admin tools: users, pets, exports, audit, maintenance
- Email notifications for feedings (opt-in per admin)

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0
```

Open `http://<ip>:8000/screen`.

## First-time flow

1) Create an account (only allowed when no users exist).
2) Log in.
3) Create a pet.
4) Open the pet profile and log feedings.

## Email notifications (optional)

Set up SMTP per admin in `/admin` with:
- SMTP host, port, username, password, from address
- Up to 3 recipient emails (the first is required to enable notifications)

## Phone notifications (optional)

Web push is supported. Set `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, and `VAPID_SUBJECT`
in your environment (see `.env.example`). Then in `/screen` use the “Enable notifications”
button. On iPhone, add the app to the Home Screen first (iOS 16.4+).

## Admin tools

Open `/admin` after login for:

- User management and password reset
- Pet management and limit settings
- CSV exports
- Audit log
- Maintenance tools (clear/seed data, download DB)

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Notes

- This project uses SQLite by default (`cat_feeder.db`).
- To use Postgres, set `DATABASE_URL` like `postgresql+psycopg2://user:pass@host:5432/dbname`.
- For iPhone home-screen shortcut, open `/screen` in Safari and tap “Add to Home Screen”.
## Railway + local dev

For Railway, set `DATABASE_URL` in the Railway service environment variables. Railway internal
URLs (like `postgres.railway.internal`) only resolve inside Railway, so keep local dev/testing
on SQLite unless you use a public Railway connection string.

## Security notes

- Cookies are http-only; keep your instance on a trusted network.
- Set a strong admin password and disable unused accounts.
- If exposed publicly, use HTTPS and a reverse proxy.
