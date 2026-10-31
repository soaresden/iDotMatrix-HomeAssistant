"""Pixel Studio: a sidebar panel to make GIFs for the display and keep a gallery.

The browser does the heavy lifting: it decodes the user's video, GIF or
image locally (any size), crops, trims, resamples and tunes it, and only
sends the resulting screen-sized frames here. Home Assistant encodes them
into the device-safe GIF format (``media.encode_frames``) within a byte
budget, stores the result in ``/media/idotmatrix`` and sends it to the
display. While editing, a still of the current frame can be mirrored live
on the panel. The device cannot list what it stores, so the gallery lives
here: one GIF per item plus a small store for titles and favourites.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import re
import shutil
import time
import unicodedata

import aiohttp
import voluptuous as vol
from aiohttp import web
from PIL import Image, ImageSequence

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import KEY_HASS, HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .journal import LOG_EVENT, Journal, gif_stats
from .media import ConvertOptions, encode_frames
from .pages import extra_pages
from .meteo import SEND_LABEL, WEATHER_SCHEMA, WeatherService, labels_of, local_now, preview_of, render_meteo_minute
from .routines import RESUME_DELAY, ROUTINE_SCHEMA, RoutineRunner
from .schedule import SCHEDULE_SCHEMA, Scheduler
from .weather import frames_to_gif

PANEL_URL = "pixel-studio"
PANEL_COMPONENT = "idotmatrix-studio"
GALLERY_FOLDER = DOMAIN
MEDIA_ID_PREFIX = "media-source://media_source/local/"
TRANSFER_EVENT = f"{DOMAIN}_transfer"
ROUTINE_EVENT = f"{DOMAIN}_routine"
SCHEDULE_EVENT = f"{DOMAIN}_schedule"
WORKSPACE_EVENT = f"{DOMAIN}_workspace"
ENCODE_URL = "/api/idotmatrix/studio/encode"
# Until a transfer is timed: a Pi's built-in Bluetooth with fast writes and
# its MTU acquired (measured on 2026-10-29: 0.5 s writing, 0.08 s waiting).
DEFAULT_SECONDS_PER_PACKET = 0.6
PACKET_BYTES = 4096
MAX_FRAMES = 600
DEFAULT_FUZZ = 24

_STORE_KEY = f"{DOMAIN}_studio"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def slugify_name(name: str) -> str:
    """File-system friendly item name ("Mon Chat !" -> "mon_chat")."""
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text[:60] or "animation"


def unique_file(folder: str, slug: str, keep: str | None = None) -> str:
    """``<slug>.gif`` in folder, numbered if taken (``keep`` may be reused)."""
    candidate, number = f"{slug}.gif", 2
    while os.path.exists(os.path.join(folder, candidate)) and candidate != keep:
        candidate = f"{slug}_{number}.gif"
        number += 1
    return candidate


def estimate_seconds(size_bytes: int, seconds_per_packet: float | None) -> int:
    """Time to send a GIF over Bluetooth (4 KB packets, one handshake each)."""
    packets = max(1, math.ceil(size_bytes / PACKET_BYTES))
    return round(packets * (seconds_per_packet or DEFAULT_SECONDS_PER_PACKET))


def frames_from_sheet(sheet: bytes, durations: list[int], size: int,
                      columns: int = 1) -> list[tuple[Image.Image, int]]:
    """Split a grid of square frames, row by row (as the browser sends them).

    A grid rather than one strip: browsers cap canvases at 32767 px.
    """
    count = len(durations)
    if not 0 < count <= MAX_FRAMES:
        raise ValueError(f"Between 1 and {MAX_FRAMES} frames are supported")
    columns = max(1, min(columns, count))
    rows = math.ceil(count / columns)
    with Image.open(io.BytesIO(sheet)) as image:
        grid = image.convert("RGB")
    if grid.size != (columns * size, rows * size):
        raise ValueError("Frame sheet does not match the frame durations")
    frames = []
    for i, ms in enumerate(durations):
        x, y = (i % columns) * size, (i // columns) * size
        frames.append((grid.crop((x, y, x + size, y + size)), max(20, int(ms))))
    return frames


def encode_options(data: dict, size: int) -> ConvertOptions:
    """Encoding settings from the editor (tones are already applied by the browser).

    The gallery lives on Home Assistant, so GIFs are kept at full quality unless
    a ``max_kb`` budget is asked for.
    """
    options = ConvertOptions(size=size, contrast=1, saturation=1, black_level=0)
    max_kb = int(data.get("max_kb") or 0)
    options.max_bytes = max_kb * 1024 if max_kb > 0 else None
    options.dither = bool(data.get("dither", False))
    options.boomerang = bool(data.get("boomerang", False))
    options.merge_similar = bool(data.get("merge_similar", True))
    # Lighter GIFs: video noise below this is not sent again (24 halves most clips).
    options.fuzz = max(0, min(64, int(data.get("fuzz", DEFAULT_FUZZ))))
    # Render settings: palette size and a frame-rate cap (frames sooner are folded in).
    if data.get("colors"):
        options.colors = max(2, min(256, int(data["colors"])))
    if data.get("max_fps"):
        options.max_fps = max(1.0, min(30.0, float(data["max_fps"])))
    return options


# Where « Alléger » keeps the GIFs it replaced (not listed in the gallery).
BACKUP_FOLDER = ".backup"


def lighten_gif(path: str, fuzz: int = DEFAULT_FUZZ) -> dict:
    """Optimise a gallery GIF the way new ones are made, keeping its timing.

    Nearly identical frames are merged and frames closer than ~30 ms folded
    together (their delays add up, so the animation lasts as long), then
    later frames only hold what changed, within the colour tolerance. The
    result replaces the GIF only when it is at least 10 % lighter and saves
    at least one 4 KB Bluetooth packet; the old one is kept in ``.backup``.
    Returns old/new sizes and frame counts, and whether it was replaced.
    """
    old = os.path.getsize(path)
    with Image.open(path) as image:
        frames = [(frame.convert("RGB"), max(20, int(frame.info.get("duration") or 100)))
                  for frame in ImageSequence.Iterator(image)]
    report = {"old": old, "new": old, "frames_before": len(frames), "frames_after": len(frames), "replaced": False,
              "duration_ms": sum(ms for _, ms in frames)}
    if len(frames) < 2:
        return report
    result = encode_frames(frames, encode_options({"fuzz": fuzz}, frames[0][0].width))
    data = result.data
    report.update(new=len(data), frames_after=result.frames)
    duration = sum(ms for _, ms in frames)
    if result.duration_ms != duration:
        # Never change how long the animation lasts.
        report["new"] = old
        return report
    if len(data) > old * 0.9 or math.ceil(len(data) / PACKET_BYTES) >= math.ceil(old / PACKET_BYTES):
        return report
    folder = os.path.dirname(path)
    backup = os.path.join(folder, BACKUP_FOLDER)
    os.makedirs(backup, exist_ok=True)
    shutil.copy2(path, os.path.join(backup, os.path.basename(path)))
    temporary = f"{path}.tmp"
    with open(temporary, "wb") as handle:
        handle.write(data)
    os.replace(temporary, path)
    report["replaced"] = True
    return report


def still_gif(png: bytes) -> bytes:
    """One-frame device GIF from a PNG still (live preview on the panel)."""
    with Image.open(io.BytesIO(png)) as image:
        frame = image.convert("RGB")
    return frames_to_gif([frame], 1000)


def list_gallery(folder: str, meta: dict[str, dict]) -> list[dict]:
    """Gallery items, newest first. Any GIF dropped in the folder is listed."""
    items = []
    if not os.path.isdir(folder):
        return items
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if not name.lower().endswith(".gif") or not os.path.isfile(path):
            continue
        info = meta.get(name, {})
        try:
            with Image.open(path) as image:
                frames, size = getattr(image, "n_frames", 1), image.size
        except OSError:
            continue
        items.append({
            "file": name,
            "title": info.get("title") or os.path.splitext(name)[0],
            "size_bytes": os.path.getsize(path),
            "frames": frames,
            "width": size[0],
            "height": size[1],
            "modified": os.path.getmtime(path),
            "favorite": bool(info.get("favorite")),
            # Workspace clip it was made from (originals stay in the browser).
            "clip": info.get("clip"),
            "source": info.get("source"),
            "folder": info.get("folder") or "",
            # Who sent it: the browser's name in the Studio and the Home Assistant user.
            "device": info.get("device"),
            "user": info.get("user"),
        })
    items.sort(key=lambda item: item["modified"], reverse=True)
    return items


# ---------------------------------------------------------------------------
# Home Assistant glue
# ---------------------------------------------------------------------------

class Frame:
    """What one display runs on its own: a routine and a day schedule."""

    def __init__(self, studio: "Studio", entry_id: str) -> None:
        hass = studio.hass
        def routine_status(status: dict) -> None:
            hass.bus.async_fire(ROUTINE_EVENT, {**status, "entry_id": entry_id})
            _log_routine(studio, self.runner, entry_id, status)

        self.runner = RoutineRunner(hass, studio.gallery_path, lambda: _coordinator(hass, entry_id), routine_status,
                                    studio.routine_files, weather=studio.weather,
                                    busy=lambda: studio.display_busy(entry_id))
        self.scheduler = Scheduler(
            hass, self.runner, lambda: studio.routines, lambda: _coordinator(hass, entry_id),
            lambda status: hass.bus.async_fire(SCHEDULE_EVENT, {**status, "entry_id": entry_id}),
        )

    @property
    def data(self) -> dict:
        return {"active": self.runner.active_id, "schedule": self.scheduler.schedule}


def _file_stats(path: str) -> dict:
    """Size and frame-by-frame make-up of a GIF, for the log."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return {}
    # The summary only: routines show a GIF every few minutes, and the
    # frame-by-frame list is already in the entry of its encoding.
    stats = gif_stats(data)
    stats.pop("frames", None)
    return {"size_bytes": len(data), "gif": stats}


