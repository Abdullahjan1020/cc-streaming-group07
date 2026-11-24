import importlib.util
from pathlib import Path

import httpx
import pytest


def load_app():
    path = Path(__file__).parents[2] / "services" / "notification-service" / "app.py"
    spec = importlib.util.spec_from_file_location("notification_app", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InMemoryNotificationRepository:
    def __init__(self):
        self.notifications = []
        self.next_id = 1

    async def create(self, data):
        notification = {"_id": str(self.next_id), **data}
        self.next_id += 1
        self.notifications.append(notification)
        return notification

    async def list(self, order_id=None, user_id=None):
        return [
            item for item in self.notifications
            if (order_id is None or item["order_id"] == order_id)
            and (user_id is None or item["user_id"] == user_id)
        ]


@pytest.mark.asyncio
async def test_create_and_list_notifications():
    module = load_app()
    app = module.make_app(InMemoryNotificationRepository())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post("/notifications", json={
            "order_id": "order-1",
            "user_id": "user-1",
            "type": "order_created",
            "message": "Order created",
        })
        assert created.status_code == 201

        listed = await client.get("/notifications", params={"order_id": "order-1"})
        assert listed.status_code == 200
        assert len(listed.json()) == 1
