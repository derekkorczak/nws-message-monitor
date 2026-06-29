import asyncio
import logging
from datetime import datetime, timezone
import httpx
from app.config import get_settings
from app.models import MessageCreate
from app.message_processor import message_processor

logger = logging.getLogger(__name__)

NWS_API_BASE = "https://api.weather.gov"


class APIPoller:
    def __init__(self):
        self._task = None
        self._running = False
        self._status = {
            "connected": False,
            "last_poll": None,
            "messages_count": 0,
        }

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("API poller started")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("API poller stopped")

    async def _poll_loop(self):
        while self._running:
            try:
                await self._poll_once()
            except Exception:
                logger.exception("API poller error")
            settings = get_settings()
            await asyncio.sleep(settings.api_poll_interval)

    async def _poll_once(self):
        settings = get_settings()
        headers = {"User-Agent": settings.api_user_agent}

        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            resp = await client.get(f"{NWS_API_BASE}/alerts/active")
            if resp.status_code != 200:
                logger.warning("API poll failed: %s", resp.status_code)
                self._status["connected"] = False
                return

            self._status["connected"] = True
            self._status["last_poll"] = datetime.now(timezone.utc).isoformat()

            data = resp.json()
            features = data.get("features", [])

            for feature in features:
                props = feature.get("properties", {})
                await self._process_alert(props)

    async def _process_alert(self, alert: dict):
        alert_id = alert.get("id")
        if not alert_id:
            return

        event = alert.get("event", "Unknown")
        headline = alert.get("headline", "")
        description = alert.get("description", "")
        area_desc = alert.get("areaDesc", "")
        severity = alert.get("severity", "")
        urgency = alert.get("urgency", "")
        certainty = alert.get("certainty", "")
        sender = alert.get("senderName", "")

        product_text = f"{event}\n{headline}\n\n{description}\n\nArea: {area_desc}\nSeverity: {severity}\nUrgency: {urgency}\nCertainty: {certainty}\nSender: {sender}"

        params = alert.get("parameters") or {}

        wmo_heading = None
        wmo_vals = params.get("WMOidentifier") or []
        if wmo_vals and wmo_vals[0]:
            wmo_heading = wmo_vals[0]

        office = "NWS"
        pil_code = event[:3].upper() if len(event) >= 3 else event.upper()

        awips_vals = params.get("AWIPSidentifier") or []
        if awips_vals and awips_vals[0] and len(awips_vals[0]) >= 6:
            code = awips_vals[0].upper()
            pil_code = code[:3]
            office = code[-3:]
        elif wmo_heading:
            parts = wmo_heading.split()
            if len(parts) >= 2 and len(parts[1]) >= 4:
                candidate = parts[1].upper()
                if candidate[0] in ("K", "P", "T", "U"):
                    office = candidate[1:4]

        expires_at = None
        if alert.get("expires"):
            try:
                expires_at = datetime.fromisoformat(alert["expires"].replace("Z", "+00:00"))
            except Exception:
                pass

        msg = MessageCreate(
            source="api",
            wmo_heading=wmo_heading[:50] if wmo_heading else None,
            awips_id=alert_id[:255],
            pil_code=pil_code[:50],
            office=office[:50],
            product_text=product_text,
            severity=severity if severity else None,
            expires_at=expires_at,
        )

        stored = await message_processor.process(msg)
        if stored:
            self._status["messages_count"] += 1

    @property
    def status(self) -> dict:
        return self._status


api_poller = APIPoller()
