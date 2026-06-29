import asyncio
import logging
from app.config import get_settings
from app.database import get_pool
from app.sse import broadcaster

logger = logging.getLogger(__name__)


class RetentionCleanup:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Retention cleanup started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self):
        while self._running:
            try:
                await self._cleanup()
            except Exception:
                logger.exception("Retention cleanup failed")
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                break

    async def _cleanup(self) -> int:
        settings = get_settings()
        pool = get_pool()

        expired_rows = await pool.fetch(
            "DELETE FROM messages WHERE expires_at IS NOT NULL AND expires_at < NOW() RETURNING id"
        )
        expired_ids = [str(r["id"]) for r in expired_rows]

        deleted = await pool.execute(
            "DELETE FROM messages WHERE is_deleted = TRUE AND deleted_at < NOW() - INTERVAL '7 days'"
        )

        if expired_ids:
            await broadcaster.broadcast_messages_expired(expired_ids)

        total = len(expired_ids) + int(deleted.split()[-1])
        if total > 0:
            logger.info("Retention cleanup: removed %d expired, %d deleted records",
                        len(expired_ids), int(deleted.split()[-1]))
        return total


retention = RetentionCleanup()
