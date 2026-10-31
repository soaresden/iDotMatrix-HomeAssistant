"""Routines: rotate gallery GIFs on the display, like the Android app's playlists.

Two modes:

* ``ha`` — Home Assistant sends the next GIF every ``interval`` seconds,
  picked at random (never the same twice in a row) or in order, from any
  number of GIFs, optionally only between two times of day. Each change
  costs a Bluetooth upload; each GIF then stays the whole interval once it
  has arrived.
  The next 12 GIFs are drawn in advance (``upcoming`` in the status), so
  the Studio can show them; ``skip`` shows the next one, or a chosen one,
  right away (after the one being sent).
* ``carousel`` — up to 12 GIFs are uploaded once into the display's native
  carousel, which then rotates by itself with no Bluetooth traffic. Random
  order shuffles the selection; larger random selections are re-drawn
  every ``reshuffle`` seconds.
* ``weather`` — the time and the day ahead (meteo.py): a one-image GIF
  (one Bluetooth packet) each minute for the clock, the forecast fetched
  again every ``interval`` seconds. It waits while something else is on
  its way to the display.

The active routine survives Home Assistant restarts.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import time
from datetime import datetime, time as dtime

import voluptuous as vol

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .meteo import WEATHER_SCHEMA, brightness_for, local_now, placeholders, seconds_to_next_minute

_LOGGER = logging.getLogger(__name__)

CAROUSEL_SLOTS = 12
# How many upcoming GIFs a routine driven by Home Assistant draws in advance.
QUEUE_LENGTH = 12
# Let Bluetooth settle after a Home Assistant start before resuming.
RESUME_DELAY = 60
OUTSIDE_HOURS_CHECK = 30
RESHUFFLE_SECONDS = 3600
# Weather: a failed forecast is asked again after this; a busy display is checked this often.
WEATHER_RETRY = 300
BUSY_POLL = 1.0

_HHMM = vol.Match(r"^([01]\d|2[0-3]):[0-5]\d$")

def _gifs_or_collection(routine: dict) -> dict:
    """An ensemble lists its GIFs, or takes those of a collection (kept in step).

    A weather view shows no GIF: it says where the weather comes from, and
    its interval is how often the forecast is fetched (15 min to 1 h).
    """
    if routine["mode"] == "weather":
        if not routine.get("weather"):
            raise vol.Invalid("Choisis d'où vient la météo")
        if not 900 <= routine["interval"] <= 3600:
            raise vol.Invalid("La météo se met à jour toutes les 15 à 60 minutes")
        return routine
    if not routine["files"] and not routine.get("collection"):
        raise vol.Invalid("Choose at least one GIF or a collection")
    return routine


_ROUTINE_FIELDS = vol.Schema({
    vol.Required("id"): vol.All(str, vol.Length(min=1, max=64)),
    vol.Required("name"): vol.All(str, vol.Length(min=1, max=80)),
    vol.Optional("files", default=list): [str],
    # Takes the GIFs of this collection (as it is when each GIF is drawn).
    vol.Optional("collection"): vol.Any(None, vol.All(str, vol.Length(min=1, max=64))),
    vol.Required("interval"): vol.All(vol.Coerce(int), vol.Range(min=5, max=86400)),
    vol.Optional("order", default="random"): vol.In(("random", "sequence")),
    vol.Optional("mode", default="ha"): vol.In(("ha", "carousel", "weather")),
    vol.Optional("hours"): vol.Any(None, {vol.Required("from"): _HHMM, vol.Required("to"): _HHMM}),
    vol.Optional("weather"): vol.Any(None, WEATHER_SCHEMA),
})
ROUTINE_SCHEMA = vol.All(_ROUTINE_FIELDS, _gifs_or_collection)


def within_hours(hours: dict | None, now: datetime) -> bool:
    """Whether ``now`` falls in the routine's daily window (overnight allowed)."""
    if not hours:
        return True
    start = dtime.fromisoformat(hours["from"])
    end = dtime.fromisoformat(hours["to"])
    current = now.time()
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def pick_next(files: list[str], order: str, previous: str | None, rng: random.Random | None = None) -> str:
    """Next GIF: in order after ``previous``, or random without repeating it."""
    if order == "sequence":
        if previous in files:
            return files[(files.index(previous) + 1) % len(files)]
        return files[0]
    rng = rng or random
    choices = [f for f in files if f != previous] or files
    return rng.choice(choices)


