from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./cat_feeder.db")

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def ensure_schema() -> None:
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
