from __future__ import annotations

import base64
import csv
import io
import os
import logging
import secrets
import json
import smtplib
import threading
import time as time_module
from datetime import date, datetime, time, timedelta
from email.message import EmailMessage

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import func, select
try:
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover - optional dependency
    WebPushException = Exception
    webpush = None
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
APP_VERSION = os.getenv("APP_VERSION", "V.0.2")
SACHET_SIZE_GRAMS = 85
LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "5"))
FOOD_OPTIONS = [
    "Whiskas Poultry",
    "Whiskas Tuna",
    "Royal Canin",
    "Purina One",
    "Hill's Science Diet",
]

ASSET_DIR = os.path.join(os.path.dirname(__file__))
TEMPLATE_DIR = os.path.join(ASSET_DIR, "templates")
STATIC_DIR = os.path.join(ASSET_DIR, "static")
TUXEDO_CAT_PATH = os.path.join(ASSET_DIR, "cute-tuxedo-cat-mascot-character-.png")
SW_PATH = os.path.join(ASSET_DIR, "sw.js")
DB_INIT_RETRIES = int(os.getenv("DB_INIT_RETRIES", "5"))
DB_INIT_DELAY_SECONDS = float(os.getenv("DB_INIT_DELAY_SECONDS", "2.0"))
DB_INIT_STRICT = os.getenv("DB_INIT_STRICT", "0") == "1"
_schema_lock = threading.Lock()
_schema_ready = False

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
    global _schema_ready
    _schema_ready = True


def send_smtp_email(
    host: str,
    port: int,
    user: str,
    password: str,
    from_email: str,
    recipients: list[str],
    subject: str,
    body: str,
) -> None:
    if not host or not user or not password or not from_email or not recipients:
        return
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = ", ".join(sorted(set(recipients)))
    message.set_content(body)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10) as server:
                server.login(user, password)
                server.send_message(message)
            return
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.send_message(message)
    except Exception:
        return


def send_feeding_notifications(pet: models.Pet, event: models.FeedingEvent, configs: list[dict]) -> None:
    if not configs:
        return
    diet = event.diet_type or pet.diet_type or "Unknown"
    subject = f"Feeding logged: {pet.name}"
    body = (
        f"Pet: {pet.name}\n"
        f"Amount: {event.amount_grams}g\n"
        f"Diet: {diet}\n"
        f"Fed at (UTC): {event.fed_at.isoformat()}\n"
    )
    for config in configs:
        host = str(config.get("host") or "")
        port = int(config.get("port") or 587)
        user = str(config.get("user") or "")
        password = str(config.get("password") or "")
        from_email = str(config.get("from_email") or "")
        recipients = list(config.get("recipients") or [])
        send_smtp_email(host, port, user, password, from_email, recipients, subject, body)


def send_push_notifications(
    db: Session,
    pet: models.Pet,
    event: models.FeedingEvent,
) -> None:
    if webpush is None:
        return
    vapid_public = os.getenv("VAPID_PUBLIC_KEY")
    vapid_private = os.getenv("VAPID_PRIVATE_KEY")
    vapid_subject = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    if not vapid_public or not vapid_private:
        return
    diet = event.diet_type or pet.diet_type or "Unknown"
    payload = {
        "title": "Feeding logged",
        "body": f"{pet.name} - {event.amount_grams}g - {diet}",
        "url": f"/pets/{pet.id}/profile",
    }
    subscriptions = crud.list_push_subscriptions(db)
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=json.dumps(payload),
                vapid_private_key=vapid_private,
                vapid_claims={"sub": vapid_subject},
            )
        except WebPushException as exc:
            if exc.response and exc.response.status_code in {404, 410}:
                crud.delete_push_subscription(db, sub.endpoint)
            continue


def send_push_message(db: Session, title: str, body: str, url: str) -> None:
    if webpush is None:
        return
    vapid_public = os.getenv("VAPID_PUBLIC_KEY")
    vapid_private = os.getenv("VAPID_PRIVATE_KEY")
    vapid_subject = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    if not vapid_public or not vapid_private:
        return
    payload = {"title": title, "body": body, "url": url}
    subscriptions = crud.list_push_subscriptions(db)
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
                },
                data=json.dumps(payload),
                vapid_private_key=vapid_private,
                vapid_claims={"sub": vapid_subject},
            )
        except WebPushException as exc:
            if exc.response and exc.response.status_code in {404, 410}:
                crud.delete_push_subscription(db, sub.endpoint)
            continue


