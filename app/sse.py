import asyncio
import json
import logging
from app.models import Message

logger = logging.getLogger(__name__)


class SSEBroadcaster:
    def __init__(self):
        self._clients: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._clients.append(queue)
        logger.debug("SSE client subscribed, total: %d", len(self._clients))
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        if queue in self._clients:
            self._clients.remove(queue)
            logger.debug("SSE client unsubscribed, total: %d", len(self._clients))

    async def broadcast_message(self, message: Message):
        data = json.dumps({
            "event": "new_message",
            "data": message.model_dump(mode="json"),
        })
        await self._send(data)

    async def broadcast_filter_update(self):
        data = json.dumps({"event": "filters_updated", "data": {}})
        await self._send(data)

    async def broadcast_status(self, status: dict):
        data = json.dumps({"event": "status_update", "data": status})
        await self._send(data)

    async def _send(self, data: str):
        dead = []
        for q in self._clients:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._clients.remove(q)

    @property
    def client_count(self) -> int:
        return len(self._clients)


broadcaster = SSEBroadcaster()
