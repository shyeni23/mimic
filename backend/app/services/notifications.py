"""
WebSocket-based real-time notification hub (G11).

Maintains a set of active WebSocket connections per channel. When something
worth notifying happens (e.g. a new staff escalation request), the caller
broadcasts a JSON message to every connected client on the relevant channel.

Usage from anywhere in the backend:
    from app.services.notifications import hub
    await hub.broadcast("staff", {"type": "new_request", ...})

Clients connect via ws://<host>/ws/<channel> (see staff.py for the
/ws/staff endpoint).
"""
import asyncio
import json
import logging
from collections import defaultdict

from fastapi import WebSocket

log = logging.getLogger(__name__)


class NotificationHub:
    def __init__(self):
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)

    async def connect(self, channel: str, ws: WebSocket):
        await ws.accept()
        self._channels[channel].add(ws)
        log.info("ws client connected to channel '%s' (%d total)", channel, len(self._channels[channel]))

    def disconnect(self, channel: str, ws: WebSocket):
        self._channels[channel].discard(ws)
        log.info("ws client disconnected from channel '%s' (%d remaining)", channel, len(self._channels[channel]))

    async def broadcast(self, channel: str, message: dict):
        payload = json.dumps(message)
        dead = []
        for ws in self._channels[channel]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._channels[channel].discard(ws)

    def broadcast_sync(self, channel: str, message: dict):
        """Fire-and-forget broadcast from synchronous code (e.g. a tool function).
        Schedules the async broadcast on the running event loop."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(channel, message))
        except RuntimeError:
            pass


hub = NotificationHub()