def handle_inventory_after_feeding(
    db: Session,
    pet: models.Pet,
    amount_grams: int,
) -> None:
    inventory = crud.get_pet_inventory(db, pet.id)
    if not inventory:
        return
    previous = inventory.sachet_count
    updated = crud.apply_inventory_consumption(db, pet.id, amount_grams)
    if not updated:
        return
    if previous > LOW_STOCK_THRESHOLD and updated.sachet_count <= LOW_STOCK_THRESHOLD:
        detail = f"{pet.name} low stock: {updated.sachet_count} sachets left"
        crud.create_audit_log(db, "low_stock", details=detail)
        send_push_message(
            db,
            "Low food stock",
            detail,
            f"/pets/{pet.id}/profile",
        )


SEED_DIET_DEFAULT = "Whiskas Poultry"
SEED_GRAMS_DEFAULT = 85
SEED_EVENTS_DEFAULT = 2


def get_db():
    global _schema_ready
    if not _schema_ready:
        with _schema_lock:
            if not _schema_ready:
                init_db_schema()
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


@app.get("/sw.js")
def service_worker():
    if not os.path.exists(SW_PATH):
        raise HTTPException(status_code=404, detail="Service worker not found.")
    return FileResponse(SW_PATH, media_type="application/javascript")


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
    detail = f"{pet.name} - {event.amount_grams}g"
    if event.diet_type:
        detail += f" - {event.diet_type}"
    crud.create_audit_log(db, "feeding_logged", details=detail)
    handle_inventory_after_feeding(db, pet, event.amount_grams)
    send_feeding_notifications(pet, event, crud.list_notify_configs(db))
    send_push_notifications(db, pet, event)
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


def render_template(name: str, replacements: dict[str, str] | None = None) -> str:
    template_path = os.path.join(TEMPLATE_DIR, name)
    with open(template_path, "r", encoding="utf-8") as handle:
        html = handle.read()
    html = html.replace("__APP_VERSION__", APP_VERSION)
    if replacements:
        for key, value in replacements.items():
            html = html.replace(key, value)
    return html


def build_food_options(selected: str | None = None) -> str:
    options = FOOD_OPTIONS[:]
    if selected and selected not in options:
        options.insert(0, selected)
    selected_value = selected or ""
    return "\n".join(
        f'<option value="{item}"{" selected" if item == selected_value else ""}>{item}</option>'
        for item in options
    )


def build_screen_html(initial_hash: str, mode: str) -> str:
    return render_template(
        "screen.html",
        {"__INITIAL_HASH__": initial_hash, "__MODE__": mode},
    )


@app.get("/screen", response_class=HTMLResponse)
def screen():
    return HTMLResponse(content=build_screen_html("status", "dashboard"))


@app.get("/screen/status", response_class=HTMLResponse)
def screen_status():
    return HTMLResponse(content=build_screen_html("status", "single"))


@app.get("/screen/feed", response_class=HTMLResponse)
def screen_feed():
    return RedirectResponse(url="/pets/list")


@app.get("/screen/pets", response_class=HTMLResponse)
def screen_pets():
    return RedirectResponse(url="/pets/list")


@app.get("/pets/list", response_class=HTMLResponse)
def pets_list(_: None = Depends(require_auth)):
    return HTMLResponse(content=render_template("pet_list.html"))


@app.get("/pets/new", response_class=HTMLResponse)
def pet_new(_: None = Depends(require_auth)):
    return HTMLResponse(content=render_template("pet_new.html"))