def _display_name(hass: HomeAssistant, entry_id: str | None) -> str | None:
    return next((c.entry.title for c in _coordinators(hass) if c.entry.entry_id == entry_id), None)


def _log_routine(studio: "Studio", runner: RoutineRunner, entry_id: str, status: dict) -> None:
    """A routine's GIF changes, carousel uploads and errors."""
    routine = runner.routine or {}
    name = routine.get("name")
    where = {"display": _display_name(studio.hass, entry_id), "routine": name, "mode": routine.get("mode")}
    state = status.get("state")
    if routine.get("mode") == "weather":
        # The time goes out every minute: only the forecasts and the errors are logged.
        weather = status.get("weather") or {}
        if state == "updated":
            rain = f", pluie {weather['rain']} %" if weather.get("rain") is not None else ""
            temperature = f"{round(weather['temperature'])}°" if weather.get("temperature") is not None else "?"
            studio.journal.add("routine", f"Routine « {name} » : météo de {weather.get('place')} à jour, "
                                          f"{temperature} {weather.get('condition')}{rain}", weather=weather, **where)
        elif status.get("message") and status.get("message") != getattr(runner, "logged_message", None):
            # Once: a forecast that fails is asked again every few minutes.
            studio.journal.add("error", f"Routine « {name} » : {status['message']}", **where)
        runner.logged_message = status.get("message")
        return
    if state == "sending" and status.get("current"):
        studio.journal.add("routine", f"Routine « {name} » : envoi de {status['current']}",
                           file=status["current"], upcoming=status.get("upcoming"), **where)
    elif state == "sending":
        studio.journal.add("routine", f"Routine « {name} » : envoi du carrousel", files=status.get("carousel"), **where)
    elif state == "error":
        studio.journal.add("error", f"Routine « {name} » : {status.get('message')}", **where)

    def stop(self) -> None:
        self.runner.stop(reset_display=False)
        self.scheduler.stop()


