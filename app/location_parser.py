import asyncio
import logging
import re
import time

import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

UGC_CODE_RE = re.compile(r'\b([A-Z]{2}[CZ]\d{3})\b')

UGC_LINE_RE = re.compile(
    r'^[A-Z]{2}[CZ]\d{3}(?:-[A-Z]{2}[CZ]\d{3})*-\d{6}-',
    re.MULTILINE,
)

_COUNTY_RE = re.compile(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s+County\b')

_CITY_DISTANCE_RE = re.compile(
    r'\b(\d+)\s+(?:miles?|mi)\s+(?:N|S|E|W|NE|NW|SE|SW|NNW|NNE|SSW|SSE|ENE|WNW|WSW|ESE)\s+of\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)',
)


class ZoneResolver:
    def __init__(self):
        self._cache: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._last_fetch: float = 0
        self._ttl: float = 86400

    async def resolve(self, codes: list[str]) -> list[str]:
        if not codes:
            return []

        unknown = [c for c in codes if c.upper() not in self._cache]
        if unknown:
            await self._fetch_zones(unknown)

        resolved = []
        for c in codes:
            name = self._cache.get(c.upper())
            resolved.append(name if name else c)
        return resolved

    async def _fetch_zones(self, codes: list[str]):
        async with self._lock:
            if codes and self._cache and time.time() - self._last_fetch < self._ttl:
                return

            states: set[str] = set()
            for c in codes:
                if len(c) >= 2:
                    states.add(c[:2])
            if not states:
                return

            settings = get_settings()
            headers = {"User-Agent": settings.api_user_agent}
            fetched: dict[str, str] = {}

            try:
                async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
                    for st in states:
                        for zone_type in ["county", "forecast", "public", "marine"]:
                            url = "https://api.weather.gov/zones"
                            params = {"state": st, "type": zone_type, "limit": 500}
                            try:
                                resp = await client.get(url, params=params)
                                if resp.status_code != 200:
                                    continue
                                data = resp.json()
                                for feature in data.get("features", []):
                                    props = feature.get("properties", {})
                                    zid = (props.get("id") or "").upper()
                                    zname = props.get("name") or ""
                                    if zid and zname and zid not in fetched:
                                        fetched[zid] = zname.strip()
                            except Exception as e:
                                logger.debug("Zone fetch error for %s/%s: %s", st, zone_type, e)
            except Exception as e:
                logger.warning("Zone resolution failed: %s", e)

            self._cache.update(fetched)
            self._last_fetch = time.time()


_resolver = ZoneResolver()


def extract_ugc_codes(product_text: str) -> list[str]:
    if not product_text:
        return []

    seen: list[str] = []
    seen_set: set[str] = set()

    for match in UGC_LINE_RE.finditer(product_text):
        line = match.group(0)
        for code_match in UGC_CODE_RE.finditer(line):
            code = code_match.group(1).upper()
            if code not in seen_set:
                seen.append(code)
                seen_set.add(code)

    if not seen:
        for code_match in UGC_CODE_RE.finditer(product_text):
            code = code_match.group(1).upper()
            if code not in seen_set:
                seen.append(code)
                seen_set.add(code)
            if len(seen) >= 20:
                break

    return seen


def extract_text_locations(product_text: str) -> list[str]:
    if not product_text:
        return []

    seen: list[str] = []
    seen_set: set[str] = set()

    def add(loc: str):
        loc = " ".join(loc.strip().split())
        if loc and len(loc) > 2 and loc not in seen_set:
            seen.append(loc)
            seen_set.add(loc)

    for m in _CITY_DISTANCE_RE.finditer(product_text):
        add(f"{m.group(2)}")

    for m in _COUNTY_RE.finditer(product_text):
        add(f"{m.group(1)} County")

    return seen[:6]


async def resolve_location(product_text: str, pil_code: str) -> str | None:
    if pil_code and pil_code.upper() in ("AFD",):
        return None

    codes = extract_ugc_codes(product_text)
    if codes:
        names = await _resolver.resolve(codes)
        unique_names: list[str] = []
        unique_set: set[str] = set()
        for n in names:
            if n not in unique_set:
                unique_names.append(n)
                unique_set.add(n)
        if unique_names:
            return "; ".join(unique_names[:5])

    text_locs = extract_text_locations(product_text)
    if text_locs:
        return "; ".join(text_locs[:3])

    return None


def extract_location_sync(product_text: str, pil_code: str) -> str | None:
    codes = extract_ugc_codes(product_text)
    if not codes:
        text_locs = extract_text_locations(product_text)
        if text_locs:
            return "; ".join(text_locs[:3])
        return None

    names: list[str] = []
    seen: set[str] = set()
    for c in codes:
        name = _resolver._cache.get(c.upper())
        if name and name not in seen:
            names.append(name)
            seen.add(name)
        elif not name and c not in seen:
            names.append(c)
            seen.add(c)
        if len(names) >= 5:
            break

    return "; ".join(names) if names else None