@app.get("/admin", response_class=HTMLResponse)
def admin_settings(_: None = Depends(require_auth)):
    return HTMLResponse(content=render_template("admin.html"))


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
    email_fields = {
        "email": payload.email,
        "notify_email": payload.notify_email,
        "notify_email_1": payload.notify_email_1,
        "notify_email_2": payload.notify_email_2,
        "notify_email_3": payload.notify_email_3,
        "smtp_host": payload.smtp_host,
        "smtp_port": payload.smtp_port,
        "smtp_user": payload.smtp_user,
        "smtp_pass": payload.smtp_pass,
        "smtp_from": payload.smtp_from,
    }
    if any(value is not None for value in email_fields.values()):
        notify_enabled = payload.notify_email if payload.notify_email is not None else user.notify_email
        email_1 = payload.notify_email_1 if payload.notify_email_1 is not None else user.notify_email_1
        smtp_host = payload.smtp_host if payload.smtp_host is not None else user.smtp_host
        smtp_port = payload.smtp_port if payload.smtp_port is not None else user.smtp_port
        smtp_user = payload.smtp_user if payload.smtp_user is not None else user.smtp_user
        smtp_pass = payload.smtp_pass if payload.smtp_pass is not None else user.smtp_pass
        smtp_from = payload.smtp_from if payload.smtp_from is not None else user.smtp_from
        if notify_enabled:
            if not email_1:
                raise HTTPException(
                    status_code=400, detail="Primary notification email is required."
                )
            if not smtp_host:
                raise HTTPException(status_code=400, detail="SMTP host is required.")
            if not smtp_user:
                raise HTTPException(status_code=400, detail="SMTP username is required.")
            if not smtp_pass:
                raise HTTPException(status_code=400, detail="SMTP password is required.")
            if not smtp_from:
                raise HTTPException(status_code=400, detail="SMTP from address is required.")
            if smtp_port is None:
                smtp_port = 587
        user = crud.update_user_email_settings(
            db,
            user,
            payload.email,
            payload.notify_email,
            payload.notify_email_1,
            payload.notify_email_2,
            payload.notify_email_3,
            payload.smtp_host,
            smtp_port,
            payload.smtp_user,
            payload.smtp_pass,
            payload.smtp_from,
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


@app.get("/push/vapid-public-key")
def get_vapid_public_key(_: None = Depends(require_auth)):
    if webpush is None:
        raise HTTPException(status_code=500, detail="Push dependency not installed.")
    public_key = os.getenv("VAPID_PUBLIC_KEY")
    if not public_key:
        raise HTTPException(status_code=404, detail="Push not configured.")
    return {"public_key": public_key}


@app.post("/push/subscribe")
def subscribe_push(
    payload: schemas.PushSubscriptionIn,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(require_auth),
):
    if not user:
        raise HTTPException(status_code=401, detail="Auth required.")
    if not payload.endpoint or not payload.keys.p256dh or not payload.keys.auth:
        raise HTTPException(status_code=400, detail="Invalid subscription.")
    crud.upsert_push_subscription(
        db,
        user.id,
        payload.endpoint,
        payload.keys.p256dh,
        payload.keys.auth,
    )
    return {"ok": True}


@app.post("/push/unsubscribe")
def unsubscribe_push(
    payload: schemas.PushSubscriptionIn,
    db: Session = Depends(get_db),
    user: models.User | None = Depends(require_auth),
):
    if not user:
        raise HTTPException(status_code=401, detail="Auth required.")
    if not payload.endpoint:
        raise HTTPException(status_code=400, detail="Invalid subscription.")
    crud.delete_push_subscription(db, payload.endpoint, user_id=user.id)
    return {"ok": True}


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
    detail = f"{pet.name} - {event.amount_grams}g"
    if event.diet_type:
        detail += f" - {event.diet_type}"
    crud.create_audit_log(db, "feeding_logged", details=detail)
    handle_inventory_after_feeding(db, pet, event.amount_grams)
    send_feeding_notifications(pet, event, crud.list_notify_configs(db))
    send_push_notifications(db, pet, event)
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
        feed_time_1=payload.feed_time_1,
        feed_time_2=payload.feed_time_2,
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
        else:
            data["photo_blob"] = None
            data["photo_mime"] = None
            data.setdefault("photo_url", None)
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
    db.query(models.FeedingEvent).filter(models.FeedingEvent.pet_id == pet_id).delete()
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


@app.get("/pets/{pet_id}/inventory", response_model=schemas.PetInventoryOut)
def get_pet_inventory(
    pet_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    inventory = crud.get_pet_inventory(db, pet_id)
    if not inventory:
        return schemas.PetInventoryOut(
            pet_id=pet_id,
            food_name=None,
            sachet_count=0,
            sachet_size_grams=SACHET_SIZE_GRAMS,
            remaining_grams=0,
            updated_at=None,
            low_stock=True,
        )
    return schemas.PetInventoryOut(
        pet_id=pet_id,
        food_name=inventory.food_name,
        sachet_count=inventory.sachet_count,
        sachet_size_grams=inventory.sachet_size_grams,
        remaining_grams=inventory.remaining_grams,
        updated_at=inventory.updated_at,
        low_stock=inventory.sachet_count <= LOW_STOCK_THRESHOLD,
    )


@app.put("/pets/{pet_id}/inventory", response_model=schemas.PetInventoryOut)
def update_pet_inventory(
    pet_id: int,
    payload: schemas.PetInventoryUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    inventory = crud.upsert_pet_inventory(
        db,
        pet_id=pet_id,
        food_name=payload.food_name,
        sachet_count=payload.sachet_count,
        sachet_size_grams=SACHET_SIZE_GRAMS,
    )
    return schemas.PetInventoryOut(
        pet_id=pet_id,
        food_name=inventory.food_name,
        sachet_count=inventory.sachet_count,
        sachet_size_grams=inventory.sachet_size_grams,
        remaining_grams=inventory.remaining_grams,
        updated_at=inventory.updated_at,
        low_stock=inventory.sachet_count <= LOW_STOCK_THRESHOLD,
    )


@app.get("/inventory/low-stock", response_model=list[schemas.LowStockItem])
def list_low_stock_inventory(
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    items = crud.list_low_stock_inventory(db, LOW_STOCK_THRESHOLD)
    return [
        schemas.LowStockItem(
            pet_id=pet.id,
            pet_name=pet.name,
            food_name=inventory.food_name,
            sachet_count=inventory.sachet_count,
            remaining_grams=inventory.remaining_grams,
        )
        for inventory, pet in items
    ]


@app.get("/pets/{pet_id}/weights", response_model=list[schemas.PetWeightOut])
def list_pet_weights(
    pet_id: int,
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    return crud.list_weight_entries(db, pet_id, limit)


@app.post("/pets/{pet_id}/weights", response_model=schemas.PetWeightOut)
def create_pet_weight(
    pet_id: int,
    payload: schemas.PetWeightCreate,
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    recorded_at = payload.recorded_at or datetime.utcnow()
    entry = crud.create_weight_entry(db, pet_id, payload.weight_kg, recorded_at)
    detail = f"{pet.name} weight logged: {entry.weight_kg}kg"
    crud.create_audit_log(db, "weight_logged", details=detail)
    return entry


@app.get("/pets/{pet_id}/report.pdf")
def pet_report_pdf(
    pet_id: int,
    start: date | None = Query(default=None),
    end: date | None = Query(default=None),
    db: Session = Depends(get_db),
    _: None = Depends(require_auth),
):
    pet = crud.get_pet(db, pet_id)
    if not pet:
        raise HTTPException(status_code=404, detail="Pet not found.")
    if end:
        end_dt = datetime.combine(end + timedelta(days=1), time.min)
    else:
        end_dt = datetime.utcnow() + timedelta(days=1)
    if start:
        start_dt = datetime.combine(start, time.min)
    else:
        start_dt = end_dt - timedelta(days=30)
    feedings = crud.list_feedings_range(db, pet_id, start_dt, end_dt)
    weights = crud.list_weight_entries_range(db, pet_id, start_dt, end_dt)
    inventory = crud.get_pet_inventory(db, pet_id)
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    _, height = letter
    y = height - 40
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, f"{pet.name} Report")
    y -= 18
    pdf.setFont("Helvetica", 10)
    end_display = (end_dt - timedelta(days=1)).date()
    date_range = f"{start_dt.date().isoformat()} to {end_display.isoformat()}"
    pdf.drawString(40, y, f"Date range: {date_range}")
    y -= 16
    pdf.drawString(40, y, f"Generated: {datetime.utcnow().isoformat(timespec='minutes')} UTC")
    y -= 22

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, y, "Inventory")
    y -= 14
    pdf.setFont("Helvetica", 10)
    if inventory:
        pdf.drawString(
            40,
            y,
            f"{inventory.food_name} - {inventory.sachet_count} sachets "
            f"({inventory.remaining_grams}g remaining)",
        )
    else:
        pdf.drawString(40, y, "No inventory set.")
    y -= 22

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, y, "Weight Entries")
    y -= 14
    pdf.setFont("Helvetica", 10)
    if not weights:
        pdf.drawString(40, y, "No weight entries.")
        y -= 16
    else:
        for entry in weights:
            if y < 80:
                pdf.showPage()
                y = height - 40
                pdf.setFont("Helvetica", 10)
            pdf.drawString(40, y, f"{entry.recorded_at.isoformat()} - {entry.weight_kg}kg")
            y -= 14
    y -= 8

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, y, "Feedings")
    y -= 14
    pdf.setFont("Helvetica", 10)
    if not feedings:
        pdf.drawString(40, y, "No feedings.")
        y -= 16
    else:
        for entry in feedings:
            if y < 80:
                pdf.showPage()
                y = height - 40
                pdf.setFont("Helvetica", 10)
            diet = f" ({entry.diet_type})" if entry.diet_type else ""
            pdf.drawString(
                40,
                y,
                f"{entry.fed_at.isoformat()} - {entry.amount_grams}g{diet}",
            )
            y -= 14
    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    filename = f"{pet.name.replace(' ', '_').lower()}_report.pdf"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return Response(content=buffer.getvalue(), media_type="application/pdf", headers=headers)


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
    daily_count = crud.get_daily_count(db, day_start, day_end, pet_id)
    daily_limit = pet.daily_limit_count or DAILY_LIMIT
    remaining_feedings = max(0, daily_limit - daily_count)
    daily_grams_limit = pet.daily_grams_limit
    remaining_grams = (
        max(0, daily_grams_limit - daily_total_grams) if daily_grams_limit else None
    )
    photo_html = ""
    if pet.photo_blob:
        photo_html = f'<img class="pet-photo" alt="{pet.name}" id="pet-photo" data-photo="blob">'
    elif pet.photo_url:
        photo_html = f'<img class="pet-photo" src="{pet.photo_url}" alt="{pet.name}">'
    daily_grams_limit_text = str(daily_grams_limit) if daily_grams_limit else "No limit"
    remaining_grams_text = str(remaining_grams) if remaining_grams is not None else "No limit"
    inventory = crud.get_pet_inventory(db, pet_id)
    inventory_sachets = inventory.sachet_count if inventory else 0
    inventory_remaining = inventory.remaining_grams if inventory else 0
    inventory_food = inventory.food_name if inventory else ""
    inventory_updated = inventory.updated_at.isoformat() if inventory else "--"
    feed_time_1 = pet.feed_time_1 or "Not set"
    feed_time_2 = pet.feed_time_2 or "Not set"
    html = render_template(
        "pet_profile.html",
        {
            "__PET_ID__": str(pet_id),
            "__PET_NAME__": pet.name,
            "__PHOTO_HTML__": photo_html,
            "__PET_AGE__": str(pet.age_years or "Unknown"),
            "__PET_SEX__": str(pet.sex or "Unknown"),
            "__PET_DIET__": str(pet.diet_type or "Unknown"),
            "__PET_DIET_VALUE__": str(pet.diet_type or ""),
            "__PET_VET__": str(pet.last_vet_visit or "Unknown"),
            "__PET_BREED__": str(pet.breed or "Unknown"),
            "__PET_WEIGHT__": str(pet.estimated_weight_kg or "Unknown"),
            "__DAILY_TOTAL_KG__": f"{daily_total_kg:.2f}",
            "__DAILY_COUNT__": str(daily_count),
            "__DAILY_LIMIT__": str(daily_limit),
            "__REMAINING_FEEDINGS__": str(remaining_feedings),
            "__DAILY_GRAMS_LIMIT__": daily_grams_limit_text,
            "__REMAINING_GRAMS__": remaining_grams_text,
            "__FEED_TIME_1__": feed_time_1,
            "__FEED_TIME_2__": feed_time_2,
            "__INVENTORY_SACHETS__": str(inventory_sachets),
            "__INVENTORY_REMAINING__": str(inventory_remaining),
            "__INVENTORY_UPDATED__": inventory_updated,
            "__FOOD_OPTIONS__": build_food_options(inventory_food),
        },
    )
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
    html = render_template(
        "pet_edit.html",
        {
            "__PET_ID__": str(pet_id),
            "__PET_NAME__": pet.name,
            "__PHOTO_HTML__": photo_html,
            "__BREED_OPTIONS__": breed_options_html,
            "__PET_AGE__": str(pet.age_years or ""),
            "__PET_SEX__": str(pet.sex or ""),
            "__PET_WEIGHT__": str(pet.estimated_weight_kg or ""),
            "__PET_DIET__": str(pet.diet_type or ""),
            "__PET_PHOTO_URL__": str(pet.photo_url or ""),
            "__PET_VET__": str(pet.last_vet_visit or ""),
            "__FEED_TIME_1__": str(pet.feed_time_1 or ""),
            "__FEED_TIME_2__": str(pet.feed_time_2 or ""),
        },
    )
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
