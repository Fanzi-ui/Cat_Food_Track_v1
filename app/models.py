from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    notify_email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notify_email_1: Mapped[str | None] = mapped_column(String, nullable=True)
    notify_email_2: Mapped[str | None] = mapped_column(String, nullable=True)
    notify_email_3: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_host: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_user: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_pass: Mapped[str | None] = mapped_column(String, nullable=True)
    smtp_from: Mapped[str | None] = mapped_column(String, nullable=True)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    details: Mapped[str | None] = mapped_column(String, nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Pet(Base):
    __tablename__ = "pets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    age_years: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sex: Mapped[str | None] = mapped_column(String, nullable=True)
    diet_type: Mapped[str | None] = mapped_column(String, nullable=True)
    last_vet_visit: Mapped[date | None] = mapped_column(Date, nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    photo_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    photo_mime: Mapped[str | None] = mapped_column(String, nullable=True)
    breed: Mapped[str | None] = mapped_column(String, nullable=True)
    estimated_weight_kg: Mapped[float | None] = mapped_column(nullable=True)
    daily_limit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    daily_grams_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FeedingEvent(Base):
    __tablename__ = "feeding_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    fed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    amount_grams: Mapped[int] = mapped_column(Integer, nullable=False)
    diet_type: Mapped[str | None] = mapped_column(String, nullable=True)
    pet_id: Mapped[int | None] = mapped_column(ForeignKey("pets.id"), nullable=True)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    p256dh: Mapped[str] = mapped_column(String, nullable=False)
    auth: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
