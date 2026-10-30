import io
from types import SimpleNamespace

import pytest
from PIL import Image, ImageSequence

from custom_components.idotmatrix.media import encode_frames
from custom_components.idotmatrix.studio import (
    DEFAULT_SECONDS_PER_PACKET,
    MAX_FRAMES,
    Studio,
    encode_options,
    estimate_seconds,
    frames_from_sheet,
    list_gallery,
    slugify_name,
    still_gif,
    unique_file,
)
from homeassistant.exceptions import HomeAssistantError


def _gif(path, frames=3):
    images = [Image.new("RGB", (64, 64), (i * 60, 0, 0)) for i in range(frames)]
    images[0].save(path, save_all=True, append_images=images[1:], duration=100, loop=0)


def _sheet(colors, size=64, columns=1) -> bytes:
    rows = -(-len(colors) // columns)
    grid = Image.new("RGB", (size * columns, size * rows))
    for i, color in enumerate(colors):
        grid.paste(Image.new("RGB", (size, size), color), ((i % columns) * size, (i // columns) * size))
    buf = io.BytesIO()
    grid.save(buf, format="PNG")
    return buf.getvalue()


def test_optimising_a_small_gif_that_saves_no_packet_leaves_it(tmp_path):
    from custom_components.idotmatrix.studio import lighten_gif

    frames = []
    for i in range(12):  # a square moving at 50 fps: 12 full frames, a few KB
        frame = Image.new("RGB", (64, 64), (0, 0, 60))
        frame.paste((255, 255, 0), (i * 4, 20, i * 4 + 10, 30))
        frames.append(frame)
    path = tmp_path / "carre.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=20, loop=0)
    before = path.read_bytes()
    report = lighten_gif(str(path))
    assert report["old"] < 4096 and report["replaced"] is False
    assert path.read_bytes() == before and not (tmp_path / ".backup").exists()


def test_lighten_replaces_a_heavy_gif_and_keeps_a_backup(tmp_path):
    import random

    from custom_components.idotmatrix.studio import lighten_gif

    rng = random.Random(1)
    frames = []
    colours = [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(200)]
    base = [rng.choice(colours) for _ in range(64 * 64)]  # busy, hard to compress
    for i in range(30):
        # A few pixels flicker from frame to frame: invisible on the panel,
        # but every frame was stored in full.
        pixels = list(base)
        for _ in range(5):
            pixels[rng.randrange(64 * 64)] = rng.choice(colours)
        frame = Image.new("RGB", (64, 64))
        frame.putdata(pixels)
        frames.append(frame)
    path = tmp_path / "bruit.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=80, loop=0)
    report = lighten_gif(str(path))
    assert report["replaced"] and report["new"] < report["old"] * 0.9 and path.stat().st_size == report["new"]
    assert (tmp_path / ".backup" / "bruit.gif").stat().st_size == report["old"]
    # Noise the panel cannot show is merged away; the animation lasts as long.
    assert report["frames_before"] == 30 and report["frames_after"] < 30
    with Image.open(path) as image:
        assert image.n_frames == report["frames_after"]
        assert sum(frame.info["duration"] for frame in ImageSequence.Iterator(image)) == 30 * 80
    # Already optimal: left alone.
    assert lighten_gif(str(path))["replaced"] is False
    # The backup folder is not part of the gallery.
    assert [i["file"] for i in list_gallery(str(tmp_path), {})] == ["bruit.gif"]


async def test_sends_queue_per_display_and_can_be_cancelled(tmp_path, monkeypatch):
    import asyncio
    import os

    from custom_components.idotmatrix import studio as studio_module
    from custom_components.idotmatrix.const import DOMAIN

    hass = SimpleNamespace(data={}, config=SimpleNamespace(
        media_dirs={"local": str(tmp_path)}, path=lambda *p: str(tmp_path.joinpath(*p)), config_dir=str(tmp_path)))
    studio = Studio(hass)
    logged = []
    studio.journal = SimpleNamespace(add=lambda kind, msg, **data: logged.append((kind, msg, data)))
    events = []
    hass.data[DOMAIN] = {"_studio": studio}
    hass.bus = SimpleNamespace(async_fire=lambda kind, data: events.append(data))
    hass.async_create_background_task = lambda coro, name: asyncio.ensure_future(coro)

    async def executor(func, *args):
        return func(*args)
    hass.async_add_executor_job = executor
    release = asyncio.Event()
    sent = []

    async def display_gif(path):
        sent.append(os.path.basename(path))
        await release.wait()
        if coordinator.conn.abort_requested:
            raise HomeAssistantError("Transfer cancelled")

    coordinator = SimpleNamespace(entry=SimpleNamespace(entry_id="a", title="Salon"), async_display_gif=display_gif,
                                  conn=SimpleNamespace(abort_requested=False), _carousel_active=False)
    monkeypatch.setattr(studio_module, "_coordinator", lambda hass, entry_id=None: coordinator)
    monkeypatch.setattr(studio_module, "_coordinators", lambda hass: [coordinator])
    studio_module._start_display(hass, str(tmp_path / "un.gif"))
    await asyncio.sleep(0)  # « un » is on its way
    for name in ("deux.gif", "trois.gif"):
        studio_module._start_display(hass, str(tmp_path / name))
    await asyncio.sleep(0)
    # The newest request wins: « un » stops before its next packet, « deux » never starts.
    assert coordinator.conn.abort_requested is True
    release.set()
    for _ in range(10):
        await asyncio.sleep(0)
    assert sent == ["un.gif", "trois.gif"]
    assert sorted(e["file"] for e in events if e.get("state") == "superseded") == ["deux.gif", "un.gif"]
    assert not [e for e in events if e.get("state") == "error"]
    # The next send cleared the partial file first; nothing left in the list.
    assert coordinator._carousel_active is True and coordinator.conn.abort_requested is False
    assert studio.jobs == {}
    # Each send is in the 📜 log, with its outcome and timings.
    displays = {data["file"]: (msg, data) for kind, msg, data in logged if kind == "display"}
    assert "remplacé" in displays["un.gif"][0] and "affiché" in displays["trois.gif"][0]
    assert displays["trois.gif"][1]["display"] == "Salon" and "display_s" in displays["trois.gif"][1]

    # A send can still be cancelled by hand from the « File » tab.
    release.clear()
    studio_module._start_display(hass, str(tmp_path / "quatre.gif"))
    await asyncio.sleep(0)
    results = []
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True), send_result=lambda _id, r: results.append(r),
                                 send_error=lambda _id, code, message: results.append(("error", message)))
    studio_module.ws_jobs(hass, connection, {"id": 1, "type": "idotmatrix/studio/jobs"})
    jobs = results.pop()["jobs"]
    assert [(j["label"], j["state"], j["display"]) for j in jobs] == [("quatre.gif", "sending", "Salon")]
    studio_module.ws_job_cancel(hass, connection, {"id": 2, "type": "idotmatrix/studio/job_cancel", "job_id": jobs[0]["id"]})
    release.set()
    for _ in range(10):
        await asyncio.sleep(0)
    assert [e["message"] for e in events if e.get("state") == "error"] == ["annulé"]
    assert studio.jobs == {}


def test_slugify_name():
    assert slugify_name("Mon Chat ! (été)") == "mon_chat_ete"
    assert slugify_name("***") == "animation"


def test_unique_file_numbers_taken_names_but_keeps_the_edited_one(tmp_path):
    _gif(tmp_path / "chat.gif")
    assert unique_file(str(tmp_path), "chien") == "chien.gif"
    assert unique_file(str(tmp_path), "chat") == "chat_2.gif"
    assert unique_file(str(tmp_path), "chat", keep="chat.gif") == "chat.gif"


def test_estimate_counts_one_handshake_per_4kb_packet():
    assert estimate_seconds(1000, 2.0) == 2
    assert estimate_seconds(4097, 2.0) == 4
    assert estimate_seconds(4096, None) == round(DEFAULT_SECONDS_PER_PACKET)


def test_browser_frames_are_encoded_with_their_timing():
    frames = frames_from_sheet(_sheet([(255, 0, 0), (0, 0, 255), (0, 255, 0)], columns=2), [100, 250, 400], 64, 2)
    result = encode_frames(frames, encode_options({"max_kb": 32}, 64))
    with Image.open(io.BytesIO(result.data)) as image:
        decoded = [(f.size, f.info["duration"]) for f in ImageSequence.Iterator(image)]
    assert decoded == [((64, 64), 100), ((64, 64), 250), ((64, 64), 400)]
    assert result.size_bytes <= 32 * 1024


def test_encode_options_keep_browser_tones_untouched():
    opts = encode_options({"max_kb": 20, "dither": True, "boomerang": True, "contrast": 3}, 32)
    assert (opts.size, opts.max_bytes, opts.dither, opts.boomerang) == (32, 20 * 1024, True, True)


def test_without_budget_every_frame_keeps_a_full_palette():
    colours = [(i * 37 % 256, i * 91 % 256, i * 53 % 256) for i in range(12)]
    frames = frames_from_sheet(_sheet(colours, columns=4), [80] * 12, 64, 4)
    opts = encode_options({}, 64)
    assert opts.max_bytes is None
    result = encode_frames(frames, opts)
    assert (result.frames, result.frame_step, result.colors) == (12, 1, 256)


@pytest.mark.parametrize("durations", [[100], [100, 100, 100]])
def test_sheet_must_match_durations(durations):
    with pytest.raises(ValueError):
        frames_from_sheet(_sheet([(1, 2, 3)] * 2), durations, 64)


def test_sheet_frame_limit():
    with pytest.raises(ValueError, match="frames are supported"):
        frames_from_sheet(_sheet([(0, 0, 0)] * (MAX_FRAMES + 1), size=4, columns=32), [100] * (MAX_FRAMES + 1), 4, 32)


def test_grid_frames_keep_their_order():
    colors = [(i * 40, 0, 0) for i in range(5)]
    frames = frames_from_sheet(_sheet(colors, size=8, columns=2), [100] * 5, 8, 2)
    assert [f.getpixel((0, 0)) for f, _ in frames] == colors


def test_still_gif_is_a_single_device_frame():
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (0, 200, 0)).save(buf, format="PNG")
    with Image.open(io.BytesIO(still_gif(buf.getvalue()))) as image:
        assert image.size == (64, 64) and getattr(image, "n_frames", 1) == 1


def test_list_gallery_merges_metadata_and_skips_other_files(tmp_path):
    _gif(tmp_path / "chat.gif", frames=4)
    _gif(tmp_path / "loose.gif", frames=1)
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / "originals").mkdir()
    items = list_gallery(str(tmp_path), {"chat.gif": {"title": "Mon chat", "favorite": True, "clip": "c1", "source": "chat.mp4"}})
    by_file = {item["file"]: item for item in items}
    assert set(by_file) == {"chat.gif", "loose.gif"}
    assert by_file["chat.gif"]["title"] == "Mon chat" and by_file["chat.gif"]["favorite"]
    assert by_file["chat.gif"]["frames"] == 4
    assert (by_file["chat.gif"]["clip"], by_file["chat.gif"]["source"]) == ("c1", "chat.mp4")
    assert by_file["loose.gif"]["clip"] is None
    assert by_file["loose.gif"]["title"] == "loose" and not by_file["loose.gif"]["favorite"]


