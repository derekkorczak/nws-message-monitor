import asyncio
import logging
import re
import ssl
from datetime import datetime, timezone

import slixmpp
from slixmpp.xmlstream import XMLStream
from app.config import get_settings
from app.models import MessageCreate
from app.message_processor import message_processor

logger = logging.getLogger(__name__)

NWWS_HOST = "nwws-oi.weather.gov"
NWWS_PORT = 5222
NWWS_MUC = "NWWS@conference.nwws-oi.weather.gov"

# XML namespace used by NWWS-OI for the product extension element.
# Each groupchat message carries a <x xmlns="nwws-oi"> element whose text
# content is the full NWS product and whose attributes supply all metadata.
_NWWS_OI_NS = "nwws-oi"
_NWWS_OI_X_TAG = f"{{{_NWWS_OI_NS}}}x"

# P-VTEC line: /k.aaa.cccc.pp.s.####.YYMMDDTHHMMz-YYMMDDTHHMMz/
_PVTEC = re.compile(
    r'/[OTX]\.([A-Z]{3})\.[A-Z0-9]{4}\.([A-Z]{2})\.([A-Z])\.\d{4}\.'
    r'(\d{6}T\d{4})Z-(\d{6}T\d{4})Z/',
    re.IGNORECASE,
)

# (phenomenon, significance) pairs that map to Extreme severity
_VTEC_EXTREME = {
    ("TO", "W"), ("TO", "A"),  # Tornado Warning/Watch
    ("HU", "W"), ("HU", "A"),  # Hurricane Warning/Watch
    ("TS", "W"), ("TS", "A"),  # Tropical Storm Warning/Watch
    ("EW", "W"),               # Extreme Wind Warning
}


def _parse_vtec_time(ts: str) -> datetime | None:
    """Parse VTEC timestamp 'YYMMDDTHHmm' to a UTC datetime."""
    try:
        if ts == "000000T0000":
            return None
        year = 2000 + int(ts[0:2])
        month = int(ts[2:4])
        day = int(ts[4:6])
        hour = int(ts[7:9])
        minute = int(ts[9:11])
        return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
    except Exception:
        return None


