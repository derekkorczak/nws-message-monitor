import json
import logging
import os
import re

logger = logging.getLogger(__name__)

UGC_CODE_RE = re.compile(r'\b([A-Z]{2}[CZ]\d{3})\b')

# Matches a UGC line that begins with a full zone code and may include
# additional full codes, partial codes (implicit state), and ranges
# (e.g. MNZ001-015>017-NDZ027>030-141930-).
UGC_LINE_RE = re.compile(
    r'^([A-Z]{2}[CZ]\d{3}(?:-(?:[A-Z]{2}[CZ]\d{3}(?:>\d{3})?|\d{3}(?:>\d{3})?))*)-\d{6}-',
    re.MULTILINE,
)

_COUNTY_RE = re.compile(r'\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)\s+County\b')

_CITY_DISTANCE_RE = re.compile(
    r'\b(\d+)\s+(?:miles?|mi)\s+(?:N|S|E|W|NE|NW|SE|SW|NNW|NNE|SSW|SSE|ENE|WNW|WSW|ESE)\s+of\s+([A-Z][a-z]+(?:\s[A-Z][a-z]+)*)',
)


class ZoneResolver:
    def __init__(self):
        self._cache: dict[str, str] = {}
        data_path = os.path.join(os.path.dirname(__file__), "zone_names.json")
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                self._cache.update(json.load(f))
            logger.info("Loaded %d zone names from %s", len(self._cache), data_path)
        except Exception as e:
            logger.warning("Failed to load bundled zone names from %s: %s", data_path, e)

    async def resolve(self, codes: list[str]) -> list[str]:
        if not codes:
            return []
        resolved = []
        for c in codes:
            name = self._cache.get(c.upper())
            resolved.append(name if name else c)
        return resolved


_resolver = ZoneResolver()


def _expand_ugc_token(token: str, current_state: str | None) -> tuple[list[str], str | None]:
    """Expand a single UGC token into full zone/county codes.

    Tokens may be full codes (MNZ001), partial codes (015), or ranges
    (015>017, NDZ027>030).  Returns the expanded codes and the updated
    state prefix (state + zone type) to apply to subsequent tokens.
    """
    token = token.strip().upper()
    if not token:
        return [], current_state

    if '>' in token:
        start, end = token.split('>', 1)
        start = start.strip()
        end = end.strip()

        if re.fullmatch(r'[A-Z]{2}[CZ]\d{3}', start):
            start_code = start
            current_state = start_code[:3]
        elif re.fullmatch(r'\d{3}', start) and current_state:
            start_code = current_state + start
        else:
            return [], current_state

        if re.fullmatch(r'[A-Z]{2}[CZ]\d{3}', end):
            end_code = end
        elif re.fullmatch(r'\d{3}', end) and current_state:
            end_code = current_state + end
        else:
            return [], current_state

        start_num = int(start_code[3:])
        end_num = int(end_code[3:])
        if end_num < start_num:
            return [], current_state
        codes = [f"{start_code[:3]}{n:03d}" for n in range(start_num, end_num + 1)]
        return codes, current_state

    if re.fullmatch(r'[A-Z]{2}[CZ]\d{3}', token):
        return [token], token[:3]

    if re.fullmatch(r'\d{3}', token) and current_state:
        return [f"{current_state}{token}"], current_state

    return [], current_state


def extract_ugc_codes(product_text: str) -> list[str]:
    if not product_text:
        return []

    seen: list[str] = []
    seen_set: set[str] = set()

    for match in UGC_LINE_RE.finditer(product_text):
        line = match.group(1)
        current_state: str | None = None
        for token in line.split('-'):
            codes, current_state = _expand_ugc_token(token, current_state)
            for code in codes:
                code = code.upper()
                if code not in seen_set:
                    seen.append(code)
                    seen_set.add(code)

    if not seen:
        for code_match in UGC_CODE_RE.finditer(product_text):
            code = code_match.group(1).upper()
            if code not in seen_set:
                seen.append(code)
                seen_set.add(code)

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
            return "; ".join(unique_names)

    text_locs = extract_text_locations(product_text)
    if text_locs:
        return "; ".join(text_locs)

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
