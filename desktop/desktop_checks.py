"""The desktop Pixel Studio against a simulated display.

Run in a process of its own (tests/test_desktop.py): it loads
desktop/homeassistant in place of Home Assistant.
"""
import asyncio
import io
import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest
from PIL import Image

DESKTOP = Path(__file__).resolve().parent
sys.path.insert(0, str(DESKTOP))
import pixel_studio  # noqa: E402

ADDRESS = "AA:BB:CC:DD:EE:FF"
WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"
READ_UUID = "0000fa03-0000-1000-8000-00805f9b34fb"


def fake_display():
    """A connected client answering each 4 KB transfer packet like the display."""
    from bleak.backends.characteristic import BleakGATTCharacteristic
    from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection

    services = BleakGATTServiceCollection()
    service = BleakGATTService(None, 1, "0000fa00-0000-1000-8000-00805f9b34fb")
    services.add_service(service)
    for handle, uuid in enumerate((READ_UUID, WRITE_UUID), 2):
        services.add_characteristic(BleakGATTCharacteristic(
            None, handle, uuid, ["write", "write-without-response", "notify"], lambda: 509, service))
    state = {"buffer": b"", "received": 0, "notify": None, "files": [], "commands": []}

    async def start_notify(uuid, callback):
        state["notify"] = callback

    async def write_gatt_char(uuid, data, response):
        if response:  # commands (reset, screen on/off) are acknowledged writes
            state["commands"].append(bytes(data))
            return
        state["buffer"] += bytes(data)
        length = int.from_bytes(state["buffer"][:2], "little")
        if len(state["buffer"]) >= 16 and len(state["buffer"]) >= length:
            packet, state["buffer"] = state["buffer"][:length], state["buffer"][length:]
            if packet[4] == 0:
                state["files"].append(0)
            state["files"][-1] += length - 16
            done = state["files"][-1] >= int.from_bytes(packet[5:9], "little")
            asyncio.get_running_loop().call_soon(state["notify"], None, bytes([5, 0, 1, 0, 3 if done else 1]))

    async def disconnect():
        client.is_connected = False

    client = SimpleNamespace(
        is_connected=True, services=services, mtu_size=247, state=state,
        start_notify=start_notify, stop_notify=AsyncMock(), write_gatt_char=write_gatt_char,
        disconnect=disconnect, clear_cache=AsyncMock(return_value=True),
    )
    return client


@pytest.fixture
async def server(tmp_path, monkeypatch):
    runner, url, hass = await pixel_studio.start(0, tmp_path / "data", tmp_path / "media")
    try:
        yield SimpleNamespace(url=url, hass=hass, home=tmp_path)
    finally:
        await pixel_studio.stop(runner, hass)


@pytest.fixture
def display(monkeypatch):
    import bleak_retry_connector
    from bleak import BleakScanner
    from idmcore.client.connectionManager import ConnectionManager

    client = fake_display()
    monkeypatch.setattr(ConnectionManager, "_instances", {})
    monkeypatch.setattr(ConnectionManager, "scan", AsyncMock(return_value=[(ADDRESS, "IDM-48BC9B")]))
    monkeypatch.setattr(BleakScanner, "find_device_by_address",
                        AsyncMock(return_value=SimpleNamespace(address=ADDRESS, name="IDM-48BC9B")))
    monkeypatch.setattr(bleak_retry_connector, "establish_connection", AsyncMock(return_value=client))
    return client


class Page:
    """The panel's side of the websocket."""

    def __init__(self, ws):
        self.ws, self.next_id, self.events = ws, 1, asyncio.Queue()

    async def call(self, kind, **data):
        msg_id, self.next_id = self.next_id, self.next_id + 1
        await self.ws.send_json({"id": msg_id, "type": kind, **data})
        while True:
            msg = await asyncio.wait_for(self.ws.receive_json(), 20)
            if msg["type"] == "event":
                await self.events.put(msg["event"])
            elif msg["id"] == msg_id:
                return msg

    async def event(self, predicate):
        while True:
            while not self.events.empty():
                event = self.events.get_nowait()
                if predicate(event):
                    return event
            msg = await asyncio.wait_for(self.ws.receive_json(), 20)
            if msg["type"] == "event":
                await self.events.put(msg["event"])