@pytest.fixture
def studio(tmp_path):
    hass = SimpleNamespace(data={}, config=SimpleNamespace(
        media_dirs={"local": str(tmp_path)}, path=lambda *p: str(tmp_path.joinpath(*p)),
        config_dir=str(tmp_path),
    ))
    return Studio(hass)


def test_media_url_points_at_the_gallery_folder(studio):
    assert studio.media_url("chat.gif") == "/media/local/idotmatrix/chat.gif"


@pytest.mark.parametrize("file", ["../x.gif", "sub/x.gif", "x.png"])
def test_gallery_path_rejects_other_files(studio, file):
    with pytest.raises(HomeAssistantError):
        studio.gallery_path(file)


def _sync(studio, **changes):
    from custom_components.idotmatrix.const import DOMAIN
    from custom_components.idotmatrix.studio import ws_workspace, ws_workspace_sync

    fired = studio.__dict__.setdefault("fired", [])
    hass = SimpleNamespace(data={DOMAIN: {"_studio": studio}},
                           bus=SimpleNamespace(async_fire=lambda event, data: fired.append((event, data))))
    results = []
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True), send_result=lambda _id, r: results.append(r),
                                 send_error=lambda *a: results.append(("error",) + a[1:]))
    msg = {"id": 1, "type": "idotmatrix/studio/workspace_sync", "put_originals": [], "put_clips": [],
           "delete_originals": [], "delete_clips": [], "clear": False, **changes}
    ws_workspace_sync(hass, connection, msg)
    ws_workspace(hass, connection, {"id": 2, "type": "idotmatrix/studio/workspace"})
    return results


