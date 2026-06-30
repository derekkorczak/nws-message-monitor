import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from pathlib import Path
from uuid import UUID
import httpx

from app.config import get_settings
from app.database import init_db, close_db, get_pool
from app.models import (
    Message, MessageList, Filter, FilterCreate, FilterUpdate,
    Settings as SettingsModel, SettingsUpdate, Status,
)
from app.sse import broadcaster
from app.api_poller import api_poller
from app.nwws_client import nwws_manager
from app.retention import retention
from app.nws_offices import NWS_OFFICES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await api_poller.start()
    await nwws_manager.start()
    await retention.start()
    logger.info("NWS Message Monitor started")
    yield
    await retention.stop()
    await nwws_manager.stop()
    await api_poller.stop()
    await close_db()
    logger.info("NWS Message Monitor stopped")


app = FastAPI(title="NWS Message Monitor", lifespan=lifespan)

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = static_dir / "index.html"
    return HTMLResponse(html_path.read_text())


@app.get("/api/messages")
async def list_messages(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    pil_code: str | None = None,
    office: str | None = None,
    source: str | None = None,
    search: str | None = None,
    include_deleted: bool = False,
):
    pool = get_pool()
    conditions = []
    params = []
    idx = 1

    conditions.append("(expires_at IS NULL OR expires_at >= NOW())")
    if not include_deleted:
        conditions.append("is_deleted = FALSE")
    if pil_code:
        conditions.append(f"pil_code ILIKE ${idx}")
        params.append(f"%{pil_code}%")
        idx += 1
    if office:
        conditions.append(f"office ILIKE ${idx}")
        params.append(f"%{office}%")
        idx += 1
    if source:
        conditions.append(f"source = ${idx}")
        params.append(source)
        idx += 1
    if search:
        conditions.append(f"(product_text ILIKE ${idx} OR awips_id ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1

    where = "WHERE " + " AND ".join(conditions) if conditions else ""

    total = await pool.fetchval(f"SELECT COUNT(*) FROM messages {where}", *params)

    offset = (page - 1) * page_size
    rows = await pool.fetch(
        f"SELECT * FROM messages {where} ORDER BY received_at DESC LIMIT ${idx} OFFSET ${idx+1}",
        *params, page_size, offset,
    )

    messages = []
    for r in rows:
        messages.append(Message(
            id=r["id"],
            received_at=r["received_at"],
            source=r["source"],
            wmo_heading=r["wmo_heading"],
            awips_id=r["awips_id"],
            pil_code=r["pil_code"],
            office=r["office"],
            product_text=r["product_text"],
            severity=r["severity"],
            area_desc=r["area_desc"],
            is_deleted=r["is_deleted"],
            deleted_at=r["deleted_at"],
            expires_at=r["expires_at"],
            read_at=r["read_at"],
        ))

    return MessageList(messages=messages, total=total, page=page, page_size=page_size)


@app.get("/api/messages/{message_id}")
async def get_message(message_id: UUID):
    pool = get_pool()
    row = await pool.fetchrow("SELECT * FROM messages WHERE id = $1", message_id)
    if not row:
        raise HTTPException(404, "Message not found")
    if not row["read_at"]:
        await pool.execute(
            "UPDATE messages SET read_at = NOW() WHERE id = $1 AND read_at IS NULL",
            message_id,
        )
        row = await pool.fetchrow("SELECT * FROM messages WHERE id = $1", message_id)
    return Message(
        id=row["id"],
        received_at=row["received_at"],
        source=row["source"],
        wmo_heading=row["wmo_heading"],
        awips_id=row["awips_id"],
        pil_code=row["pil_code"],
        office=row["office"],
        product_text=row["product_text"],
        severity=row["severity"],
        area_desc=row["area_desc"],
        is_deleted=row["is_deleted"],
        deleted_at=row["deleted_at"],
        expires_at=row["expires_at"],
        read_at=row["read_at"],
    )


@app.post("/api/messages/mark-all-read")
async def mark_all_read():
    pool = get_pool()
    result = await pool.execute(
        "UPDATE messages SET read_at = NOW() WHERE read_at IS NULL AND is_deleted = FALSE"
    )
    return {"status": "ok"}


@app.delete("/api/messages/{message_id}")
async def delete_message(message_id: UUID):
    pool = get_pool()
    result = await pool.execute(
        "UPDATE messages SET is_deleted = TRUE, deleted_at = NOW() WHERE id = $1 AND is_deleted = FALSE",
        message_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(404, "Message not found or already deleted")
    return {"status": "deleted"}


@app.get("/api/stream")
async def sse_stream(request: Request):
    queue = broadcaster.subscribe()

    async def event_generator():
        try:
            yield f"data: {__import__('json').dumps({'event': 'connected', 'data': {}})}\n\n"
            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=30.0)
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield f"data: {__import__('json').dumps({'event': 'ping', 'data': {}})}\n\n"
            except asyncio.CancelledError:
                pass
        finally:
            broadcaster.unsubscribe(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/filters")
async def list_filters():
    pool = get_pool()
    rows = await pool.fetch("SELECT * FROM filters ORDER BY type, name")
    return [Filter(
        id=r["id"],
        name=r["name"],
        type=r["type"],
        mode=r["mode"],
        values=r["values"],
        enabled=r["enabled"],
        created_at=r["created_at"],
    ) for r in rows]


@app.post("/api/filters", status_code=201)
async def create_filter(data: FilterCreate):
    pool = get_pool()
    row = await pool.fetchrow(
        "INSERT INTO filters (name, type, mode, values, enabled) VALUES ($1, $2, $3, $4, $5) "
        "RETURNING id, created_at",
        data.name, data.type, data.mode, data.values if data.values else [], data.enabled,
    )
    await broadcaster.broadcast_filter_update()
    return Filter(
        id=row["id"],
        name=data.name,
        type=data.type,
        mode=data.mode,
        values=data.values or [],
        enabled=data.enabled,
        created_at=row["created_at"],
    )


@app.put("/api/filters/{filter_id}")
async def update_filter(filter_id: UUID, data: FilterUpdate):
    pool = get_pool()
    existing = await pool.fetchrow("SELECT * FROM filters WHERE id = $1", filter_id)
    if not existing:
        raise HTTPException(404, "Filter not found")

    name = data.name if data.name is not None else existing["name"]
    ftype = data.type if data.type is not None else existing["type"]
    mode = data.mode if data.mode is not None else existing["mode"]
    values = data.values if data.values is not None else existing["values"]
    enabled = data.enabled if data.enabled is not None else existing["enabled"]

    await pool.execute(
        "UPDATE filters SET name = $1, type = $2, mode = $3, values = $4, enabled = $5 WHERE id = $6",
        name, ftype, mode, values if values else [], enabled, filter_id,
    )
    await broadcaster.broadcast_filter_update()
    return Filter(
        id=filter_id, name=name, type=ftype, mode=mode,
        values=values or [], enabled=enabled, created_at=existing["created_at"],
    )


@app.delete("/api/filters/{filter_id}")
async def delete_filter(filter_id: UUID):
    pool = get_pool()
    result = await pool.execute("DELETE FROM filters WHERE id = $1", filter_id)
    if result == "DELETE 0":
        raise HTTPException(404, "Filter not found")
    await broadcaster.broadcast_filter_update()
    return {"status": "deleted"}


@app.get("/api/settings")
async def get_settings_api():
    pool = get_pool()
    rows = await pool.fetch("SELECT key, value FROM settings")
    d = {r["key"]: r["value"] for r in rows}
    raw_pil = d.get("pil_expirations", '{}')
    try:
        pil_expirations = json.loads(raw_pil) if isinstance(raw_pil, str) else raw_pil
        if not isinstance(pil_expirations, dict):
            pil_expirations = {}
    except (json.JSONDecodeError, TypeError):
        pil_expirations = {}
    return SettingsModel(
        retention_days=int(d.get("retention_days", "30")),
        api_poll_interval=int(d.get("api_poll_interval", "30")),
        data_source=d.get("data_source", "api"),
        default_expiration_minutes=int(d.get("default_expiration_minutes", "120")),
        pil_expirations=pil_expirations,
    )


@app.put("/api/settings")
async def update_settings(data: SettingsUpdate):
    pool = get_pool()
    updates = {}
    if data.retention_days is not None:
        updates["retention_days"] = str(data.retention_days)
    if data.api_poll_interval is not None:
        updates["api_poll_interval"] = str(data.api_poll_interval)
    if data.data_source is not None:
        updates["data_source"] = data.data_source
    if data.default_expiration_minutes is not None:
        updates["default_expiration_minutes"] = str(data.default_expiration_minutes)
    if data.pil_expirations is not None:
        updates["pil_expirations"] = json.dumps(data.pil_expirations)

    for k, v in updates.items():
        await pool.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ($1, $2, NOW()) "
            "ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()",
            k, v,
        )

    return {"status": "updated", "changed": list(updates.keys())}


@app.get("/api/filters/export")
async def export_filters():
    pool = get_pool()
    rows = await pool.fetch("SELECT name, type, mode, values, enabled FROM filters ORDER BY type, name")
    return [{"name": r["name"], "type": r["type"], "mode": r["mode"],
             "values": r["values"], "enabled": r["enabled"]} for r in rows]


@app.get("/api/filter-options/{filter_type}")
async def get_filter_options(filter_type: str):
    pool = get_pool()
    settings = get_settings()
    
    if filter_type == "product":
        rows = await pool.fetch(
            "SELECT DISTINCT pil_code FROM messages ORDER BY pil_code"
        )
        return [r["pil_code"] for r in rows]
    elif filter_type == "office":
        return sorted(NWS_OFFICES.keys())
    elif filter_type == "full_pil":
        rows = await pool.fetch(
            "SELECT DISTINCT pil_code, office FROM messages ORDER BY pil_code, office"
        )
        return [r["pil_code"].upper() + r["office"].upper() for r in rows]
    elif filter_type == "zone":
        # Query NWS zones API for all available zones
        zones = set()
        try:
            async with httpx.AsyncClient() as client:
                for zone_type in ["county", "forecast", "public"]:
                    resp = await client.get(
                        "https://api.weather.gov/zones",
                        params={"type": zone_type},
                        headers={"User-Agent": settings.api_user_agent},
                        timeout=10.0
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        for feature in data.get("features", []):
                            props = feature.get("properties", {})
                            zone_id = props.get("id", "")
                            if zone_id:
                                zones.add(zone_id)
        except Exception as e:
            logger.warning(f"Failed to fetch zones from NWS API: {e}")
        
        # Also extract from existing messages
        rows = await pool.fetch(
            "SELECT DISTINCT product_text FROM messages "
            "WHERE product_text ILIKE '%Z%' OR product_text ILIKE '%C%'"
        )
        for r in rows:
            matches = re.findall(r'\b([A-Z]{2}[CZ]\d{3})\b', r["product_text"])
            zones.update(matches)
        
        return sorted(zones)
    elif filter_type == "location":
        # Query NWS zones API for all county/zone names
        locations = set()
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    "https://api.weather.gov/zones",
                    params={"type": "county"},
                    headers={"User-Agent": settings.api_user_agent},
                    timeout=10.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for feature in data.get("features", []):
                        props = feature.get("properties", {})
                        name = props.get("name", "")
                        if name:
                            locations.add(name)
        except Exception as e:
            logger.warning(f"Failed to fetch locations from NWS API: {e}")
        
        # Also extract from existing messages
        rows = await pool.fetch("SELECT product_text FROM messages")
        for r in rows:
            for line in r["product_text"].splitlines():
                if line.startswith("Areas:"):
                    area_str = line[6:].strip()
                    for loc in area_str.split(";"):
                        loc = " ".join(loc.strip().split())
                        if loc and len(loc) > 2:
                            locations.add(loc)
        
        return sorted(locations)
    return []


@app.get("/api/offices")
async def get_offices():
    return NWS_OFFICES


@app.post("/api/filters/import")
async def import_filters(filters: list[dict]):
    pool = get_pool()
    imported = 0
    for f in filters:
        name = f.get("name", "Imported")
        ftype = f.get("type", "product")
        mode = f.get("mode", "include")
        values = f.get("values", [])
        enabled = f.get("enabled", True)
        if ftype not in ("product", "office", "zone", "location", "full_pil", "pil_zone"):
            continue
        if mode not in ("include", "exclude"):
            continue
        await pool.execute(
            "INSERT INTO filters (name, type, mode, values, enabled) VALUES ($1, $2, $3, $4, $5)",
            name, ftype, mode, values, enabled,
        )
        imported += 1
    await broadcaster.broadcast_filter_update()
    return {"imported": imported}


@app.get("/api/status")
async def get_status():
    pool = get_pool()
    total = await pool.fetchval("SELECT COUNT(*) FROM messages")
    deleted = await pool.fetchval("SELECT COUNT(*) FROM messages WHERE is_deleted = TRUE")
    api_count = await pool.fetchval("SELECT COUNT(*) FROM messages WHERE source = 'api'")

    return Status(
        nwws_oi="connected" if nwws_manager.status.get("connected") else "disconnected",
        api="connected" if api_poller.status.get("connected") else "disconnected",
        api_last_poll=datetime.fromisoformat(api_poller.status.get("last_poll")) if api_poller.status.get("last_poll") else None,
        api_messages_count=api_count,
        total_messages=total,
        deleted_messages=deleted,
        uptime_seconds=time.time() - _start_time,
    )
