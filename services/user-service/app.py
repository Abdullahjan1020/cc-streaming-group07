import base64
import hashlib
import hmac
import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

from bson import ObjectId
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from pymongo import AsyncMongoClient
from redis.asyncio import Redis

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("user-service")


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str


class UserResponse(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return f"{base64.b64encode(salt).decode()}.{base64.b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        salt_text, digest_text = encoded.split(".", 1)
        salt = base64.b64decode(salt_text)
        digest = base64.b64decode(digest_text)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
        return hmac.compare_digest(candidate, digest)
    except (ValueError, TypeError):
        return False


class MongoUserRepository:
    def __init__(self, database):
        self.users = database.users

    async def create(self, data: dict) -> dict:
        result = await self.users.insert_one(data)
        return await self.users.find_one({"_id": result.inserted_id})

    async def find_by_email(self, email: str) -> dict | None:
        return await self.users.find_one({"email": email.lower()})

    async def find_by_id(self, user_id: str) -> dict | None:
        if not ObjectId.is_valid(user_id):
            return None
        return await self.users.find_one({"_id": ObjectId(user_id)})


def make_app(repository=None) -> FastAPI:
    mongo = None
    redis = None

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        nonlocal mongo, redis
        mongo = AsyncMongoClient(os.getenv("MONGODB_URI", "mongodb://localhost:27017"))
        database = mongo[os.getenv("MONGODB_DATABASE", "user_db")]
        await database.users.create_index("email", unique=True)
        redis = Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
        application.state.repository = repository or MongoUserRepository(database)
        application.state.redis = redis
        application.state.mongo = mongo
        logger.info("User service started")
        yield
        await redis.aclose()
        await mongo.close()

    app = FastAPI(title="User Service", lifespan=lifespan)
    app.state.repository = repository
    app.state.redis = None
    app.state.mongo = None

    @app.get("/health")
    async def health():
        if app.state.mongo:
            await app.state.mongo.admin.command("ping")
        return {"status": "ok", "service": "user-service"}

    @app.post("/users/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
    async def register(request: RegisterRequest):
        existing = await app.state.repository.find_by_email(str(request.email))
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
        now = datetime.now(timezone.utc)
        created = await app.state.repository.create({
            "name": request.name.strip(),
            "email": str(request.email).lower(),
            "password_hash": hash_password(request.password),
            "created_at": now,
        })
        return _user_response(created)

    @app.post("/auth/login", response_model=LoginResponse)
    async def login(request: LoginRequest):
        user = await app.state.repository.find_by_email(str(request.email))
        if not user or not verify_password(request.password, user["password_hash"]):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
        token = secrets.token_urlsafe(32)
        if app.state.redis:
            await app.state.redis.setex(f"session:{token}", 3600, str(user["_id"]))
        return LoginResponse(
            access_token=token,
            user=_user_response(user),
        )

    @app.get("/users/me", response_model=UserResponse)
    async def profile(authorization: Annotated[str | None, Header()] = None):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Bearer token required")
        token = authorization.split(" ", 1)[1].strip()
        user_id = await app.state.redis.get(f"session:{token}") if app.state.redis else None
        if not user_id:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
        user = await app.state.repository.find_by_id(user_id.decode() if isinstance(user_id, bytes) else str(user_id))
        if not user:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
        return _user_response(user)

    app.state.mongo = None
    return app


def _user_response(user: dict) -> UserResponse:
    return UserResponse(
        id=str(user["_id"]),
        name=user["name"],
        email=user["email"],
        created_at=user["created_at"],
    )


app = make_app()
