import logging
import json
from datetime import datetime, timezone
from app.database import get_pool
from app.models import Message, MessageCreate
from app.filter_engine import filter_engine
from app.sse import broadcaster

logger = logging.getLogger(__name__)


class MessageProcessor:
    async def process(self, msg: MessageCreate) -> bool:
        """
        Process an incoming message: apply filters, check duplicates, store, broadcast.
        Returns True if the message was stored.
        """
        if not await filter_engine.should_store(msg):
            logger.debug("Message filtered out: pil=%s office=%s", msg.pil_code, msg.office)
            return False

        pool = get_pool()

        if msg.awips_id:
            existing = await pool.fetchval(
                "SELECT id FROM messages WHERE awips_id = $1 "
                "AND received_at > NOW() - INTERVAL '5 minutes'",
                msg.awips_id,
            )
            if existing:
                if msg.source == "nwws":
                    await pool.execute(
                        "UPDATE messages SET source = 'nwws', product_text = $1, "
                        "wmo_heading = $2 WHERE id = $3",
                        msg.product_text, msg.wmo_heading, existing,
                    )
                    logger.debug("Upgraded dedup message %s to nwws", existing)
                else:
                    logger.debug("Duplicate message skipped: %s", msg.awips_id)
                return False

        row = await pool.fetchrow(
            "INSERT INTO messages (source, wmo_heading, awips_id, pil_code, office, "
            "product_text, expires_at) VALUES ($1, $2, $3, $4, $5, $6, $7) "
            "RETURNING id, received_at",
            msg.source, msg.wmo_heading, msg.awips_id, msg.pil_code,
            msg.office, msg.product_text, msg.expires_at,
        )

        stored = Message(
            id=row["id"],
            received_at=row["received_at"],
            source=msg.source,
            wmo_heading=msg.wmo_heading,
            awips_id=msg.awips_id,
            pil_code=msg.pil_code,
            office=msg.office,
            product_text=msg.product_text,
            is_deleted=False,
            deleted_at=None,
            expires_at=msg.expires_at,
        )

        await broadcaster.broadcast_message(stored)
        logger.info("Stored message: pil=%s office=%s source=%s", msg.pil_code, msg.office, msg.source)
        return True


message_processor = MessageProcessor()