def test_workspace_sync_keeps_the_newest_edit_and_drops_clips_of_removed_originals():
    studio = SimpleNamespace(workspace={"originals": {}, "clips": {}, "deleted": {}}, save_meta=lambda: None)
    _sync(studio, put_originals=[{"id": "o1", "name": "mario.mp4", "size": 1234, "device": "téléphone"}],
          put_clips=[{"id": "c1", "originalId": "o1", "title": "Mario", "updated": 20},
                     {"id": "c2", "originalId": "o1", "title": "Saut", "updated": 5}])
    # An older copy from another browser does not overwrite a newer edit.
    _, listed = _sync(studio, put_clips=[{"id": "c1", "originalId": "o1", "title": "Ancien", "updated": 10}])
    assert {c["id"]: c["title"] for c in listed["clips"]} == {"c1": "Mario", "c2": "Saut"}
    # Each change tells the other open pages, naming the page that made it.
    assert studio.fired[-1] == ("idotmatrix_workspace", {"client": None})
    _, listed = _sync(studio, delete_originals=["o1"])
    assert (listed["originals"], listed["clips"], sorted(listed["deleted"])) == ([], [], ["c1", "c2", "o1"])
    # A browser that still had the clip cannot bring it back.
    _, listed = _sync(studio, put_clips=[{"id": "c1", "originalId": "o1", "title": "Mario", "updated": 99}])
    assert listed["clips"] == []


