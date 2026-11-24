import importlib.util
from pathlib import Path

import httpx
import pytest


def load_app():
    path = Path(__file__).parents[2] / "services" / "order-service" / "app.py"
    spec = importlib.util.spec_from_file_location("order_app", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InMemoryOrderRepository:
    def __init__(self):
        self.orders = {}
        self.next_id = 1

    async def create(self, data):
        order_id = str(self.next_id)
        self.next_id += 1
        order = {"_id": order_id, **data}
        self.orders[order_id] = order
        return order

    async def find(self, order_id):
        return self.orders.get(order_id)

    async def list_for_user(self, user_id):
        return [order for order in self.orders.values() if order["user_id"] == user_id]

    async def update_status(self, order_id, order_status):
        if order_id not in self.orders:
            return None
        self.orders[order_id]["status"] = order_status
        return self.orders[order_id]


class MockProductClient:
    async def get(self, url):
        return httpx.Response(
            200,
            json={"id": "product-1", "name": "Plan", "price": 12.0, "stock": 3},
            request=httpx.Request("GET", url),
        )

    async def post(self, url, json):
        return httpx.Response(
            201,
            json={"id": "notification-1"},
            request=httpx.Request("POST", url),
        )


@pytest.mark.asyncio
async def test_create_retrieve_and_update_order():
    module = load_app()
    app = module.make_app(InMemoryOrderRepository())
    app.state.http = MockProductClient()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post("/orders", json={
            "user_id": "user-1",
            "items": [{"product_id": "product-1", "quantity": 2}],
        })
        assert created.status_code == 201
        order_id = created.json()["id"]
        assert created.json()["total"] == 24.0

        retrieved = await client.get(f"/orders/{order_id}")
        assert retrieved.status_code == 200

        updated = await client.patch(
            f"/orders/{order_id}/status",
            json={"status": "confirmed"},
        )
        assert updated.status_code == 200
        assert updated.json()["status"] == "confirmed"
