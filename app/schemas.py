from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FeedingEventCreate(BaseModel):
    fed_at: datetime
    amount_grams: int = Field(..., ge=1)
    diet_type: Optional[str] = None
    pet_id: Optional[int] = None


class FeedingEventOut(BaseModel):
    id: int
    fed_at: datetime
    amount_grams: int
    diet_type: Optional[str] = None
    pet_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class FeedingStatus(BaseModel):
    last_fed_at: Optional[datetime]
    last_diet_type: Optional[str]
    daily_count: int
    remaining_grams: int
    daily_limit: int
    remaining_feedings: int


class DailyStat(BaseModel):
    date: str
    grams: int
    count: int


class DailyStatsResponse(BaseModel):
    days: int
    items: list[DailyStat]


class PetCreate(BaseModel):
    name: str = Field(..., min_length=1)
    age_years: Optional[int] = Field(default=None, ge=0)
    sex: Optional[str] = None
    diet_type: Optional[str] = None
    last_vet_visit: Optional[date] = None
    photo_url: Optional[str] = None
    photo_base64: Optional[str] = None
    breed: Optional[str] = None
    estimated_weight_kg: Optional[float] = Field(default=None, ge=0)


class PetUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1)
    age_years: Optional[int] = Field(default=None, ge=0)
    sex: Optional[str] = None
    diet_type: Optional[str] = None
    last_vet_visit: Optional[date] = None
    photo_url: Optional[str] = None
    photo_base64: Optional[str] = None
    breed: Optional[str] = None
    estimated_weight_kg: Optional[float] = Field(default=None, ge=0)


class PetOut(BaseModel):
    id: int
    name: str
    age_years: Optional[int] = None
    sex: Optional[str] = None
    diet_type: Optional[str] = None
    last_vet_visit: Optional[date] = None
    photo_url: Optional[str] = None
    breed: Optional[str] = None
    estimated_weight_kg: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class PetStatus(BaseModel):
    pet_id: int
    last_fed_at: Optional[datetime]
    last_diet_type: Optional[str]
    daily_count: int
    daily_limit: int
    remaining_feedings: int


class DeviceFeedRequest(BaseModel):
    amount_grams: int = Field(..., ge=1)
    fed_at: Optional[datetime] = None
    diet_type: Optional[str] = None
    pet_id: Optional[int] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


class SignupRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class AdminUserOut(BaseModel):
    id: int
    username: str
    is_active: bool
    email: Optional[str] = None
    notify_email: bool
    notify_email_1: Optional[str] = None
    notify_email_2: Optional[str] = None
    notify_email_3: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_from: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminUserUpdate(BaseModel):
    is_active: Optional[bool] = None
    email: Optional[str] = None
    notify_email: Optional[bool] = None
    notify_email_1: Optional[str] = None
    notify_email_2: Optional[str] = None
    notify_email_3: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    smtp_from: Optional[str] = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str


class AuditLogOut(BaseModel):
    id: int
    created_at: datetime
    action: str
    details: Optional[str] = None
    actor_user_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class AdminPetOut(BaseModel):
    id: int
    name: str
    breed: Optional[str] = None
    diet_type: Optional[str] = None
    age_years: Optional[int] = None
    sex: Optional[str] = None
    estimated_weight_kg: Optional[float] = None
    last_vet_visit: Optional[date] = None
    daily_limit_count: Optional[int] = None
    daily_grams_limit: Optional[int] = None
    feedings_count: int


class AdminPetUpdate(BaseModel):
    daily_limit_count: Optional[int] = Field(default=None, ge=1)
    daily_grams_limit: Optional[int] = Field(default=None, ge=1)


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: PushKeys
