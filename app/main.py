from __future__ import annotations

import base64
import csv
import io
import os
import logging
import secrets
import smtplib
import time as time_module
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from . import crud, models, schemas
from .database import SessionLocal, engine, ensure_schema

app = FastAPI(title="Cat Feeder API", docs_url=None, redoc_url=None, openapi_url=None)

logger = logging.getLogger(__name__)

DAILY_LIMIT = 3
SESSION_MAX_AGE = 60 * 60 * 24 * 7
CSRF_COOKIE_NAME = "csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

ASSET_DIR = os.path.join(os.path.dirname(__file__))
TUXEDO_CAT_PATH = os.path.join(ASSET_DIR, "cute-tuxedo-cat-mascot-character-.png")
DB_INIT_RETRIES = int(os.getenv("DB_INIT_RETRIES", "5"))
DB_INIT_DELAY_SECONDS = float(os.getenv("DB_INIT_DELAY_SECONDS", "2.0"))
DB_INIT_STRICT = os.getenv("DB_INIT_STRICT", "0") == "1"


def init_db_schema() -> None:
    attempts = max(DB_INIT_RETRIES, 1)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            models.Base.metadata.create_all(bind=engine)
            ensure_schema()
            return
        except OperationalError as exc:
            last_error = exc
            logger.warning(
                "Database init failed (attempt %s/%s).", attempt, attempts, exc_info=exc
            )
            if attempt < attempts:
                time_module.sleep(DB_INIT_DELAY_SECONDS)
            else:
                break
    if DB_INIT_STRICT and last_error:
        raise last_error


def send_feeding_email(pet: models.Pet, event: models.FeedingEvent, recipients: list[str]) -> None:
    host = os.getenv("SMTP_HOST")
    to_list = os.getenv("SMTP_TO")
    all_recipients = [email for email in recipients if email]
    if to_list:
        all_recipients.extend([email.strip() for email in to_list.split(",") if email.strip()])
    if not host or not all_recipients:
        return
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    from_addr = os.getenv("SMTP_FROM") or user
    if not from_addr:
        return
    diet = event.diet_type or pet.diet_type or "Unknown"
    subject = f"Feeding logged: {pet.name}"
    body = (
        f"Pet: {pet.name}\n"
        f"Amount: {event.amount_grams}g\n"
        f"Diet: {diet}\n"
        f"Fed at (UTC): {event.fed_at.isoformat()}\n"
    )
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr
    message["To"] = ", ".join(sorted(set(all_recipients)))
    message.set_content(body)
    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            if os.getenv("SMTP_STARTTLS", "1") == "1":
                server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(message)
    except Exception:
        return


SEED_DIET_DEFAULT = "Whiskas Poultry"
SEED_GRAMS_DEFAULT = 85
SEED_EVENTS_DEFAULT = 2


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_user_from_session(db: Session, session_token: str | None) -> models.User | None:
    if not session_token:
        return None
    session = crud.get_session(db, session_token)
    if not session:
        return None
    return db.get(models.User, session.user_id)


def require_auth(
    request: Request,
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias="session"),
) -> models.User | None:
    if not crud.has_users(db):
        return None
    user = get_user_from_session(db, session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Auth required.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled.")
    verify_csrf(request)
    return user


def issue_csrf_cookie(response: Response) -> str:
    token = secrets.token_urlsafe(32)
    response.set_cookie(
        CSRF_COOKIE_NAME,
        token,
        httponly=False,
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE,
    )
    return token


def verify_csrf(request: Request) -> None:
    if request.method not in UNSAFE_METHODS:
        return
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    header_token = request.headers.get(CSRF_HEADER_NAME)
    if not cookie_token or not header_token:
        raise HTTPException(status_code=403, detail="CSRF token missing.")
    if not secrets.compare_digest(cookie_token, header_token):
        raise HTTPException(status_code=403, detail="CSRF token invalid.")


def parse_photo_base64(photo_base64: str) -> tuple[bytes, str]:
    if not photo_base64.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="Invalid image data.")
    try:
        header, encoded = photo_base64.split(",", 1)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid image data.") from exc
    mime = header.split(";")[0].replace("data:", "")
    try:
        data = base64.b64decode(encoded)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid image data.") from exc
    if len(data) > 2_000_000:
        raise HTTPException(status_code=413, detail="Image too large (max 2MB).")
    return data, mime


@app.on_event("startup")
def startup_db() -> None:
    init_db_schema()


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/assets/tuxedo-cat.png")
def tuxedo_cat_asset():
    if not os.path.exists(TUXEDO_CAT_PATH):
        raise HTTPException(status_code=404, detail="Asset not found.")
    return FileResponse(TUXEDO_CAT_PATH, media_type="image/png")


@app.get("/manifest.webmanifest")
def web_manifest():
    return {
        "name": "Cat Feeder",
        "short_name": "Cat Feeder",
        "start_url": "/screen",
        "display": "standalone",
        "background_color": "#f8f2e9",
        "theme_color": "#f8f2e9",
        "icons": [{"src": "/assets/tuxedo-cat.png", "sizes": "512x512", "type": "image/png"}],
    }


@app.get("/apple-touch-icon.png")
def apple_touch_icon():
    if not os.path.exists(TUXEDO_CAT_PATH):
        raise HTTPException(status_code=404, detail="Asset not found.")
    return FileResponse(TUXEDO_CAT_PATH, media_type="image/png")


@app.get("/auth/status")
def auth_status(db: Session = Depends(get_db)):
    return {"has_users": crud.has_users(db)}


