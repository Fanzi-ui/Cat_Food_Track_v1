import importlib
import os
import sys
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient


def build_client(tmp_path: str) -> TestClient:
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path}/test.db"
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from app import database

    importlib.reload(database)
    from app import main

    importlib.reload(main)
    return TestClient(main.app)


def auth_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("csrf")
    return {"X-CSRF-Token": token} if token else {}


def test_health(tmp_path):
    client = build_client(tmp_path)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_signup_login_pet_feeding_flow(tmp_path):
    client = build_client(tmp_path)

    signup = client.post("/signup", json={"username": "admin", "password": "test1234"})
    assert signup.status_code == 200

    login = client.post("/login", json={"username": "admin", "password": "test1234"})
    assert login.status_code == 200

    pet = client.post(
        "/pets",
        json={
            "name": "Whiskers",
            "diet_type": "Whiskas Poultry",
            "age_years": 2,
        },
        headers=auth_headers(client),
    )
    assert pet.status_code == 200
    pet_id = pet.json()["id"]

    fed_at = datetime.utcnow().isoformat()
    feeding = client.post(
        "/feedings",
        json={
            "pet_id": pet_id,
            "amount_grams": 85,
            "fed_at": fed_at,
            "diet_type": "Whiskas Poultry",
        },
        headers=auth_headers(client),
    )
    assert feeding.status_code == 200

    status = client.get("/status")
    assert status.status_code == 200
    assert status.json()["daily_count"] >= 1
