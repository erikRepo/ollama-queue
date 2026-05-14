"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.config import load_settings
from server.database import get_db_path, init_db
from server.router import router

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)

_settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run database migrations on startup."""
    init_db(get_db_path(_settings.database_url))
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(router, prefix="/api")
