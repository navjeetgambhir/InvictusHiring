from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from sqlalchemy import select
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.core.database import engine, Base, get_db
from app.core.logging import setup_logging
from app.core.security import encrypt_email, hash_email, hash_password
from app.db.models import User
from app.api.routes import jd, auth, jobs, agent_cards, candidates, analytics, interviews

setup_logging()

_DEMO_USERS = [
    {"email": "hr@invictushiring.co",  "name": "Sarah Chen",  "role": "hr",  "password": "password"},
    {"email": "hm@invictushiring.co",  "name": "Alex Kumar",  "role": "hm",  "password": "password"},
]


async def _seed_demo_users() -> None:
    """Insert demo users on first startup. Skips any that already exist."""
    async for db in get_db():
        for u in _DEMO_USERS:
            digest = hash_email(u["email"])
            exists = await db.execute(select(User).where(User.email_hash == digest))
            if exists.scalar_one_or_none():
                continue
            db.add(User(
                email_hash=digest,
                email_encrypted=encrypt_email(u["email"]),
                name=u["name"],
                role=u["role"],
                hashed_password=hash_password(u["password"]),
            ))
        await db.commit()
        logger.info("Demo users seeded")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Hiring Automation API — initialising database tables")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database ready")
    await _seed_demo_users()
    yield
    logger.info("Shutting down")


app = FastAPI(
    title="Hiring Automation API",
    description="Agentic JD drafting, candidate shortlisting, and interview coordination",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.debug(f"→ {request.method} {request.url.path}")
    response = await call_next(request)
    logger.debug(f"← {request.method} {request.url.path} {response.status_code}")
    return response


app.include_router(auth.router, prefix="/api")
app.include_router(jd.router, prefix="/api")
app.include_router(jobs.router, prefix="/api")
app.include_router(candidates.router, prefix="/api")
app.include_router(analytics.router, prefix="/api")
app.include_router(interviews.router, prefix="/api")
app.include_router(agent_cards.router)  # served at root — no /api prefix


@app.get("/health")
async def health():
    return {"status": "ok"}