class Studio:
    """Gallery folder, metadata, the displays' routines and the live-preview queue."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.media_root = hass.config.media_dirs.get("local") or hass.config.path("media")
        self.folder = os.path.join(self.media_root, GALLERY_FOLDER)
        self._store: Store[dict] = Store(hass, 1, _STORE_KEY)
        self.meta: dict[str, dict] = {}
        self.frames: dict[str, Frame] = {}
        self._live_png: tuple[bytes, str | None] | None = None
        self._live_task = None
        # Store files fetched this run, by URL. Only URLs the store listed are
        # fetched (with their names), so the panel cannot make Home Assistant
        # download anything else.
        # What the Pi does for the panel, listed in its « File » tab: sends to
        # the displays (one at a time per display) and gallery re-encodings.
        self.jobs: dict[str, dict] = {}
        self.display_locks: dict[str, asyncio.Lock] = {}
        # Editor previews: one encodes at a time, and one asked before the
        # last request of its editor is dropped (each costs the Pi up to a
        # minute, which slowed the sends to the displays).
        self.preview_lock = asyncio.Lock()
        self.preview_seq: dict[str, int] = {}
        self._job_seq = 0
        self.store_files: dict[str, bytes] = {}
        self.store_urls: dict[str, str] = {}
        # Store animations starred in the panel: url -> what the card shows.
        self.store_favorites: dict[str, dict] = {}
        # What happened, for the panel's 📜 tab.
        self.journal = Journal(hass)
        self.collections: dict[str, dict] = {}
        self.hidden_folders: list[str] = []
        # Forecasts of the weather views, shared by the routines and the panel's preview.
        self.weather = WeatherService(hass)

    async def async_load(self) -> None:
        await self.journal.async_load()
        data = await self._store.async_load() or {}
        self.meta = data.get("items", {})
        self.routines: dict[str, dict] = data.get("routines", {})
        # The Pixel Studio workspace without its media: originals (name, size,
        # where they were imported) and clips (settings), shared by browsers.
        self.workspace: dict[str, dict] = data.get("workspace") or {"originals": {}, "clips": {}}
        # Ids deleted by one browser, so another one does not bring them back.
        self.workspace.setdefault("deleted", {})
        self.store_favorites = data.get("store_favorites", {})
        # Custom lists of gallery GIFs picked from any folders (like Batocera's
        # collections): id -> {id, name, files}. A GIF can be in several.
        self.collections: dict[str, dict] = data.get("collections", {})
        # Folders kept out of sight in the panel until shown again.
        self.hidden_folders: list[str] = data.get("hidden_folders", [])
        # Starred animations can be shown and imported without listing their page again.
        self.store_urls.update((url, item.get("name") or "store") for url, item in self.store_favorites.items())
        if self.workspace.get("trash") != 1:
            # Deletions used to be final and spread at once, so an accidental
            # "clear" also erased other devices. Browsers now use a trash;
            # forget the old deletions once so devices can send back what they
            # still hold.
            self.workspace["deleted"] = {}
            self.workspace["trash"] = 1
        # Routine and schedule of each display, kept while it is not set up.
        self.frame_state: dict[str, dict] = data.get("frames", {})
        if "frames" not in data and (data.get("active") or data.get("schedule")):
            # Saved before several displays: it goes to the first one.
            self.frame_state[_LEGACY_FRAME] = {"active": data.get("active"), "schedule": data.get("schedule")}
        # The display the panel drives when a command names none.
        self.selected: str | None = data.get("selected")
        # Folders made by hand, kept while still empty.
        self.workspace.setdefault("folders", [])
        await self.hass.async_add_executor_job(os.makedirs, self.folder, 0o755, True)
        self.sync_frames()

    def save_meta(self) -> None:
        self._store.async_delay_save(lambda: {
            "items": self.meta, "routines": self.routines,
            "frames": {**self.frame_state, **{key: frame.data for key, frame in self.frames.items()}},
            "selected": self.selected,
            "workspace": self.workspace,
            "store_favorites": self.store_favorites,
            "collections": self.collections,
            "hidden_folders": self.hidden_folders,
        }, 1.0)

    @callback
    def sync_frames(self) -> None:
        """Give each display set up its routine runner and schedule."""
        entry_ids = [c.entry.entry_id for c in _coordinators(self.hass)]
        for entry_id in [key for key in self.frames if key not in entry_ids]:
            frame = self.frames.pop(entry_id)
            self.frame_state[entry_id] = frame.data
            frame.stop()
        for entry_id in entry_ids:
            if entry_id in self.frames:
                continue
            state = self.frame_state.pop(entry_id, None) or self.frame_state.pop(_LEGACY_FRAME, None) or {}
            frame = self.frames[entry_id] = Frame(self, entry_id)
            frame.scheduler.schedule = state.get("schedule") or {"enabled": False, "blocks": []}
            active = self.routines.get(state.get("active") or "")
            if active:
                frame.runner.start(active, delay=RESUME_DELAY)
            frame.scheduler.start()

    def frame(self, entry_id: str | None = None) -> Frame:
        """The named display's routine and schedule (else the selected display's)."""
        key = _coordinator(self.hass, entry_id).entry.entry_id
        if key not in self.frames:
            self.sync_frames()
        return self.frames[key]

    def forget_files(self, files: list[str]) -> None:
        """Drop deleted GIFs from the routines and collections that listed them."""
        gone = set(files)
        for routine in self.routines.values():
            routine["files"] = [f for f in routine["files"] if f not in gone]
        for collection in self.collections.values():
            collection["files"] = [f for f in collection["files"] if f not in gone]

    def routine_files(self, routine: dict) -> list[str]:
        """An ensemble's GIFs: its collection's (as it is now) when it has one."""
        collection = self.collections.get(routine.get("collection") or "")
        return list(collection["files"]) if collection is not None else routine["files"]

    def display_busy(self, entry_id: str | None) -> bool:
        """Whether something is on its way to the display: a gallery GIF, the live preview, a message.

        The weather clock sends nothing then (it would cut in the middle of a
        GIF, or replace it before it is seen); it draws the time once it is free.
        """
        if any(job["kind"] == "display" and job.get("entry_id") in (entry_id, None) for job in self.jobs.values()):
            return True
        lock = self.display_locks.get(entry_id or "")
        if (lock and lock.locked()) or self._live_png is not None or (self._live_task and not self._live_task.done()):
            return True
        try:
            coordinator = _coordinator(self.hass, entry_id)
        except HomeAssistantError:
            return False
        return coordinator._device_lock.locked() or bool(getattr(coordinator, "_message_cfg", None))

    def add_job(self, kind: str, label: str, entry_id: str | None = None, state: str = "waiting") -> dict:
        self._job_seq += 1
        job = {"id": f"j{self._job_seq}", "kind": kind, "label": label, "entry_id": entry_id,
               "state": state, "created": time.time()}
        self.jobs[job["id"]] = job
        return job

    def store_file(self, url: str) -> str | None:
        """The gallery GIF already imported from this store URL, if any."""
        return next((file for file, info in self.meta.items() if info.get("store_url") == url), None)

    def gallery_path(self, file: str) -> str:
        if os.path.basename(file) != file or not file.lower().endswith(".gif"):
            raise HomeAssistantError(f"Invalid gallery file: {file}")
        return os.path.join(self.folder, file)

    def media_url(self, file: str) -> str:
        return "/media/local/" + os.path.relpath(
            self.gallery_path(file), self.media_root
        ).replace(os.sep, "/")

    @callback
    def queue_live(self, png: bytes, entry_id: str | None = None) -> None:
        """Show a still on the panel; while one is being sent, keep only the latest."""
        self._live_png = (png, entry_id)
        if self._live_task is None or self._live_task.done():
            self._live_task = self.hass.async_create_background_task(
                self._send_live(), f"{DOMAIN} studio live preview"
            )

    async def _send_live(self) -> None:
        while self._live_png is not None:
            (png, entry_id), self._live_png = self._live_png, None
            try:
                gif = await self.hass.async_add_executor_job(still_gif, png)
                await _coordinator(self.hass, entry_id)._upload_single(gif, label="live")
                if self._live_png is None:  # the panel clears its "live" bar
                    self.hass.bus.async_fire(TRANSFER_EVENT, {"file": "live", "state": "done", "entry_id": entry_id})
            except (HomeAssistantError, OSError, ValueError) as err:
                self.hass.bus.async_fire(TRANSFER_EVENT, {
                    "file": "live", "state": "error", "message": str(err), "entry_id": entry_id,
                })


_LEGACY_FRAME = "_legacy"


def _coordinators(hass: HomeAssistant) -> list:
    from .coordinator import IDotMatrixCoordinator

    return [value for value in hass.data.get(DOMAIN, {}).values() if isinstance(value, IDotMatrixCoordinator)]


def _coordinator(hass: HomeAssistant, entry_id: str | None = None):
    """The named display, else the one selected in the panel, else the first."""
    coordinators = {c.entry.entry_id: c for c in _coordinators(hass)}
    if entry_id is not None:
        if entry_id not in coordinators:
            raise HomeAssistantError(f"Unknown iDotMatrix display: {entry_id}")
        return coordinators[entry_id]
    studio = hass.data.get(DOMAIN, {}).get("_studio")
    selected = coordinators.get(studio.selected) if studio else None
    if selected is not None:
        return selected
    if coordinators:
        return next(iter(coordinators.values()))
    raise HomeAssistantError("No iDotMatrix display is set up")


def _studio(hass: HomeAssistant) -> Studio:
    return hass.data[DOMAIN]["_studio"]


def _screen_size(hass: HomeAssistant, entry_id: str | None = None) -> int:
    return int(_coordinator(hass, entry_id).text_settings.get("screen_size", 32))


def _seconds_per_packet(hass: HomeAssistant, entry_id: str | None = None) -> float | None:
    try:
        return _coordinator(hass, entry_id).conn.seconds_per_packet
    except HomeAssistantError:
        return None


async def async_setup_studio(hass: HomeAssistant, static_url: str) -> None:
    """Register the panel, HTTP view and websocket commands once per run."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if "_studio" in domain_data:
        domain_data["_studio"].sync_frames()  # another display was set up
        return
    studio = Studio(hass)
    await studio.async_load()
    domain_data["_studio"] = studio

    from .client.connectionManager import ConnectionManager

    @callback
    def transfer_progress(sent: int, total: int, address: str | None) -> None:
        display = next((c for c in _coordinators(hass) if c.conn.address == address), None)
        for job in studio.jobs.values():
            if job["kind"] == "display" and job["state"] == "sending" and display and job["entry_id"] == display.entry.entry_id:
                job.update(sent=sent, total=total)
        # Name what is being sent: a still queued behind a GIF must not take its progress.
        hass.bus.async_fire(TRANSFER_EVENT, {
            "state": "progress", "sent": sent, "total": total,
            "entry_id": display.entry.entry_id if display else None,
            "file": display.conn.transfer_label if display else None,
        })

    ConnectionManager.transfer_listener = transfer_progress

    @callback
    def transfer_log(address: str | None, label: str | None, report: dict) -> None:
        if label == SEND_LABEL and not report.get("error"):
            return  # the weather clock's one packet a minute would fill the log
        display = next((c for c in _coordinators(hass) if c.conn.address == address), None)
        name = display.entry.title if display else address
        packets = [p for attempt in report["attempts"] for p in attempt["packets"]]
        waits = sorted(p[1] for p in packets if p[1] is not None)
        modes = " puis ".join(a["mode"] for a in report["attempts"]) or "aucun"
        outcome = f"échec ({report['error']})" if report.get("error") else f"en {report['seconds']} s"
        studio.journal.add(
            "transfer",
            f"{label or 'fichier'} → {name} : {report['packets']} paquets, "
            f"{round(report['bytes'] / 1024, 1)} Ko {outcome} (écriture {modes})",
            display=name, file=label, **report,
            write_s=round(sum(p[0] or 0 for p in packets), 3),
            wait_s=round(sum(waits), 3),
            wait_median_s=waits[len(waits) // 2] if waits else None,
        )

    ConnectionManager.transfer_log = transfer_log
    studio.journal.capture_warnings(__package__)
    if not domain_data.get("_studio_view"):
        hass.http.register_view(StudioEncodeView())
        domain_data["_studio_view"] = True
    for command in (ws_info, ws_gallery, ws_delete, ws_favorite, ws_display, ws_live,
                    ws_routines, ws_routine_save, ws_routine_delete, ws_routine_start, ws_routine_next, ws_routine_stop,
                    ws_status, ws_select, ws_screen, ws_schedule_save, ws_workspace, ws_workspace_sync,
                    ws_organize, ws_lighten, ws_jobs, ws_job_cancel,
                    ws_log, ws_log_add, ws_log_clear, ws_write_pause,
                    ws_collection_save, ws_collection_delete, ws_folder_hidden,
                    ws_weather_sources, ws_weather_geocode, ws_weather_preview, ws_weather_calendars_refresh):
        websocket_api.async_register_command(hass, command)
    try:  # the Store tab is optional: left out of public copies of the integration
        from . import store_ws
    except ImportError:
        store_ws = None
    domain_data["_store"] = store_ws is not None
    for command in store_ws.COMMANDS if store_ws else ():
        websocket_api.async_register_command(hass, command)
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL,
        webcomponent_name=PANEL_COMPONENT,
        sidebar_title="Pixel Studio",
        sidebar_icon="mdi:led-strip-variant",
        module_url=f"{static_url}/idotmatrix-studio.js?v={int(time.time())}",
        require_admin=True,
    )


