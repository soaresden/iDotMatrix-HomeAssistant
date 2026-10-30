"""homeassistant.core for the desktop app: an event loop, an event bus, data and paths."""
from __future__ import annotations

import asyncio
import os


def callback(func):
    """Marks event-loop functions in Home Assistant; nothing to do here."""
    return func


class EventBus:
    def __init__(self) -> None:
        self._listeners: dict[str, set] = {}

    def async_fire(self, event_type: str, event_data: dict | None = None) -> None:
        for listener in list(self._listeners.get(event_type, ())):
            listener(event_type, dict(event_data or {}))

    def async_listen(self, event_type: str, listener):
        """Call ``listener(event_type, data)`` for each event; returns the remover."""
        self._listeners.setdefault(event_type, set()).add(listener)
        return lambda: self._listeners.get(event_type, set()).discard(listener)


class Config:
    def __init__(self, config_dir: str, media_dir: str) -> None:
        self.config_dir = config_dir
        self.media_dirs = {"local": media_dir}

    def path(self, *parts: str) -> str:
        return os.path.join(self.config_dir, *parts)


class HomeAssistant:
    """What the Studio modules call on ``hass``. Create it inside the running loop."""

    def __init__(self, config_dir: str, media_dir: str) -> None:
        self.loop = asyncio.get_running_loop()
        self.data: dict = {}
        self.bus = EventBus()
        self.config = Config(config_dir, media_dir)
        self.http = None  # the desktop server: register_view()
        self.is_running = True
        self._tasks: set[asyncio.Task] = set()
        self.stores: list = []  # helpers.storage.Store instances, flushed on exit

    def async_add_executor_job(self, target, *args):
        return self.loop.run_in_executor(None, target, *args)

    def async_create_task(self, target, name: str | None = None, eager_start: bool = True) -> asyncio.Task:
        task = self.loop.create_task(target, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async_create_background_task = async_create_task

    async def async_stop(self) -> None:
        """Write the delayed saves, then stop what is still running."""
        for store in self.stores:
            await store.async_flush()
        for task in list(self._tasks):
            task.cancel()
        session = self.data.get("aiohttp_session")
        if session is not None:
            await session.close()
