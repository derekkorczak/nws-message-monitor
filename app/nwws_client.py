import asyncio
import logging
import re
import ssl
from datetime import timedelta
from datetime import datetime, timezone

import httpx
import slixmpp
from slixmpp.xmlstream import XMLStream
from app.config import get_settings
from app.models import MessageCreate
from app.message_processor import message_processor

logger = logging.getLogger(__name__)

NWWS_HOST = "nwws-oi.weather.gov"
NWWS_PORT = 5222
NWWS_MUC = "NWWS@conference.nwws-oi.weather.gov"
NWS_API_BASE = "https://api.weather.gov"


class NWWSClient(slixmpp.ClientXMPP):
    def __init__(self, username: str, password: str):
        super().__init__(username, password)

        self.ssl_context.check_hostname = False
        self.ssl_context.verify_mode = ssl.CERT_NONE

        for attr in ("enable_direct_tls", "enable_starttls", "enable_plaintext"):
            if hasattr(self, attr):
                setattr(self, "enable_direct_tls", False)
                setattr(self, "enable_starttls", True)
                setattr(self, "enable_plaintext", False)
                break

        self.use_ssl = False
        self.force_starttls = True

        self.register_plugin("xep_0045")
        self.register_plugin("xep_0199")
        self._configure_keepalive()
        self.add_event_handler("session_start", self.on_session_start)
        self.add_event_handler("groupchat_message", self.on_groupchat_message)
        self.add_event_handler("groupchat_presence", self.on_groupchat_presence)
        self.add_event_handler("disconnected", self.on_disconnected)
        self.add_event_handler("connection_failed", self.on_connection_failed)
        self.add_event_handler("failed_auth", self.on_failed_auth)

        self._connected = False
        self._reconnect_delay = 5
        self._max_delay = 300
        self._messages_count = 0
        self._on_disconnect = None
        self._running = False
        self._connect_event = asyncio.Event()

    def _configure_keepalive(self):
        """Configure XMPP ping keepalive for different slixmpp API versions."""
        try:
            xep_0199 = self.plugin["xep_0199"]
            if hasattr(xep_0199, 'settings') and isinstance(xep_0199.settings, dict):
                xep_0199.settings['send_keepalive'] = True
                xep_0199.settings['keepalive_interval'] = 30
            elif hasattr(xep_0199, 'keepalive'):
                xep_0199.keepalive = True
        except Exception as e:
            logger.warning(f"Could not configure keepalive: {e}")

    async def on_session_start(self, event):
        logger.info("NWWS-OI session started, joining MUC room")
        self._connected = True
        self._reconnect_delay = 5
        self._connect_event.set()
        # Use make_join_stanza instead of join_muc/join_muc_wait because
        # NWWS-OI doesn't send the status-110 self-presence confirmation that
        # join_muc_wait requires, causing it to always time out.
        try:
            from slixmpp import JID
            room = JID(NWWS_MUC)
            xep_0045 = self.plugin["xep_0045"]
            xep_0045.rooms[None][room] = {}
            xep_0045.our_nicks[None][room] = self.boundjid.user
            stanza = xep_0045.make_join_stanza(room, self.boundjid.user, maxstanzas=0)
            stanza.send()
            logger.info("NWWS-OI MUC join presence sent")
            logger.info(f"Registered rooms: {list(xep_0045.rooms[None].keys())}")
            logger.info(f"Our MUC nick: {xep_0045.our_nicks[None].get(room, 'not set')}")
        except Exception:
            logger.exception("Error joining NWWS-OI MUC room")

    async def on_groupchat_message(self, msg):
        if msg["from"].resource == self.boundjid.user:
            return

        body = msg["body"]
        if not body:
            return

        logger.debug("NWWS-OI message body: %s", body[:120].replace('\n', ' '))

        try:
            parsed = self._parse_message(body)
            if parsed:
                # For short-form NWWS notifications (no WMO heading), try to fetch
                # the full product text from the NWS API using office and PIL code.
                if (parsed.source == "nwws"
                        and parsed.wmo_heading is None
                        and parsed.awips_id is None
                        and parsed.pil_code != "UNK"):
                    full_text = await self._fetch_full_product(
                        parsed.office, parsed.pil_code, body,
                    )
                    if full_text:
                        parsed.product_text = full_text
                        logger.info(
                            "Fetched full product text for office=%s pil=%s (len=%d)",
                            parsed.office, parsed.pil_code, len(full_text),
                        )

                stored = await message_processor.process(parsed)
                if stored:
                    self._messages_count += 1
                    if parsed.source == "nwws" and parsed.wmo_heading is None:
                        logger.info(
                            "Stored NWWS notification for office=%s pil=%s (text length=%d)",
                            parsed.office, parsed.pil_code, len(parsed.product_text),
                        )
                else:
                    logger.debug("NWWS-OI message not stored (duplicate?): pil=%s", parsed.pil_code)
            else:
                logger.debug("NWWS-OI message not parsed (no pil/wmo?): %s", body[:80].replace('\n', ' '))
        except Exception:
            logger.exception("Error processing NWWS message")

    async def on_groupchat_presence(self, prs):
        pass  # Presence flood on join; handled by xep_0045 internally

    # NWWS-OI notification formats:
    # "KBIS issues Severe Weather Statement (SVS) valid 2026-06-29T21:27:00Z"
    # "KWBC issues CAP valid 2026-06-29T21:24:00Z"
    # "KLBF issued, valid 2026-06-29T21:28:00Z"
    _NWWS_WITH_PIL = re.compile(
        r"^([A-Z]{4})\s+issues?\s+.*?\(([A-Z]{2,6})\)", re.IGNORECASE
    )
    _NWWS_BARE_PIL = re.compile(
        r"^([A-Z]{4})\s+issues?\s+([A-Z]{2,6})\s+valid", re.IGNORECASE
    )
    _NWWS_ISSUED = re.compile(r"^([A-Z]{4})\s+issued", re.IGNORECASE)
    _WMO_PATTERN = re.compile(r"^([A-Z]{4}\d{2})\s+(\w+)\s+(\d+)", re.IGNORECASE)
    _AWIPS_PATTERN = re.compile(r"^[A-Z]{3,4}$")

    def _parse_message(self, body: str) -> MessageCreate | None:
        body = body.strip()
        if not body:
            return None

        # --- NWWS-OI notification format (single-line summary) ---
        m = self._NWWS_WITH_PIL.match(body)
        if m:
            icao, pil_code = m.group(1).upper(), m.group(2).upper()
            office = icao[1:] if len(icao) == 4 else icao
            return MessageCreate(
                source="nwws", wmo_heading=None, awips_id=None,
                pil_code=pil_code[:50], office=office[:50], product_text=body,
            )

        m = self._NWWS_BARE_PIL.match(body)
        if m:
            icao, pil_code = m.group(1).upper(), m.group(2).upper()
            office = icao[1:] if len(icao) == 4 else icao
            return MessageCreate(
                source="nwws", wmo_heading=None, awips_id=None,
                pil_code=pil_code[:50], office=office[:50], product_text=body,
            )

        m = self._NWWS_ISSUED.match(body)
        if m:
            icao = m.group(1).upper()
            office = icao[1:] if len(icao) == 4 else icao
            return MessageCreate(
                source="nwws", wmo_heading=None, awips_id=None,
                pil_code="UNK", office=office[:50], product_text=body,
            )

        # --- Raw WMO product format (multi-line) ---
        lines = body.splitlines()
        wmo_heading = awips_id = pil_code = office = None

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if wmo_heading is None and self._WMO_PATTERN.match(line):
                parts = line.split()
                wmo_heading = parts[0]
                if len(parts) > 1:
                    office = parts[1][:50]
            elif awips_id is None and self._AWIPS_PATTERN.match(line):
                awips_id = line
                pil_code = line
            if wmo_heading and awips_id:
                break

        if not pil_code:
            for line in lines:
                line = line.strip()
                if self._AWIPS_PATTERN.match(line):
                    pil_code = line
                    break

        if not pil_code:
            pil_code = "UNK"
        if not office:
            office = "NWS"

        return MessageCreate(
            source="nwws",
            wmo_heading=wmo_heading[:50] if wmo_heading else None,
            awips_id=awips_id[:255] if awips_id else None,
            pil_code=pil_code[:50],
            office=office[:50],
            product_text=body,
        )

    async def _fetch_full_product(self, office: str, pil_code: str, body: str) -> str | None:
        """Fetch the full product text from the NWS API.

        Uses GET /products/types/{PIL}/locations/{OFFICE} to find the most
        recent matching product, then fetches the full productText via
        GET /products/{id}.  The plain /products endpoint does not support
        time-range filtering and returns 400.
        """
        m = re.search(
            r'valid\s+(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})Z', body, re.IGNORECASE,
        )
        valid_dt = None
        if m:
            try:
                valid_dt = datetime.fromisoformat(m.group(1) + "+00:00")
            except Exception:
                pass

        # Build the 4-letter ICAO office code expected by the API.
        office_upper = office.upper()
        icao = office_upper if len(office_upper) == 4 else f"K{office_upper}"
        pil_upper = pil_code.upper()

        settings = get_settings()
        headers = {"User-Agent": settings.api_user_agent}

        try:
            async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
                # Step 1: get the list of recent products of this type from this office.
                url = f"{NWS_API_BASE}/products/types/{pil_upper}/locations/{icao}"
                resp = await client.get(url)
                if resp.status_code == 404:
                    # Some offices use the 3-letter code without K prefix.
                    url = f"{NWS_API_BASE}/products/types/{pil_upper}/locations/{office_upper}"
                    resp = await client.get(url)
                if resp.status_code != 200:
                    logger.debug(
                        "NWS API product list failed: office=%s pil=%s status=%s",
                        icao, pil_upper, resp.status_code,
                    )
                    return None

                graph = resp.json().get("@graph", [])
                if not graph:
                    logger.debug(
                        "NWS API returned empty product list for office=%s pil=%s",
                        icao, pil_upper,
                    )
                    return None

                # Pick the product whose issuance time is closest to our valid time.
                # If we have no valid time, just take the first (most recent) entry.
                product_id = graph[0].get("id")
                if valid_dt and len(graph) > 1:
                    best = None
                    best_delta = None
                    for item in graph:
                        iso = item.get("issuanceTime", "")
                        try:
                            item_dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
                            delta = abs((item_dt - valid_dt).total_seconds())
                            if best_delta is None or delta < best_delta:
                                best_delta = delta
                                best = item.get("id")
                        except Exception:
                            continue
                    if best:
                        product_id = best

                if not product_id:
                    return None

                # Step 2: fetch the individual product to get productText.
                resp2 = await client.get(f"{NWS_API_BASE}/products/{product_id}")
                if resp2.status_code != 200:
                    logger.debug(
                        "NWS API individual product fetch failed: id=%s status=%s",
                        product_id, resp2.status_code,
                    )
                    return None

                product_text = resp2.json().get("productText", "")
                return product_text if product_text else None

        except Exception:
            logger.exception("Error fetching full product text from NWS API")
            return None

    def on_disconnected(self, event):
        self._connected = False
        self._connect_event.set()
        logger.warning("NWWS-OI disconnected: %s", event)

    def on_connection_failed(self, event):
        self._connected = False
        self._connect_event.set()
        logger.warning("NWWS-OI connection failed: %s", event)

    def on_failed_auth(self, event):
        self._connected = False
        self._connect_event.set()
        logger.warning("NWWS-OI auth failed: %s", event)

    def connect(self):
        if hasattr(self, 'init_plugins'):
            self.init_plugins()
        logger.info(f"Connecting to NWWS-OI at {NWWS_HOST}:{NWWS_PORT}")
        return XMLStream.connect(self, NWWS_HOST, NWWS_PORT)

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
                self._client.connect()
                try:
                    await asyncio.wait_for(self._client._connect_event.wait(), timeout=30)
                except asyncio.TimeoutError:
                    logger.warning("NWWS-OI connection timed out after 30s")
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