def fill_queue(queue: list[str], files: list[str], order: str, previous: str | None,
               rng: random.Random | None = None) -> list[str]:
    """Top up the upcoming GIFs, in place, to 12 (fewer for small selections).

    GIFs gone from the gallery leave the queue. In order, it follows
    ``pick_next``; at random, it draws GIFs not already waiting (never the
    same twice in a row either), so the next 12 are 12 different GIFs.
    """
    kept = [f for f in queue if f in files]
    queue[:] = [f for i, f in enumerate(kept) if i == 0 or f != kept[i - 1]]
    while len(queue) < min(QUEUE_LENGTH, len(files)):
        last = queue[-1] if queue else previous
        fresh = [f for f in files if f not in queue and f != last] if order == "random" else []
        queue.append((rng or random).choice(fresh) if fresh else pick_next(files, order, last, rng))
    return queue


def carousel_selection(files: list[str], order: str, rng: random.Random | None = None) -> list[str]:
    """The GIFs (at most 12) to upload into the display's carousel."""
    if order == "random":
        rng = rng or random
        return rng.sample(files, min(CAROUSEL_SLOTS, len(files)))
    return files[:CAROUSEL_SLOTS]


class RoutineRunner:
    """Runs at most one routine at a time against the display."""

    def __init__(self, hass: HomeAssistant, gallery_path, coordinator, notify, files_of=None,
                 weather=None, busy=None) -> None:
        self.hass = hass
        self._gallery_path = gallery_path   # file name -> absolute path
        # routine -> its GIFs (those of its collection when it has one)
        self._files_of = files_of or (lambda routine: routine["files"])
        self._coordinator = coordinator     # () -> IDotMatrixCoordinator
        self._notify = notify               # (status dict) -> None
        self._weather = weather             # meteo.WeatherService
        # () -> whether something else is on its way to the display
        self._busy = busy or (lambda: False)
        self._task: asyncio.Task | None = None
        # Set by skip(): ends the wait for the next GIF.
        self._skip = asyncio.Event()
        self._queue: list[str] = []  # upcoming GIFs (mode « ha »)
        self.routine: dict | None = None
        self.status: dict = {"active": None}

    @property
    def active_id(self) -> str | None:
        # A carousel keeps running on the display after its upload task ends.
        return self.routine["id"] if self.routine else None

    def start(self, routine: dict, delay: float = 0) -> None:
        self.stop(reset_display=False)
        self.routine = routine
        self._skip.clear()
        self._queue = []
        self._set_status(state="starting", current=None, next_at=time.time() + delay,
                         mode=routine.get("mode", "ha"))
        self._task = self.hass.async_create_background_task(
            self._run(routine, delay), f"idotmatrix routine {routine['name']}"
        )

    def stop(self, reset_display: bool = True) -> None:
        was_carousel = self.routine and self.routine.get("mode") == "carousel"
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self.routine = None
        self.status = {"active": None}
        self._notify(self.status)
        if reset_display and was_carousel:
            self.hass.async_create_task(self._stop_carousel())

    def update(self, routine: dict) -> bool:
        """Take a running weather view's new settings without starting over: the display gets
        them at once, after the send in progress if there is one (changes made meanwhile come
        down to the newest). False when it is not the running view (start it instead)."""
        if not self.routine or self.routine["id"] != routine["id"] or routine.get("mode") != "weather"                 or self.routine.get("mode") != "weather" or not self._task or self._task.done():
            return False
        self.routine = routine
        self._skip.set()  # ends the wait for the next minute
        return True

    def skip(self, file: str | None = None) -> bool:
        """Show the next GIF now, or ``file`` (one of the routine's GIFs).

        False when nothing runs, the display rotates by itself or ``file``
        is not in the routine.
        """
        if not self.routine or self.routine.get("mode") in ("carousel", "weather"):
            return False
        if file is not None:
            if file not in self._files_of(self.routine):
                return False
            if file in self._queue:
                self._queue.remove(file)
            self._queue.insert(0, file)
            self._queue[:] = [f for i, f in enumerate(self._queue) if i == 0 or f != self._queue[i - 1]]
            self._set_status(upcoming=list(self._queue))
        self._skip.set()
        if self.status.get("state") == "showing":
            self._set_status(next_at=time.time())
        return True

    async def _wait(self, seconds: float) -> None:
        """Sleep, unless skip() asks for the next GIF first."""
        try:
            await asyncio.wait_for(self._skip.wait(), seconds)
        except asyncio.TimeoutError:
            pass

    async def _stop_carousel(self) -> None:
        try:
            await self._coordinator().async_stop_gif_display()
        except HomeAssistantError as err:
            _LOGGER.debug("Could not stop the carousel: %s", err)

    def _set_status(self, **values) -> None:
        self.status = {**self.status, **values, "active": self.active_id}
        self._notify(self.status)

    async def _run(self, routine: dict, delay: float) -> None:
        if delay:
            await asyncio.sleep(delay)
        if routine.get("mode") == "carousel":
            await self._run_carousel(routine)
        elif routine.get("mode") == "weather":
            await self._run_weather(routine)
        else:
            await self._run_ha(routine)

    def _available(self, routine: dict) -> list[str]:
        return [f for f in self._files_of(routine) if os.path.isfile(self._gallery_path(f))]

    async def _run_ha(self, routine: dict) -> None:
        previous = None
        while True:
            if not within_hours(routine.get("hours"), datetime.now()):
                self._skip.clear()  # nothing to skip to outside the hours
                self._set_status(state="waiting", next_at=time.time() + OUTSIDE_HOURS_CHECK)
                await asyncio.sleep(OUTSIDE_HOURS_CHECK)
                continue
            # Cleared before sending: a skip asked during the send below
            # still ends the wait that follows it.
            self._skip.clear()
            files = await self.hass.async_add_executor_job(self._available, routine)
            if not files:
                self._set_status(state="error", message="Aucun GIF de la routine n'est dans la galerie")
                return
            order = routine.get("order", "random")
            fill_queue(self._queue, files, order, previous)
            file = self._queue.pop(0)
            fill_queue(self._queue, files, order, file)
            previous = file
            self._set_status(state="sending", current=file, upcoming=list(self._queue), message=None)
            try:
                await self._coordinator().async_display_gif(path=self._gallery_path(file))
            except HomeAssistantError as err:
                _LOGGER.warning("Routine %s: could not show %s: %s", routine["name"], file, err)
                self._set_status(message=str(err))
            # The interval is how long each GIF stays on screen once it has
            # arrived. Counting the send in it chained big GIFs back to back:
            # a 4-minute send in a 60 s routine left 5 s on screen, and the
            # panel spent its time frozen receiving.
            wait = float(routine["interval"])
            self._set_status(state="showing", next_at=time.time() + wait)
            await self._wait(wait)

    async def _run_carousel(self, routine: dict) -> None:
        while True:
            files = await self.hass.async_add_executor_job(self._available, routine)
            if not files:
                self._set_status(state="error", message="Aucun GIF de la routine n'est dans la galerie")
                return
            selection = carousel_selection(files, routine.get("order", "random"))
            self._set_status(state="sending", current=None, carousel=selection, message=None)
            try:
                await self._coordinator().async_display_gif(
                    files=[self._gallery_path(f) for f in selection],
                    rotation_interval=routine["interval"],
                )
            except HomeAssistantError as err:
                self._set_status(state="error", message=str(err))
                return
            # When the display started rotating, for the Studio to estimate
            # which slot it shows (the display never says).
            shown = {"carousel_at": time.time(), "interval": routine["interval"]}
            if routine.get("order") != "random" or len(files) <= CAROUSEL_SLOTS:
                self._set_status(state="carousel", next_at=None, **shown)
                return
            self._set_status(state="carousel", next_at=time.time() + RESHUFFLE_SECONDS, **shown)
            await asyncio.sleep(RESHUFFLE_SECONDS)

    async def _run_weather(self, routine: dict) -> None:
        forecasts, due, seen = None, 0.0, None
        # How long the last minute took to reach the display: the next one is
        # drawn from that second on, so its seconds are right once it plays.
        lead = 1.5
        brightness = None
        while True:
            # The settings as they are now (update() changes them live).
            routine = self.routine or routine
            cfg = routine["weather"]
            self._skip.clear()
            if seen is not None and seen != (routine["interval"], [p.get("place") or p for p in cfg["profiles"]]):
                due = 0.0  # other places: their forecasts at once
            seen = (routine["interval"], [p.get("place") or p for p in cfg["profiles"]])
            if not within_hours(routine.get("hours"), datetime.now()):
                self._set_status(state="waiting", next_at=time.time() + OUTSIDE_HOURS_CHECK)
                await asyncio.sleep(OUTSIDE_HOURS_CHECK)
                continue
            if self._weather is None:
                self._set_status(state="error", message="La météo n'est pas disponible ici")
                return
            if time.time() >= due:
                try:
                    forecasts = await self._weather.forecasts(cfg, max_age=routine["interval"])
                    due = time.time() + routine["interval"]
                    self._set_status(state="updated", weather=_summary(forecasts), message=None)
                except HomeAssistantError as err:
                    _LOGGER.warning("Routine %s: no forecast: %s", routine["name"], err)
                    due = time.time() + WEATHER_RETRY
                    # The last forecast stays up meanwhile; the clock goes on.
                    self._set_status(message=str(err), **({} if forecasts else {"state": "error"}))
            # Never in the middle of another send (a gallery GIF, the live
            # preview, a message): the time waits for it, then is drawn anew.
            while self._busy():
                if self.status.get("state") != "busy":
                    self._set_status(state="busy")
                await asyncio.sleep(BUSY_POLL)
            # No forecast to be had yet (no network): the time goes on, the weather as dashes.
            shown = forecasts or placeholders(cfg)
            try:
                extras = await self._weather.extras(cfg)
            except Exception:  # noqa: BLE001 - the pages wait, the time goes on
                extras = None
            if shown:
                wanted = brightness_for(cfg, forecasts or [], local_now())
                if wanted is not None and wanted != brightness:
                    try:
                        await self._weather.set_brightness(self._coordinator(), wanted)
                        brightness = wanted
                    except HomeAssistantError as err:
                        _LOGGER.warning("Routine %s: brightness: %s", routine["name"], err)
                self._set_status(state="sending")
                started = time.monotonic()
                try:
                    await self._weather.show(self._coordinator(), shown, cfg, lead, extras)
                    lead = min(10.0, max(0.5, time.monotonic() - started))
                except HomeAssistantError as err:
                    _LOGGER.warning("Routine %s: could not show the weather: %s", routine["name"], err)
                    self._set_status(message=str(err))
            wait = seconds_to_next_minute()
            self._set_status(state="showing", next_at=time.time() + wait)
            await self._wait(wait)


def _summary(forecasts: list) -> dict:
    """What the status says about a weather view: its places, the first one's weather."""
    summary = forecasts[0].summary()
    summary["place"] = " / ".join(f.place for f in forecasts)
    return summary