async def test_screen_buttons_switch_the_display_and_override_the_schedule(monkeypatch):
    from custom_components.idotmatrix import studio as studio_module
    from custom_components.idotmatrix.const import DOMAIN

    calls = []

    async def device_call(func, *args, **kwargs):
        calls.append(func.__name__)

    coordinator = SimpleNamespace(text_settings={"is_on": True}, _device_call=device_call, conn=None,
                                  entry=SimpleNamespace(entry_id="b", title="Salon"),
                                  async_update_listeners=lambda: calls.append("refresh"))
    asked = []
    monkeypatch.setattr(studio_module, "_coordinator",
                        lambda hass, entry_id=None: asked.append(entry_id) or coordinator)
    stopped = []
    runner = SimpleNamespace(active_id="matin", stop=lambda reset_display=True: stopped.append(reset_display))
    frame = SimpleNamespace(scheduler=SimpleNamespace(screen_off=True), runner=runner)
    logged = []
    studio = SimpleNamespace(frame=lambda entry_id: frame, save_meta=lambda: None,
                             journal=SimpleNamespace(add=lambda kind, msg, **data: logged.append(msg)))
    tasks = []
    hass = SimpleNamespace(data={DOMAIN: {"_studio": studio}},
                           async_create_background_task=lambda coro, *a, **k: tasks.append(coro))
    results = []
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True), send_result=lambda _id, r: results.append(r),
                                 send_error=lambda *a: results.append(("error",) + a[1:]))

    for on in (False, True):
        studio_module.ws_screen(hass, connection, {"id": 1, "type": "idotmatrix/studio/screen", "on": on,
                                                   "entry_id": "b"})
        await tasks.pop()
        assert coordinator.text_settings["is_on"] is on
    assert calls == ["screenOff", "refresh", "screenOn", "refresh"]
    assert results == [{"screen_on": False}, {"screen_on": True}]
    # Waking by hand clears the schedule's "off" so the status bar no longer shows it dark.
    assert frame.scheduler.screen_off is False
    # Switching off by hand stopped the running routine, without resetting the panel.
    assert stopped == [False]
    assert asked == ["b", "b"]
    assert logged == ["Écran éteint à la main (Salon)", "Écran allumé à la main (Salon)"]