def _parse_vtec(product_text: str) -> tuple[str | None, datetime | None]:
    """Extract severity and expires_at from the first P-VTEC line in a product."""
    m = _PVTEC.search(product_text)
    if not m:
        return None, None

    action = m.group(1).upper()
    ph = m.group(2).upper()
    sig = m.group(3).upper()
    end_ts = m.group(5)

    # CAN/EXP actions mean the event is ending – no meaningful future expiry
    expires_at = None
    if action not in ("CAN", "EXP"):
        expires_at = _parse_vtec_time(end_ts)

    if (ph, sig) in _VTEC_EXTREME:
        severity = "Extreme"
    elif sig == "W":
        severity = "Severe"
    elif sig == "A":
        severity = "Severe"
    elif sig == "Y":
        severity = "Moderate"
    elif sig in ("S", "F", "N", "O"):
        severity = "Minor"
    else:
        severity = None

    return severity, expires_at


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

        try:
            # Primary: extract the full product from the <x xmlns="nwws-oi"> extension.
            parsed = self._parse_nwws_extension(msg)
            if parsed is None:
                # Fallback: parse body text (handles raw WMO products or plain bodies).
                parsed = self._parse_message(body)

            if parsed:
                stored = await message_processor.process(parsed)
                if stored:
                    self._messages_count += 1
                    logger.info(
                        "Stored NWWS message: pil=%s office=%s len=%d",
                        parsed.pil_code, parsed.office, len(parsed.product_text),
                    )
        except Exception:
            logger.exception("Error processing NWWS message")

    async def on_groupchat_presence(self, prs):
        pass  # Presence flood on join; handled by xep_0045 internally

    # Full WMO header line: TTAAII CCCC DDHHMM [BBB]
    _WMO_HEADER = re.compile(r'^[A-Z]{4}\d{2}\s+\w{4}\s+\d{6}', re.IGNORECASE)

    def _parse_nwws_extension(self, msg) -> MessageCreate | None:
        """Parse the full NWS product from the <x xmlns='nwws-oi'> stanza extension.

        NWWS-OI groupchat messages carry the full product text as the text content
        of this element, along with metadata attributes:
          ttaaii  - WMO collective identifier, e.g. "WHUS53"
          cccc    - 4-letter ICAO office, e.g. "KDLH"
          awipsid - AWIPS product ID, e.g. "SMWDLH"
          issue   - issuance time ISO string
        """
        x_elem = msg.xml.find(_NWWS_OI_X_TAG)
        if x_elem is None:
            return None

        product_text = (x_elem.text or "").strip()
        if not product_text:
            return None

        # Strip the leading NWWS sequence number (e.g. "314\n\n") that precedes
        # the actual product content.  The sequence number is a short integer on
        # its own line at the very top of the element text.
        product_text = re.sub(r'^\d{1,6}\s*\n+', '', product_text)

        # Remove blank lines between text lines (collapse double-spacing to single-spacing).
        product_text = re.sub(r'\n\n', '\n', product_text)

        ttaaii  = x_elem.get("ttaaii", "").strip()   # e.g. "WHUS53"
        cccc    = x_elem.get("cccc",    "").strip()   # e.g. "KDLH"
        awipsid = x_elem.get("awipsid", "").strip()   # e.g. "SMWDLH"

        # Derive 3-letter office from the 4-letter ICAO code (strip leading K/P/T).
        if len(cccc) == 4 and cccc[0].upper() in "KPTU":
            office = cccc[1:].upper()
        else:
            office = cccc.upper() or "NWS"

        # Extract the full WMO heading line (TTAAII CCCC DDHHMM) from the product
        # text.  This includes the issuance timestamp absent from the XML attributes
        # and allows cross-source deduplication with API-sourced messages which store
        # the same WMO heading (e.g. "WWUS53 KBIS 292230").
        wmo_heading = None
        for line in product_text.splitlines():
            line = line.strip()
            if line and self._WMO_HEADER.match(line):
                wmo_heading = line
                break
        # Fall back to attribute-based heading if the product text has no WMO line.
        if not wmo_heading and ttaaii and cccc:
            wmo_heading = f"{ttaaii} {cccc}".strip()

        # Derive PIL code from awipsid by stripping the trailing 3-letter office.
        # e.g. "SMWDLH" - "DLH" = "SMW"; "RR3ACR" - "ACR" = "RR3".
        # For IDs where the suffix doesn't match the office (e.g. "WOU6"),
        # extract the leading alpha characters instead.
        pil_code = "UNK"
        if awipsid:
            if office and awipsid.upper().endswith(office.upper()):
                pil_code = awipsid[: -len(office)].strip() or "UNK"
            else:
                m = re.match(r'^([A-Z]{2,4})', awipsid.upper())
                pil_code = m.group(1) if m else awipsid[:3].upper()

        severity, expires_at = _parse_vtec(product_text)

        return MessageCreate(
            source="nwws",
            wmo_heading=wmo_heading[:50] if wmo_heading else None,
            awips_id=awipsid[:255] if awipsid else None,
            pil_code=pil_code[:50],
            office=office[:50],
            product_text=product_text,
            severity=severity,
            expires_at=expires_at,
        )

    # Fallback patterns for messages without the nwws-oi extension element.
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
        """Fallback parser for message bodies without the nwws-oi XML extension."""
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

        severity, expires_at = _parse_vtec(body)

        return MessageCreate(
            source="nwws",
            wmo_heading=wmo_heading[:50] if wmo_heading else None,
            awips_id=awips_id[:255] if awips_id else None,
            pil_code=pil_code[:50],
            office=office[:50],
            product_text=body,
            severity=severity,
            expires_at=expires_at,
        )

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
