from __future__ import annotations

import hashlib
import secrets
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models


def create_feeding_event(
    db: Session,
    fed_at: datetime,
    amount_grams: int,
    diet_type: str | None = None,
    pet_id: int | None = None,
) -> models.FeedingEvent:
    event = models.FeedingEvent(
        fed_at=fed_at,
        amount_grams=amount_grams,
        diet_type=diet_type,
        pet_id=pet_id,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_last_feeding_event(db: Session) -> models.FeedingEvent | None:
    return db.execute(
        select(models.FeedingEvent).order_by(models.FeedingEvent.fed_at.desc()).limit(1)
    ).scalar_one_or_none()


def get_last_feeding_event_for_pet(db: Session, pet_id: int) -> models.FeedingEvent | None:
    return db.execute(
        select(models.FeedingEvent)
        .where(models.FeedingEvent.pet_id == pet_id)
        .order_by(models.FeedingEvent.fed_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def get_daily_count(
    db: Session, day_start: datetime, day_end: datetime, pet_id: int | None = None
) -> int:
    query = (
        select(func.count())
        .select_from(models.FeedingEvent)
        .where(
            models.FeedingEvent.fed_at >= day_start,
            models.FeedingEvent.fed_at < day_end,
        )
    )
    if pet_id is not None:
        query = query.where(models.FeedingEvent.pet_id == pet_id)
    return db.execute(query).scalar_one()


def get_total_consumed(db: Session) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(models.FeedingEvent.amount_grams), 0))
    ).scalar_one()
    return int(total)


def get_daily_totals(
    db: Session,
    start: datetime,
    end: datetime,
    pet_id: int | None = None,
) -> dict[str, dict[str, int]]:
    query = (
        select(
            func.date(models.FeedingEvent.fed_at),
            func.count(),
            func.coalesce(func.sum(models.FeedingEvent.amount_grams), 0),
        )
        .where(
            models.FeedingEvent.fed_at >= start,
            models.FeedingEvent.fed_at < end,
        )
        .group_by(func.date(models.FeedingEvent.fed_at))
    )
    if pet_id:
        query = query.where(models.FeedingEvent.pet_id == pet_id)
    rows = db.execute(query).all()
    totals: dict[str, dict[str, int]] = {}
    for day, count, grams in rows:
        totals[str(day)] = {"count": int(count), "grams": int(grams)}
    return totals


def create_pet(db: Session, payload: models.Pet) -> models.Pet:
    db.add(payload)
    db.commit()
    db.refresh(payload)
    return payload


def list_pets(db: Session) -> list[models.Pet]:
    return db.execute(select(models.Pet).order_by(models.Pet.name.asc())).scalars().all()


def get_pet(db: Session, pet_id: int) -> models.Pet | None:
    return db.execute(select(models.Pet).where(models.Pet.id == pet_id)).scalar_one_or_none()


def update_pet(db: Session, pet: models.Pet, payload: dict) -> models.Pet:
    for key, value in payload.items():
        setattr(pet, key, value)
    db.commit()
    db.refresh(pet)
    return pet


def delete_pet(db: Session, pet: models.Pet) -> None:
    db.delete(pet)
    db.commit()


