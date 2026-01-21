from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cat_feeder.db")
IS_SQLITE = DATABASE_URL.startswith("sqlite")

engine_kwargs = {}
if IS_SQLITE:
    engine_kwargs["connect_args"] = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
    dialect = engine.dialect.name
    if dialect == "sqlite":
        with engine.begin() as conn:
            columns = {row[1] for row in conn.execute(text("PRAGMA table_info(feeding_events)"))}
            if not columns:
                return
            if "diet_type" not in columns:
                conn.execute(text("ALTER TABLE feeding_events ADD COLUMN diet_type VARCHAR"))
            if "pet_id" not in columns:
                conn.execute(text("ALTER TABLE feeding_events ADD COLUMN pet_id INTEGER"))
            pet_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(pets)"))}
            if pet_columns and "photo_url" not in pet_columns:
                conn.execute(text("ALTER TABLE pets ADD COLUMN photo_url VARCHAR"))
            if pet_columns and "photo_blob" not in pet_columns:
                conn.execute(text("ALTER TABLE pets ADD COLUMN photo_blob BLOB"))
            if pet_columns and "photo_mime" not in pet_columns:
                conn.execute(text("ALTER TABLE pets ADD COLUMN photo_mime VARCHAR"))
            if pet_columns and "breed" not in pet_columns:
                conn.execute(text("ALTER TABLE pets ADD COLUMN breed VARCHAR"))
            if pet_columns and "estimated_weight_kg" not in pet_columns:
                conn.execute(text("ALTER TABLE pets ADD COLUMN estimated_weight_kg FLOAT"))
            if pet_columns and "daily_limit_count" not in pet_columns:
                conn.execute(text("ALTER TABLE pets ADD COLUMN daily_limit_count INTEGER"))
            if pet_columns and "daily_grams_limit" not in pet_columns:
                conn.execute(text("ALTER TABLE pets ADD COLUMN daily_grams_limit INTEGER"))
            user_columns = {row[1] for row in conn.execute(text("PRAGMA table_info(users)"))}
            if user_columns and "is_active" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1"))
                conn.execute(text("UPDATE users SET is_active = 1 WHERE is_active IS NULL"))
            if user_columns and "email" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN email VARCHAR"))
            if user_columns and "notify_email" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN notify_email INTEGER DEFAULT 0"))
                conn.execute(text("UPDATE users SET notify_email = 0 WHERE notify_email IS NULL"))
            if user_columns and "notify_email_1" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN notify_email_1 VARCHAR"))
                conn.execute(
                    text(
                        "UPDATE users SET notify_email_1 = email "
                        "WHERE notify_email_1 IS NULL AND email IS NOT NULL"
                    )
                )
            if user_columns and "notify_email_2" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN notify_email_2 VARCHAR"))
            if user_columns and "notify_email_3" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN notify_email_3 VARCHAR"))
            if user_columns and "smtp_host" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN smtp_host VARCHAR"))
            if user_columns and "smtp_port" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN smtp_port INTEGER"))
            if user_columns and "smtp_user" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN smtp_user VARCHAR"))
            if user_columns and "smtp_pass" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN smtp_pass VARCHAR"))
            if user_columns and "smtp_from" not in user_columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN smtp_from VARCHAR"))
        return

    if dialect in {"postgresql", "postgres"}:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE feeding_events ADD COLUMN IF NOT EXISTS diet_type VARCHAR"))
            conn.execute(text("ALTER TABLE feeding_events ADD COLUMN IF NOT EXISTS pet_id INTEGER"))
            conn.execute(text("ALTER TABLE pets ADD COLUMN IF NOT EXISTS photo_url VARCHAR"))
            conn.execute(text("ALTER TABLE pets ADD COLUMN IF NOT EXISTS photo_blob BYTEA"))
            conn.execute(text("ALTER TABLE pets ADD COLUMN IF NOT EXISTS photo_mime VARCHAR"))
            conn.execute(text("ALTER TABLE pets ADD COLUMN IF NOT EXISTS breed VARCHAR"))
            conn.execute(text("ALTER TABLE pets ADD COLUMN IF NOT EXISTS estimated_weight_kg FLOAT"))
            conn.execute(text("ALTER TABLE pets ADD COLUMN IF NOT EXISTS daily_limit_count INTEGER"))
            conn.execute(text("ALTER TABLE pets ADD COLUMN IF NOT EXISTS daily_grams_limit INTEGER"))
            conn.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
            )
            conn.execute(
                text(
                    "UPDATE users SET is_active = TRUE "
                    "WHERE is_active IS NULL"
                )
            )
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR"))
            conn.execute(
                text("ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_email BOOLEAN DEFAULT FALSE")
            )
            conn.execute(
                text(
                    "UPDATE users SET notify_email = FALSE "
                    "WHERE notify_email IS NULL"
                )
            )
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_email_1 VARCHAR"))
            conn.execute(
                text(
                    "UPDATE users SET notify_email_1 = email "
                    "WHERE notify_email_1 IS NULL AND email IS NOT NULL"
                )
            )
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_email_2 VARCHAR"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS notify_email_3 VARCHAR"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_host VARCHAR"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_port INTEGER"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_user VARCHAR"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_pass VARCHAR"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS smtp_from VARCHAR"))