def _display(entry_id):
    return SimpleNamespace(entry=SimpleNamespace(entry_id=entry_id))


def test_commands_reach_the_named_display_else_the_selected_one(monkeypatch):
    from custom_components.idotmatrix import studio as studio_module
    from custom_components.idotmatrix.const import DOMAIN

    first, second = _display("a"), _display("b")
    monkeypatch.setattr(studio_module, "_coordinators", lambda hass: [first, second])
    studio = SimpleNamespace(selected=None)
    hass = SimpleNamespace(data={DOMAIN: {"_studio": studio}})
    assert studio_module._coordinator(hass) is first
    studio.selected = "b"
    assert studio_module._coordinator(hass) is second
    assert studio_module._coordinator(hass, "a") is first
    with pytest.raises(HomeAssistantError):
        studio_module._coordinator(hass, "removed")
    # A selected display that was removed falls back to the first one.
    studio.selected = "removed"
    assert studio_module._coordinator(hass) is first


class _FakeFrame:
    def __init__(self, studio, entry_id):
        self.started = None
        self.stopped = False
        self.scheduler = SimpleNamespace(schedule=None, start=lambda: None)
        self.runner = SimpleNamespace(start=lambda routine, delay=0: setattr(self, "started", routine["id"]))

    @property
    def data(self):
        return {"active": self.started, "schedule": self.scheduler.schedule}

    def stop(self):
        self.stopped = True


def test_each_display_keeps_its_own_routine_and_schedule(monkeypatch):
    from custom_components.idotmatrix import studio as studio_module

    displays = [_display("a"), _display("b")]
    monkeypatch.setattr(studio_module, "_coordinators", lambda hass: list(displays))
    monkeypatch.setattr(studio_module, "Frame", _FakeFrame)
    schedule = {"enabled": True, "blocks": []}
    studio = object.__new__(Studio)
    studio.hass, studio.frames, studio.routines = None, {}, {"r1": {"id": "r1"}}
    # Saved before several displays were supported: it goes to the first one.
    studio.frame_state = {"_legacy": {"active": "r1", "schedule": schedule}}
    studio.sync_frames()
    first, second = studio.frames["a"], studio.frames["b"]
    assert (first.started, first.scheduler.schedule) == ("r1", schedule)
    assert (second.started, second.scheduler.schedule) == (None, {"enabled": False, "blocks": []})
    # A removed display stops, and gets its routine back when set up again.
    second.started = "r1"
    displays.pop()
    studio.sync_frames()
    assert second.stopped and list(studio.frames) == ["a"]
    displays.append(_display("b"))
    studio.sync_frames()
    assert studio.frames["b"].started == "r1"


