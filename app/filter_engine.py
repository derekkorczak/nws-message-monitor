import logging
from app.database import get_pool
from app.models import MessageCreate

logger = logging.getLogger(__name__)


class FilterEngine:
    async def should_store(self, msg: MessageCreate) -> bool:
        pool = get_pool()
        rows = await pool.fetch(
            "SELECT type, mode, values FROM filters WHERE enabled = TRUE"
        )

        includes = [r for r in rows if r["mode"] == "include"]
        excludes = [r for r in rows if r["mode"] == "exclude"]

        if includes:
            included = False
            for f in includes:
                if self._matches(msg, f["type"], f["values"]):
                    included = True
                    break
            if not included:
                return False

        for f in excludes:
            if self._matches(msg, f["type"], f["values"]):
                return False

        return True

    def _matches(self, msg: MessageCreate, filter_type: str, values: list[str]) -> bool:
        lower_values = [v.lower().strip() for v in values]
        if filter_type == "product":
            return msg.pil_code.lower().strip() in lower_values
        elif filter_type == "office":
            return msg.office.lower().strip() in lower_values
        elif filter_type == "zone":
            text = msg.product_text.lower()
            return any(v in text for v in lower_values)
        elif filter_type == "pil_zone":
            text = msg.product_text.lower()
            for v in lower_values:
                parts = v.split(":", 1)
                if len(parts) != 2:
                    continue
                pil_part, code_part = parts[0].strip(), parts[1].strip()
                if pil_part == msg.pil_code.lower().strip() and code_part in text:
                    return True
            return False
        elif filter_type == "full_pil":
            full_code = (msg.pil_code + msg.office).lower().strip()
            return full_code in lower_values
        elif filter_type == "location":
            text = msg.product_text.lower()
            header = (msg.wmo_heading or "").lower()
            combined = text + " " + header
            return any(v in combined for v in lower_values)
        return False


filter_engine = FilterEngine()