def gif_bytes(size, frames=6, seed=1):
    rng = random.Random(seed)
    images = [Image.frombytes("RGB", (size, size), rng.randbytes(size * size * 3)) for _ in range(frames)]
    buffer = io.BytesIO()
    images[0].save(buffer, format="GIF", save_all=True, append_images=images[1:], duration=100, loop=0)
    return buffer.getvalue()


def test_home_assistant_is_the_desktop_stand_in():
    pixel_studio.load_integration()
    import homeassistant
    assert Path(homeassistant.__file__).parent == DESKTOP / "homeassistant"


async def test_page_panel_and_media_are_served(server):
    async with aiohttp.ClientSession() as session:
        async with session.get(server.url) as response:
            assert response.status == 200 and 'id="bt"' in await response.text()
        async with session.get(server.url + "static/idotmatrix-studio.js") as response:
            assert response.status == 200 and "idotmatrix-studio" in await response.text()
        async with session.get(server.url + "static/..%2Fstudio.py") as response:
            assert response.status == 404
        async with session.get(server.url + "media/local/..%2F..%2Fdata%2Fsettings.json") as response:
            assert response.status == 404


async def test_a_second_start_finds_the_running_one(server):
    port = int(server.url.rsplit(":", 1)[1].strip("/"))
    assert await pixel_studio.already_running(port) == f"http://127.0.0.1:{port}/"
    assert await pixel_studio.already_running(1) is None


async def test_another_web_page_cannot_use_the_websocket(server):
    async with aiohttp.ClientSession() as session:
        with pytest.raises(aiohttp.WSServerHandshakeError) as err:
            await session.ws_connect(server.url + "api/websocket", headers={"Origin": "https://example.com"})
        assert err.value.status == 403
        own = server.url.rstrip("/")
        async with session.ws_connect(server.url + "api/websocket", headers={"Origin": own}) as ws:
            assert (await Page(ws).call("desktop/state"))["success"]


async def test_panel_commands_answer_before_a_display_is_chosen(server):
    async with aiohttp.ClientSession() as session, session.ws_connect(server.url + "api/websocket") as ws:
        page = Page(ws)
        state = await page.call("desktop/state")
        assert state["result"]["display"] is None and state["result"]["connected"] is False
        gallery = await page.call("idotmatrix/studio/gallery")
        assert gallery["success"], gallery
        assert (await page.call("auth/sign_path", path="/media/local/x.gif"))["result"] == {"path": "/media/local/x.gif"}
        unknown = await page.call("nope/nope")
        assert unknown["error"]["code"] == "unknown_command"
        invalid = await page.call("idotmatrix/studio/display")
        assert invalid["error"]["code"] == "invalid_format"


async def test_collections_and_job_cancel_keep_their_own_ids(server):
    """Their ids once travelled as "id", the websocket message's own number."""
    gallery = Path(server.hass.config.media_dirs["local"]) / "idotmatrix"
    gallery.mkdir(parents=True, exist_ok=True)
    (gallery / "a.gif").write_bytes(gif_bytes(16, frames=1))
    async with aiohttp.ClientSession() as session, session.ws_connect(server.url + "api/websocket") as ws:
        page = Page(ws)
        page.next_id = 520
        created = await page.call("idotmatrix/studio/collection_save", collection_id="kzelda", name="Zelda", add=["a.gif"])
        assert created["success"], created
        assert created["result"] == {"id": "kzelda", "name": "Zelda", "files": ["a.gif"]}
        renamed = await page.call("idotmatrix/studio/collection_save", collection_id="kzelda", name="Zelda II")
        assert renamed["result"]["name"] == "Zelda II"
        assert (await page.call("idotmatrix/studio/collection_delete", collection_id="kzelda"))["success"]
        cancel = await page.call("idotmatrix/studio/job_cancel", job_id="j1")
        assert cancel["error"]["message"] == "Already finished"


