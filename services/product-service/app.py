import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient
from redis.asyncio import Redis

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("product-service")


class ProductCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    description: str = Field(default="", max_length=2000)
    price: float = Field(gt=0, le=1_000_000)
    stock: int = Field(ge=0, le=1_000_000)


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    description: str | None = Field(default=None, max_length=2000)
    price: float | None = Field(default=None, gt=0, le=1_000_000)
    stock: int | None = Field(default=None, ge=0, le=1_000_000)


class ProductResponse(BaseModel):
    id: str
    name: str
    description: str
    price: float
    stock: int
    created_at: datetime
    updated_at: datetime


class MongoProductRepository:
    def __init__(self, database):
        self.products = database.products

    async def create(self, data: dict) -> dict:
        result = await self.products.insert_one(data)
        return await self.products.find_one({"_id": result.inserted_id})

    async def list(self, skip: int, limit: int) -> list[dict]:
        return await self.products.find().sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)

    async def count(self) -> int:
        return await self.products.count_documents({})

    async def find(self, product_id: str) -> dict | None:
        if not ObjectId.is_valid(product_id):
            return None
        return await self.products.find_one({"_id": ObjectId(product_id)})

    async def update(self, product_id: str, data: dict) -> dict | None:
        if not ObjectId.is_valid(product_id):
            return None
        result = await self.products.find_one_and_update(
            {"_id": ObjectId(product_id)},
            {"$set": data},
            return_document=True,
        )
        return result

    async def delete(self, product_id: str) -> bool:
        if not ObjectId.is_valid(product_id):
            return False
        result = await self.products.delete_one({"_id": ObjectId(product_id)})
        return result.deleted_count == 1


def make_app(repository=None) -> FastAPI:
    mongo = None
    redis = None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        nonlocal mongo, redis
        mongo = AsyncMongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
        database = mongo[os.getenv("MONGODB_DATABASE", "product_db")]
        await database.products.create_index("name")
        redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        application.state.repository = repository or MongoProductRepository(database)
        application.state.redis = redis
        application.state.mongo = mongo
        logger.info("Product service started")
        yield
        await redis.aclose()
        await mongo.close()

    app = FastAPI(title="Product Service", lifespan=lifespan)
    app.state.redis = None
    app.state.repository = repository

    @app.get("/health")
    async def health():
        if app.state.mongo:
            await app.state.mongo.admin.command("ping")
        return {"status": "ok", "service": "product-service"}

    @app.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
    async def create_product(request: ProductCreate):
        now = datetime.now(timezone.utc)
        created = await app.state.repository.create({
            **request.model_dump(),
            "created_at": now,
            "updated_at": now,
        })
        return _response(created)

    @app.get("/products")
    async def list_products(
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        cache_key = f"products:list:{skip}:{limit}"
        if app.state.redis:
            cached = await app.state.redis.get(cache_key)
            if cached:
                payload = json.loads(cached)
                return {"items": payload["items"], "total": payload["total"]}
        items = await app.state.repository.list(skip, limit)
        total = await app.state.repository.count()
        payload = {"items": [_response(item).model_dump(mode="json") for item in items], "total": total}
        if app.state.redis:
            await app.state.redis.setex(cache_key, 30, json.dumps(payload))
        return payload

    @app.get("/products/{product_id}", response_model=ProductResponse)
    async def get_product(product_id: str):
        cache_key = f"product:{product_id}"
        if app.state.redis:
            cached = await app.state.redis.get(cache_key)
            if cached:
                return json.loads(cached)
        product = await app.state.repository.find(product_id)
        if not product:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
        response = _response(product).model_dump(mode="json")
        if app.state.redis:
            await app.state.redis.setex(cache_key, 30, json.dumps(response))
        return response

    @app.patch("/products/{product_id}", response_model=ProductResponse)
    async def update_product(product_id: str, request: ProductUpdate):
        updates = request.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields supplied")
        updates["updated_at"] = datetime.now(timezone.utc)
        updated = await app.state.repository.update(product_id, updates)
        if not updated:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
        if app.state.redis:
            await app.state.redis.delete(f"product:{product_id}")
        return _response(updated)

    @app.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_product(product_id: str):
        deleted = await app.state.repository.delete(product_id)
        if not deleted:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
        if app.state.redis:
            await app.state.redis.delete(f"product:{product_id}")
        return None

    app.state.mongo = None
    return app


def _response(product: dict) -> ProductResponse:
    return ProductResponse(
        id=str(product["_id"]),
        name=product["name"],
        description=product.get("description", ""),
        price=product["price"],
        stock=product["stock"],
        created_at=product["created_at"],
        updated_at=product["updated_at"],
    )


app = make_app()