@callback
def async_unload_studio(hass: HomeAssistant) -> None:
    """Remove the panel when the last display is removed."""
    from homeassistant.components import frontend

    from .client.connectionManager import ConnectionManager

    studio = hass.data.get(DOMAIN, {}).pop("_studio", None)
    if studio is not None:
        for frame in studio.frames.values():
            frame.stop()
        frontend.async_remove_panel(hass, PANEL_URL)
        ConnectionManager.transfer_listener = None
        ConnectionManager.transfer_log = None
        studio.journal.release(__package__)


async def latest_preview(studio: "Studio", key: str, work):
    """Run an editor preview's ``work()`` unless a newer one of that editor came first.

    Previews encode one at a time; one still waiting when its editor asks
    again is dropped (returns None) instead of costing the Pi its encode.
    """
    seq = studio.preview_seq[key] = studio.preview_seq.get(key, 0) + 1
    async with studio.preview_lock:
        if studio.preview_seq.get(key) != seq:
            return None
        return await work()


class StudioEncodeView(HomeAssistantView):
    """Encode frames prepared by the browser; optionally save and display them.

    Multipart form: ``sheet`` (PNG grid of frames, row by row) and ``meta``
    (JSON: durations, size, columns, options, optional title/replace, display). Plain HTTP
    rather than websocket: long clips exceed the websocket message limit.
    """

    url = ENCODE_URL
    name = "api:idotmatrix:studio:encode"

    async def post(self, request: web.Request) -> web.Response:
        hass = request.app[KEY_HASS]
        if not request["hass_user"].is_admin:
            return self.json_message("Admin required", 403)
        form = await request.post()
        try:
            meta = json.loads(form["meta"])
            upload = form["sheet"].file
            studio = _studio(hass)
            replace = meta.get("replace")
            if replace:
                studio.gallery_path(replace)

            timings = {}

            def run():
                started = time.monotonic()
                size = int(meta.get("size") or _screen_size(hass, meta.get("entry_id")))
                sheet = upload.read()
                frames = frames_from_sheet(sheet, meta["durations"], size, int(meta.get("columns", 1)))
                timings.update(sheet_bytes=len(sheet), read_s=round(time.monotonic() - started, 3))
                started = time.monotonic()
                result = encode_frames(frames, encode_options(meta.get("options", {}), size))
                timings["encode_s"] = round(time.monotonic() - started, 3)
                file = None
                if meta.get("title"):
                    file = unique_file(studio.folder, slugify_name(meta["title"]), keep=replace)
                    with open(os.path.join(studio.folder, file), "wb") as handle:
                        handle.write(result.data)
                    if replace and replace != file and os.path.exists(studio.gallery_path(replace)):
                        os.remove(studio.gallery_path(replace))
                return result, file

            if not meta.get("title"):
                done = await latest_preview(studio, str(meta.get("preview") or meta.get("device") or ""),
                                            lambda: hass.async_add_executor_job(run))
                if done is None:
                    return self.json({"superseded": True})
                result, file = done
            else:
                job = studio.add_job("encode", meta["title"], meta.get("entry_id"), "running")
                try:
                    result, file = await hass.async_add_executor_job(run)
                finally:
                    studio.jobs.pop(job["id"], None)
        except (HomeAssistantError, KeyError, OSError, ValueError) as err:
            if "_studio" in hass.data.get(DOMAIN, {}):
                _studio(hass).journal.add("error", f"Encodage refusé : {err}")
            return self.json_message(str(err), 400)

        durations = meta["durations"]
        stats = gif_stats(result.data)
        if not file:
            stats.pop("frames", None)  # editor previews come at every change: the summary is enough
        studio.journal.add(
            "encode" if file else "preview",
            f"{meta.get('title') or 'aperçu'} : {len(durations)} images → {result.frames}, "
            f"{round(result.size_bytes / 1024, 1)} Ko, {result.colors} couleurs, encodé en {timings['encode_s']} s",
            title=meta.get("title"), file=file, source=meta.get("source"), device=meta.get("device"),
            options=meta.get("options", {}), clip_info=meta.get("log"),
            frames_in=len(durations), duration_in_ms=sum(durations),
            frames_out=result.frames, duration_out_ms=result.duration_ms, colors=result.colors,
            frame_step=result.frame_step, size_bytes=result.size_bytes, **timings, gif=stats,
        )
        if file:
            previous = studio.meta.pop(replace or "", {})
            studio.meta[file] = {
                "title": meta["title"], "favorite": previous.get("favorite", False),
                "clip": meta.get("clip"), "source": meta.get("source"),
                # A GIF moved in the gallery stays there; a new one follows its original.
                "folder": previous.get("folder") or (meta.get("folder") or "").strip(),
                "device": str(meta.get("device") or "")[:40] or None,
                "user": request["hass_user"].name,
            }
            studio.save_meta()
            if meta.get("display"):
                _start_display(hass, studio.gallery_path(file), meta.get("entry_id"))
        return self.json({
            "file": file,
            "gif": base64.b64encode(result.data).decode(),
            "size_bytes": result.size_bytes,
            "frames": result.frames,
            "duration_ms": result.duration_ms,
            "colors": result.colors,
            "frame_step": result.frame_step,
            "estimate_s": estimate_seconds(result.size_bytes, _seconds_per_packet(hass, meta.get("entry_id"))),
        })


def _error(connection, msg, err: Exception) -> None:
    connection.send_error(msg["id"], "studio_error", str(err))


