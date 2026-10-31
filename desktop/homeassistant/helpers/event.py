"""helpers.event timers for the desktop app (the routines' schedule ticks)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta


def _seconds(delay) -> float:
    return delay.total_seconds() if isinstance(delay, timedelta) else float(delay)


def _run(hass, action) -> None:
    result = action(datetime.now().astimezone())
    if asyncio.iscoroutine(result):
        hass.async_create_task(result)


def async_call_later(hass, delay, action):
    """Run ``action(now)`` once after ``delay``; returns the canceller."""
    return hass.loop.call_later(_seconds(delay), _run, hass, action).cancel


def async_track_time_interval(hass, action, interval, **_options):
    """Run ``action(now)`` every ``interval``; returns the canceller."""
    seconds = _seconds(interval)
    state = {}

    def tick() -> None:
        state["handle"] = hass.loop.call_later(seconds, tick)
        _run(hass, action)

    state["handle"] = hass.loop.call_later(seconds, tick)
    return lambda: state["handle"].cancel()
