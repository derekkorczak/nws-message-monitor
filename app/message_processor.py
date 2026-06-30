import logging
import json
from datetime import datetime, timezone, timedelta
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
            return False

        pool = get_pool()

        # --- Dedup by awips_id (same-source or same URN) ---
        if msg.awips_id:
            existing = await pool.fetchrow(
                "SELECT id, is_deleted, source, product_text, wmo_heading FROM messages "
                "WHERE awips_id = $1 "
                "AND COALESCE(expires_at, received_at + INTERVAL '1 hour') > NOW()",
                msg.awips_id,
            )
            if existing:
                if not existing["is_deleted"] and msg.source == "nwws":
                    new_text = msg.product_text
                    existing_text = existing["product_text"]
                    new_wmo = msg.wmo_heading if msg.wmo_heading else existing["wmo_heading"]
                    if new_text and existing_text and len(new_text) < len(existing_text):
                        new_text = existing_text
                    await pool.execute(
                        "UPDATE messages SET source = 'nwws', product_text = $1, "
                        "wmo_heading = $2 WHERE id = $3",
                        new_text, new_wmo, existing["id"],
                    )
                return False

        # --- Dedup by wmo_heading (cross-source: NWWS vs API for same product) ---
        # Both NWWS and API carry the same WMO heading line (e.g. "WWUS53 KBIS 292230")
        # which uniquely identifies a product issuance.  Use it to avoid storing the
        # same product twice when both sources deliver it.
        if msg.wmo_heading:
            existing_wmo = await pool.fetchrow(
                "SELECT id, is_deleted, source, product_text FROM messages "
                "WHERE wmo_heading = $1 "
                "AND COALESCE(expires_at, received_at + INTERVAL '2 hours') > NOW()",
                msg.wmo_heading,
            )
            if existing_wmo and not existing_wmo["is_deleted"]:
                if msg.source == "nwws" and existing_wmo["source"] != "nwws":
                    # Upgrade the existing API record to NWWS with the raw product text.
                    await pool.execute(
                        "UPDATE messages SET source = 'nwws', product_text = $1, "
                        "awips_id = COALESCE(awips_id, $2) WHERE id = $3",
                        msg.product_text,
                        msg.awips_id,
                        existing_wmo["id"],
                    )
                return False

        row = await pool.fetchrow(
            "INSERT INTO messages (source, wmo_heading, awips_id, pil_code, office, "
            "product_text, severity, expires_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
            "RETURNING id, received_at",
            msg.source, msg.wmo_heading, msg.awips_id, msg.pil_code,
            msg.office, msg.product_text, msg.severity, msg.expires_at,
        )

        expires_at = msg.expires_at
        if expires_at is None:
            pil_exp_row = await pool.fetchrow(
                "SELECT value FROM settings WHERE key = 'pil_expirations'"
            )
            pil_minutes = None
            if pil_exp_row:
                try:
                    pil_map = json.loads(pil_exp_row["value"])
                    if isinstance(pil_map, dict) and msg.pil_code:
                        raw = pil_map.get(msg.pil_code) or pil_map.get(msg.pil_code.upper())
                        if raw is not None:
                            pil_minutes = int(raw)
                except (json.JSONDecodeError, TypeError, ValueError):
                    pil_minutes = None

            minutes = None
            if pil_minutes and pil_minutes > 0:
                minutes = pil_minutes
            else:
                default_exp_row = await pool.fetchrow(
                    "SELECT value FROM settings WHERE key = 'default_expiration_minutes'"
                )
                if default_exp_row:
                    try:
                        default_minutes = int(default_exp_row["value"])
                        if default_minutes > 0:
                            minutes = default_minutes
                    except ValueError:
                        minutes = None

            if minutes is not None:
                expires_at = row["received_at"] + timedelta(minutes=minutes)
                await pool.execute(
                    "UPDATE messages SET expires_at = $1 WHERE id = $2",
                    expires_at, row["id"],
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
            severity=msg.severity,
            is_deleted=False,
            deleted_at=None,
            expires_at=expires_at,
        )

        await broadcaster.broadcast_message(stored)
        logger.info("Stored message: pil=%s office=%s source=%s", msg.pil_code, msg.office, msg.source)
        return True


message_processor = MessageProcessor()
