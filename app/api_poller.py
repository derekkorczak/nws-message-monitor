import asyncio
import logging
import json
from datetime import datetime, timezone
import httpx
from app.config import get_settings
from app.models import MessageCreate
from app.message_processor import message_processor

logger = logging.getLogger(__name__)

NWS_API_BASE = "https://api.weather.gov"


class APIPoller:
    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        self._last_poll: datetime | None = None
        self._last_error: str | None = None
        self._connected = False
        self._alerts_seen: set[str] = set()
        self._messages_count = 0

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
        settings = get_settings()
        async with httpx.AsyncClient(
            headers={"User-Agent": settings.api_user_agent},
            timeout=30.0,
        ) as client:
            while self._running:
                try:
                    await self._poll_once(client)
                    self._connected = True
                    self._last_error = None
                except Exception as exc:
                    self._connected = False
                    self._last_error = str(exc)
                    logger.exception("API poll failed")

                try:
                    await asyncio.sleep(settings.api_poll_interval)
                except asyncio.CancelledError:
                    break

    async def _poll_once(self, client: httpx.AsyncClient):
        resp = await client.get(f"{NWS_API_BASE}/alerts/active")
        resp.raise_for_status()
        data = resp.json()

        self._last_poll = datetime.now(timezone.utc)

        features = data.get("features", [])
        new_count = 0

        for feature in features:
            alert_id = feature.get("id", "")
            if alert_id in self._alerts_seen:
                continue
            self._alerts_seen.add(alert_id)

            msg = self._feature_to_message(feature)
            if msg and await message_processor.process(msg):
                new_count += 1

        keep = 1000
        if len(self._alerts_seen) > keep:
            excess = len(self._alerts_seen) - keep
            for _ in range(excess):
                self._alerts_seen.pop()

        if new_count:
            self._messages_count += new_count
            logger.info("API poll: %d new alerts of %d active", new_count, len(features))

    def _feature_to_message(self, feature: dict) -> MessageCreate | None:
        props = feature.get("properties", {})
        event = props.get("event", "UNKNOWN")
        sender = props.get("sender", "NWS")
        headline = props.get("headline", event)
        expires_str = props.get("expires")
        expires_at = None
        if expires_str:
            try:
                expires_at = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
            except ValueError:
                pass

        geometry = feature.get("geometry")
        if geometry:
            summary = f"ALERT: {headline}\n\nEvent: {event}\nSender: {sender}\n"
            for k in ("severity", "urgency", "certainty", "responseTypes"):
                if k in props:
                    summary += f"{k}: {props[k]}\n"
            if props.get("description"):
                summary += f"\nDescription:\n{props['description']}\n"
            if props.get("instruction"):
                summary += f"\nInstruction:\n{props['instruction']}\n"
            if props.get("areaDesc"):
                summary += f"\nAreas: {props['areaDesc']}\n"
            if props.get("parameter"):
                summary += f"\nParameters:\n{json.dumps(props['parameter'], indent=2)}\n"
            if geometry:
                summary += f"\nGeometry:\n{json.dumps(geometry)}\n"
            product_text = summary
        else:
            product_text = headline

        office = sender.split("/")[-1] if "/" in sender else sender[:10]

        return MessageCreate(
            source="api",
            wmo_heading=None,
            awips_id=props.get("id", None),
            pil_code=event.upper().replace(" ", "_")[:10],
            office=office[:10],
            product_text=product_text,
            expires_at=expires_at,
        )

    @property
    def status(self) -> dict:
        return {
            "connected": self._connected,
            "last_poll": self._last_poll.isoformat() if self._last_poll else None,
            "messages_count": self._messages_count,
            "error": self._last_error,
        }


api_poller = APIPoller()
