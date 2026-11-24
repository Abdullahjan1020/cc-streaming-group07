import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient
from redis.asyncio import Redis

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("notification-service")


class NotificationCreate(BaseModel):
    order_id: str = Field(min_length=1, max_length=100)
    user_id: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=2, max_length=50)
    message: str = Field(min_length=1, max_length=2000)


class NotificationResponse(BaseModel):
    id: str
    order_id: str
    user_id: str
    type: str
    message: str
    created_at: datetime


class MongoNotificationRepository:
    def __init__(self, database):
        self.notifications = database.notifications

    async def create(self, data: dict) -> dict:
        result = await self.notifications.insert_one(data)
        return await self.notifications.find_one({"_id": result.inserted_id})

    async def list(self, order_id: str | None = None, user_id: str | None = None) -> list[dict]:
        query = {}
        if order_id:
            query["order_id"] = order_id
        if user_id:
            query["user_id"] = user_id
        cursor = self.notifications.find(query).sort("created_at", -1)
        return await cursor.to_list(length=200)


def make_app(repository=None) -> FastAPI:
    mongo = None
    redis = None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        nonlocal mongo, redis
        mongo = AsyncMongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
        database = mongo[os.getenv("MONGODB_DATABASE", "notification_db")]
        await database.notifications.create_index("order_id")
        await database.notifications.create_index("user_id")
        redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        application.state.repository = repository or MongoNotificationRepository(database)
        application.state.redis = redis
        application.state.mongo = mongo
        logger.info("Notification service started")
        yield
        await redis.aclose()
        await mongo.close()

    app = FastAPI(title="Notification Service", lifespan=lifespan)
    app.state.repository = repository
    app.state.redis = None
    app.state.mongo = None

    @app.get("/health")
    async def health():
        if app.state.mongo:
            await app.state.mongo.admin.command("ping")
        return {"status": "ok", "service": "notification-service"}

    @app.post("/notifications", response_model=NotificationResponse, status_code=status.HTTP_201_CREATED)
    async def create_notification(request: NotificationCreate):
        created = await app.state.repository.create({
            **request.model_dump(),
            "created_at": datetime.now(timezone.utc),
        })
        return _response(created)

    @app.get("/notifications", response_model=list[NotificationResponse])
    async def list_notifications(order_id: str | None = None, user_id: str | None = None):
        notifications = await app.state.repository.list(order_id=order_id, user_id=user_id)
        return [_response(notification) for notification in notifications]

    return app


def _response(notification: dict) -> NotificationResponse:
    return NotificationResponse(
        id=str(notification["_id"]),
        order_id=notification["order_id"],
        user_id=notification["user_id"],
        type=notification["type"],
        message=notification["message"],
        created_at=notification["created_at"],
    )


app = make_app()
