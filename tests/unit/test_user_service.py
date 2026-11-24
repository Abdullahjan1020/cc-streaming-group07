import importlib.util
from pathlib import Path

import httpx
import pytest

def load_app():
    path = Path(__file__).parents[2] / "services" / "user-service" / "app.py"
    spec = importlib.util.spec_from_file_location("user_app", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InMemoryUserRepository:
    def __init__(self):
        self.users = {}
        self.next_id = 1

    async def find_by_email(self, email):
        return next((u for u in self.users.values() if u["email"] == email.lower()), None)

    async def create(self, data):
        user_id = str(self.next_id)
        self.next_id += 1
        user = {"_id": user_id, **data}
        self.users[user_id] = user
        return user

    async def find_by_id(self, user_id):
        return self.users.get(user_id)


class InMemoryRedis:
    def __init__(self):
        self.values = {}

    async def setex(self, key, ttl, value):
        self.values[key] = value

    async def get(self, key):
        return self.values.get(key)


@pytest.mark.asyncio
async def test_register_login_and_profile():
    module = load_app()
    app = module.make_app(InMemoryUserRepository())
    app.state.redis = InMemoryRedis()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        health = await client.get("/health")
        assert health.status_code == 200

        registered = await client.post("/users/register", json={
            "name": "Test User",
            "email": "test@example.com",
            "password": "securepass",
        })
        assert registered.status_code == 201
        assert registered.json()["email"] == "test@example.com"

        login = await client.post("/auth/login", json={
            "email": "test@example.com",
            "password": "securepass",
        })
        assert login.status_code == 200
        token = login.json()["access_token"]

        profile = await client.get(
            "/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert profile.status_code == 200