@app.post("/auth/signup", response_model=schemas.LoginResponse)
def signup(payload: schemas.SignupRequest, response: Response, db: Session = Depends(get_db)):
    if crud.has_users(db):
        raise HTTPException(status_code=403, detail="Signup disabled.")
    try:
        user = crud.create_user(db, payload.username, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session = crud.create_session(db, user.id)
    crud.create_audit_log(db, "signup", actor_user_id=user.id, details=f"username={user.username}")
    response.set_cookie(
        "session",
        session.token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE,
    )
    issue_csrf_cookie(response)
    return schemas.LoginResponse(token=session.token)


@app.post("/signup", response_model=schemas.LoginResponse)
def signup_alias(payload: schemas.SignupRequest, response: Response, db: Session = Depends(get_db)):
    return signup(payload, response, db)


@app.get("/openapi.json", include_in_schema=False)
def openapi_json(_: None = Depends(require_auth)):
    return app.openapi()


@app.get("/docs", include_in_schema=False)
def docs_ui(_: None = Depends(require_auth)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="Cat Feeder API Docs")


@app.get("/redoc", include_in_schema=False)
def redoc_ui(_: None = Depends(require_auth)):
    return get_redoc_html(openapi_url="/openapi.json", title="Cat Feeder API Docs")


@app.post("/feedings", response_model=schemas.FeedingEventOut)
def log_feeding(
    payload: schemas.FeedingEventCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    if payload.pet_id is None:
        raise HTTPException(status_code=400, detail="Pet is required.")
    pet = crud.get_pet(db, payload.pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    limit_count = pet.daily_limit_count or DAILY_LIMIT
    day_start = datetime.combine(payload.fed_at.date(), time.min)
    day_end = datetime.combine(payload.fed_at.date(), time.max)
    daily_count = crud.get_daily_count(db, day_start, day_end, payload.pet_id)
    if daily_count >= limit_count:
        raise HTTPException(status_code=400, detail="Daily feeding limit reached.")
    if pet.daily_grams_limit:
        daily_grams = crud.get_daily_total_for_pet(db, day_start, day_end, payload.pet_id)
        if daily_grams + payload.amount_grams > pet.daily_grams_limit:
            raise HTTPException(status_code=400, detail="Daily grams limit reached.")
    event = crud.create_feeding_event(
        db,
        payload.fed_at,
        payload.amount_grams,
        payload.diet_type,
        payload.pet_id,
    )
    detail = f"{pet.name} • {event.amount_grams}g"
    if event.diet_type:
        detail += f" • {event.diet_type}"
    crud.create_audit_log(db, "feeding_logged", details=detail)
    send_feeding_email(pet, event, crud.list_notify_emails(db))
    return event


def build_status(db: Session) -> schemas.FeedingStatus:
    now = datetime.utcnow()
    day_start = datetime.combine(now.date(), time.min)
    day_end = datetime.combine(now.date(), time.max)

    last_event = crud.get_last_feeding_event(db)
    daily_count = crud.get_daily_count(db, day_start, day_end)
    total_consumed = crud.get_total_consumed(db)

    remaining_grams = max(0, 2000 - total_consumed)
    remaining_feedings = max(0, DAILY_LIMIT - daily_count)

    return schemas.FeedingStatus(
        last_fed_at=last_event.fed_at if last_event else None,
        last_diet_type=last_event.diet_type if last_event else None,
        daily_count=daily_count,
        remaining_grams=remaining_grams,
        daily_limit=DAILY_LIMIT,
        remaining_feedings=remaining_feedings,
    )


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/screen")


def build_screen_html(initial_hash: str, mode: str) -> str:
    template = """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Cat Feeder</title>
        <link rel="manifest" href="/manifest.webmanifest">
        <link rel="icon" href="/assets/tuxedo-cat.png" type="image/png">
        <link rel="apple-touch-icon" href="/apple-touch-icon.png">
        <meta name="apple-mobile-web-app-capable" content="yes">
        <meta name="apple-mobile-web-app-title" content="Cat Feeder">
        <style>
          :root {
            --ink: #1f1b16;
            --muted: #6c6058;
            --cream: #f8f2e9;
            --sand: #efe4d6;
            --mint: #e4efe9;
            --shadow: 0 12px 28px rgba(40, 30, 24, 0.16);
          }
          * { box-sizing: border-box; }
          html, body, #app { height: 100%; }
          body {
            margin: 0;
            font-family: "Optima", "Gill Sans", "Candara", sans-serif;
            color: var(--ink);
            background: radial-gradient(circle at top, #fdf8f1, var(--cream));
          }
          .shell {
            max-width: 900px;
            margin: 0 auto;
            padding: 1.5rem 1rem 4.5rem;
          }
          .appbar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem 1.2rem;
            border-radius: 20px;
            background: #fff7ec;
            box-shadow: var(--shadow);
          }
          .brand {
            display: flex;
            align-items: center;
            gap: 0.6rem;
          }
          .brand img {
            width: 40px;
            height: 40px;
            border-radius: 12px;
            object-fit: cover;
            border: 1px solid #efe0d2;
          }
          .appbar-right {
            display: flex;
            align-items: center;
            gap: 0.5rem;
          }
          .username {
            font-size: 0.85rem;
            color: var(--muted);
          }
          .logout {
            padding: 0.4rem 0.75rem;
            border-radius: 999px;
            border: 1px solid #e4d3c3;
            background: #fffaf4;
            font-size: 0.85rem;
          }
          .pill {
            padding: 0.35rem 0.7rem;
            border-radius: 999px;
            background: #fffaf4;
            border: 1px solid #e4d3c3;
            font-size: 0.85rem;
            color: var(--muted);
          }
          .page-links {
            margin-top: 0.8rem;
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
          }
          .page-links a {
            text-decoration: none;
            font-size: 0.85rem;
            background: #fffaf4;
            color: var(--ink);
            padding: 0.4rem 0.75rem;
            border-radius: 999px;
            border: 1px solid #e4d3c3;
          }
          .panel {
            margin-top: 1rem;
            padding: 1rem;
            border-radius: 18px;
            background: var(--mint);
            box-shadow: var(--shadow);
          }
          .card-grid {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 0.75rem;
          }
          .card {
            background: #fffdf9;
            border-radius: 16px;
            padding: 0.85rem;
            border: 1px solid #efe0d2;
          }
          .label {
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted);
          }
          .tip-text {
            margin-top: 0.6rem;
            font-size: 0.95rem;
            color: var(--ink);
          }
          .activity-list {
            display: grid;
            gap: 0.5rem;
            margin-top: 0.8rem;
          }
          .activity-item {
            padding: 0.6rem 0.75rem;
            background: #fffaf4;
            border: 1px solid #e4d3c3;
            border-radius: 12px;
            font-size: 0.9rem;
          }
          .value {
            margin-top: 0.3rem;
            font-size: 1.05rem;
            font-weight: 600;
          }
          .chart {
            display: flex;
            align-items: flex-end;
            gap: 0.6rem;
            height: 140px;
            padding: 0.5rem 0 1.6rem;
            overflow-x: auto;
          }
          .filters {
            display: grid;
            gap: 0.6rem;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            margin-bottom: 0.8rem;
          }
          .filters button {
            padding: 0.6rem 0.9rem;
            border-radius: 999px;
            border: none;
            background: #1f1b16;
            color: #fff7ec;
            font-weight: 600;
          }
          .button-link {
            display: inline-block;
            text-decoration: none;
            padding: 0.55rem 0.9rem;
            border-radius: 999px;
            border: 1px solid #e4d3c3;
            background: #fffaf4;
            color: var(--ink);
            font-weight: 600;
          }
          .ring-grid {
            margin-top: 0.75rem;
            display: flex;
            justify-content: center;
          }
          .ring {
            height: 130px;
            width: 130px;
            border-radius: 18px;
            background: #fffaf4;
            border: 1px solid #e4d3c3;
            display: grid;
            place-items: center;
            position: relative;
          }
          .ring::before {
            content: "";
            position: absolute;
            inset: 10px;
            border-radius: 50%;
            background: conic-gradient(
              #b5633f calc(var(--percent) * 1%),
              #efe4d6 0
            );
          }
          .ring::after {
            content: "";
            position: absolute;
            inset: 24px;
            border-radius: 50%;
            background: #fffdf9;
          }
          .ring-content {
            position: relative;
            text-align: center;
            z-index: 1;
          }
          .ring-grams {
            font-weight: 700;
            font-size: 1.05rem;
          }
          .ring-sub {
            font-size: 0.75rem;
            color: var(--muted);
          }
          .ring-date {
            font-size: 0.75rem;
            color: var(--muted);
          }
          .ring-badge {
            position: absolute;
            top: 10px;
            right: 10px;
            font-size: 0.7rem;
            padding: 0.2rem 0.45rem;
            border-radius: 999px;
            background: #b5633f;
            color: #fff7ec;
          }
          .sparkline {
            width: 100%;
            height: 80px;
            margin-top: 0.6rem;
          }
          .bar {
            min-width: 38px;
            background: #b5633f;
            border-radius: 10px 10px 6px 6px;
            position: relative;
          }
          .bar span {
            position: absolute;
            bottom: -1.4rem;
            font-size: 0.75rem;
            color: var(--muted);
            white-space: nowrap;
          }
          .bar b {
            position: absolute;
            top: -1.2rem;
            font-size: 0.75rem;
            color: var(--ink);
          }
          form {
            display: grid;
            gap: 0.75rem;
          }
          label { font-weight: 600; }
          input, select {
            padding: 0.6rem 0.75rem;
            border-radius: 12px;
            border: 1px solid #d8c8b6;
            background: #fffaf4;
            width: 100%;
          }
          button.primary {
            padding: 0.7rem 1rem;
            border-radius: 999px;
            border: none;
            background: #1f1b16;
            color: #fff7ec;
            font-weight: 600;
          }
          .note { color: var(--muted); font-size: 0.9rem; }
          .pet-list {
            list-style: none;
            padding: 0;
            margin: 0.5rem 0 0 0;
            display: grid;
            gap: 0.5rem;
          }
          .pet-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #fffaf4;
            border: 1px solid #e4d3c3;
            border-radius: 12px;
            padding: 0.6rem 0.75rem;
          }
          .pet-item a {
            text-decoration: none;
            color: var(--ink);
            font-weight: 600;
          }
          .hidden { display: none; }
          body[data-mode="single"] .segmented,
          body[data-mode="dashboard"] .segmented {
            display: none;
          }
          @media (min-width: 700px) {
            .card-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
          }
        </style>
      </head>
      <body data-initial="__INITIAL_HASH__" data-mode="__MODE__">
        <div class="shell">
          <div class="appbar">
            <div class="brand">
              <img src="/assets/tuxedo-cat.png" alt="Tuxedo cat">
              <div>
              <div class="label">Cat Feeder</div>
              <div class="value">Dashboard</div>
              </div>
            </div>
            <div class="appbar-right">
              <div class="username" id="username-display"></div>
              <button class="logout" id="logout-btn" style="display: none;">Logout</button>
              <div class="pill" id="auth-pill">Signed out</div>
            </div>
          </div>
          <div class="page-links" id="page-links" style="display: none;">
            <a href="/screen/status">Status</a>
            <a href="/screen/pets">Pets</a>
            <a href="/admin">Admin</a>
          </div>

          <div class="panel" id="auth-panel">
            <div class="note">Sign in or create an account to continue.</div>
            <div class="card-grid" style="margin-top: 0.75rem;">
              <div class="card">
                <div class="label">Login</div>
                <form id="login-form">
                  <div>
                    <label for="login_user">Username</label>
                    <input id="login_user" type="text">
                  </div>
                  <div>
                    <label for="login_pass">Password</label>
                    <input id="login_pass" type="password">
                  </div>
                  <button class="primary" type="submit">Sign In</button>
                </form>
                <div class="note" id="login-status"></div>
              </div>
              <div class="card" id="signup-card">
                <div class="label">Create Account</div>
                <form id="signup-form">
                  <div>
                    <label for="signup_user">Username</label>
                    <input id="signup_user" type="text">
                  </div>
                  <div>
                    <label for="signup_pass">Password</label>
                    <input id="signup_pass" type="password">
                  </div>
                  <button class="primary" type="submit">Create</button>
                </form>
                <div class="note" id="signup-status"></div>
              </div>
            </div>
          </div>

          <div class="panel hidden" id="dashboard-panel">
            <div class="label">Dashboard</div>
            <div class="note">Use the navigation links above.</div>
            <div class="tip-text" id="tip-text">Tip: Log feedings from each pet profile.</div>
            <div class="activity-list" id="activity-list"></div>
          </div>

          <div class="panel hidden" id="status-panel">
            <div class="card">
              <div class="label">Filters</div>
              <div class="filters">
                <div>
                  <label for="stats-start">Start Date</label>
                  <input id="stats-start" type="date">
                </div>
                <div>
                  <label for="stats-end">End Date</label>
                  <input id="stats-end" type="date">
                </div>
                <div>
                  <label for="stats-pet">Pet</label>
                  <select id="stats-pet">
                    <option value="">All pets</option>
                  </select>
                </div>
                <div>
                  <label>&nbsp;</label>
                  <button id="stats-apply" type="button">Apply</button>
                </div>
              </div>
              <a class="button-link" id="stats-export" href="/stats/export">Export CSV</a>
            </div>
            <div class="card-grid">
              <div class="card">
                <div class="label">Last Fed At</div>
                <div class="value" id="last-fed-at">-</div>
              </div>
              <div class="card">
                <div class="label">Last Diet Type</div>
                <div class="value" id="last-diet-type">-</div>
              </div>
              <div class="card">
                <div class="label">Daily Count</div>
                <div class="value" id="daily-count">-</div>
              </div>
              <div class="card">
                <div class="label">Remaining Feedings</div>
                <div class="value" id="remaining-feedings">-</div>
              </div>
            </div>
            <div class="ring-grid" id="ring-grid">
              <div class="ring" id="ring-summary">
                <div class="ring-content">
                  <div class="ring-grams" id="ring-total">0g</div>
                  <div class="ring-sub" id="ring-sub">No data</div>
                </div>
              </div>
            </div>
            <svg
              class="sparkline"
              id="sparkline"
              viewBox="0 0 100 40"
              preserveAspectRatio="none"
            ></svg>
          </div>

          <div class="panel hidden" id="pets-panel">
            <form id="pet-form">
              <div>
                <label for="pet_name">Name</label>
                <input id="pet_name" type="text" required>
              </div>
              <div>
                <label for="pet_breed">Breed</label>
                <select id="pet_breed">
                  <option value="">Unknown</option>
                  <option>Domestic Shorthair</option>
                  <option>Domestic Longhair</option>
                  <option>Maine Coon</option>
                  <option>Siamese</option>
                  <option>Persian</option>
                  <option>Bengal</option>
                  <option>British Shorthair</option>
                  <option>Sphynx</option>
                  <option>Ragdoll</option>
                </select>
              </div>
              <div>
                <label for="pet_age">Age (years)</label>
                <input id="pet_age" type="number" min="0">
              </div>
              <div>
                <label for="pet_sex">Sex</label>
                <input id="pet_sex" type="text">
              </div>
              <div>
                <label for="pet_weight">Estimated Weight (kg)</label>
                <input id="pet_weight" type="number" step="0.1" min="0">
              </div>
              <div>
                <label for="pet_diet">Diet Type</label>
                <input id="pet_diet" type="text">
              </div>
              <div>
                <label for="pet_photo">Photo (from phone)</label>
                <input id="pet_photo" type="file" accept="image/*">
              </div>
              <div>
                <label for="pet_vet">Last Vet Visit</label>
                <input id="pet_vet" type="date">
              </div>
              <button class="primary" type="submit">Create Pet</button>
              <div class="note" id="pet-status"></div>
            </form>
            <ul class="pet-list" id="pet-list"></ul>
          </div>
        </div>
        <script>
          const authPill = document.getElementById("auth-pill");
          const usernameDisplay = document.getElementById("username-display");
          const logoutBtn = document.getElementById("logout-btn");
          const ringGrid = document.getElementById("ring-grid");
          const sparkline = document.getElementById("sparkline");
          const petList = document.getElementById("pet-list");
          const petStatus = document.getElementById("pet-status");
          const loginStatus = document.getElementById("login-status");
          const signupStatus = document.getElementById("signup-status");
          const signupCard = document.getElementById("signup-card");
          const petPhotoInput = document.getElementById("pet_photo");
          const petBreed = document.getElementById("pet_breed");
          const petWeight = document.getElementById("pet_weight");
          const pageLinks = document.getElementById("page-links");
          const authPanel = document.getElementById("auth-panel");
          const dashboardPanel = document.getElementById("dashboard-panel");
          const contentPanels = ["status-panel", "pets-panel"];
          const statsStart = document.getElementById("stats-start");
          const statsEnd = document.getElementById("stats-end");
          const statsPet = document.getElementById("stats-pet");
          const statsApply = document.getElementById("stats-apply");
          const statsExport = document.getElementById("stats-export");
          let petsCache = [];
          const tips = [
            "Tip: Log feedings from each pet profile.",
            "Tip: Use the pet photo field to spot the right cat fast.",
            "Tip: Set daily limits per pet in Admin to prevent overfeeding.",
            "Tip: Check Status for today’s totals at a glance.",
            "Tip: Export CSVs from Admin for backups."
          ];
          let tipIndex = 0;
          const tipText = document.getElementById("tip-text");
          const activityList = document.getElementById("activity-list");
          let petPhotoData = null;

          function getCookie(name) {
            const cookie = document.cookie
              .split("; ")
              .find(row => row.startsWith(`${name}=`));
            return cookie ? cookie.split("=").slice(1).join("=") : "";
          }

          function headers() {
            const headerMap = { "Content-Type": "application/json" };
            const csrfToken = getCookie("csrf");
            if (csrfToken) {
              headerMap["X-CSRF-Token"] = csrfToken;
            }
            return headerMap;
          }

          function showPanel(panelId) {
            contentPanels.forEach(id => {
              document.getElementById(id).classList.toggle("hidden", id !== panelId);
            });
          }

          function renderSparkline(items) {
            const values = items.map(item => item.grams);
            const max = Math.max(1, ...values);
            const points = values.map((v, i) => {
              const x = (i / Math.max(1, values.length - 1)) * 100;
              const y = 36 - (v / max) * 32;
              return `${x.toFixed(2)},${y.toFixed(2)}`;
            }).join(" ");
            const moving = values.map((_, i) => {
              const start = Math.max(0, i - 2);
              const slice = values.slice(start, i + 1);
              const avg = slice.reduce((a, b) => a + b, 0) / slice.length;
              const x = (i / Math.max(1, values.length - 1)) * 100;
              const y = 36 - (avg / max) * 32;
              return `${x.toFixed(2)},${y.toFixed(2)}`;
            }).join(" ");
            sparkline.innerHTML = `
              <polyline fill="none" stroke="#b5633f" stroke-width="2" points="${points}" />
              <polyline fill="none" stroke="#6c6058" stroke-width="1.5" points="${moving}" />
            `;
          }

          function renderRingSummary(items, limitGrams) {
            const ring = document.getElementById("ring-summary");
            const totalEl = document.getElementById("ring-total");
            const subEl = document.getElementById("ring-sub");
            const total = items.reduce((sum, item) => sum + item.grams, 0);
            const days = Math.max(1, items.length);
            const avg = Math.round(total / days);
            const limitTotal = limitGrams ? limitGrams * days : null;
            const percent = limitTotal ? Math.min(100, Math.round((total / limitTotal) * 100)) : 0;
            ring.style.setProperty("--percent", percent);
            totalEl.textContent = `${total}g`;
            if (limitTotal) {
              subEl.textContent = `${avg}g/day • ${percent}% of limit`;
            } else {
              subEl.textContent = `${avg}g/day • no limit`;
            }
          }

          function updateStatsExport(params) {
            statsExport.href = "/stats/export" + params;
          }

          function petLimitGrams(petId) {
            if (!petId) return null;
            const pet = petsCache.find(item => String(item.id) === String(petId));
            return pet && pet.daily_grams_limit ? pet.daily_grams_limit : null;
          }

          function updateStatsPetSelect() {
            if (!statsPet) {
              return;
            }
            statsPet.innerHTML = '<option value="">All pets</option>';
            petsCache.forEach(pet => {
              const option = document.createElement("option");
              option.value = pet.id;
              option.textContent = pet.name;
              statsPet.appendChild(option);
            });
          }

          async function fetchStatus(petId) {
            const url = petId ? `/pets/${petId}/status` : "/status";
            const statusRes = await fetch(url, { headers: headers(), credentials: "include" });
            if (!statusRes.ok) {
              return;
            }
            const data = await statusRes.json();
            const lastFed = document.getElementById("last-fed-at");
            const lastDiet = document.getElementById("last-diet-type");
            const dailyCount = document.getElementById("daily-count");
            const remaining = document.getElementById("remaining-feedings");
            lastFed.textContent = data.last_fed_at || "Never";
            lastDiet.textContent = data.last_diet_type || "Unknown";
            dailyCount.textContent = data.daily_count;
            remaining.textContent = data.remaining_feedings;
          }

          async function refreshStats() {
            const petId = statsPet ? statsPet.value : "";
            const startVal = statsStart && statsStart.value ? statsStart.value : "";
            const endVal = statsEnd && statsEnd.value ? statsEnd.value : "";
            let params = "";
            if (startVal && endVal) {
              params = `?start=${startVal}&end=${endVal}`;
            }
            if (petId) {
              params += params ? `&pet_id=${petId}` : `?pet_id=${petId}`;
            }
            const statsUrl = "/stats/daily" + (params || "?days=7");
            const chartRes = await fetch(statsUrl, { headers: headers(), credentials: "include" });
            if (chartRes.ok) {
              const chartData = await chartRes.json();
              const limitGrams = petLimitGrams(petId);
              renderRingSummary(chartData.items, limitGrams);
              renderSparkline(chartData.items);
              updateStatsExport(params || "?days=7");
            }
            await fetchStatus(petId);
          }

          async function loadActivity() {
            if (!activityList) {
              return;
            }
            const response = await fetch("/activity?limit=5", { credentials: "include" });
            if (!response.ok) {
              activityList.textContent = "";
              return;
            }
            const items = await response.json();
            activityList.innerHTML = "";
            if (!items.length) {
              activityList.innerHTML = "<div class='activity-item'>No recent feedings.</div>";
              return;
            }
            items.forEach(entry => {
              const item = document.createElement("div");
              item.className = "activity-item";
              const when = new Date(entry.created_at).toLocaleString();
              item.textContent = `${when} — ${entry.details || "Feeding logged"}`;
              activityList.appendChild(item);
            });
          }

          async function refreshAll() {
            const meRes = await fetch("/me", { credentials: "include" });
            if (!meRes.ok) {
              authPill.textContent = "Signed out";
              usernameDisplay.textContent = "";
              logoutBtn.style.display = "none";
              authPanel.classList.remove("hidden");
              dashboardPanel.classList.add("hidden");
              pageLinks.style.display = "none";
              contentPanels.forEach(id => document.getElementById(id).classList.add("hidden"));
              return;
            }
            const me = await meRes.json();
            authPill.textContent = "Signed in";
            usernameDisplay.textContent = me.username || "";
            logoutBtn.style.display = "inline-flex";
            authPanel.classList.add("hidden");
            pageLinks.style.display = "flex";
            if (document.body.dataset.mode === "dashboard") {
              dashboardPanel.classList.remove("hidden");
              contentPanels.forEach(id => document.getElementById(id).classList.add("hidden"));
              return;
            }
            dashboardPanel.classList.add("hidden");
            const hash = window.location.hash.replace("#", "") || "status";
            const panelByHash = {
              status: "status-panel",
              pets: "pets-panel",
            };
            showPanel(panelByHash[hash] || "status-panel");
            await loadPets();
            await refreshStats();
            await loadActivity();
          }

          async function loadPets() {
            const response = await fetch("/pets", { headers: headers(), credentials: "include" });
            if (!response.ok) {
              return;
            }
            const pets = await response.json();
            petsCache = pets;
            updateStatsPetSelect();
            petList.innerHTML = "";
            pets.forEach(pet => {
              const item = document.createElement("li");
              item.className = "pet-item";
              const link = document.createElement("a");
              link.href = "/pets/" + pet.id + "/profile";
              link.textContent = pet.name;
              const view = document.createElement("span");
              view.textContent = "View";
              item.appendChild(link);
              item.appendChild(view);
              petList.appendChild(item);
            });
          }

          petPhotoInput.addEventListener("change", () => {
            const file = petPhotoInput.files[0];
            if (!file) {
              petPhotoData = null;
              return;
            }
            const reader = new FileReader();
            reader.onload = () => {
              petPhotoData = reader.result;
            };
            reader.readAsDataURL(file);
          });

          document.getElementById("pet-form").addEventListener("submit", async (event) => {
            event.preventDefault();
            petStatus.textContent = "Creating...";
            const payload = {
              name: document.getElementById("pet_name").value.trim(),
              breed: petBreed.value || null,
              age_years: document.getElementById("pet_age").value
                ? parseInt(document.getElementById("pet_age").value, 10)
                : null,
              sex: document.getElementById("pet_sex").value.trim() || null,
              estimated_weight_kg: petWeight.value ? parseFloat(petWeight.value) : null,
              diet_type: document.getElementById("pet_diet").value.trim() || null,
              photo_base64: petPhotoData,
              last_vet_visit: document.getElementById("pet_vet").value || null
            };
            const response = await fetch("/pets", {
              method: "POST",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify(payload)
            });
            if (response.ok) {
              petStatus.textContent = "Pet created.";
              document.getElementById("pet_name").value = "";
              petBreed.value = "";
              document.getElementById("pet_age").value = "";
              document.getElementById("pet_sex").value = "";
              petWeight.value = "";
              document.getElementById("pet_diet").value = "";
              document.getElementById("pet_photo").value = "";
              document.getElementById("pet_vet").value = "";
              petPhotoData = null;
              loadPets();
            } else {
              const error = await response.json();
              petStatus.textContent = error.detail || "Failed to create pet.";
            }
          });

          document.getElementById("login-form").addEventListener("submit", async (event) => {
            event.preventDefault();
            loginStatus.textContent = "Signing in...";
            const payload = {
              username: document.getElementById("login_user").value.trim(),
              password: document.getElementById("login_pass").value
            };
            const response = await fetch("/login", {
              method: "POST",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify(payload)
            });
            if (response.ok) {
              await response.json();
              loginStatus.textContent = "Signed in.";
              refreshAll();
            } else {
              loginStatus.textContent = "Invalid credentials.";
            }
          });

          document.getElementById("signup-form").addEventListener("submit", async (event) => {
            event.preventDefault();
            signupStatus.textContent = "Creating...";
            const payload = {
              username: document.getElementById("signup_user").value.trim(),
              password: document.getElementById("signup_pass").value
            };
            const response = await fetch("/signup", {
              method: "POST",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify(payload)
            });
            if (response.ok) {
              await response.json();
              signupStatus.textContent = "Account created.";
              refreshAll();
            } else {
              const error = await response.json();
              signupStatus.textContent = error.detail || "Signup failed.";
            }
          });


          logoutBtn.addEventListener("click", () => {
            fetch("/logout", { method: "POST", headers: headers(), credentials: "include" }).finally(() => {
              refreshAll();
            });
          });

          if (statsApply) {
            statsApply.addEventListener("click", () => {
              refreshStats();
            });
          }

          async function checkAuthStatus() {
            const response = await fetch("/auth/status", { credentials: "include" });
            if (response.ok) {
              const data = await response.json();
              signupCard.style.display = data.has_users ? "none" : "block";
            }
          }

          checkAuthStatus();
          if (document.body.dataset.mode !== "dashboard") {
            if (!window.location.hash && document.body.dataset.initial) {
              window.location.hash = document.body.dataset.initial;
            }
          }
          if (statsStart && statsEnd) {
            const today = new Date();
            const end = new Date(today.getTime() - today.getTimezoneOffset() * 60000);
            const start = new Date(end);
            start.setDate(start.getDate() - 6);
            statsEnd.value = end.toISOString().slice(0, 10);
            statsStart.value = start.toISOString().slice(0, 10);
          }
          refreshAll();
          setInterval(refreshAll, 30000);
          setInterval(() => {
            if (!tipText) {
              return;
            }
            tipIndex = (tipIndex + 1) % tips.length;
            tipText.textContent = tips[tipIndex];
          }, 10000);
        </script>
      </body>
    </html>
    """
    return template.replace("__INITIAL_HASH__", initial_hash).replace("__MODE__", mode)


@app.get("/screen", response_class=HTMLResponse)
def screen():
    return HTMLResponse(content=build_screen_html("status", "dashboard"))


@app.get("/screen/status", response_class=HTMLResponse)
def screen_status():
    return HTMLResponse(content=build_screen_html("status", "single"))


@app.get("/screen/feed", response_class=HTMLResponse)
def screen_feed():
    return RedirectResponse(url="/screen/pets")


@app.get("/screen/pets", response_class=HTMLResponse)
def screen_pets():
    return HTMLResponse(content=build_screen_html("pets", "single"))


@app.get("/admin", response_class=HTMLResponse)
def admin_settings(_: None = Depends(require_auth)):
    html = """
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Admin Settings</title>
        <style>
          body {
            margin: 0;
            font-family: "Optima", "Gill Sans", "Candara", sans-serif;
            background: #f8f2e9;
            color: #1f1b16;
          }
          .shell {
            max-width: 640px;
            margin: 0 auto;
            padding: 1.5rem 1rem 2.5rem;
          }
          .top-nav {
            display: flex;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
          }
          .top-nav a {
            text-decoration: none;
            font-size: 0.85rem;
            background: #fffaf4;
            color: #1f1b16;
            padding: 0.4rem 0.75rem;
            border-radius: 999px;
            border: 1px solid #e4d3c3;
          }
          .card {
            background: #fffdf9;
            border-radius: 18px;
            padding: 1.2rem;
            box-shadow: 0 10px 30px rgba(40, 30, 24, 0.08);
            margin-top: 1rem;
          }
          form {
            display: grid;
            gap: 0.8rem;
            margin-top: 1rem;
          }
          label { font-weight: 600; }
          input {
            width: 100%;
            padding: 0.6rem 0.75rem;
            border-radius: 12px;
            border: 1px solid #d8c8b6;
            background: #fffaf4;
          }
          button {
            padding: 0.7rem 1rem;
            background: #1f1b16;
            color: #fff7ec;
            border: none;
            border-radius: 999px;
            font-weight: 600;
            cursor: pointer;
          }
          .note {
            font-size: 0.9rem;
            color: #6c6058;
          }
          .user-row {
            display: grid;
            gap: 0.6rem;
            padding: 0.75rem 0;
            border-bottom: 1px solid #efe0d2;
          }
          .user-controls {
            display: grid;
            gap: 0.6rem;
          }
          .user-controls button {
            padding: 0.5rem 0.9rem;
          }
          .user-controls input[type="email"],
          .user-controls input[type="password"] {
            max-width: 100%;
          }
          .user-actions {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
          }
          .user-actions button {
            padding: 0.5rem 0.9rem;
          }
          .user-field {
            display: grid;
            gap: 0.3rem;
          }
          .user-field label {
            font-size: 0.8rem;
            color: #6c6058;
          }
          .pet-row {
            display: grid;
            gap: 0.5rem;
            padding: 0.75rem 0;
            border-bottom: 1px solid #efe0d2;
          }
          .pet-controls {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
          }
          .button-link {
            display: inline-block;
            text-decoration: none;
            padding: 0.6rem 0.9rem;
            border-radius: 999px;
            border: 1px solid #e4d3c3;
            background: #fffaf4;
            color: #1f1b16;
            font-weight: 600;
          }
          .audit-list {
            display: grid;
            gap: 0.6rem;
          }
          .audit-item {
            padding: 0.6rem 0.75rem;
            background: #fffaf4;
            border: 1px solid #e4d3c3;
            border-radius: 12px;
            font-size: 0.9rem;
          }
        </style>
      </head>
      <body>
        <div class="shell">
          <div class="top-nav">
            <a href="/screen">Home</a>
          </div>
          <h1>Admin Settings</h1>
          <div class="card">
            <div class="note">Reset your password.</div>
            <form id="change-pass-form">
              <div>
                <label for="current_pass">Current Password</label>
                <input id="current_pass" type="password">
              </div>
              <div>
                <label for="new_pass">New Password</label>
                <input id="new_pass" type="password">
              </div>
              <button type="submit">Change Password</button>
              <div class="note" id="change-pass-status"></div>
            </form>
          </div>
          <div class="card">
            <div class="note">User management</div>
            <div id="user-list"></div>
          </div>
          <div class="card">
            <div class="note">Pet management</div>
            <div id="pet-list"></div>
          </div>
          <div class="card">
            <div class="note">Data export</div>
            <div class="pet-controls">
              <a class="button-link" href="/admin/export/pets">Download Pets CSV</a>
              <a class="button-link" href="/admin/export/feedings">Download Feedings CSV</a>
            </div>
          </div>
          <div class="card">
            <div class="note">Audit log</div>
            <div class="audit-list" id="audit-list"></div>
          </div>
          <div class="card">
            <div class="note">Maintenance</div>
            <div class="pet-controls">
              <button id="clear-data-btn">Clear Test Data</button>
              <button id="seed-data-btn">Seed Sample Data</button>
              <a class="button-link" href="/admin/export/db">Download DB</a>
            </div>
            <div class="note" id="maintenance-status"></div>
          </div>
        </div>
        <script>
          const userList = document.getElementById("user-list");
          const petList = document.getElementById("pet-list");
          const auditList = document.getElementById("audit-list");
          const maintenanceStatus = document.getElementById("maintenance-status");

          function getCookie(name) {
            const cookie = document.cookie
              .split("; ")
              .find(row => row.startsWith(`${name}=`));
            return cookie ? cookie.split("=").slice(1).join("=") : "";
          }

          function headers() {
            const headerMap = { "Content-Type": "application/json" };
            const csrfToken = getCookie("csrf");
            if (csrfToken) {
              headerMap["X-CSRF-Token"] = csrfToken;
            }
            return headerMap;
          }

          function userRow(user) {
            const wrapper = document.createElement("div");
            wrapper.className = "user-row";
            const name = document.createElement("div");
            name.textContent = user.username + (user.is_active ? "" : " (disabled)");
            const controls = document.createElement("div");
            controls.className = "user-controls";
            const toggleBtn = document.createElement("button");
            toggleBtn.textContent = user.is_active ? "Disable" : "Enable";
            toggleBtn.addEventListener("click", () => toggleUser(user.id, !user.is_active));
            const emailField = document.createElement("div");
            emailField.className = "user-field";
            const emailLabel = document.createElement("label");
            emailLabel.textContent = "Email for alerts";
            const emailInput = document.createElement("input");
            emailInput.type = "email";
            emailInput.placeholder = "name@example.com";
            emailInput.value = user.email || "";
            emailField.appendChild(emailLabel);
            emailField.appendChild(emailInput);
            const notifyWrap = document.createElement("label");
            notifyWrap.style.display = "flex";
            notifyWrap.style.alignItems = "center";
            notifyWrap.style.gap = "0.4rem";
            const notifyCheckbox = document.createElement("input");
            notifyCheckbox.type = "checkbox";
            notifyCheckbox.checked = !!user.notify_email;
            const notifyText = document.createElement("span");
            notifyText.textContent = "Email me on feedings";
            notifyWrap.appendChild(notifyCheckbox);
            notifyWrap.appendChild(notifyText);
            const passField = document.createElement("div");
            passField.className = "user-field";
            const passLabel = document.createElement("label");
            passLabel.textContent = "Reset password";
            const resetInput = document.createElement("input");
            resetInput.type = "password";
            resetInput.placeholder = "New password";
            passField.appendChild(passLabel);
            passField.appendChild(resetInput);
            const actions = document.createElement("div");
            actions.className = "user-actions";
            const saveBtn = document.createElement("button");
            saveBtn.textContent = "Save Email";
            saveBtn.addEventListener("click", () => {
              updateUserEmail(user.id, emailInput.value, notifyCheckbox.checked);
            });
            const resetBtn = document.createElement("button");
            resetBtn.textContent = "Reset Password";
            resetBtn.addEventListener("click", () => resetPassword(user.id, resetInput.value));
            actions.appendChild(toggleBtn);
            actions.appendChild(saveBtn);
            actions.appendChild(resetBtn);
            controls.appendChild(emailField);
            controls.appendChild(notifyWrap);
            controls.appendChild(passField);
            controls.appendChild(actions);
            wrapper.appendChild(name);
            wrapper.appendChild(controls);
            return wrapper;
          }

          async function loadUsers() {
            const response = await fetch("/admin/users", { credentials: "include" });
            if (!response.ok) {
              userList.textContent = "Unable to load users.";
              return;
            }
            const users = await response.json();
            userList.innerHTML = "";
            users.forEach(user => userList.appendChild(userRow(user)));
          }

          function petRow(pet) {
            const wrapper = document.createElement("div");
            wrapper.className = "pet-row";
            const title = document.createElement("div");
            title.textContent = pet.name + " (" + pet.feedings_count + " feedings)";
            const meta = document.createElement("div");
            meta.className = "note";
            const bits = [];
            if (pet.breed) bits.push(pet.breed);
            if (pet.diet_type) bits.push(pet.diet_type);
            meta.textContent = bits.join(" • ") || "No extra details";
            const controls = document.createElement("div");
            controls.className = "pet-controls";
            const limitCount = document.createElement("input");
            limitCount.type = "number";
            limitCount.min = "1";
            limitCount.placeholder = "Daily limit (count)";
            limitCount.value = pet.daily_limit_count || "";
            const limitGrams = document.createElement("input");
            limitGrams.type = "number";
            limitGrams.min = "1";
            limitGrams.placeholder = "Daily grams limit";
            limitGrams.value = pet.daily_grams_limit || "";
            const saveBtn = document.createElement("button");
            saveBtn.textContent = "Save Limits";
            saveBtn.addEventListener("click", () => {
              updatePetLimits(pet.id, limitCount.value, limitGrams.value);
            });
            const deleteBtn = document.createElement("button");
            deleteBtn.textContent = "Delete Pet + Feedings";
            deleteBtn.addEventListener("click", () => deletePet(pet.id));
            controls.appendChild(limitCount);
            controls.appendChild(limitGrams);
            controls.appendChild(saveBtn);
            controls.appendChild(deleteBtn);
            wrapper.appendChild(title);
            wrapper.appendChild(meta);
            wrapper.appendChild(controls);
            return wrapper;
          }

          async function loadPets() {
            const response = await fetch("/admin/pets", { credentials: "include" });
            if (!response.ok) {
              petList.textContent = "Unable to load pets.";
              return;
            }
            const pets = await response.json();
            petList.innerHTML = "";
            pets.forEach(pet => petList.appendChild(petRow(pet)));
          }

          async function deletePet(petId) {
            if (!confirm("Delete this pet and its feedings?")) {
              return;
            }
            const response = await fetch(`/admin/pets/${petId}`, {
              method: "DELETE",
              headers: headers(),
              credentials: "include"
            });
            if (response.ok) {
              loadPets();
            } else {
              const error = await response.json();
              alert(error.detail || "Delete failed.");
            }
          }

          async function updatePetLimits(petId, limitCount, limitGrams) {
            const payload = {
              daily_limit_count: limitCount ? parseInt(limitCount, 10) : null,
              daily_grams_limit: limitGrams ? parseInt(limitGrams, 10) : null
            };
            const response = await fetch(`/admin/pets/${petId}`, {
              method: "PATCH",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify(payload)
            });
            if (response.ok) {
              loadPets();
            } else {
              const error = await response.json();
              alert(error.detail || "Update failed.");
            }
          }

          async function loadAudit() {
            const response = await fetch("/admin/audit?limit=30", { credentials: "include" });
            if (!response.ok) {
              auditList.textContent = "Unable to load audit log.";
              return;
            }
            const logs = await response.json();
            auditList.innerHTML = "";
            if (!logs.length) {
              auditList.textContent = "No audit entries yet.";
              return;
            }
            logs.forEach(entry => {
              const item = document.createElement("div");
              item.className = "audit-item";
              const when = new Date(entry.created_at).toLocaleString();
              const who = entry.actor_user_id ? "user " + entry.actor_user_id : "system";
              const details = entry.details ? " • " + entry.details : "";
              item.textContent = `${when} — ${entry.action} (${who})${details}`;
              auditList.appendChild(item);
            });
          }

          async function toggleUser(userId, isActive) {
            const response = await fetch(`/admin/users/${userId}`, {
              method: "PATCH",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify({ is_active: isActive })
            });
            if (response.ok) {
              loadUsers();
            } else {
              const error = await response.json();
              alert(error.detail || "Update failed.");
            }
          }

          async function resetPassword(userId, newPassword) {
            if (!newPassword) {
              alert("Enter a new password.");
              return;
            }
            const response = await fetch(`/admin/users/${userId}/reset-password`, {
              method: "POST",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify({ new_password: newPassword })
            });
            if (response.ok) {
              loadUsers();
            } else {
              const error = await response.json();
              alert(error.detail || "Reset failed.");
            }
          }

          async function updateUserEmail(userId, email, notifyEmail) {
            const response = await fetch(`/admin/users/${userId}`, {
              method: "PATCH",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify({
                email: email ? email.trim() : null,
                notify_email: !!notifyEmail
              })
            });
            if (response.ok) {
              loadUsers();
            } else {
              const error = await response.json();
              alert(error.detail || "Update failed.");
            }
          }

          document.getElementById("change-pass-form").addEventListener("submit", async (event) => {
            event.preventDefault();
            const status = document.getElementById("change-pass-status");
            status.textContent = "Updating...";
            const payload = {
              current_password: document.getElementById("current_pass").value,
              new_password: document.getElementById("new_pass").value
            };
            const response = await fetch("/change-password", {
              method: "POST",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify(payload)
            });
            if (response.ok) {
              status.textContent = "Password updated.";
              document.getElementById("current_pass").value = "";
              document.getElementById("new_pass").value = "";
            } else {
              const error = await response.json();
              status.textContent = error.detail || "Update failed.";
            }
          });

          document.getElementById("clear-data-btn").addEventListener("click", async () => {
            if (!confirm("Clear all pets and feedings? This cannot be undone.")) {
              return;
            }
            maintenanceStatus.textContent = "Clearing...";
            const response = await fetch("/admin/maintenance/clear", {
              method: "POST",
              headers: headers(),
              credentials: "include"
            });
            if (response.ok) {
              maintenanceStatus.textContent = "Data cleared.";
              loadPets();
              loadAudit();
            } else {
              const error = await response.json();
              maintenanceStatus.textContent = error.detail || "Clear failed.";
            }
          });

          document.getElementById("seed-data-btn").addEventListener("click", async () => {
            maintenanceStatus.textContent = "Seeding...";
            const response = await fetch("/admin/maintenance/seed", {
              method: "POST",
              headers: headers(),
              credentials: "include"
            });
            if (response.ok) {
              maintenanceStatus.textContent = "Seeded sample data.";
              loadPets();
              loadAudit();
            } else {
              const error = await response.json();
              maintenanceStatus.textContent = error.detail || "Seed failed.";
            }
          });

          loadUsers();
          loadPets();
          loadAudit();
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/admin/users", response_model=list[schemas.AdminUserOut])
def admin_list_users(
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    return crud.list_users(db)


@app.patch("/admin/users/{user_id}", response_model=schemas.AdminUserOut)
def admin_toggle_user(
    user_id: int,
    payload: schemas.AdminUserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(require_auth),
):
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    if current_user and user.id == current_user.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="You cannot disable your own account.")
    if payload.is_active is not None:
        user = crud.set_user_active(db, user, payload.is_active)
        crud.create_audit_log(
            db,
            "user_status",
            actor_user_id=current_user.id if current_user else None,
            details=f"user_id={user_id} is_active={payload.is_active}",
        )
    if payload.email is not None or payload.notify_email is not None:
        user = crud.update_user_email_settings(
            db,
            user,
            payload.email,
            payload.notify_email,
        )
        crud.create_audit_log(
            db,
            "user_email",
            actor_user_id=current_user.id if current_user else None,
            details=f"user_id={user_id} notify_email={payload.notify_email}",
        )
    return user


@app.post("/admin/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    payload: schemas.AdminResetPasswordRequest,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(require_auth),
):
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    user = db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    crud.update_user_password(db, user, payload.new_password)
    crud.create_audit_log(
        db,
        "admin_reset_password",
        actor_user_id=current_user.id if current_user else None,
        details=f"target_id={user_id}",
    )
    return {"ok": True}


@app.get("/admin/pets", response_model=list[schemas.AdminPetOut])
def admin_list_pets(
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    rows = crud.list_pets_with_counts(db)
    return [
        schemas.AdminPetOut(
            id=pet.id,
            name=pet.name,
            breed=pet.breed,
            diet_type=pet.diet_type,
            age_years=pet.age_years,
            sex=pet.sex,
            estimated_weight_kg=pet.estimated_weight_kg,
            last_vet_visit=pet.last_vet_visit,
            daily_limit_count=pet.daily_limit_count,
            daily_grams_limit=pet.daily_grams_limit,
            feedings_count=count,
        )
        for pet, count in rows
    ]


@app.delete("/admin/pets/{pet_id}")
def admin_delete_pet(
    pet_id: int,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    db.query(models.FeedingEvent).filter(models.FeedingEvent.pet_id == pet_id).delete()
    crud.delete_pet(db, pet)
    crud.create_audit_log(
        db,
        "admin_delete_pet",
        actor_user_id=current_user.id if current_user else None,
        details=f"pet_id={pet_id} name={pet.name}",
    )
    return {"deleted": True}


@app.patch("/admin/pets/{pet_id}", response_model=schemas.AdminPetOut)
def admin_update_pet(
    pet_id: int,
    payload: schemas.AdminPetUpdate,
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    data = payload.model_dump(exclude_unset=True)
    pet = crud.update_pet(db, pet, data)
    crud.create_audit_log(
        db,
        "admin_update_pet_limits",
        actor_user_id=current_user.id if current_user else None,
        details=f"pet_id={pet_id}",
    )
    count = db.execute(
        select(func.count(models.FeedingEvent.id)).where(models.FeedingEvent.pet_id == pet_id)
    ).scalar_one()
    return schemas.AdminPetOut(
        id=pet.id,
        name=pet.name,
        breed=pet.breed,
        diet_type=pet.diet_type,
        age_years=pet.age_years,
        sex=pet.sex,
        estimated_weight_kg=pet.estimated_weight_kg,
        last_vet_visit=pet.last_vet_visit,
        daily_limit_count=pet.daily_limit_count,
        daily_grams_limit=pet.daily_grams_limit,
        feedings_count=int(count or 0),
    )


@app.get("/admin/audit", response_model=list[schemas.AuditLogOut])
def admin_audit_log(
    limit: int = Query(30, ge=1, le=200),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    return crud.list_audit_logs(db, limit)


@app.post("/admin/maintenance/clear")
def admin_clear_data(
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(require_auth),
):
    db.query(models.FeedingEvent).delete()
    db.query(models.Pet).delete()
    crud.create_audit_log(
        db,
        "maintenance_clear",
        actor_user_id=current_user.id if current_user else None,
    )
    return {"ok": True}


@app.post("/admin/maintenance/seed")
def admin_seed_data(
    db: Session = Depends(get_db),
    current_user: models.User | None = Depends(require_auth),
):
    pet = models.Pet(
        name="Whiskers",
        diet_type="Whiskas Poultry",
        age_years=2,
        sex="F",
        breed="Domestic Shorthair",
        estimated_weight_kg=4.2,
    )
    pet = crud.create_pet(db, pet)
    now = datetime.utcnow()
    for offset in range(3):
        fed_at = now - timedelta(hours=6 * (2 - offset))
        crud.create_feeding_event(db, fed_at, 85, pet.diet_type, pet.id)
    crud.create_audit_log(
        db,
        "maintenance_seed",
        actor_user_id=current_user.id if current_user else None,
        details=f"pet_id={pet.id}",
    )
    return {"ok": True}


@app.get("/admin/export/db")
def admin_export_db(_: None = Depends(require_auth)):
    db_path = os.path.join(os.path.dirname(__file__), "..", "cat_feeder.db")
    try:
        with open(db_path, "rb") as handle:
            data = handle.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Database file not found.")
    response = Response(content=data, media_type="application/octet-stream")
    response.headers["Content-Disposition"] = "attachment; filename=cat_feeder.db"
    return response


@app.get("/activity", response_model=list[schemas.AuditLogOut])
def activity_feed(
    limit: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    return crud.list_feeding_activity(db, limit)


@app.get("/admin/export/pets")
def admin_export_pets(
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    rows = crud.list_pets(db)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "name",
            "breed",
            "age_years",
            "sex",
            "diet_type",
            "last_vet_visit",
            "estimated_weight_kg",
            "daily_limit_count",
            "daily_grams_limit",
        ]
    )
    for pet in rows:
        writer.writerow(
            [
                pet.id,
                pet.name,
                pet.breed or "",
                pet.age_years or "",
                pet.sex or "",
                pet.diet_type or "",
                pet.last_vet_visit or "",
                pet.estimated_weight_kg or "",
                pet.daily_limit_count or "",
                pet.daily_grams_limit or "",
            ]
        )
    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=pets.csv"
    return response


@app.get("/admin/export/feedings")
def admin_export_feedings(
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    rows = db.execute(
        select(
            models.FeedingEvent.id,
            models.FeedingEvent.fed_at,
            models.FeedingEvent.amount_grams,
            models.FeedingEvent.diet_type,
            models.FeedingEvent.pet_id,
            models.Pet.name,
        )
        .outerjoin(models.Pet, models.Pet.id == models.FeedingEvent.pet_id)
        .order_by(models.FeedingEvent.fed_at.asc())
    ).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "fed_at", "amount_grams", "diet_type", "pet_id", "pet_name"])
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.fed_at.isoformat() if row.fed_at else "",
                row.amount_grams,
                row.diet_type or "",
                row.pet_id or "",
                row.name or "",
            ]
        )
    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=feedings.csv"
    return response


@app.get("/status", response_model=schemas.FeedingStatus)
def get_status(db: Session = Depends(get_db), _: None = Depends(require_auth)):
    return build_status(db)


@app.get("/stats/daily", response_model=schemas.DailyStatsResponse)
def get_daily_stats(
    days: int = Query(7, ge=1, le=31),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    pet_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="Start date must be before end date.")
    if start and end:
        today = end
        start_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end + timedelta(days=1), time.min)
        days = (end - start).days + 1
    else:
        today = datetime.utcnow().date()
        start_dt = datetime.combine(today - timedelta(days=days - 1), time.min)
        end_dt = datetime.combine(today + timedelta(days=1), time.min)
    totals = crud.get_daily_totals(db, start_dt, end_dt, pet_id)
    items = []
    for offset in range(days):
        day = today - timedelta(days=days - 1 - offset)
        key = day.isoformat()
        day_total = totals.get(key, {"grams": 0, "count": 0})
        items.append(
            schemas.DailyStat(date=key, grams=day_total["grams"], count=day_total["count"])
        )
    return schemas.DailyStatsResponse(days=days, items=items)


@app.get("/stats/export")
def export_stats(
    days: int = Query(7, ge=1, le=31),
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    pet_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    if start and end and start > end:
        raise HTTPException(status_code=400, detail="Start date must be before end date.")
    if start and end:
        start_dt = datetime.combine(start, time.min)
        end_dt = datetime.combine(end + timedelta(days=1), time.min)
        days = (end - start).days + 1
        today = end
    else:
        today = datetime.utcnow().date()
        start_dt = datetime.combine(today - timedelta(days=days - 1), time.min)
        end_dt = datetime.combine(today + timedelta(days=1), time.min)
    totals = crud.get_daily_totals(db, start_dt, end_dt, pet_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "grams", "count", "pet_id"])
    for offset in range(days):
        day = today - timedelta(days=days - 1 - offset)
        key = day.isoformat()
        day_total = totals.get(key, {"grams": 0, "count": 0})
        writer.writerow([key, day_total["grams"], day_total["count"], pet_id or ""])
    response = Response(content=output.getvalue(), media_type="text/csv")
    response.headers["Content-Disposition"] = "attachment; filename=stats.csv"
    return response


@app.post("/seed")
def seed(
    count: int = Query(SEED_EVENTS_DEFAULT, ge=1, le=20),
    grams: int = Query(SEED_GRAMS_DEFAULT, ge=1),
    diet_type: str = Query(SEED_DIET_DEFAULT),
    token: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    required_token = os.getenv("SEED_TOKEN")
    if required_token and token != required_token:
        raise HTTPException(status_code=401, detail="Seed token required.")
    now = datetime.utcnow()
    today = now.date()
    times = []
    for idx in range(count):
        hour = 8 + idx * 4
        times.append(datetime.combine(today, time(hour=hour)))
    created = []
    for fed_at in times:
        day_start = datetime.combine(fed_at.date(), time.min)
        day_end = datetime.combine(fed_at.date(), time.max)
        daily_count = crud.get_daily_count(db, day_start, day_end)
        if daily_count >= DAILY_LIMIT:
            break
        created.append(crud.create_feeding_event(db, fed_at, grams, diet_type))
    return {"created": len(created)}


@app.post("/login", response_model=schemas.LoginResponse)
def login(payload: schemas.LoginRequest, response: Response, db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, payload.username)
    if not user or not crud.verify_user_password(user, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials.")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled.")
    session = crud.create_session(db, user.id)
    crud.create_audit_log(db, "login", actor_user_id=user.id)
    response.set_cookie(
        "session",
        session.token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=SESSION_MAX_AGE,
    )
    issue_csrf_cookie(response)
    return schemas.LoginResponse(token=session.token)


@app.post("/change-password")
def change_password(
    payload: schemas.ChangePasswordRequest,
    user: models.User | None = Depends(require_auth),
    db: Session = Depends(get_db),
):
    if not user:
        raise HTTPException(status_code=401, detail="Auth required.")
    if not crud.verify_user_password(user, payload.current_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    crud.update_user_password(db, user, payload.new_password)
    crud.create_audit_log(db, "change_password", actor_user_id=user.id)
    return {"ok": True}


@app.post("/logout")
def logout(
    request: Request,
    response: Response,
    session_token: str | None = Cookie(default=None, alias="session"),
    db: Session = Depends(get_db),
):
    verify_csrf(request)
    if session_token:
        session = crud.get_session(db, session_token)
        if session:
            crud.create_audit_log(db, "logout", actor_user_id=session.user_id)
        crud.delete_session(db, session_token)
    response.delete_cookie("session", path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"ok": True}


@app.get("/me")
def me(user: models.User | None = Depends(require_auth)):
    if not user:
        raise HTTPException(status_code=401, detail="Auth required.")
    return {"username": user.username}


@app.post("/device/feed", response_model=schemas.FeedingEventOut)
def device_feed(
    payload: schemas.DeviceFeedRequest,
    db: Session = Depends(get_db),
    device_token: str | None = Header(default=None, alias="X-Device-Token"),
    _: None = Depends(require_auth),
):
    required_token = os.getenv("DEVICE_TOKEN")
    if required_token and device_token != required_token:
        raise HTTPException(status_code=401, detail="Invalid device token.")
    fed_at = payload.fed_at or datetime.utcnow()
    if payload.pet_id is None:
        raise HTTPException(status_code=400, detail="Pet is required.")
    pet = crud.get_pet(db, payload.pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    limit_count = pet.daily_limit_count or DAILY_LIMIT
    day_start = datetime.combine(fed_at.date(), time.min)
    day_end = datetime.combine(fed_at.date(), time.max)
    daily_count = crud.get_daily_count(db, day_start, day_end, payload.pet_id)
    if daily_count >= limit_count:
        raise HTTPException(status_code=400, detail="Daily feeding limit reached.")
    if pet.daily_grams_limit:
        daily_grams = crud.get_daily_total_for_pet(db, day_start, day_end, payload.pet_id)
        if daily_grams + payload.amount_grams > pet.daily_grams_limit:
            raise HTTPException(status_code=400, detail="Daily grams limit reached.")
    event = crud.create_feeding_event(
        db,
        fed_at,
        payload.amount_grams,
        payload.diet_type,
        payload.pet_id,
    )
    detail = f"{pet.name} • {event.amount_grams}g"
    if event.diet_type:
        detail += f" • {event.diet_type}"
    crud.create_audit_log(db, "feeding_logged", details=detail)
    send_feeding_email(pet, event, crud.list_notify_emails(db))
    return event


@app.post("/pets", response_model=schemas.PetOut)
def create_pet(
    payload: schemas.PetCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    photo_blob = None
    photo_mime = None
    photo_url = payload.photo_url
    if payload.photo_base64:
        photo_blob, photo_mime = parse_photo_base64(payload.photo_base64)
        photo_url = None
    pet = models.Pet(
        name=payload.name,
        age_years=payload.age_years,
        sex=payload.sex,
        diet_type=payload.diet_type,
        last_vet_visit=payload.last_vet_visit,
        photo_url=photo_url,
        photo_blob=photo_blob,
        photo_mime=photo_mime,
        breed=payload.breed,
        estimated_weight_kg=payload.estimated_weight_kg,
    )
    return crud.create_pet(db, pet)


@app.get("/pets", response_model=list[schemas.PetOut])
def list_pets(db: Session = Depends(get_db), _: None = Depends(require_auth)):
    return crud.list_pets(db)


@app.get("/pets/{pet_id}", response_model=schemas.PetOut)
def get_pet(pet_id: int, db: Session = Depends(get_db), _: None = Depends(require_auth)):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    return pet


@app.patch("/pets/{pet_id}", response_model=schemas.PetOut)
def update_pet(
    pet_id: int,
    payload: schemas.PetUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    data = payload.model_dump(exclude_unset=True)
    if "photo_base64" in data:
        photo_base64 = data.pop("photo_base64")
        if photo_base64:
            photo_blob, photo_mime = parse_photo_base64(photo_base64)
            data["photo_blob"] = photo_blob
            data["photo_mime"] = photo_mime
            data["photo_url"] = None
    return crud.update_pet(db, pet, data)


@app.delete("/pets/{pet_id}")
def delete_pet(
    pet_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    crud.delete_pet(db, pet)
    return {"deleted": True}


@app.get("/pets/{pet_id}/photo")
def get_pet_photo(
    pet_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet or not pet.photo_blob:
        raise HTTPException(status_code=404, detail="Photo not found.")
    return Response(content=pet.photo_blob, media_type=pet.photo_mime or "image/jpeg")


@app.get("/pets/{pet_id}/feedings", response_model=list[schemas.FeedingEventOut])
def list_pet_feedings(
    pet_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    return crud.list_feedings_for_pet(db, pet_id, limit)


@app.get("/pets/{pet_id}/profile", response_class=HTMLResponse)
def pet_profile(
    pet_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    now = datetime.utcnow()
    day_start = datetime.combine(now.date(), time.min)
    day_end = datetime.combine(now.date(), time.max)
    daily_total_grams = crud.get_daily_total_for_pet(db, day_start, day_end, pet_id)
    daily_total_kg = daily_total_grams / 1000
    photo_html = ""
    if pet.photo_blob:
        photo_html = f'<img class="pet-photo" alt="{pet.name}" id="pet-photo" data-photo="blob">'
    elif pet.photo_url:
        photo_html = f'<img class="pet-photo" src="{pet.photo_url}" alt="{pet.name}">'
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Pet Profile</title>
        <style>
          body {{
            margin: 0;
            font-family: "Optima", "Gill Sans", "Candara", sans-serif;
            background: #f8f2e9;
            color: #1f1b16;
          }}
          .shell {{
            max-width: 640px;
            margin: 0 auto;
            padding: 1.5rem 1rem 2.5rem;
          }}
          .top-nav {{
            display: flex;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
          }}
          .top-nav a {{
            text-decoration: none;
            font-size: 0.85rem;
            background: #fffaf4;
            color: #1f1b16;
            padding: 0.4rem 0.75rem;
            border-radius: 999px;
            border: 1px solid #e4d3c3;
          }}
          .card {{
            background: #fffdf9;
            border-radius: 18px;
            padding: 1.2rem;
            box-shadow: 0 10px 30px rgba(40, 30, 24, 0.08);
            margin-top: 1rem;
          }}
          .pet-photo {{
            width: 180px;
            height: 180px;
            border-radius: 50%;
            border: 1px solid #e4d3c3;
            margin-top: 0.75rem;
            object-fit: cover;
          }}
          .info-grid {{
            display: grid;
            gap: 0.6rem;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            margin-top: 0.75rem;
          }}
          .info-item {{
            background: #fffaf4;
            border: 1px solid #e4d3c3;
            border-radius: 12px;
            padding: 0.6rem 0.75rem;
          }}
          .info-item span {{
            display: block;
            font-size: 0.75rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: #6c6058;
          }}
          .info-item strong {{
            display: block;
            margin-top: 0.25rem;
          }}
          .feed-list {{
            list-style: none;
            padding: 0;
            margin: 0.5rem 0 0 0;
            display: grid;
            gap: 0.5rem;
          }}
          .feed-item {{
            padding: 0.6rem 0.75rem;
            background: #fffaf4;
            border-radius: 12px;
            border: 1px solid #e4d3c3;
            font-size: 0.9rem;
          }}
          h1 {{ margin: 0; }}
          label {{ font-weight: 600; }}
          input {{
            width: 100%;
            padding: 0.6rem 0.75rem;
            border-radius: 12px;
            border: 1px solid #d8c8b6;
            background: #fffaf4;
          }}
          form {{
            display: grid;
            gap: 0.8rem;
            margin-top: 1rem;
          }}
          button {{
            padding: 0.7rem 1rem;
            background: #1f1b16;
            color: #fff7ec;
            border: none;
            border-radius: 999px;
            font-weight: 600;
            cursor: pointer;
          }}
          .row {{
            display: grid;
            gap: 0.35rem;
          }}
          .actions {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
          }}
          .actions a {{
            text-decoration: none;
            padding: 0.5rem 0.9rem;
            border-radius: 999px;
            border: 1px solid #e4d3c3;
            background: #fffaf4;
            color: #1f1b16;
            font-weight: 600;
          }}
          .danger {{
            background: #b5633f;
          }}
          .note {{
            font-size: 0.9rem;
            color: #6c6058;
          }}
        </style>
      </head>
      <body>
        <div class="shell">
          <div class="top-nav">
            <a href="/">Home</a>
          </div>
          <h1>{pet.name}</h1>
          {photo_html}
          <div class="info-grid">
            <div class="info-item">
              <span>Age</span>
              <strong>{pet.age_years or "Unknown"}</strong>
            </div>
            <div class="info-item">
              <span>Sex</span>
              <strong>{pet.sex or "Unknown"}</strong>
            </div>
            <div class="info-item">
              <span>Diet</span>
              <strong>{pet.diet_type or "Unknown"}</strong>
            </div>
            <div class="info-item">
              <span>Last Vet Visit</span>
              <strong>{pet.last_vet_visit or "Unknown"}</strong>
            </div>
            <div class="info-item">
              <span>Breed</span>
              <strong>{pet.breed or "Unknown"}</strong>
            </div>
            <div class="info-item">
              <span>Weight (kg)</span>
              <strong>{pet.estimated_weight_kg or "Unknown"}</strong>
            </div>
            <div class="info-item">
              <span>Today (kg)</span>
              <strong>{daily_total_kg:.2f}</strong>
            </div>
          </div>
          <div class="card">
            <div class="note">Profile data shown above. Use the Edit page to update.</div>
            <div class="actions">
              <a href="/pets/{pet_id}/edit">Edit / Delete</a>
            </div>
          </div>
          <div class="card">
            <h2>Recent Feedings</h2>
            <ul class="feed-list" id="feed-list"></ul>
          </div>
          <div class="card">
            <h2>Log Feeding</h2>
            <form id="feed-form">
              <div class="row">
                <label for="fed_at">Fed At (UTC)</label>
                <input id="fed_at" type="datetime-local" required>
              </div>
              <div class="row">
                <label for="amount_grams">Amount (grams)</label>
                <input id="amount_grams" type="number" min="1" value="85" required>
              </div>
              <div class="row">
                <label for="diet_type">Diet Type</label>
                <input id="diet_type" value="{pet.diet_type or ''}">
              </div>
              <button type="submit">Save Feeding</button>
              <div class="note" id="feed-status"></div>
            </form>
          </div>
        </div>
        <script>
          const feedList = document.getElementById("feed-list");
          const feedStatus = document.getElementById("feed-status");
          function getCookie(name) {{
            const cookie = document.cookie
              .split("; ")
              .find(row => row.startsWith(`${{name}}=`));
            return cookie ? cookie.split("=").slice(1).join("=") : "";
          }}
          function headers() {{
            const headerMap = {{ "Content-Type": "application/json" }};
            const csrfToken = getCookie("csrf");
            if (csrfToken) {{
              headerMap["X-CSRF-Token"] = csrfToken;
            }}
            return headerMap;
          }}

          async function loadFeedings() {{
            const response = await fetch("/pets/{pet_id}/feedings?limit=20", {{
              headers: headers(),
              credentials: "include",
            }});
            if (!response.ok) {{
              if (response.status === 401) {{
                feedList.innerHTML = "<li class='feed-item'>Sign in to view feedings.</li>";
                return;
              }}
              feedList.innerHTML = "<li class='feed-item'>Unable to load feedings.</li>";
              return;
            }}
            const data = await response.json();
            if (!data.length) {{
              feedList.innerHTML = "<li class='feed-item'>No feedings yet.</li>";
              return;
            }}
            feedList.innerHTML = "";
            data.forEach(item => {{
              const li = document.createElement("li");
              li.className = "feed-item";
              const when = new Date(item.fed_at).toLocaleString();
              const diet = item.diet_type ? " • " + item.diet_type : "";
              li.textContent = when + " — " + item.amount_grams + "g" + diet;
              feedList.appendChild(li);
            }});
          }}

          loadFeedings();

          document.getElementById("feed-form").addEventListener("submit", async (event) => {{
            event.preventDefault();
            feedStatus.textContent = "Saving...";
            const payload = {{
              fed_at: new Date(document.getElementById("fed_at").value).toISOString(),
              amount_grams: parseInt(document.getElementById("amount_grams").value, 10),
              diet_type: document.getElementById("diet_type").value || null,
              pet_id: {pet.id},
            }};
            const response = await fetch("/feedings", {{
              method: "POST",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify(payload),
            }});
            if (response.ok) {{
              feedStatus.textContent = "Saved.";
              loadFeedings();
            }} else {{
              const error = await response.json();
              feedStatus.textContent = error.detail || "Failed to save.";
            }}
          }});

          const img = document.getElementById("pet-photo");
          if (img && img.dataset.photo === "blob") {{
            img.src = "/pets/{pet_id}/photo";
          }}

          const now = new Date();
          document.getElementById("fed_at").value =
            new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0,16);
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/pets/{pet_id}/edit", response_class=HTMLResponse)
def pet_profile_edit(
    pet_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    breed_options = [
        "",
        "Domestic Shorthair",
        "Domestic Longhair",
        "Maine Coon",
        "Siamese",
        "Persian",
        "Bengal",
        "British Shorthair",
        "Sphynx",
        "Ragdoll",
    ]
    breed_value = pet.breed or ""
    breed_options_html = "\n".join(
        f'<option value="{breed}"{" selected" if breed == breed_value else ""}>'
        f'{"Unknown" if breed == "" else breed}'
        "</option>"
        for breed in breed_options
    )
    photo_html = ""
    if pet.photo_blob:
        photo_html = f'<img class="pet-photo" alt="{pet.name}" id="pet-photo" data-photo="blob">'
    elif pet.photo_url:
        photo_html = f'<img class="pet-photo" src="{pet.photo_url}" alt="{pet.name}">'
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Edit Pet</title>
        <style>
          html, body, #app {{ height: 100%; }}
          body {{
            margin: 0;
            font-family: "Optima", "Gill Sans", "Candara", sans-serif;
            background: #f8f2e9;
            color: #1f1b16;
          }}
          .shell {{
            max-width: 640px;
            margin: 0 auto;
            padding: 1.5rem 1rem 2.5rem;
          }}
          .top-nav {{
            display: flex;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
          }}
          .top-nav a {{
            text-decoration: none;
            font-size: 0.85rem;
            background: #fffaf4;
            color: #1f1b16;
            padding: 0.4rem 0.75rem;
            border-radius: 999px;
            border: 1px solid #e4d3c3;
          }}
          .card {{
            background: #fffdf9;
            border-radius: 18px;
            padding: 1.2rem;
            box-shadow: 0 10px 30px rgba(40, 30, 24, 0.08);
            margin-top: 1rem;
          }}
          .pet-photo {{
            width: 180px;
            height: 180px;
            border-radius: 50%;
            border: 1px solid #e4d3c3;
            margin-top: 0.75rem;
            object-fit: cover;
          }}
          label {{ font-weight: 600; }}
          input, select {{
            width: 100%;
            padding: 0.6rem 0.75rem;
            border-radius: 12px;
            border: 1px solid #d8c8b6;
            background: #fffaf4;
          }}
          form {{
            display: grid;
            gap: 0.8rem;
            margin-top: 1rem;
          }}
          button {{
            padding: 0.7rem 1rem;
            background: #1f1b16;
            color: #fff7ec;
            border: none;
            border-radius: 999px;
            font-weight: 600;
            cursor: pointer;
          }}
          .actions {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
          }}
          .danger {{
            background: #b5633f;
          }}
          .note {{
            font-size: 0.9rem;
            color: #6c6058;
          }}
        </style>
      </head>
      <body>
        <div class="shell">
          <div class="top-nav">
            <a href="/pets/{pet_id}/profile">Back</a>
          </div>
          <h1>Edit {pet.name}</h1>
          {photo_html}
          <div class="card">
            <div class="note">Update details or delete the pet.</div>
            <form id="edit-form">
              <div>
                <label for="name">Name</label>
                <input id="name" value="{pet.name}">
              </div>
              <div>
                <label for="breed">Breed</label>
                <select id="breed">
                  {breed_options_html}
                </select>
              </div>
              <div>
                <label for="age_years">Age (years)</label>
                <input id="age_years" type="number" min="0" value="{pet.age_years or ''}">
              </div>
              <div>
                <label for="sex">Sex</label>
                <input id="sex" value="{pet.sex or ''}">
              </div>
              <div>
                <label for="estimated_weight_kg">Estimated Weight (kg)</label>
                <input
                  id="estimated_weight_kg"
                  type="number"
                  step="0.1"
                  min="0"
                  value="{pet.estimated_weight_kg or ''}"
                >
              </div>
              <div>
                <label for="diet_type">Diet Type</label>
                <input id="diet_type" value="{pet.diet_type or ''}">
              </div>
              <div>
                <label for="photo_url">Photo URL</label>
                <input id="photo_url" value="{pet.photo_url or ''}">
              </div>
              <div>
                <label for="photo_file">Photo (from phone)</label>
                <input id="photo_file" type="file" accept="image/*">
              </div>
              <div>
                <label for="last_vet_visit">Last Vet Visit</label>
                <input id="last_vet_visit" type="date" value="{pet.last_vet_visit or ''}">
              </div>
              <div class="actions">
                <button type="submit">Save</button>
                <button type="button" class="danger" id="delete-btn">Delete</button>
              </div>
              <div class="note" id="status"></div>
            </form>
          </div>
        </div>
        <script>
          const statusEl = document.getElementById("status");
          const photoFile = document.getElementById("photo_file");
          let photoData = null;
          function getCookie(name) {{
            const cookie = document.cookie
              .split("; ")
              .find(row => row.startsWith(`${{name}}=`));
            return cookie ? cookie.split("=").slice(1).join("=") : "";
          }}
          function headers() {{
            const headerMap = {{ "Content-Type": "application/json" }};
            const csrfToken = getCookie("csrf");
            if (csrfToken) {{
              headerMap["X-CSRF-Token"] = csrfToken;
            }}
            return headerMap;
          }}
          photoFile.addEventListener("change", () => {{
            const file = photoFile.files[0];
            if (!file) {{
              photoData = null;
              return;
            }}
            const reader = new FileReader();
            reader.onload = () => {{
              photoData = reader.result;
              const img = document.getElementById("pet-photo");
              if (img) {{
                img.src = photoData;
              }}
            }};
            reader.readAsDataURL(file);
          }});
          document.getElementById("edit-form").addEventListener("submit", async (event) => {{
            event.preventDefault();
            statusEl.textContent = "Saving...";
            const payload = {{
              name: document.getElementById("name").value.trim(),
              breed: document.getElementById("breed").value.trim() || null,
              age_years: document.getElementById("age_years").value
                ? parseInt(document.getElementById("age_years").value, 10)
                : null,
              sex: document.getElementById("sex").value.trim() || null,
              estimated_weight_kg: document.getElementById("estimated_weight_kg").value
                ? parseFloat(document.getElementById("estimated_weight_kg").value)
                : null,
              diet_type: document.getElementById("diet_type").value.trim() || null,
              photo_url: document.getElementById("photo_url").value.trim() || null,
              photo_base64: photoData,
              last_vet_visit: document.getElementById("last_vet_visit").value || null,
            }};
            const response = await fetch(`/pets/{pet_id}`, {{
              method: "PATCH",
              headers: headers(),
              credentials: "include",
              body: JSON.stringify(payload),
            }});
            if (response.ok) {{
              statusEl.textContent = "Saved.";
            }} else {{
              const error = await response.json();
              statusEl.textContent = error.detail || "Failed to save.";
            }}
          }});
          document.getElementById("delete-btn").addEventListener("click", async () => {{
            if (!confirm("Delete this pet?")) {{
              return;
            }}
            statusEl.textContent = "Deleting...";
            const response = await fetch(`/pets/{pet_id}`, {{
              method: "DELETE",
              headers: headers(),
              credentials: "include",
            }});
            if (response.ok) {{
              statusEl.textContent = "Deleted.";
              setTimeout(() => {{
                window.location.href = "/";
              }}, 800);
            }} else {{
              const error = await response.json();
              statusEl.textContent = error.detail || "Failed to delete.";
            }}
          }});
          const img = document.getElementById("pet-photo");
          if (img && img.dataset.photo === "blob") {{
            img.src = "/pets/{pet_id}/photo";
          }}
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)


@app.get("/pets/{pet_id}/status", response_model=schemas.PetStatus)
def get_pet_status(
    pet_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    now = datetime.utcnow()
    day_start = datetime.combine(now.date(), time.min)
    day_end = datetime.combine(now.date(), time.max)
    last_event = crud.get_last_feeding_event_for_pet(db, pet_id)
    daily_count = crud.get_daily_count(db, day_start, day_end, pet_id)
    daily_limit = pet.daily_limit_count or DAILY_LIMIT
    remaining_feedings = max(0, daily_limit - daily_count)
    return schemas.PetStatus(
        pet_id=pet_id,
        last_fed_at=last_event.fed_at if last_event else None,
        last_diet_type=last_event.diet_type if last_event else None,
        daily_count=daily_count,
        daily_limit=daily_limit,
        remaining_feedings=remaining_feedings,
    )
