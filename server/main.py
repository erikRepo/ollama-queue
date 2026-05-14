"""FastAPI application entry point."""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.config import load_settings
from server.database import get_connection, get_db_path, init_db
from server.router import router
from server.worker import run_worker

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)

_settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Run database migrations and start the background worker on startup."""
    db_path = get_db_path(_settings.database_url)
    init_db(db_path)
    conn = get_connection(db_path)
    task = asyncio.create_task(run_worker(_settings, conn))
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        conn.close()


app = FastAPI(lifespan=lifespan)
app.include_router(router, prefix="/api")