def test_workspace_keeps_hand_made_folders_trimmed_and_unique():
    studio = SimpleNamespace(workspace={"originals": {}, "clips": {}, "deleted": {}}, save_meta=lambda: None)
    _, listed = _sync(studio, folders=[" Noël ", "", "Chats", "Noël"])
    assert listed["folders"] == ["Chats", "Noël"]
    # Other changes leave the list alone; clearing the workspace keeps it too.
    _, listed = _sync(studio, clear=True)
    assert listed["folders"] == ["Chats", "Noël"]


def test_deleted_gifs_leave_the_routines():
    studio = object.__new__(Studio)
    studio.routines = {"r1": {"id": "r1", "files": ["a.gif", "b.gif", "c.gif"]}}
    studio.collections = {"k1": {"id": "k1", "name": "Soirée", "files": ["b.gif", "c.gif"]}}
    studio.forget_files(["b.gif", "zzz.gif"])
    assert studio.routines["r1"]["files"] == ["a.gif", "c.gif"]
    assert studio.collections["k1"]["files"] == ["c.gif"]


async def test_live_stills_tell_the_panel_when_the_last_one_is_on_the_display(monkeypatch):
    from unittest.mock import AsyncMock

    from custom_components.idotmatrix import studio as studio_module

    fired = []
    coordinator = SimpleNamespace(_upload_single=AsyncMock(return_value=True))
    monkeypatch.setattr(studio_module, "_coordinator", lambda hass, entry_id=None: coordinator)

    async def executor(func, *args):
        return func(*args)

    studio = object.__new__(Studio)
    studio.hass = SimpleNamespace(async_add_executor_job=executor,
                                  bus=SimpleNamespace(async_fire=lambda event, data: fired.append(data)))
    png = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 0, 0)).save(png, format="PNG")
    studio._live_png = (png.getvalue(), "e1")
    await studio._send_live()
    assert coordinator._upload_single.await_args.kwargs == {"label": "live"}
    assert fired == [{"file": "live", "state": "done", "entry_id": "e1"}]


def test_a_new_image_replaces_the_sends_still_going_to_that_display(monkeypatch):
    from unittest.mock import MagicMock

    from custom_components.idotmatrix import studio as studio_module

    display = SimpleNamespace(entry=SimpleNamespace(entry_id="e1"), conn=SimpleNamespace(abort_requested=False))
    monkeypatch.setattr(studio_module, "_coordinator", lambda hass, entry_id=None: display)
    studio = SimpleNamespace(jobs={
        "j1": {"id": "j1", "kind": "display", "entry_id": "e1", "state": "sending", "task": MagicMock()},
        "j2": {"id": "j2", "kind": "display", "entry_id": "e1", "state": "waiting", "task": MagicMock()},
        "j3": {"id": "j3", "kind": "display", "entry_id": "other", "state": "waiting", "task": MagicMock()},
        "j4": {"id": "j4", "kind": "push", "entry_id": "e1", "state": "waiting", "task": MagicMock()},
    })
    studio_module._supersede_displays(None, studio, None)
    assert display.conn.abort_requested is True                 # the running send stops at its next packet
    studio.jobs["j2"]["task"].cancel.assert_called_once()       # the waiting one never starts
    assert studio.jobs["j1"]["superseded"] and studio.jobs["j2"]["superseded"]
    studio.jobs["j3"]["task"].cancel.assert_not_called()        # another display is left alone
    assert "cancelled" not in studio.jobs["j4"]                 # so are other kinds of jobs


def test_render_settings_set_the_palette_and_a_frame_rate_cap():
    # A 25 fps clip of a square moving every frame, 2 s long.
    frames = []
    for i in range(50):
        frame = Image.new("RGB", (64, 64), (0, 0, 0))
        frame.paste((255, 255 - i * 4, i * 5), (i, 20, i + 12, 32))
        frames.append((frame, 40))
    fast = encode_frames(frames, encode_options({"colors": 64, "max_fps": 10, "fuzz": 24}, 64))
    faithful = encode_frames(frames, encode_options({"fuzz": 0, "merge_similar": False}, 64))
    # Capped at 10 frames a second, as long as before; a smaller palette.
    assert fast.frames == 20 and fast.duration_ms == 2000 and fast.colors == 64
    assert faithful.frames == 50 and faithful.duration_ms == 2000 and faithful.colors == 256
    assert fast.size_bytes < faithful.size_bytes
    assert encode_options({"max_fps": 99, "colors": 1}, 64).max_fps == 30 and encode_options({"colors": 1}, 64).colors == 2