async def test_connect_then_send_a_gallery_gif(server, display):
    gallery = Path(server.hass.config.media_dirs["local"]) / "idotmatrix"
    gallery.mkdir(parents=True, exist_ok=True)
    data = gif_bytes(32)
    assert len(data) > 12 * 1024  # its first image goes ahead of it
    (gallery / "bruit.gif").write_bytes(data)
    async with aiohttp.ClientSession() as session, session.ws_connect(server.url + "api/websocket") as ws:
        page = Page(ws)
        scan = await page.call("desktop/scan")
        assert scan["result"]["devices"] == [{"address": ADDRESS, "name": "IDM-48BC9B"}]
        connect = await page.call("desktop/connect", address=ADDRESS, name="IDM-48BC9B", size=32)
        assert connect["result"]["connected"] is True, connect
        info = await page.call("idotmatrix/studio/info")
        assert info["result"]["screen_size"] == 32
        status = await page.call("idotmatrix/studio/status")
        assert status["result"]["connected"] is True and status["result"]["display"] == "IDM-48BC9B"
        items = (await page.call("idotmatrix/studio/gallery"))["result"]["items"]
        assert [item["file"] for item in items] == ["bruit.gif"]
        assert items[0]["url"] == "/media/local/idotmatrix/bruit.gif"
        assert (await page.call("subscribe_events", event_type="idotmatrix_transfer"))["success"]

        sent = await page.call("idotmatrix/studio/display", file="bruit.gif")
        assert sent["success"], sent
        done = await page.event(lambda e: e["data"].get("state") in ("done", "error"))
        assert done["data"]["state"] == "done", done

    # The carousel state is unknown after a start: reset first, then the still and the GIF.
    assert display.state["commands"][:2] == [bytes.fromhex("04 00 03 80"), bytes.fromhex("05 00 04 80 50")]
    assert len(display.state["files"]) == 2 and display.state["files"][1] == len(data)
    settings = json.loads((server.home / "data" / "settings.json").read_text(encoding="utf-8"))
    assert settings["display"] == {"address": ADDRESS, "name": "IDM-48BC9B", "size": 32}
    async with aiohttp.ClientSession() as session:
        async with session.get(server.url + "media/local/idotmatrix/bruit.gif") as response:
            assert response.status == 200 and await response.read() == data


async def test_test_button_sends_a_rainbow(server, display):
    async with aiohttp.ClientSession() as session, session.ws_connect(server.url + "api/websocket") as ws:
        page = Page(ws)
        assert (await page.call("desktop/test"))["error"]["message"] == "Choisis d'abord un cadre"
        await page.call("desktop/connect", address=ADDRESS, name="IDM-48BC9B", size=16)
        await page.call("subscribe_events", event_type="idotmatrix_transfer")
        result = await page.call("desktop/test")
        assert result["result"]["file"] == "test-16px.gif"
        done = await page.event(lambda e: e["data"].get("state") in ("done", "error"))
        assert done["data"]["state"] == "done", done
    assert display.state["files"][-1] == result["result"]["size_bytes"]


async def test_encode_view_saves_a_clip_to_the_gallery(server):
    sheet = Image.new("RGB", (64, 32))
    sheet.paste((255, 0, 0), (0, 0, 32, 32))
    sheet.paste((0, 0, 255), (32, 0, 64, 32))
    png = io.BytesIO()
    sheet.save(png, format="PNG")
    form = aiohttp.FormData()
    form.add_field("sheet", png.getvalue(), filename="sheet.png", content_type="image/png")
    form.add_field("meta", json.dumps({"durations": [200, 200], "size": 32, "columns": 2, "title": "Rouge bleu"}))
    async with aiohttp.ClientSession() as session:
        async with session.post(server.url + "api/idotmatrix/studio/encode", data=form) as response:
            body = await response.json()
            assert response.status == 200, body
    path = Path(server.hass.config.media_dirs["local"]) / "idotmatrix" / body["file"]
    with Image.open(path) as image:
        assert image.size == (32, 32) and image.n_frames == 2


async def test_studio_state_survives_a_restart(tmp_path, display):
    runner, url, hass = await pixel_studio.start(0, tmp_path / "data", tmp_path / "media")
    async with aiohttp.ClientSession() as session, session.ws_connect(url + "api/websocket") as ws:
        page = Page(ws)
        await page.call("desktop/connect", address=ADDRESS, name="IDM-48BC9B", size=64)
        saved = await page.call("idotmatrix/studio/routine_save",
                                routine={"id": "r1", "name": "Matin", "files": ["a.gif"], "interval": 60})
    await pixel_studio.stop(runner, hass)

    runner, url, hass = await pixel_studio.start(0, tmp_path / "data", tmp_path / "media")
    try:
        async with aiohttp.ClientSession() as session, session.ws_connect(url + "api/websocket") as ws:
            page = Page(ws)
            state = (await page.call("desktop/state"))["result"]
            assert state["display"]["address"] == ADDRESS
            routines = (await page.call("idotmatrix/studio/routines"))["result"]
    finally:
        await pixel_studio.stop(runner, hass)
    assert saved["success"], saved
    assert "Matin" in json.dumps(routines)
