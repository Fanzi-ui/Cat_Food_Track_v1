from __future__ import annotations

import os

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
SEED_DIET_DEFAULT = "Whiskas Poultry"
SEED_GRAMS_DEFAULT = 85
SEED_EVENTS_DEFAULT = 2