async def test_previews_encode_one_at_a_time_and_stale_ones_are_dropped():
    import asyncio

    from custom_components.idotmatrix.studio import latest_preview

    studio = SimpleNamespace(preview_lock=asyncio.Lock(), preview_seq={})
    release = asyncio.Event()
    ran = []

    def work(name):
        async def encode():
            ran.append(name)
            await release.wait()
            return name
        return encode

    first = asyncio.create_task(latest_preview(studio, "clip1", work("1")))
    await asyncio.sleep(0)
    # Settings changed twice while « 1 » encodes: only the last one is worth it.
    second = asyncio.create_task(latest_preview(studio, "clip1", work("2")))
    third = asyncio.create_task(latest_preview(studio, "clip1", work("3")))
    other = asyncio.create_task(latest_preview(studio, "clip2", work("other")))  # another editor
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second, third, other) == ["1", None, "3", "other"]
    assert ran == ["1", "3", "other"]


def test_the_bluetooth_write_pause_can_be_tuned_without_a_restart(monkeypatch):
    from custom_components.idotmatrix import studio as studio_module
    from custom_components.idotmatrix.client.connectionManager import ConnectionManager
    from custom_components.idotmatrix.const import DOMAIN

    monkeypatch.setattr(ConnectionManager, "WRITE_PAUSE_S", 0.02)
    monkeypatch.setattr(ConnectionManager, "WRITE_BURST", False)
    logged = []
    hass = SimpleNamespace(data={DOMAIN: {"_studio": SimpleNamespace(
        journal=SimpleNamespace(add=lambda kind, msg, **data: logged.append(data)))}})
    results = []
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True), send_result=lambda _id, r: results.append(r))
    studio_module.ws_write_pause(hass, connection, {"id": 1, "type": "idotmatrix/studio/write_pause"})
    studio_module.ws_write_pause(hass, connection, {"id": 2, "type": "idotmatrix/studio/write_pause", "ms": 5})
    assert results == [{"ms": 20.0, "burst": False}, {"ms": 5.0, "burst": False}]
    assert ConnectionManager.WRITE_PAUSE_S == 0.005 and logged == [{"write_pause_ms": 5}]
    studio_module.ws_write_pause(hass, connection, {"id": 3, "type": "idotmatrix/studio/write_pause", "burst": True})
    assert results[-1]["burst"] is True and ConnectionManager.WRITE_BURST is True


def test_turning_an_ensemble_on_by_hand_switches_to_manual_mode(monkeypatch):
    from custom_components.idotmatrix import studio as studio_module
    from custom_components.idotmatrix.const import DOMAIN

    updates, started, logged = [], [], []
    scheduler = SimpleNamespace(schedule={"enabled": True, "blocks": [{"from": "08:00", "to": "09:00", "action": "off"}]})
    scheduler.update = lambda schedule: (updates.append(schedule), setattr(scheduler, "schedule", schedule))
    runner = SimpleNamespace(start=lambda routine: started.append(routine["id"]), status={"active": "r1"})
    frame = SimpleNamespace(scheduler=scheduler, runner=runner)
    studio = SimpleNamespace(routines={"r1": {"id": "r1", "name": "Matin"}}, frame=lambda entry_id: frame,
                             save_meta=lambda: None, journal=SimpleNamespace(add=lambda kind, msg, **d: logged.append(msg)))
    hass = SimpleNamespace(data={DOMAIN: {"_studio": studio}})
    results = []
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True), send_result=lambda _id, r: results.append(r),
                                 send_error=lambda *a: results.append(("error",) + a[1:]))
    studio_module.ws_routine_start(hass, connection, {"id": 1, "type": "idotmatrix/studio/routine_start", "routine_id": "r1"})
    # The planning is kept (its slots too) but waits: Manuel mode.
    assert updates == [{"enabled": False, "blocks": [{"from": "08:00", "to": "09:00", "action": "off"}]}]
    assert started == ["r1"] and any("Mode Manuel" in m for m in logged)
    # Already manual: nothing to switch.
    studio_module.ws_routine_start(hass, connection, {"id": 2, "type": "idotmatrix/studio/routine_start", "routine_id": "r1"})
    assert len(updates) == 1 and started == ["r1", "r1"]


