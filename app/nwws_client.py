import asyncio
import logging
import re
import slixmpp
from app.config import get_settings
from app.models import MessageCreate
from app.message_processor import message_processor

logger = logging.getLogger(__name__)

NWWS_HOST = "nwws-oi.weather.gov"
NWWS_PORT = 5223
NWWS_MUC = "NWWS@conference.nwws-oi.weather.gov"


class NWWSClient(slixmpp.ClientXMPP):
    def __init__(self, username: str, password: str):
        super().__init__(username, password)

        self.ssl_version = "tls"
        self.force_starttls = True
        self.use_srv = False
        self.port = NWWS_PORT

        self.register_plugin("xep_0045")  # MUC
        self.add_event_handler("session_start", self.on_session_start)
        self.add_event_handler("groupchat_message", self.on_groupchat_message)
        self.add_event_handler("disconnected", self.on_disconnected)
        self.add_event_handler("connection_failed", self.on_connection_failed)

        self._connected = False
        self._reconnect_delay = 5
        self._max_delay = 300
        self._messages_count = 0
        self._on_disconnect = None
        self._running = False

    async def on_session_start(self, event):
        logger.info("NWWS-OI session started, joining MUC room")
        self._connected = True
        self._reconnect_delay = 5
        self.get_plugin("xep_0045").join_muc(NWWS_MUC, self.boundjid.user)
        await self.plugin["xep_0199"].keepalive(timeout=60)

    async def on_groupchat_message(self, msg):
        if msg["mucnick"] == self.boundjid.user:
            return

        body = msg["body"]
        if not body:
            return

        try:
            parsed = self._parse_message(body)
            if parsed:
                stored = await message_processor.process(parsed)
                if stored:
                    self._messages_count += 1
        except Exception:
            logger.exception("Error processing NWWS message")

    def _parse_message(self, body: str) -> MessageCreate | None:
        lines = body.strip().splitlines()
        if not lines:
            return None

        wmo_heading = None
        awips_id = None
        pil_code = None
        office = None

        # WMO heading pattern: 6 uppercase letters + 2 digits (e.g., WFUS53)
        wmo_pattern = re.compile(r"^([A-Z]{4}\d{2})\s+(\w+)\s+(\d+)", re.IGNORECASE)
        # AWIPS pattern: 3-4 letters
        awips_pattern = re.compile(r"^[A-Z]{3,4}$")

        for i, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            if wmo_heading is None and wmo_pattern.match(line):
                parts = line.split()
                wmo_heading = parts[0]
                if len(parts) > 1:
                    office = parts[1][:10]
            elif awips_id is None and awips_pattern.match(line):
                awips_id = line
                pil_code = line
            if wmo_heading and awips_id:
                break

        if not pil_code:
            for line in lines:
                line = line.strip()
                if awips_pattern.match(line):
                    pil_code = line
                    break

        if not pil_code:
            # Try to derive from content
            for line in lines[:10]:
                line = line.strip()
                if len(line) >= 3 and len(line) <= 6 and line.isalpha():
                    pil_code = line.upper()
                    break

        if not pil_code:
            pil_code = "UNK"

        if not office:
            office = "NWS"

        return MessageCreate(
            source="nwws",
            wmo_heading=wmo_heading,
            awips_id=awips_id,
            pil_code=pil_code,
            office=office,
            product_text=body,
        )

    def on_disconnected(self, event):
        self._connected = False
        logger.warning("NWWS-OI disconnected")

    def on_connection_failed(self, event):
        self._connected = False
        logger.warning("NWWS-OI connection failed")

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def messages_count(self) -> int:
        return self._messages_count


class NWWSManager:
    def __init__(self):
        self._client: NWWSClient | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._enabled = False

    async def start(self):
        settings = get_settings()
        if not settings.nwws_enabled:
            logger.info("NWWS-OI credentials not provided, skipping")
            return

        self._enabled = True
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("NWWS-OI manager started")

    async def stop(self):
        self._running = False
        if self._client:
            self.disconnect()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NWWS-OI manager stopped")

    async def _run_loop(self):
        settings = get_settings()
        delay = 5
        max_delay = 300

        while self._running:
            try:
                self._client = NWWSClient(settings.nwws_username, settings.nwws_password)
                self._client.connect(use_ssl=False)
                self._client.process(forever=False)
                while self._running and self._client._connected:
                    await asyncio.sleep(1)
            except Exception:
                logger.exception("NWWS-OI error")
            finally:
                if self._client:
                    self._client.disconnect()

            if self._running:
                logger.info("Reconnecting in %d seconds...", delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, max_delay)

    @property
    def status(self) -> dict:
        return {
            "enabled": self._enabled,
            "connected": bool(self._client and self._client.is_connected),
            "messages_count": self._client.messages_count if self._client else 0,
        }


nwws_manager = NWWSManager()
