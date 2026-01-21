from __future__ import annotations

import json
import os
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from .. import crud, models

try:
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover - optional dependency
    WebPushException = Exception
    webpush = None


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


def send_feeding_notifications(
    pet: models.Pet,
    event: models.FeedingEvent,
    configs: list[dict],
) -> None:
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
    vapid_private = os.getenv("VAPID_PRIVATE_KEY")
    vapid_subject = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    if not vapid_private:
        return
    diet = event.diet_type or pet.diet_type or "Unknown"
    payload = {
        "title": "Feeding logged",
        "body": f"{pet.name} - {event.amount_grams}g - {diet}",
        "url": f"/pets/{pet.id}/profile",
    }
    _send_push_payload(db, payload, vapid_private, vapid_subject)


def send_push_message(db: Session, title: str, body: str, url: str) -> None:
    if webpush is None:
        return
    vapid_private = os.getenv("VAPID_PRIVATE_KEY")
    vapid_subject = os.getenv("VAPID_SUBJECT", "mailto:admin@example.com")
    if not vapid_private:
        return
    payload = {"title": title, "body": body, "url": url}
    _send_push_payload(db, payload, vapid_private, vapid_subject)


def _send_push_payload(
    db: Session,
    payload: dict,
    vapid_private: str,
    vapid_subject: str,
) -> None:
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