# Commands acting on a display take its entry id; without one they act on
# the display selected in the panel.
_DISPLAY = vol.Optional("entry_id")


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/info", _DISPLAY: str})
@websocket_api.require_admin
@callback
def ws_info(hass, connection, msg):
    connection.send_result(msg["id"], {
        "screen_size": _screen_size(hass, msg.get("entry_id")),
        "seconds_per_packet": _seconds_per_packet(hass, msg.get("entry_id")) or DEFAULT_SECONDS_PER_PACKET,
        "transfer_event": TRANSFER_EVENT,
        "routine_event": ROUTINE_EVENT,
        "schedule_event": SCHEDULE_EVENT,
        "log_event": LOG_EVENT,
        "workspace_event": WORKSPACE_EVENT,
        "encode_url": ENCODE_URL,
        "max_frames": MAX_FRAMES,
        "store": bool(hass.data.get(DOMAIN, {}).get("_store")),
    })


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/gallery"})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_gallery(hass, connection, msg):
    studio = _studio(hass)
    items = await hass.async_add_executor_job(list_gallery, studio.folder, studio.meta)
    spp = _seconds_per_packet(hass)
    for item in items:
        item["url"] = studio.media_url(item["file"])
        item["estimate_s"] = estimate_seconds(item["size_bytes"], spp)
    connection.send_result(msg["id"], {
        "items": items, "collections": list(studio.collections.values()), "hidden_folders": studio.hidden_folders,
    })


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/collection_save",
    # Not "id": that is the websocket message's own number.
    vol.Required("collection_id"): vol.All(str, vol.Length(min=1, max=64)),
    vol.Optional("name"): vol.All(str, vol.Length(min=1, max=60)),
    # GIFs added to its end (once) and removed from it.
    vol.Optional("add", default=list): [str],
    vol.Optional("remove", default=list): [str],
})
@websocket_api.require_admin
@callback
def ws_collection_save(hass, connection, msg):
    """Create or rename a collection, and add or remove GIFs."""
    studio = _studio(hass)
    collection_id = msg["collection_id"]
    collection = studio.collections.get(collection_id)
    if collection is None:
        if not msg.get("name"):
            _error(connection, msg, HomeAssistantError("A new collection needs a name"))
            return
        collection = studio.collections[collection_id] = {"id": collection_id, "name": msg["name"], "files": []}
    if msg.get("name"):
        collection["name"] = msg["name"].strip()
    gone = set(msg.get("remove", []))
    files = [f for f in collection["files"] if f not in gone]
    files += [f for f in dict.fromkeys(msg.get("add", [])) if f not in files and _in_gallery(studio, f)]
    collection["files"] = files
    studio.save_meta()
    connection.send_result(msg["id"], collection)


