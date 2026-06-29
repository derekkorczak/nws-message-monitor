import logging
import asyncpg
from app.config import get_settings

logger = logging.getLogger(__name__)

pool: asyncpg.Pool | None = None


async def init_db():
    global pool
    settings = get_settings()
    pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )
    await _migrate()
    logger.info("Database pool initialized")


async def _migrate():
    import pathlib
    schema_path = pathlib.Path(__file__).resolve().parent.parent / "db" / "schema.sql"
    sql = schema_path.read_text()
    async with pool.acquire() as conn:
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for sql in statements:
            try:
                await conn.execute(sql)
            except Exception as e:
                logger.warning("Migration statement warning: %s", e)
    logger.info("Database schema migrated")


async def close_db():
    global pool
    if pool:
        await pool.close()
        pool = None
        logger.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return pool
