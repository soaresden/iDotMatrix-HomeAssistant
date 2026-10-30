"""Day schedule: time blocks that start a routine or switch the screen off.

The schedule acts on block changes only: entering an "off" block stops the
routine and darkens the panel, entering a routine block (or leaving an "off"
block) wakes the panel and starts that routine. Between blocks the screen
is off too (``gaps: "off"``, the default) unless the schedule keeps what
runs (``gaps: "keep"``). Between two changes, a routine started or stopped
by hand, or the screen woken by hand, stays as the user left it. Blocks may
cross midnight; when several overlap, the one with the highest ``priority``
wins, then the shortest (an all-day routine is a background the others
interrupt), then the first listed. A block may
keep to some days of the week (``days``, 0 = Monday); one that crosses
midnight belongs to the day it starts. A block from a time to the same time
lasts all day; a routine switched off in the panel keeps its blocks with
``enabled: false``, which do nothing until it is switched on again.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, time as dtime

import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .client.modules.common import Common
from .routines import RESUME_DELAY, within_hours

_LOGGER = logging.getLogger(__name__)

TICK = timedelta(seconds=20)

_HHMM = vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$")

BLOCK_SCHEMA = vol.Schema({
    vol.Required("from"): _HHMM,
    vol.Required("to"): _HHMM,
    vol.Required("action"): vol.In(("off", "routine")),
    vol.Optional("routine_id"): vol.Any(None, str),
    vol.Optional("enabled"): bool,
    # Which block wins an overlap: 0 low, 1 normal (default), 2 high.
    vol.Optional("priority"): vol.All(int, vol.Range(min=0, max=2)),
    # Days of the week it runs (0 = Monday); none means every day.
    vol.Optional("days"): vol.Any(None, vol.All([vol.All(int, vol.Range(min=0, max=6))], vol.Length(max=7))),
})

SCHEDULE_SCHEMA = vol.Schema({
    vol.Optional("enabled", default=False): bool,
    vol.Optional("blocks", default=list): vol.All([BLOCK_SCHEMA], vol.Length(max=48)),
    vol.Optional("gaps", default="off"): vol.In(("off", "keep")),
})

# What a gap between blocks does when the schedule switches the screen off there.
GAP_OFF = {"action": "off", "gap": True}


def gap_off(schedule: dict) -> bool:
    return bool(schedule.get("blocks")) and schedule.get("gaps", "off") == "off"


def covers(block: dict, now: datetime) -> bool:
    """Whether the block runs at ``now``: its hours, on one of its days."""
    if block.get("enabled") is False:
        return False
    if block["from"] != block["to"] and not within_hours(block, now):
        return False
    days = block.get("days")
    if not days:
        return True
    # After midnight, a block that crosses it still belongs to the day before.
    started = now.weekday() if now.strftime("%H:%M") >= block["from"] else (now.weekday() - 1) % 7
    return started in days


def block_minutes(block: dict) -> int:
    """How long a block lasts (from a time to the same time: all day)."""
    start = int(block["from"][:2]) * 60 + int(block["from"][3:])
    end = int(block["to"][:2]) * 60 + int(block["to"][3:])
    return (end - start) % 1440 or 1440


def block_at(blocks: list[dict], now: datetime) -> int | None:
    """Index of the block covering ``now``, if any.

    Highest priority first, then the shortest block, then the first listed.
    """
    covering = [index for index, block in enumerate(blocks) if covers(block, now)]
    if not covering:
        return None
    return min(covering, key=lambda i: (-blocks[i].get("priority", 1), block_minutes(blocks[i]), i))


def next_change(blocks: list[dict], now: datetime) -> datetime | None:
    """When the covering block next changes, to the minute (within a day)."""
    current = block_at(blocks, now)
    probe = now.replace(second=0, microsecond=0)
    for _ in range(24 * 60):
        probe += timedelta(minutes=1)
        if block_at(blocks, probe) != current:
            return probe
    return None


_UNSET = object()


class Scheduler:
    """Applies the day schedule to the routine runner and the screen."""

    def __init__(self, hass: HomeAssistant, runner, routines, coordinator, notify) -> None:
        self.hass = hass
        self._runner = runner
        self._routines = routines            # () -> {id: routine}
        self._coordinator = coordinator      # () -> IDotMatrixCoordinator
        self._notify = notify                # (status dict) -> None
        self.schedule: dict = {"enabled": False, "blocks": []}
        self.screen_off = False
        self._applied: object = None
        self._unsub_tick = None
        self._unsub_start = None

    def start(self, delay: float = RESUME_DELAY) -> None:
        """Begin ticking (after Bluetooth has settled on a Home Assistant start)."""
        self.stop()
        self._unsub_tick = async_track_time_interval(self.hass, self._tick, TICK)
        self._unsub_start = async_call_later(self.hass, delay, self._tick)

    def stop(self) -> None:
        for unsub in (self._unsub_tick, self._unsub_start):
            if unsub:
                unsub()
        self._unsub_tick = self._unsub_start = None

    def update(self, schedule: dict) -> None:
        """Replace the schedule and apply the block covering now."""
        self.schedule = schedule
        self._applied = _UNSET  # apply what covers now, even "nothing"
        if not schedule.get("enabled") and self.screen_off:
            self.hass.async_create_task(self._screen(True))
        self._tick(None)

    @property
    def status(self) -> dict:
        blocks = self.schedule.get("blocks", [])
        now = datetime.now()
        index = block_at(blocks, now) if self.schedule.get("enabled") else None
        change = next_change(blocks, now) if self.schedule.get("enabled") else None
        enabled = bool(self.schedule.get("enabled"))
        return {
            "enabled": enabled,
            "block": blocks[index] if index is not None else (GAP_OFF if enabled and gap_off(self.schedule) else None),
            "screen_off": self.screen_off,
            "next_change": change.timestamp() if change else None,
        }

    @callback
    def _tick(self, _now) -> None:
        if not self.schedule.get("enabled"):
            return
        blocks = self.schedule.get("blocks", [])
        index = block_at(blocks, datetime.now())
        block = blocks[index] if index is not None else (GAP_OFF if gap_off(self.schedule) else None)
        key = (index, block["action"], block.get("routine_id")) if block else None
        if key == self._applied:
            return
        self._applied = key
        self.hass.async_create_task(self._apply(block))

    async def _apply(self, block: dict | None) -> None:
        if block and block["action"] == "off":
            self._runner.stop(reset_display=False)
            await self._screen(False)
        else:
            if self.screen_off:
                await self._screen(True)
            routine = self._routines().get(block.get("routine_id") or "") if block else None
            if routine and self._runner.active_id != routine["id"]:
                self._runner.start(routine)
        self._notify(self.status)

    async def _screen(self, on: bool) -> None:
        try:
            coordinator = self._coordinator()
            await coordinator._device_call(Common().screenOn if on else Common().screenOff)
        except (HomeAssistantError, OSError) as err:
            _LOGGER.warning("Schedule: could not switch the screen %s: %s", "on" if on else "off", err)
            return
        self.screen_off = not on
        coordinator.text_settings["is_on"] = on
        coordinator.async_update_listeners()
        self._notify(self.status)