def _in_gallery(studio: Studio, file: str) -> bool:
    try:
        return os.path.isfile(studio.gallery_path(file))
    except HomeAssistantError:
        return False


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/collection_delete",
    vol.Required("collection_id"): str,
})
@websocket_api.require_admin
@callback
def ws_collection_delete(hass, connection, msg):
    """Delete a collection (its GIFs stay); ensembles using it keep a copy of its list."""
    studio = _studio(hass)
    collection = studio.collections.pop(msg["collection_id"], None)
    if collection is not None:
        for routine in studio.routines.values():
            if routine.get("collection") == msg["collection_id"]:
                routine["files"] = list(collection["files"])
                routine["collection"] = None
    studio.save_meta()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/folder_hidden",
    vol.Required("folder"): vol.All(str, vol.Length(min=1, max=60)),
    vol.Required("hidden"): bool,
    # The folder's new name when it is renamed (it stays hidden).
    vol.Optional("rename"): vol.All(str, vol.Length(max=60)),
})
@websocket_api.require_admin
@callback
def ws_folder_hidden(hass, connection, msg):
    """Hide a folder in the panel (its GIFs leave « Tous ») or show it again."""
    studio = _studio(hass)
    hidden = [f for f in studio.hidden_folders if f != msg["folder"]]
    if msg["hidden"]:
        hidden.append((msg.get("rename") or msg["folder"]).strip())
    studio.hidden_folders = sorted({f for f in hidden if f})
    studio.save_meta()
    connection.send_result(msg["id"], {"hidden_folders": studio.hidden_folders})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/delete",
    vol.Required("file"): str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_delete(hass, connection, msg):
    studio = _studio(hass)
    try:
        path = studio.gallery_path(msg["file"])
        await hass.async_add_executor_job(lambda: os.path.exists(path) and os.remove(path))
    except (HomeAssistantError, OSError) as err:
        _error(connection, msg, err)
        return
    studio.meta.pop(msg["file"], None)
    studio.forget_files([msg["file"]])
    studio.save_meta()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/organize",
    vol.Required("files"): vol.All([str], vol.Length(min=1, max=1000)),
    vol.Optional("folder"): vol.Any(None, vol.All(str, vol.Length(max=60))),
    vol.Optional("favorite"): bool,
    vol.Optional("delete", default=False): bool,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_organize(hass, connection, msg):
    """Move several gallery GIFs to a folder, (un)favourite or delete them at once.

    Folders are labels kept with the gallery metadata: the files stay where
    routines and the media browser expect them.
    """
    studio = _studio(hass)
    try:
        paths = [studio.gallery_path(file) for file in msg["files"]]
    except HomeAssistantError as err:
        _error(connection, msg, err)
        return
    if msg["delete"]:
        def remove() -> None:
            for path in paths:
                if os.path.exists(path):
                    os.remove(path)

        try:
            await hass.async_add_executor_job(remove)
        except OSError as err:
            _error(connection, msg, err)
            return
        for file in msg["files"]:
            studio.meta.pop(file, None)
        studio.forget_files(msg["files"])
    else:
        for file in msg["files"]:
            info = studio.meta.setdefault(file, {})
            if "folder" in msg:
                info["folder"] = (msg["folder"] or "").strip()
            if "favorite" in msg:
                info["favorite"] = msg["favorite"]
    studio.save_meta()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/lighten",
    vol.Required("files"): vol.All([str], vol.Length(min=1, max=1000)),
    vol.Optional("fuzz", default=DEFAULT_FUZZ): vol.All(int, vol.Range(min=0, max=64)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_lighten(hass, connection, msg):
    """Optimise gallery GIFs: fewer frames, only what changes (see lighten_gif)."""
    studio = _studio(hass)
    try:
        paths = [studio.gallery_path(file) for file in msg["files"]]
    except HomeAssistantError as err:
        _error(connection, msg, err)
        return
    results = []
    job = studio.add_job("lighten", f"{len(paths)} GIF", state="running")
    job.update(sent=0, total=len(paths))
    try:
        for file, path in zip(msg["files"], paths):
            if job.get("cancelled"):
                break
            try:
                report = await hass.async_add_executor_job(lighten_gif, path, msg["fuzz"])
            except (OSError, ValueError) as err:
                results.append({"file": file, "error": str(err)})
                studio.journal.add("error", f"Optimiser {file} : {err}", file=file)
                continue
            finally:
                job["sent"] += 1
            results.append({"file": file, **report})
            # Kept: what is left to gain would show (fewer colours or images, a shorter clip).
            kept = "" if report["replaced"] else " (rien à gagner sans perte visible, gardé tel quel)"
            studio.journal.add(
                "lighten",
                f"Optimiser {file} : {round(report['duration_ms'] / 1000, 1)} s, "
                f"{report['frames_before']} → {report['frames_after']} images, "
                f"{round(report['old'] / 1024, 1)} → {round(report['new'] / 1024, 1)} Ko{kept}",
                file=file, fuzz=msg["fuzz"], **report)
    finally:
        studio.jobs.pop(job["id"], None)
    connection.send_result(msg["id"], {"results": results})


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/jobs"})
@websocket_api.require_admin
@callback
def ws_jobs(hass, connection, msg):
    """What the Pi is doing for the panel, and the routines running."""
    studio = _studio(hass)
    names = {c.entry.entry_id: c.entry.title for c in _coordinators(hass)}
    jobs = [{**{k: v for k, v in job.items() if k != "task"}, "display": names.get(job.get("entry_id"))}
            for job in studio.jobs.values()]
    routines = [
        {"entry_id": entry_id, "display": names.get(entry_id), "name": frame.runner.routine.get("name"),
         "status": frame.runner.status}
        for entry_id, frame in studio.frames.items() if frame.runner.routine
    ]
    connection.send_result(msg["id"], {"jobs": jobs, "routines": routines})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/job_cancel",
    vol.Required("job_id"): str,
})
@websocket_api.require_admin
@callback
def ws_job_cancel(hass, connection, msg):
    """Cancel a job: a waiting send goes away, a running one stops before its next packet."""
    studio = _studio(hass)
    job = studio.jobs.get(msg["job_id"])
    if job is None:
        _error(connection, msg, HomeAssistantError("Already finished"))
        return
    job["cancelled"] = True
    if job["kind"] == "display":
        if job["state"] == "waiting":
            job["task"].cancel()
        else:
            try:
                _coordinator(hass, job["entry_id"]).conn.abort_requested = True
            except HomeAssistantError:
                pass
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/favorite",
    vol.Required("file"): str,
    vol.Required("favorite"): bool,
})
@websocket_api.require_admin
@callback
def ws_favorite(hass, connection, msg):
    studio = _studio(hass)
    try:
        studio.gallery_path(msg["file"])
    except HomeAssistantError as err:
        _error(connection, msg, err)
        return
    studio.meta.setdefault(msg["file"], {})["favorite"] = msg["favorite"]
    studio.save_meta()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/display",
    vol.Required("file"): str,
    _DISPLAY: str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_display(hass, connection, msg):
    """Start sending a gallery GIF; progress arrives as transfer events."""
    studio = _studio(hass)
    try:
        path = studio.gallery_path(msg["file"])
        size = await hass.async_add_executor_job(os.path.getsize, path)
    except (HomeAssistantError, OSError) as err:
        _error(connection, msg, err)
        return
    _start_display(hass, path, msg.get("entry_id"))
    connection.send_result(msg["id"], {
        "estimate_s": estimate_seconds(size, _seconds_per_packet(hass, msg.get("entry_id"))),
    })


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/live",
    vol.Required("png"): str,
    _DISPLAY: str,
})
@websocket_api.require_admin
@callback
def ws_live(hass, connection, msg):
    """Mirror a still of the frame being edited on the display."""
    try:
        png = base64.b64decode(msg["png"].split(",")[-1])
    except ValueError as err:
        _error(connection, msg, err)
        return
    _studio(hass).queue_live(png, msg.get("entry_id"))
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/routines", _DISPLAY: str})
@websocket_api.require_admin
@callback
def ws_routines(hass, connection, msg):
    studio = _studio(hass)
    try:
        status = studio.frame(msg.get("entry_id")).runner.status
    except HomeAssistantError:
        status = {"active": None}
    connection.send_result(msg["id"], {"routines": list(studio.routines.values()), "status": status})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/routine_save",
    vol.Required("routine"): dict,
})
@websocket_api.require_admin
@callback
def ws_routine_save(hass, connection, msg):
    studio = _studio(hass)
    try:
        routine = ROUTINE_SCHEMA(msg["routine"])
        for file in routine["files"]:
            studio.gallery_path(file)
        if routine.get("collection") and routine["collection"] not in studio.collections:
            raise HomeAssistantError("Unknown collection")
    except (vol.Invalid, HomeAssistantError) as err:
        _error(connection, msg, err)
        return
    studio.routines[routine["id"]] = routine
    for frame in studio.frames.values():
        if frame.runner.active_id == routine["id"]:
            # Apply the new settings right away: a weather view without starting over (live).
            if not frame.runner.update(routine):
                frame.runner.start(routine)
    studio.save_meta()
    connection.send_result(msg["id"], routine)


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/routine_delete",
    vol.Required("routine_id"): str,
})
@websocket_api.require_admin
@callback
def ws_routine_delete(hass, connection, msg):
    studio = _studio(hass)
    for frame in studio.frames.values():
        if frame.runner.active_id == msg["routine_id"]:
            frame.runner.stop()
    studio.routines.pop(msg["routine_id"], None)
    studio.save_meta()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/routine_start",
    vol.Required("routine_id"): str,
    _DISPLAY: str,
})
@websocket_api.require_admin
@callback
def ws_routine_start(hass, connection, msg):
    studio = _studio(hass)
    routine = studio.routines.get(msg["routine_id"])
    try:
        if routine is None:
            raise HomeAssistantError("Unknown routine")
        frame = studio.frame(msg.get("entry_id"))
    except HomeAssistantError as err:
        _error(connection, msg, err)
        return
    # Turning an ensemble on by hand is the « Manuel » mode: the planning waits
    # until the panel switches back to « Planning » (it no longer takes over at
    # its next slot).
    if frame.scheduler.schedule.get("enabled"):
        frame.scheduler.update({**frame.scheduler.schedule, "enabled": False})
        studio.journal.add("schedule", "Mode Manuel : le planning attend le retour au mode Planning")
    frame.runner.start(routine)
    studio.save_meta()
    studio.journal.add("routine", f"Routine « {routine['name']} » lancée à la main", routine=routine)
    connection.send_result(msg["id"], frame.runner.status)


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/routine_next",
    vol.Optional("file"): str,  # one of the routine's GIFs, else the next drawn
    _DISPLAY: str,
})
@websocket_api.require_admin
@callback
def ws_routine_next(hass, connection, msg):
    try:
        studio = _studio(hass)
        if not studio.frame(msg.get("entry_id")).runner.skip(msg.get("file")):
            raise HomeAssistantError("Aucune routine pilotée par Home Assistant ne tourne sur ce cadre avec ce GIF")
    except HomeAssistantError as err:
        _error(connection, msg, err)
        return
    studio.journal.add("routine", f"⏭ {msg.get('file') or 'GIF suivant'} demandé", file=msg.get("file"))
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/routine_stop", _DISPLAY: str})
@websocket_api.require_admin
@callback
def ws_routine_stop(hass, connection, msg):
    studio = _studio(hass)
    try:
        studio.frame(msg.get("entry_id")).runner.stop()
        studio.journal.add("routine", "Routine arrêtée à la main")
    except HomeAssistantError as err:
        _error(connection, msg, err)
        return
    studio.save_meta()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/write_pause",
    # Pause after each 509-byte Bluetooth write without response, in ms; omitted: just read it.
    vol.Optional("ms"): vol.All(vol.Coerce(float), vol.Range(min=0, max=50)),
    # A packet's writes handed to the stack at once instead of one by one.
    vol.Optional("burst"): bool,
})
@websocket_api.require_admin
@callback
def ws_write_pause(hass, connection, msg):
    """Tune the Bluetooth write pace for every display until Home Assistant restarts (speed tests)."""
    from .client.connectionManager import ConnectionManager

    if "ms" in msg:
        ConnectionManager.WRITE_PAUSE_S = msg["ms"] / 1000
        _studio(hass).journal.add("setting", f"Pause entre écritures Bluetooth : {msg['ms']} ms", write_pause_ms=msg["ms"])
    if "burst" in msg:
        ConnectionManager.WRITE_BURST = msg["burst"]
        _studio(hass).journal.add("setting", f"Écritures Bluetooth en rafale : {'oui' if msg['burst'] else 'non'}",
                                  write_burst=msg["burst"])
    connection.send_result(msg["id"], {"ms": ConnectionManager.WRITE_PAUSE_S * 1000, "burst": ConnectionManager.WRITE_BURST})


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/log"})
@websocket_api.require_admin
@callback
def ws_log(hass, connection, msg):
    connection.send_result(msg["id"], {"entries": list(_studio(hass).journal.entries)})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/log_add",
    # What a browser did: reading an original, extracting frames, sending them...
    vol.Required("entries"): vol.All([{
        vol.Required("kind"): vol.All(str, vol.Length(max=32)),
        vol.Required("msg"): vol.All(str, vol.Length(max=500)),
        vol.Optional("data"): dict,
    }], vol.Length(max=100)),
})
@websocket_api.require_admin
@callback
def ws_log_add(hass, connection, msg):
    journal = _studio(hass).journal
    for entry in msg["entries"]:
        journal.add(entry["kind"], entry["msg"], source="browser", **entry.get("data", {}))
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/log_clear"})
@websocket_api.require_admin
@callback
def ws_log_clear(hass, connection, msg):
    _studio(hass).journal.clear()
    connection.send_result(msg["id"], {})


