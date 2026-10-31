import asyncio
import random
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from custom_components.idotmatrix import routines
from custom_components.idotmatrix.routines import (
    CAROUSEL_SLOTS,
    ROUTINE_SCHEMA,
    RoutineRunner,
    carousel_selection,
    fill_queue,
    pick_next,
    within_hours,
)

# Imported after Home Assistant so it resolves to the same validation library.
import voluptuous as vol  # noqa: E402


@pytest.mark.parametrize("hours,clock,expected", [
    (None, "03:00", True),
    ({"from": "08:00", "to": "23:00"}, "07:59", False),
    ({"from": "08:00", "to": "23:00"}, "08:00", True),
    ({"from": "08:00", "to": "23:00"}, "23:00", False),
    ({"from": "22:00", "to": "06:00"}, "23:30", True),   # overnight window
    ({"from": "22:00", "to": "06:00"}, "05:59", True),
    ({"from": "22:00", "to": "06:00"}, "12:00", False),
])
def test_within_hours(hours, clock, expected):
    now = datetime.fromisoformat(f"2026-10-24T{clock}:00")
    assert within_hours(hours, now) is expected


def test_random_never_repeats_the_previous_gif():
    rng = random.Random(3)
    files = ["a.gif", "b.gif", "c.gif"]
    previous = None
    for _ in range(50):
        current = pick_next(files, "random", previous, rng)
        assert current != previous
        previous = current
    assert pick_next(["only.gif"], "random", "only.gif", rng) == "only.gif"


def test_sequence_wraps_around():
    files = ["a.gif", "b.gif", "c.gif"]
    assert [pick_next(files, "sequence", p) for p in (None, "a.gif", "c.gif", "gone.gif")] == ["a.gif", "b.gif", "a.gif", "a.gif"]


def test_queue_draws_the_next_twelve_without_repeats():
    files = [f"{i}.gif" for i in range(30)]
    queue = fill_queue([], files, "random", "0.gif", random.Random(1))
    assert len(queue) == 12 and queue[0] != "0.gif"
    assert len(set(queue)) == 12  # twelve different GIFs
    # Topping up keeps what was drawn; GIFs gone from the gallery leave.
    head = queue[:5]
    queue.pop(0)
    fill_queue(queue, [f for f in files if f != head[2]], "random", head[0], random.Random(2))
    assert len(queue) == 12 and queue[:3] == [head[1], head[3], head[4]] and head[2] not in queue
    assert fill_queue([], ["a.gif", "b.gif", "c.gif"], "sequence", "a.gif") == ["b.gif", "c.gif", "a.gif"]


def test_carousel_selection_keeps_twelve():
    files = [f"{i}.gif" for i in range(20)]
    assert carousel_selection(files, "sequence") == files[:CAROUSEL_SLOTS]
    shuffled = carousel_selection(files, "random", random.Random(1))
    assert len(shuffled) == CAROUSEL_SLOTS and len(set(shuffled)) == CAROUSEL_SLOTS


def test_schema_defaults_and_limits():
    routine = ROUTINE_SCHEMA({"id": "r1", "name": "Salon", "files": ["a.gif"], "interval": "300"})
    assert (routine["interval"], routine["order"], routine["mode"]) == (300, "random", "ha")
    for bad in ({"interval": 2}, {"files": []}, {"mode": "stream"}, {"hours": {"from": "25:00", "to": "06:00"}}):
        with pytest.raises(vol.Invalid):
            ROUTINE_SCHEMA({"id": "r1", "name": "Salon", "files": ["a.gif"], "interval": 300, **bad})


class FakeHass:
    def async_create_background_task(self, coro, name):
        return asyncio.ensure_future(coro)

    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


async def test_runner_shows_gifs_then_waits_for_the_interval(tmp_path, monkeypatch):
    for name in ("a.gif", "b.gif"):
        (tmp_path / name).write_bytes(b"GIF89a")
    coordinator = AsyncMock()
    statuses = []
    waits = []

    async def fake_wait(self, seconds):
        waits.append(seconds)
        if len(waits) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(RoutineRunner, "_wait", fake_wait)
    runner = RoutineRunner(FakeHass(), lambda f: str(tmp_path / f), lambda: coordinator, statuses.append)
    routine = ROUTINE_SCHEMA({"id": "r1", "name": "Salon", "files": ["a.gif", "b.gif", "missing.gif"],
                              "interval": 300, "order": "sequence"})
    runner.start(routine)
    with pytest.raises(asyncio.CancelledError):
        await runner._task
    shown = [call.kwargs["path"] for call in coordinator.async_display_gif.await_args_list]
    assert shown == [str(tmp_path / "a.gif"), str(tmp_path / "b.gif")]
    assert all(295 <= w <= 300 for w in waits)
    assert runner.active_id == "r1" and statuses[-1]["current"] == "b.gif"


