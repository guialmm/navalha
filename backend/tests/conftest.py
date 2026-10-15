import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://navalha:navalha@localhost:5434/navalha_test")
os.environ["ENV"] = "test"

import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app import models  # noqa: E402, F401
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.seed import popular  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
async def schema():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def barbearia():
    async with SessionLocal() as s:
        popular(s)
        await s.commit()
    yield
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def session():
    async with SessionLocal() as s:
        yield s
