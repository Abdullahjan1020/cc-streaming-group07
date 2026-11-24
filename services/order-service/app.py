import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from bson import ObjectId
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient
from redis.asyncio import Redis

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("order-service")


class OrderItemRequest(BaseModel):
    product_id: str
    quantity: int = Field(ge=1, le=1_000)


class OrderCreateRequest(BaseModel):
    user_id: str
    items: list[OrderItemRequest] = Field(min_length=1, max_length=100)


class StatusUpdateRequest(BaseModel):
    status: str


class OrderItemResponse(BaseModel):
    product_id: str
    name: str
    price: float
    quantity: int
    subtotal: float


class OrderResponse(BaseModel):
    id: str
    user_id: str
    items: list[OrderItemResponse]
    total: float
    status: str
    created_at: datetime
    updated_at: datetime


class MongoOrderRepository:
    def __init__(self, database):
        self.orders = database.orders

    async def create(self, data: dict) -> dict:
        result = await self.orders.insert_one(data)
        return await self.orders.find_one({"_id": result.inserted_id})

    async def find(self, order_id: str) -> dict | None:
        if not ObjectId.is_valid(order_id):
            return None
        return await self.orders.find_one({"_id": ObjectId(order_id)})

    async def list_for_user(self, user_id: str) -> list[dict]:
        cursor = self.orders.find({"user_id": user_id}).sort("created_at", -1)
        return await cursor.to_list(length=200)

    async def update_status(self, order_id: str, order_status: str) -> dict | None:
        if not ObjectId.is_valid(order_id):
            return None
        return await self.orders.find_one_and_update(
            {"_id": ObjectId(order_id)},
            {"$set": {"status": order_status, "updated_at": datetime.now(timezone.utc)}},
            return_document=True,
        )


def make_app(repository=None) -> FastAPI:
    mongo = None
    redis = None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        nonlocal mongo, redis
        mongo = AsyncMongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
        database = mongo[os.getenv("MONGODB_DATABASE", "order_db")]
        await database.orders.create_index("user_id")
        redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        application.state.repository = repository or MongoOrderRepository(database)
        application.state.redis = redis
        application.state.mongo = mongo
        application.state.http = httpx.AsyncClient(timeout=3.0)
        logger.info("Order service started")
        yield
        await application.state.http.aclose()
        await redis.aclose()
        await mongo.close()

    app = FastAPI(title="Order Service", lifespan=lifespan)
    app.state.repository = repository
    app.state.redis = None
    app.state.mongo = None
    app.state.http = None

    @app.get("/health")
    async def health():
        if app.state.mongo:
            await app.state.mongo.admin.command("ping")
        return {"status": "ok", "service": "order-service"}

    @app.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
    async def create_order(request: OrderCreateRequest):
        if app.state.http is None:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Product service client unavailable")
        product_url = os.getenv("PRODUCT_SERVICE_URL", "http://localhost:8002").rstrip("/")
        notification_url = os.getenv("NOTIFICATION_SERVICE_URL", "http://localhost:8004").rstrip("/")
        items = []
        total = 0.0
        for item in request.items:
            try:
                response = await app.state.http.get(f"{product_url}/products/{item.product_id}")
            except httpx.HTTPError as exc:
                logger.error("Product validation failed: %s", exc)
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Product service unavailable")
            if response.status_code == 404:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Product {item.product_id} not found")
            if response.status_code != 200:
                raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Product validation failed")
            product = response.json()
            if product["stock"] < item.quantity:
                raise HTTPException(status.HTTP_409_CONFLICT, f"Insufficient stock for product {item.product_id}")
            subtotal = round(product["price"] * item.quantity, 2)
            items.append({
                "product_id": item.product_id,
                "name": product["name"],
                "price": product["price"],
                "quantity": item.quantity,
                "subtotal": subtotal,
            })
            total += subtotal

        now = datetime.now(timezone.utc)
        created = await app.state.repository.create({
            "user_id": request.user_id,
            "items": items,
            "total": round(total, 2),
            "status": "created",
            "created_at": now,
            "updated_at": now,
        })
        if app.state.http:
            try:
                await app.state.http.post(f"{notification_url}/notifications", json={
                    "order_id": str(created["_id"]),
                    "user_id": request.user_id,
                    "type": "order_created",
                    "message": f"Order {created['_id']} was created",
                })
            except httpx.HTTPError:
                logger.warning("Order created but notification delivery failed")
        return _response(created)

    @app.get("/orders/{order_id}", response_model=OrderResponse)
    async def get_order(order_id: str):
        order = await app.state.repository.find(order_id)
        if not order:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        return _response(order)

    @app.get("/users/{user_id}/orders", response_model=list[OrderResponse])
    async def list_user_orders(user_id: str):
        orders = await app.state.repository.list_for_user(user_id)
        return [_response(order) for order in orders]

    @app.patch("/orders/{order_id}/status", response_model=OrderResponse)
    async def update_status(order_id: str, request: StatusUpdateRequest):
        allowed = {"created", "confirmed", "processing", "shipped", "delivered", "cancelled"}
        order_status = request.status
        if order_status not in allowed:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid order status")
        updated = await app.state.repository.update_status(order_id, order_status)
        if not updated:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Order not found")
        return _response(updated)

    return app


def _response(order: dict) -> OrderResponse:
    return OrderResponse(
        id=str(order["_id"]),
        user_id=order["user_id"],
        items=order["items"],
        total=order["total"],
        status=order["status"],
        created_at=order["created_at"],
        updated_at=order["updated_at"],
    )


app = make_app()