async def test_next_shows_the_following_gif_without_waiting(tmp_path):
    for name in ("a.gif", "b.gif", "c.gif"):
        (tmp_path / name).write_bytes(b"GIF89a")
    coordinator = AsyncMock()
    statuses = []
    runner = RoutineRunner(FakeHass(), lambda f: str(tmp_path / f), lambda: coordinator, statuses.append)
    routine = ROUTINE_SCHEMA({"id": "r1", "name": "Salon", "files": ["a.gif", "b.gif", "c.gif"],
                              "interval": 3600, "order": "sequence"})
    runner.start(routine)
    shown = lambda: [call.kwargs["path"] for call in coordinator.async_display_gif.await_args_list]
    for _ in range(20):
        await asyncio.sleep(0)
    assert shown() == [str(tmp_path / "a.gif")] and runner.status["state"] == "showing"
    assert runner.skip() is True
    assert runner.status["next_at"] <= __import__("time").time()
    await asyncio.wait_for(_until(lambda: len(shown()) == 2), 1)
    assert shown()[-1] == str(tmp_path / "b.gif")
    # The following wait is a full interval again.
    for _ in range(20):
        await asyncio.sleep(0)
    assert len(shown()) == 2 and runner.status["state"] == "showing"
    runner.stop()


async def test_next_asked_during_a_send_follows_it(tmp_path):
    for name in ("a.gif", "b.gif"):
        (tmp_path / name).write_bytes(b"GIF89a")
    sending = asyncio.Event()
    coordinator = AsyncMock()

    async def display(**kw):
        await sending.wait()
    coordinator.async_display_gif.side_effect = display
    runner = RoutineRunner(FakeHass(), lambda f: str(tmp_path / f), lambda: coordinator, lambda s: None)
    runner.start(ROUTINE_SCHEMA({"id": "r1", "name": "Salon", "files": ["a.gif", "b.gif"],
                                 "interval": 3600, "order": "sequence"}))
    await asyncio.wait_for(_until(lambda: runner.status.get("state") == "sending"), 1)
    assert runner.skip() is True
    sending.set()
    await asyncio.wait_for(_until(lambda: coordinator.async_display_gif.await_count == 2), 1)
    runner.stop()


async def test_a_chosen_gif_comes_next_and_the_queue_shows_it(tmp_path):
    names = [f"{i}.gif" for i in range(20)]
    for name in names:
        (tmp_path / name).write_bytes(b"GIF89a")
    coordinator = AsyncMock()
    runner = RoutineRunner(FakeHass(), lambda f: str(tmp_path / f), lambda: coordinator, lambda s: None)
    runner.start(ROUTINE_SCHEMA({"id": "r1", "name": "Salon", "files": names, "interval": 3600}))
    await asyncio.wait_for(_until(lambda: runner.status.get("state") == "showing"), 1)
    upcoming = runner.status["upcoming"]
    assert len(upcoming) == 12 and runner.status["current"] not in upcoming[:1]
    chosen = upcoming[7]
    assert runner.skip(chosen) is True
    assert runner.status["upcoming"][0] == chosen and runner.status["upcoming"].count(chosen) == 1
    await asyncio.wait_for(_until(lambda: coordinator.async_display_gif.await_count == 2), 1)
    assert coordinator.async_display_gif.await_args.kwargs["path"] == str(tmp_path / chosen)
    assert runner.skip("not-in-the-routine.gif") is False
    runner.stop()


async def test_next_does_nothing_for_a_display_carousel(tmp_path):
    runner = RoutineRunner(FakeHass(), lambda f: str(tmp_path / f), AsyncMock, lambda s: None)
    assert runner.skip() is False  # nothing running
    runner.routine = ROUTINE_SCHEMA({"id": "r2", "name": "Nuit", "files": ["0.gif"], "interval": 300, "mode": "carousel"})
    assert runner.skip() is False


async def _until(condition):
    while not condition():
        await asyncio.sleep(0.01)


async def test_carousel_mode_uploads_once(tmp_path):
    for i in range(3):
        (tmp_path / f"{i}.gif").write_bytes(b"GIF89a")
    coordinator = AsyncMock()
    runner = RoutineRunner(FakeHass(), lambda f: str(tmp_path / f), lambda: coordinator, lambda s: None)
    routine = ROUTINE_SCHEMA({"id": "r2", "name": "Nuit", "files": ["0.gif", "1.gif", "2.gif"],
                              "interval": 300, "mode": "carousel", "order": "sequence"})
    runner.start(routine)
    await runner._task
    call = coordinator.async_display_gif.await_args
    assert call.kwargs["rotation_interval"] == 300
    assert call.kwargs["files"] == [str(tmp_path / f"{i}.gif") for i in range(3)]
    assert runner.active_id == "r2" and runner.status["state"] == "carousel"
    # When the display started rotating, for the Studio's estimate of its slot.
    assert runner.status["interval"] == 300 and runner.status["carousel_at"] > 0
    runner.stop()
    await asyncio.sleep(0)
    coordinator.async_stop_gif_display.assert_awaited_once()
    assert runner.active_id is None


async def test_each_gif_stays_the_whole_interval_however_long_it_took_to_send(tmp_path, monkeypatch):
    (tmp_path / "big.gif").write_bytes(b"GIF89a")
    clock = [1000.0]
    monkeypatch.setattr(routines.time, "monotonic", lambda: clock[0])

    async def slow_send(path):
        clock[0] += 240  # a 4-minute Bluetooth send

    coordinator = AsyncMock()
    coordinator.async_display_gif.side_effect = slow_send
    waits = []

    async def fake_wait(self, seconds):
        waits.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(RoutineRunner, "_wait", fake_wait)
    runner = RoutineRunner(FakeHass(), lambda f: str(tmp_path / f), lambda: coordinator, lambda s: None)
    runner.start(ROUTINE_SCHEMA({"id": "r1", "name": "Pn", "files": ["big.gif"], "interval": 60}))
    with pytest.raises(asyncio.CancelledError):
        await runner._task
    assert waits == [60.0]  # not 5 s squeezed out of the 60
