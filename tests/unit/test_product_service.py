import importlib.util
from pathlib import Path

import httpx
import pytest


def load_app():
    path = Path(__file__).parents[2] / "services" / "product-service" / "app.py"
    spec = importlib.util.spec_from_file_location("product_app", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InMemoryProductRepository:
    def __init__(self):
        self.products = {}
        self.next_id = 1

    async def create(self, data):
        product_id = str(self.next_id)
        self.next_id += 1
        product = {"_id": product_id, **data}
        self.products[product_id] = product
        return product

    async def list(self, skip, limit):
        values = list(self.products.values())
        return values[skip:skip + limit]

    async def count(self):
        return len(self.products)

    async def find(self, product_id):
        return self.products.get(product_id)

    async def update(self, product_id, data):
        if product_id not in self.products:
            return None
        self.products[product_id].update(data)
        return self.products[product_id]

    async def delete(self, product_id):
        return self.products.pop(product_id, None) is not None


@pytest.mark.asyncio
async def test_product_crud():
    module = load_app()
    app = module.make_app(InMemoryProductRepository())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post("/products", json={
            "name": "Streaming Plan",
            "description": "Monthly plan",
            "price": 10.5,
            "stock": 5,
        })
        assert created.status_code == 201
        product_id = created.json()["id"]

        listed = await client.get("/products")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        retrieved = await client.get(f"/products/{product_id}")
        assert retrieved.status_code == 200

        updated = await client.patch(f"/products/{product_id}", json={"stock": 8})
        assert updated.status_code == 200
        assert updated.json()["stock"] == 8

        deleted = await client.delete(f"/products/{product_id}")
        assert deleted.status_code == 204
