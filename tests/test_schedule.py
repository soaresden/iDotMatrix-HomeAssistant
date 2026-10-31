import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.idotmatrix import schedule
from custom_components.idotmatrix.schedule import SCHEDULE_SCHEMA, Scheduler, block_at, next_change

# Imported after Home Assistant so it resolves to the same validation library.
import voluptuous as vol  # noqa: E402

BLOCKS = [
    {"from": "23:00", "to": "07:00", "action": "off"},
    {"from": "07:00", "to": "12:00", "action": "routine", "routine_id": "matin"},
    {"from": "10:00", "to": "20:00", "action": "routine", "routine_id": "jour"},
]


def at(clock):
    return datetime.fromisoformat(f"2026-10-28T{clock}:00")


@pytest.mark.parametrize("clock,expected", [
    ("02:00", 0), ("06:59", 0), ("07:00", 1), ("11:00", 1),  # the shorter block wins an overlap
    ("12:00", 2), ("20:00", None), ("23:30", 0),
])
def test_block_at(clock, expected):
    assert block_at(BLOCKS, at(clock)) == expected


def test_blocks_keep_to_their_days():
    # 2026-10-28 is a Wednesday (2); the 26th a Monday.
    weekend = [{"from": "22:00", "to": "02:00", "action": "off", "days": [5, 6]},
               {"from": "08:00", "to": "09:00", "action": "off", "days": [0, 2]}]
    day = lambda date, clock: datetime.fromisoformat(f"{date}T{clock}:00")  # noqa: E731
    assert block_at(weekend, day("2026-10-28", "08:30")) == 1          # Wednesday
    assert block_at(weekend, day("2026-10-29", "08:30")) is None       # Thursday
    assert block_at(weekend, day("2026-10-31", "23:00")) == 0          # Saturday night
    assert block_at(weekend, day("2026-11-02", "01:00")) == 0          # Sunday's block, after midnight
    assert block_at(weekend, day("2026-10-31", "01:00")) is None       # Friday's night: not a weekend block
    assert SCHEDULE_SCHEMA({"blocks": weekend})["blocks"][0]["days"] == [5, 6]
    with pytest.raises(vol.Invalid):
        SCHEDULE_SCHEMA({"blocks": [{"from": "08:00", "to": "09:00", "action": "off", "days": [7]}]})


def test_all_day_and_switched_off_blocks():
    all_day = {"from": "00:00", "to": "00:00", "action": "routine", "routine_id": "jour"}
    assert block_at([all_day], at("03:17")) == 0
    assert block_at([{**all_day, "enabled": False}], at("03:17")) is None
    assert block_at([{**all_day, "days": [2]}], at("23:59")) == 0  # 2026-10-28: Wednesday
    assert SCHEDULE_SCHEMA({"blocks": [{**all_day, "enabled": False}]})["blocks"][0]["enabled"] is False


def test_overlaps_go_to_the_highest_priority_then_the_shortest_block():
    all_day = {"from": "00:00", "to": "00:00", "action": "routine", "routine_id": "fond"}
    evening = {"from": "18:00", "to": "22:00", "action": "routine", "routine_id": "soir"}
    violin = {"from": "19:00", "to": "20:00", "action": "routine", "routine_id": "violon"}
    # Listed first, the all-day routine is still the background the others interrupt.
    assert [block_at([all_day, evening, violin], at(t)) for t in ("12:00", "18:30", "19:30")] == [0, 1, 2]
    # A higher priority wins whatever its length; a lower one gives way.
    assert block_at([{**all_day, "priority": 2}, evening, violin], at("19:30")) == 0
    assert block_at([all_day, evening, {**violin, "priority": 0}], at("19:30")) == 1
    # Same priority and length: the first listed.
    assert block_at([evening, {**evening, "routine_id": "autre"}], at("19:00")) == 0
    assert SCHEDULE_SCHEMA({"blocks": [{**violin, "priority": 2}]})["blocks"][0]["priority"] == 2
    with pytest.raises(vol.Invalid):
        SCHEDULE_SCHEMA({"blocks": [{**violin, "priority": 3}]})


def test_next_change():
    assert next_change(BLOCKS, at("11:30")) == at("12:00")
    assert next_change(BLOCKS, at("21:15")) == at("23:00")
    assert next_change([], at("12:00")) is None