def list_feedings_for_pet(db: Session, pet_id: int, limit: int = 20) -> list[models.FeedingEvent]:
    return (
        db.execute(
            select(models.FeedingEvent)
            .where(models.FeedingEvent.pet_id == pet_id)
            .order_by(models.FeedingEvent.fed_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def get_daily_total_for_pet(
    db: Session, day_start: datetime, day_end: datetime, pet_id: int
) -> int:
    total = db.execute(
        select(func.coalesce(func.sum(models.FeedingEvent.amount_grams), 0)).where(
            models.FeedingEvent.fed_at >= day_start,
            models.FeedingEvent.fed_at < day_end,
            models.FeedingEvent.pet_id == pet_id,
        )
    ).scalar_one()
    return int(total)


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000
    ).hex()


def _make_salt() -> str:
    return secrets.token_hex(16)


def create_user_if_missing(db: Session, username: str, password: str) -> models.User:
    existing = get_user_by_username(db, username)
    if existing:
        return existing
    salt = _make_salt()
    password_hash = f"{salt}${_hash_password(password, salt)}"
    user = models.User(
        username=username,
        password_hash=password_hash,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_user(db: Session, username: str, password: str) -> models.User:
    existing = get_user_by_username(db, username)
    if existing:
        raise ValueError("Username already exists.")
    salt = _make_salt()
    password_hash = f"{salt}${_hash_password(password, salt)}"
    user = models.User(
        username=username,
        password_hash=password_hash,
        created_at=datetime.utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_username(db: Session, username: str) -> models.User | None:
    return db.execute(
        select(models.User).where(models.User.username == username)
    ).scalar_one_or_none()


def verify_user_password(user: models.User, password: str) -> bool:
    try:
        salt, stored = user.password_hash.split("$", 1)
    except ValueError:
        return False
    return secrets.compare_digest(_hash_password(password, salt), stored)


def update_user_password(db: Session, user: models.User, new_password: str) -> models.User:
    salt = _make_salt()
    user.password_hash = f"{salt}${_hash_password(new_password, salt)}"
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session) -> list[models.User]:
    return list(db.execute(select(models.User).order_by(models.User.id)).scalars().all())


def set_user_active(db: Session, user: models.User, is_active: bool) -> models.User:
    user.is_active = is_active
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user_email_settings(
    db: Session,
    user: models.User,
    email: str | None,
    notify_email: bool | None,
) -> models.User:
    user.email = email
    if notify_email is not None:
        user.notify_email = notify_email
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def list_notify_emails(db: Session) -> list[str]:
    rows = db.execute(
        select(models.User.email)
        .where(models.User.notify_email.is_(True))
        .where(models.User.email.is_not(None))
    ).all()
    return [row[0] for row in rows if row[0]]


def create_audit_log(
    db: Session,
    action: str,
    actor_user_id: int | None = None,
    details: str | None = None,
) -> models.AuditLog:
    record = models.AuditLog(
        action=action,
        actor_user_id=actor_user_id,
        details=details,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_audit_logs(db: Session, limit: int = 50) -> list[models.AuditLog]:
    return (
        db.execute(select(models.AuditLog).order_by(models.AuditLog.created_at.desc()).limit(limit))
        .scalars()
        .all()
    )


def list_feeding_activity(db: Session, limit: int = 20) -> list[models.AuditLog]:
    return (
        db.execute(
            select(models.AuditLog)
            .where(models.AuditLog.action == "feeding_logged")
            .order_by(models.AuditLog.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )


def list_pets_with_counts(db: Session) -> list[tuple[models.Pet, int]]:
    rows = db.execute(
        select(models.Pet, func.count(models.FeedingEvent.id))
        .outerjoin(models.FeedingEvent, models.FeedingEvent.pet_id == models.Pet.id)
        .group_by(models.Pet.id)
        .order_by(models.Pet.name.asc())
    ).all()
    return [(row[0], int(row[1] or 0)) for row in rows]


def create_auth_token(db: Session, user_id: int) -> models.AuthToken:
    token = secrets.token_urlsafe(32)
    record = models.AuthToken(
        token=token,
        user_id=user_id,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_token(db: Session, token: str) -> models.AuthToken | None:
    return db.execute(
        select(models.AuthToken).where(models.AuthToken.token == token)
    ).scalar_one_or_none()


def create_session(db: Session, user_id: int) -> models.AuthSession:
    token = secrets.token_urlsafe(32)
    record = models.AuthSession(
        token=token,
        user_id=user_id,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def get_session(db: Session, token: str) -> models.AuthSession | None:
    return db.execute(
        select(models.AuthSession).where(models.AuthSession.token == token)
    ).scalar_one_or_none()


def delete_session(db: Session, token: str) -> None:
    record = get_session(db, token)
    if not record:
        return
    db.delete(record)
    db.commit()


def has_users(db: Session) -> bool:
    return db.execute(select(func.count()).select_from(models.User)).scalar_one() > 0
