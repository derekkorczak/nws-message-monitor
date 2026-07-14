import logging
from datetime import datetime, timezone

from app.database import get_pool

logger = logging.getLogger(__name__)

TEST_WMO_PREFIX = "NTXX98 KFGF"
SETTINGS_KEY = "last_test_message_at"


def is_test_message(wmo_heading: str | None) -> bool:
    if not wmo_heading:
        return False
    return wmo_heading.strip().upper().startswith(TEST_WMO_PREFIX)


class TestMessageTracker:
    def __init__(self):
        self._last: datetime | None = None

    async def load(self):
        try:
            pool = get_pool()
            row = await pool.fetchrow("SELECT value FROM settings WHERE key = $1", SETTINGS_KEY)
            if row and row["value"]:
                parsed = datetime.fromisoformat(row["value"])
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                self._last = parsed
        except Exception as e:
            logger.warning("Failed to load last test message timestamp: %s", e)

    async def record(self, when: datetime | None = None) -> datetime:
        ts = when or datetime.now(timezone.utc)
        self._last = ts
        try:
            pool = get_pool()
            await pool.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()",
                SETTINGS_KEY, ts.isoformat(),
            )
        except Exception as e:
            logger.warning("Failed to persist last test message timestamp: %s", e)
        return ts

    @property
    def last(self) -> datetime | None:
        return self._last


test_message_tracker = TestMessageTracker()