def test_schema():
    assert SCHEDULE_SCHEMA({}) == {"enabled": False, "blocks": [], "gaps": "off"}
    with pytest.raises(vol.Invalid):
        SCHEDULE_SCHEMA({"gaps": "dim"})
    for bad in ({"from": "7:00", "to": "08:00", "action": "off"}, {"from": "07:00", "to": "08:00", "action": "dim"}):
        with pytest.raises(vol.Invalid):
            SCHEDULE_SCHEMA({"enabled": True, "blocks": [bad]})


class FakeHass:
    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)


def make_scheduler(monkeypatch, clock):
    monkeypatch.setattr(schedule, "datetime", type("Clock", (datetime,), {"now": classmethod(lambda cls: at(clock[0]))}))
    runner = MagicMock(active_id=None)
    coordinator = MagicMock(text_settings={})
    coordinator._device_call = AsyncMock()
    routines = {"matin": {"id": "matin", "name": "Matin"}, "jour": {"id": "jour", "name": "Jour"}}
    statuses = []
    scheduler = Scheduler(FakeHass(), runner, lambda: routines, lambda: coordinator, statuses.append)
    return scheduler, runner, coordinator, statuses


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


async def test_off_block_stops_the_routine_and_darkens_the_screen(monkeypatch):
    clock = ["23:30"]
    scheduler, runner, coordinator, statuses = make_scheduler(monkeypatch, clock)
    scheduler.update({"enabled": True, "blocks": BLOCKS})
    await settle()
    runner.stop.assert_called_once_with(reset_display=False)
    assert coordinator._device_call.await_args.args[0].__name__ == "screenOff"
    assert scheduler.screen_off and coordinator.text_settings["is_on"] is False
    assert statuses[-1]["screen_off"] and statuses[-1]["block"]["action"] == "off"

    # Morning: the screen wakes up and the morning routine starts.
    clock[0] = "07:00"
    scheduler._tick(None)
    await settle()
    assert coordinator._device_call.await_args.args[0].__name__ == "screenOn"
    runner.start.assert_called_once_with({"id": "matin", "name": "Matin"})
    assert not scheduler.screen_off


async def test_changes_apply_once_per_block(monkeypatch):
    clock = ["08:00"]
    scheduler, runner, _coordinator, _ = make_scheduler(monkeypatch, clock)
    scheduler.update({"enabled": True, "blocks": BLOCKS})
    await settle()
    runner.start.assert_called_once()
    # Stopped by hand: the schedule leaves it alone until the next block.
    runner.active_id = None
    scheduler._tick(None)
    await settle()
    runner.start.assert_called_once()
    clock[0] = "12:30"
    scheduler._tick(None)
    await settle()
    assert runner.start.call_args.args[0]["id"] == "jour"


async def test_gaps_between_blocks_switch_the_screen_off_unless_kept(monkeypatch):
    clock = ["21:00"]  # between "jour" (until 20:00) and the night block (from 23:00)
    scheduler, runner, coordinator, statuses = make_scheduler(monkeypatch, clock)
    scheduler.update({"enabled": True, "blocks": BLOCKS})
    await settle()
    runner.stop.assert_called_once_with(reset_display=False)
    assert coordinator._device_call.await_args.args[0].__name__ == "screenOff"
    assert statuses[-1]["block"] == {"action": "off", "gap": True} and scheduler.screen_off

    # "keep": the gap leaves what runs alone, and wakes the screen it had darkened.
    scheduler.update({"enabled": True, "blocks": BLOCKS, "gaps": "keep"})
    await settle()
    assert coordinator._device_call.await_args.args[0].__name__ == "screenOn"
    assert runner.stop.call_count == 1 and scheduler.status["block"] is None

    # Without any block there is no gap to darken.
    scheduler.update({"enabled": True, "blocks": []})
    await settle()
    assert scheduler.status["block"] is None and not scheduler.screen_off


async def test_disabled_schedule_does_nothing_and_wakes_a_dark_screen(monkeypatch):
    clock = ["02:00"]
    scheduler, runner, coordinator, _ = make_scheduler(monkeypatch, clock)
    scheduler.update({"enabled": True, "blocks": BLOCKS})
    await settle()
    scheduler.update({"enabled": False, "blocks": BLOCKS})
    await settle()
    assert coordinator._device_call.await_args.args[0].__name__ == "screenOn"
    assert not scheduler.screen_off
    assert scheduler.status["block"] is None