def _preview_entity(hass: HomeAssistant, coordinator) -> str | None:
    address = coordinator.conn.address
    if not address:
        return None
    return er.async_get(hass).async_get_entity_id("image", DOMAIN, f"{address}_preview")


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/status", _DISPLAY: str})
@websocket_api.require_admin
@callback
def ws_status(hass, connection, msg):
    """Everything the panel's status bar shows about a display, and the list of displays."""
    studio = _studio(hass)
    try:
        coordinator = _coordinator(hass, msg.get("entry_id"))
    except HomeAssistantError:
        coordinator = None
    frame = studio.frame(coordinator.entry.entry_id) if coordinator else None
    displays = []
    for value in _coordinators(hass):
        running = studio.frames.get(value.entry.entry_id)
        displays.append({
            "entry_id": value.entry.entry_id,
            "name": value.entry.title,
            "size": int(value.text_settings.get("screen_size", 32)),
            "connected": bool((value.data or {}).get("connected")),
            "screen_on": bool(value.text_settings.get("is_on", True)),
            "routine_name": ((running.runner.routine if running else None) or {}).get("name"),
        })
    connection.send_result(msg["id"], {
        "entry_id": coordinator.entry.entry_id if coordinator else None,
        "display": coordinator.entry.title if coordinator else None,
        "displays": displays,
        "connected": bool(coordinator and (coordinator.data or {}).get("connected")),
        "screen_on": bool(coordinator and coordinator.text_settings.get("is_on", True)),
        "preview_entity": _preview_entity(hass, coordinator) if coordinator else None,
        "routine": frame.runner.status if frame else {"active": None},
        "routine_name": ((frame.runner.routine if frame else None) or {}).get("name"),
        "schedule": frame.scheduler.schedule if frame else {"enabled": False, "blocks": []},
        "schedule_status": frame.scheduler.status if frame else {},
    })


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/select",
    vol.Required("entry_id"): str,
})
@websocket_api.require_admin
@callback
def ws_select(hass, connection, msg):
    """Make a display the one the panel drives (kept for every browser)."""
    studio = _studio(hass)
    try:
        _coordinator(hass, msg["entry_id"])
    except HomeAssistantError as err:
        _error(connection, msg, err)
        return
    studio.selected = msg["entry_id"]
    studio.save_meta()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/screen",
    vol.Required("on"): bool,
    _DISPLAY: str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_screen(hass, connection, msg):
    """Blank or wake the screen from the status bar."""
    from .client.modules.common import Common

    on = msg["on"]
    try:
        coordinator = _coordinator(hass, msg.get("entry_id"))
        common = Common(coordinator.conn)
        await coordinator._device_call(common.screenOn if on else common.screenOff)
    except (HomeAssistantError, OSError) as err:
        _error(connection, msg, err)
        return
    coordinator.text_settings["is_on"] = on
    coordinator.async_update_listeners()
    studio = _studio(hass)
    studio.journal.add("screen", f"Écran {'allumé' if on else 'éteint'} à la main ({coordinator.entry.title})")
    frame = studio.frame(coordinator.entry.entry_id)
    if on:
        # Waking by hand overrides an "off" schedule block until the next one.
        frame.scheduler.screen_off = False
    elif frame.runner.active_id:
        # Switching off by hand ends the running routine (its next GIF would
        # light the panel again); the schedule starts routines again at its
        # next block.
        frame.runner.stop(reset_display=False)
        studio.save_meta()
    connection.send_result(msg["id"], {"screen_on": on})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/schedule_save",
    vol.Required("schedule"): dict,
    _DISPLAY: str,
})
@websocket_api.require_admin
@callback
def ws_schedule_save(hass, connection, msg):
    studio = _studio(hass)
    try:
        schedule = SCHEDULE_SCHEMA(msg["schedule"])
        frame = studio.frame(msg.get("entry_id"))
    except (vol.Invalid, HomeAssistantError) as err:
        _error(connection, msg, err)
        return
    frame.scheduler.update(schedule)
    studio.save_meta()
    connection.send_result(msg["id"], frame.scheduler.status)


_RECORD = vol.Schema({vol.Required("id"): vol.All(str, vol.Length(min=1, max=64))}, extra=vol.ALLOW_EXTRA)
# A clip's settings include its follow-mode keyframes; anything bigger is not a clip.
MAX_RECORD_BYTES = 256 * 1024
MAX_TOMBSTONES = 2000


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/workspace"})
@websocket_api.require_admin
@callback
def ws_workspace(hass, connection, msg):
    workspace = _studio(hass).workspace
    connection.send_result(msg["id"], {
        "originals": list(workspace["originals"].values()), "clips": list(workspace["clips"].values()),
        "deleted": list(workspace["deleted"]), "folders": workspace.get("folders", []),
    })


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/workspace_sync",
    vol.Optional("put_originals", default=list): [_RECORD],
    vol.Optional("put_clips", default=list): [_RECORD],
    vol.Optional("delete_originals", default=list): [str],
    vol.Optional("delete_clips", default=list): [str],
    vol.Optional("clear", default=False): bool,
    # The page that sent the changes, so it does not reload its own edits.
    vol.Optional("client"): vol.All(str, vol.Length(max=64)),
    vol.Optional("folders"): [vol.All(str, vol.Length(max=60))],
})
@websocket_api.require_admin
@callback
def ws_workspace_sync(hass, connection, msg):
    """Apply a browser's workspace changes (newest edit wins per clip)."""
    studio = _studio(hass)
    workspace = studio.workspace
    deleted = workspace["deleted"]
    now = time.time()

    def forget(kind: str, record_id: str) -> None:
        workspace[kind].pop(record_id, None)
        deleted[record_id] = now

    if "folders" in msg:
        workspace["folders"] = sorted({folder.strip() for folder in msg["folders"] if folder.strip()})
    if msg["clear"]:
        for kind in ("originals", "clips"):
            for record_id in list(workspace[kind]):
                forget(kind, record_id)
    for kind in ("originals", "clips"):
        for record in msg[f"put_{kind}"]:
            if record["id"] in deleted:
                continue
            if len(json.dumps(record)) > MAX_RECORD_BYTES:
                _error(connection, msg, HomeAssistantError(f"Record too large: {record['id']}"))
                return
            known = workspace[kind].get(record["id"])
            if known and known.get("updated", 0) > record.get("updated", 0):
                continue
            workspace[kind][record["id"]] = record
    for original_id in msg["delete_originals"]:
        forget("originals", original_id)
        for clip_id in [k for k, c in workspace["clips"].items() if c.get("originalId") == original_id]:
            forget("clips", clip_id)
    for clip_id in msg["delete_clips"]:
        forget("clips", clip_id)
    # Keep the newest tombstones only; ids are random, so old ones never come back.
    for record_id in sorted(deleted, key=deleted.get)[:-MAX_TOMBSTONES]:
        deleted.pop(record_id)
    studio.save_meta()
    # Other open pages (the PC while the phone imports) pick the changes up at once.
    hass.bus.async_fire(WORKSPACE_EVENT, {"client": msg.get("client")})
    connection.send_result(msg["id"], {})


