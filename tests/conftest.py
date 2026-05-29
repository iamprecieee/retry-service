import os
import sys

# Add project root to sys.path so 'app' can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import tempfile
from typing import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from alembic import command
from alembic.config import Config
from app.database import AsyncSessionFactory
from app.main import app

# 1. Set environment variable BEFORE importing app modules so it uses the test DB
db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Apply migrations to the test DB."""
    alembic_cfg = Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    command.upgrade(alembic_cfg, "head")

    yield

    os.close(db_fd)
    os.unlink(db_path)


@pytest.fixture(autouse=True)
async def clear_database():
    """Clear tables before each test to ensure isolation."""
    yield
    async with AsyncSessionFactory() as session:
        await session.execute(text("DELETE FROM attempts"))
        await session.execute(text("DELETE FROM requests"))
        await session.commit()


@pytest.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Test client mounted to the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
