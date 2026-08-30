"""
Async SQLAlchemy engine + session factory.
All DB access goes through get_db() dependency — never directly.
"""
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

db_url = settings.database_url

# Automatic local SQLite fallback if default credentials are present or local postgres is absent
if "change_this_to_your_supabase_db_password" in db_url:
    # Use SQLite in the root of the project
    db_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    db_path = os.path.join(db_dir, "finance.db")
    db_url = f"sqlite+aiosqlite:///{db_path}"
    print(f"[DATABASE FALLBACK]: Supabase password not set. Using local SQLite at: {db_path}")

if db_url.startswith("sqlite"):
    engine = create_async_engine(
        db_url,
        echo=False,
    )
else:
    engine = create_async_engine(
        db_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    """FastAPI dependency that yields a database session and closes it after."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