def test_collections_pick_gifs_from_any_folder_and_feed_ensembles(tmp_path):
    from custom_components.idotmatrix import studio as studio_module
    from custom_components.idotmatrix.const import DOMAIN
    from custom_components.idotmatrix.routines import ROUTINE_SCHEMA

    hass = SimpleNamespace(data={}, config=SimpleNamespace(
        media_dirs={"local": str(tmp_path)}, path=lambda *p: str(tmp_path.joinpath(*p)), config_dir=str(tmp_path)))
    studio = Studio(hass)
    studio.save_meta = lambda: None
    studio.routines = {}  # as loaded
    hass.data[DOMAIN] = {"_studio": studio}
    (tmp_path / "idotmatrix").mkdir()
    for name in ("a.gif", "b.gif", "c.gif"):
        (tmp_path / "idotmatrix" / name).write_bytes(b"GIF89a")
    results = []
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True), send_result=lambda _id, r: results.append(r),
                                 send_error=lambda *a: results.append(("error",) + a[1:]))
    call = lambda command, **data: studio_module.__dict__[command](hass, connection, {"id": 1, **data})  # noqa: E731
    call("ws_collection_save", type="x", collection_id="k1", add=["a.gif"])
    assert results[-1][0] == "error"  # a new collection needs a name
    call("ws_collection_save", type="x", collection_id="k1", name="Soirée", add=["c.gif", "a.gif", "a.gif", "missing.gif"])
    assert studio.collections["k1"]["files"] == ["c.gif", "a.gif"]
    call("ws_collection_save", type="x", collection_id="k1", add=["b.gif"], remove=["c.gif"])
    assert studio.collections["k1"] == {"id": "k1", "name": "Soirée", "files": ["a.gif", "b.gif"]}
    # An ensemble on a collection follows it; deleting a GIF leaves both.
    routine = ROUTINE_SCHEMA({"id": "r1", "name": "Soir", "collection": "k1", "interval": 60})
    studio.routines["r1"] = routine
    assert studio.routine_files(routine) == ["a.gif", "b.gif"]
    studio.forget_files(["a.gif"])
    assert studio.routine_files(routine) == ["b.gif"]
    # Deleting the collection leaves the ensemble a copy of its list.
    call("ws_collection_delete", type="x", collection_id="k1")
    assert "k1" not in studio.collections and routine["collection"] is None and routine["files"] == ["b.gif"]
    # Hidden folders, renamed while hidden.
    call("ws_folder_hidden", type="x", folder="Pn", hidden=True)
    call("ws_folder_hidden", type="x", folder="Pn", hidden=True, rename="Soirées")
    assert studio.hidden_folders == ["Soirées"]
    call("ws_folder_hidden", type="x", folder="Soirées", hidden=False)
    assert studio.hidden_folders == []


def test_an_ensemble_needs_gifs_or_a_collection():
    import voluptuous as vol

    from custom_components.idotmatrix.routines import ROUTINE_SCHEMA

    with pytest.raises(vol.Invalid):
        ROUTINE_SCHEMA({"id": "r1", "name": "Vide", "interval": 60})
    assert ROUTINE_SCHEMA({"id": "r1", "name": "A", "files": ["a.gif"], "interval": 60})["files"] == ["a.gif"]
