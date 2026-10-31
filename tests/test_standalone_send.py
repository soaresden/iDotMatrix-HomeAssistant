"""Send a GIF without Home Assistant (tools/send_gif.py), the display mocked."""
import asyncio
import importlib.util
import random
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import homeassistant  # Initialize Home Assistant before BLE validation dependencies.
import bleak_retry_connector
from bleak import BleakScanner
from PIL import Image

from custom_components.idotmatrix.client.connectionManager import ConnectionManager
from custom_components.idotmatrix.client.const import UUID_READ_DATA, UUID_WRITE_DATA
from tests.test_connection_manager import fake_client

ROOT = Path(__file__).resolve().parents[1]
ADDRESS = "AA:BB:CC:DD:EE:FF"
DEVICE = SimpleNamespace(address=ADDRESS, name="IDM-48BC9B")


def load_tool():
    spec = importlib.util.spec_from_file_location("send_gif", ROOT / "tools" / "send_gif.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_display(**kwargs):
    """A client that answers each 4 KB transfer packet like the display does."""
    client = fake_client(**kwargs)
    state = {"buffer": b"", "received": 0, "notify": None, "packets": 0}

    async def start_notify(uuid, callback):
        assert uuid == UUID_READ_DATA
        state["notify"] = callback

    async def write_gatt_char(uuid, data, response):
        assert uuid == UUID_WRITE_DATA
        state["buffer"] += bytes(data)
        length = int.from_bytes(state["buffer"][:2], "little")
        if len(state["buffer"]) >= 16 and len(state["buffer"]) >= length:
            packet, state["buffer"] = state["buffer"][:length], state["buffer"][length:]
            state["packets"] += 1
            state["received"] += length - 16
            done = state["received"] >= int.from_bytes(packet[5:9], "little")
            reply = bytes([5, 0, 1, 0, 3 if done else 1])
            asyncio.get_running_loop().call_soon(state["notify"], None, reply)

    client.start_notify = start_notify
    client.stop_notify = AsyncMock()
    client.write_gatt_char = write_gatt_char
    client.mtu_size = 247
    client.state = state
    return client


@pytest.fixture
def standalone(monkeypatch):
    manager = object.__new__(ConnectionManager)
    ConnectionManager.__init__(manager)
    manager.address = ADDRESS
    by_address = AsyncMock(return_value=DEVICE)
    monkeypatch.setattr(BleakScanner, "find_device_by_address", by_address)
    monkeypatch.setattr(bleak_retry_connector, "establish_connection", AsyncMock(return_value=fake_client()))
    # Home Assistant's Bluetooth must not be reached without hass.
    monkeypatch.setitem(sys.modules, "homeassistant.components.bluetooth", None)
    return manager, by_address


@pytest.fixture
def gif(tmp_path):
    """A 64x64 GIF of noise, about 3 transfer packets."""
    rng = random.Random(1)
    frames = [Image.frombytes("P", (64, 64), bytes(rng.randrange(16) for _ in range(64 * 64))) for _ in range(6)]
    for frame in frames:
        frame.putpalette([v for i in range(16) for v in (i * 16, 255 - i * 16, i * 8)])
    path = tmp_path / "noise.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    return path


async def test_connect_without_hass_finds_the_display_by_address(standalone):
    manager, by_address = standalone
    await manager.connect()
    by_address.assert_awaited_once_with(ADDRESS, timeout=ConnectionManager.STANDALONE_SCAN_TIMEOUT)
    args = bleak_retry_connector.establish_connection.await_args.args
    assert args[1:] == (DEVICE, ADDRESS)
    assert manager.client.is_connected


async def test_connect_without_hass_says_when_the_display_is_not_seen(standalone):
    manager, by_address = standalone
    by_address.return_value = None
    with pytest.raises(ConnectionError, match="this computer's Bluetooth adapter"):
        await manager.connect()
    bleak_retry_connector.establish_connection.assert_not_awaited()


async def test_connect_with_hass_never_scans_on_its_own(standalone, monkeypatch):
    manager, by_address = standalone
    manager.hass = Mock()
    monkeypatch.setitem(sys.modules, "homeassistant.components.bluetooth", SimpleNamespace(
        async_ble_device_from_address=Mock(return_value=DEVICE),
    ))
    await manager.connect()
    by_address.assert_not_awaited()


async def test_find_device_without_address_takes_the_first_idm_name(monkeypatch):
    by_filter = AsyncMock(return_value=DEVICE)
    monkeypatch.setattr(BleakScanner, "find_device_by_filter", by_filter)
    assert await ConnectionManager.find_device() is DEVICE
    match = by_filter.await_args.args[0]
    named = lambda name, local=None: (SimpleNamespace(name=name), SimpleNamespace(local_name=local))
    assert match(*named(None, "IDM-48BC9B"))
    assert match(*named("IDM-48BC9B"))
    assert not match(*named("OfficeJet", "OfficeJet"))
    assert not match(*named(None))


async def test_send_gif_reports_connection_write_size_and_transfer(gif, monkeypatch):
    tool = load_tool()
    manager_cls, gif_cls = tool.load_client()
    monkeypatch.setattr(manager_cls, "_instances", {})
    display = fake_display()
    monkeypatch.setattr(manager_cls, "scan", AsyncMock(return_value=[(ADDRESS, "IDM-48BC9B")]))
    monkeypatch.setattr(BleakScanner, "find_device_by_address", AsyncMock(return_value=DEVICE))
    monkeypatch.setattr(bleak_retry_connector, "establish_connection", AsyncMock(return_value=display))
    lines = []
    pick = Mock()

    result = await tool.send(str(gif), None, manager_cls, gif_cls, out=lines.append, size=64, pick=pick)

    pick.assert_not_called()  # a single display in range is taken as is
    assert result["file"] == "noise.gif"  # already 64x64: sent untouched
    assert result["ok"] is True
    assert result["address"] == ADDRESS and result["write_size"] == 509 and result["mtu"] == 247
    (report,) = result["reports"]
    assert report["write_burst"] is True
    assert report["bytes"] == gif.stat().st_size + 16 * report["packets"]
    assert display.state["packets"] == report["packets"] >= 2
    (attempt,) = report["attempts"]
    assert attempt["mode"] == "fast" and all(w is not None and t is not None for w, t in attempt["packets"])
    text = "\n".join(lines)
    assert "Connecte a AA:BB:CC:DD:EE:FF" in text and "ecritures de 509 octets" in text
    assert f"Transfert : {report['packets']} paquets" in text and "Envoye." in text
    display.disconnect.assert_awaited()
    assert manager_cls.transfer_log is None and manager_cls.transfer_listener is None


async def test_send_asks_which_display_when_several_answer(gif, monkeypatch):
    tool = load_tool()
    manager_cls, gif_cls = tool.load_client()
    monkeypatch.setattr(manager_cls, "_instances", {})
    other = "11:22:33:44:55:66"
    devices = [(ADDRESS, "IDM-48BC9B"), (other, "IDM-0A0B0C")]
    monkeypatch.setattr(manager_cls, "scan", AsyncMock(return_value=devices))
    by_address = AsyncMock(return_value=SimpleNamespace(address=other, name="IDM-0A0B0C"))
    monkeypatch.setattr(BleakScanner, "find_device_by_address", by_address)
    monkeypatch.setattr(bleak_retry_connector, "establish_connection", AsyncMock(return_value=fake_display()))

    result = await tool.send(str(gif), None, manager_cls, gif_cls, out=lambda _line: None,
                             pick=lambda found: found[1])

    assert result["ok"] is True and result["address"] == other
    assert by_address.await_args.args[0] == other


def test_choose_display_and_size(capsys):
    tool = load_tool()
    devices = [(ADDRESS, "IDM-48BC9B"), ("11:22:33:44:55:66", "IDM-0A0B0C")]
    assert tool.choose_display(devices, ask=lambda _prompt: "") == devices[0]
    answers = iter(["9", "2"])
    assert tool.choose_display(devices, ask=lambda _prompt: next(answers)) == devices[1]
    assert tool.choose_size(32, ask=lambda _prompt: "") == 32
    answers = iter(["", "48", "16"])
    assert tool.choose_size(None, ask=lambda _prompt: next(answers)) == 16


def test_fit_to_screen_converts_only_what_does_not_fit(gif, tmp_path):
    tool = load_tool()
    assert tool.fit_to_screen(str(gif), 64) == str(gif)
    assert tool.fit_to_screen(str(gif), None) == str(gif)
    lines = []
    fitted = tool.fit_to_screen(str(gif), 32, out=lines.append)
    with Image.open(fitted) as image:
        assert image.format == "GIF" and image.size == (32, 32)
    assert "noise.gif adapte a 32x32" in lines[0]
    photo = tmp_path / "photo.png"
    Image.new("RGB", (120, 80), (200, 40, 40)).save(photo)
    with Image.open(tool.fit_to_screen(str(photo), 16, out=lines.append)) as image:
        assert image.size == (16, 16)


def test_summarize_reads_a_failed_fast_attempt():
    report = {"packets": 2, "bytes": 8192, "seconds": 4.0, "write_size": 244, "write_burst": True,
              "write_pause_s": 0.02, "attempts": [
                  {"mode": "fast", "packets": [[0.1, 0.3], [0.2, None]], "failed": "no answer to packet 2/2"},
                  {"mode": "acknowledged", "packets": [[1.0, 0.2], [1.2, 0.4]]}]}
    lines = load_tool().summarize(report)
    assert lines[0] == "Transfert : 2 paquets, 8 Ko en 4.0 s (2.0 Ko/s, 2.00 s par paquet de 4 Ko)"
    assert "ECHEC : no answer to packet 2/2" in lines[2]
    assert "   2: 0.200 + -" in lines[3]
    assert lines[4].startswith("Essai 2 (acknowledged)")


def test_exe_menu_picks_a_built_in_gif_or_only_scans(tmp_path, capsys):
    tool = load_tool()
    gifs = [tmp_path / "test-32px.gif", tmp_path / "test-64px-petit.gif"]
    for gif in gifs:
        gif.write_bytes(b"GIF89a")
    assert tool.choose_builtin(gifs, ask=lambda _prompt: "2") == str(gifs[1])
    assert tool.choose_builtin(gifs, ask=lambda _prompt: "0") is None
    assert tool.choose_builtin(gifs, ask=lambda _prompt: "") is None
    assert "  1. test-32px.gif (0 Ko)" in capsys.readouterr().out


def test_make_test_gifs_writes_device_safe_gifs(tmp_path):
    spec = importlib.util.spec_from_file_location("make_test_gifs", ROOT / "tools" / "make_test_gifs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / "small.gif"
    module.make(path, 32, 5)
    with Image.open(path) as image:
        assert image.size == (32, 32) and image.n_frames >= 10
    data = path.read_bytes()
    assert data[10] & 0x80  # one global palette (frames_to_gif writes no local ones)
    assert path.stat().st_size >= 5 * 1024


def test_client_library_imports_without_home_assistant():
    code = (
        "import sys; sys.modules['homeassistant'] = None; "
        f"sys.path.insert(0, {str(ROOT / 'tools')!r}); "
        "import send_gif; manager, gif = send_gif.load_client(); print(manager.__name__, gif.__name__)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["ConnectionManager", "Gif"]