def _supersede_displays(hass: HomeAssistant, studio: Studio, entry_id: str | None) -> None:
    """Drop the sends still going to a display: the newest request wins.

    A large GIF takes a minute over Bluetooth; asking for another one meant
    waiting for the first to finish, and the change looked missed. A waiting
    send is cancelled, a running one stops before its next packet (the next
    send then clears the partial file first, as for a manual cancel).
    """
    try:
        target = _coordinator(hass, entry_id).entry.entry_id
    except HomeAssistantError:
        return
    for job in list(studio.jobs.values()):
        if job["kind"] != "display" or job.get("cancelled") or job.get("entry_id") not in (target, None):
            continue
        job["cancelled"] = True
        job["superseded"] = True
        if job["state"] == "waiting" and job.get("task"):
            job["task"].cancel()
        elif job["state"] == "sending":
            _coordinator(hass, target).conn.abort_requested = True


def _start_display(hass: HomeAssistant, path: str, entry_id: str | None = None) -> None:
    """Send a gallery GIF to a display, replacing the sends still on their way to it.

    Listed in the panel's « File » tab until done: a waiting one can be
    cancelled, a running one stops before its next packet (the next send then
    clears the partial file first).
    """
    studio = _studio(hass)
    file = os.path.basename(path)
    _supersede_displays(hass, studio, entry_id)
    job = studio.add_job("display", file, entry_id)

    async def run():
        event = {"file": file, "entry_id": entry_id}
        coordinator = None
        queued = time.monotonic()
        timing = {}

        def log(outcome: str, **data) -> None:
            total = round(time.monotonic() - queued, 3)
            name = _display_name(hass, event["entry_id"])
            studio.journal.add("display", f"{file} → {name} : {outcome} ({total} s)",
                               file=file, display=name, total_s=total, **timing, **data)

        try:
            coordinator = _coordinator(hass, entry_id)
            event["entry_id"] = job["entry_id"] = coordinator.entry.entry_id
            async with studio.display_locks.setdefault(coordinator.entry.entry_id, asyncio.Lock()):
                timing["queued_s"] = round(time.monotonic() - queued, 3)
                job["state"] = "sending"
                hass.bus.async_fire(TRANSFER_EVENT, {**event, "state": "started"})
                started = time.monotonic()
                await coordinator.async_display_gif(path=path)
                timing["display_s"] = round(time.monotonic() - started, 3)
        except asyncio.CancelledError:
            log("remplacé par un envoi plus récent" if job.get("superseded") else "annulé")
            hass.bus.async_fire(TRANSFER_EVENT, {**event, "state": "superseded" if job.get("superseded") else "error",
                                                 "message": "annulé"})
            raise
        except HomeAssistantError as err:
            if job.get("cancelled") and coordinator is not None:
                coordinator._carousel_active = True  # a partial file waits on the device
            log("remplacé par un envoi plus récent" if job.get("superseded")
                else "annulé" if job.get("cancelled") else f"échec : {err}")
            hass.bus.async_fire(TRANSFER_EVENT, {
                **event, "state": "superseded" if job.get("superseded") else "error",
                "message": "annulé" if job.get("cancelled") else str(err),
            })
            return
        finally:
            studio.jobs.pop(job["id"], None)
            if coordinator is not None and job["state"] == "sending":
                coordinator.conn.abort_requested = False
        # How the GIF spends its bytes, old gallery GIFs included, with where it came from.
        log("affiché", gallery=studio.meta.get(file), **await hass.async_add_executor_job(_file_stats, path))
        hass.bus.async_fire(TRANSFER_EVENT, {**event, "state": "done"})

    job["task"] = hass.async_create_background_task(run(), f"{DOMAIN} studio display {file}")

    def finished(task) -> None:
        # A task cancelled before it started never ran run(): clear its job here.
        if studio.jobs.pop(job["id"], None) is not None and task.cancelled():
            hass.bus.async_fire(TRANSFER_EVENT, {
                "file": file, "entry_id": job.get("entry_id"),
                "state": "superseded" if job.get("superseded") else "error", "message": "annulé",
            })

    job["task"].add_done_callback(finished)


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/weather_sources"})
@websocket_api.require_admin
@callback
def ws_weather_sources(hass, connection, msg):
    """Where the weather can come from: Home Assistant's weather entities, zones and home."""
    connection.send_result(msg["id"], _studio(hass).weather.sources())


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/weather_calendars_refresh"})
@websocket_api.require_admin
@callback
def ws_weather_calendars_refresh(hass, connection, msg):
    """The agenda's calendars (iCal links, Home Assistant's) read again now, not in 6 hours."""
    _studio(hass).weather.forget_calendars()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/weather_geocode",
    vol.Required("query"): vol.All(str, vol.Length(min=2, max=100)),
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_weather_geocode(hass, connection, msg):
    """Places matching a name typed in the « Météo » tab (Open-Meteo)."""
    try:
        places = await _studio(hass).weather.geocode(msg["query"].strip())
    except HomeAssistantError as err:
        _error(connection, msg, err)
        return
    connection.send_result(msg["id"], {"places": places})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/weather_preview",
    vol.Required("weather"): dict,
    vol.Optional("max_age", default=1800): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
    # Also weigh a whole minute's GIF (its size and Bluetooth packets): settings changed.
    vol.Optional("minute", default=False): bool,
    # Show that page (its number in the turns) to edit it, whatever the time.
    vol.Optional("page"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=0, max=50))),
    _DISPLAY: str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_weather_preview(hass, connection, msg):
    """The weather view as the display shows it now (PNG: its place, its second), with what it says."""
    try:
        cfg = WEATHER_SCHEMA(msg["weather"])
        forecasts = await _studio(hass).weather.forecasts(cfg, max_age=msg["max_age"])
        try:
            size = _screen_size(hass, msg.get("entry_id"))
        except HomeAssistantError:  # no display chosen yet (Windows): the usual 64x64
            size = 64
        now = local_now()
        extras = await _studio(hass).weather.extras(cfg)
        png, boxes = await hass.async_add_executor_job(preview_of, forecasts, now, cfg, size, extras, msg.get("page"))
        titles, page_index = boxes.pop("_pages"), boxes.pop("_page")
        minute = None
        if msg["minute"]:
            minute = len(await hass.async_add_executor_job(
                render_meteo_minute, forecasts, now.replace(second=0), cfg, size, labels_of(cfg, forecasts), extras))
    except (vol.Invalid, HomeAssistantError) as err:
        _error(connection, msg, err)
        return
    connection.send_result(msg["id"], {
        "png": "data:image/png;base64," + base64.b64encode(png).decode(),
        "size": size, "forecast": forecasts[0].summary(), "forecasts": [f.summary() for f in forecasts],
        "minute_bytes": minute, "boxes": boxes,
        "pages": [p["kind"] for p in extra_pages(cfg, extras, now)],
        "titles": titles, "page": page_index,
        # Today's lists, to pick from (saints, world days) and to see that the agenda is read.
        "today": {
            "date": now.date().isoformat(), "saints": extras.saints or [], "world_days": extras.world_days or [],
            "agenda": [(f"{o.start.astimezone(now.tzinfo):%H:%M} " if o.start else "") + o.summary
                       for o in extras.agenda or []],
            "calendars": len(cfg.get("agenda_calendars") or []) + len(cfg.get("agenda_ics") or []),
            "ics": _studio(hass).weather.ics_status(cfg),
        },
        "minute_s": estimate_seconds(minute, _seconds_per_packet(hass, msg.get("entry_id"))) if minute else None,
    })
