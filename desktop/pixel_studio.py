"""Pixel Studio on a PC: the integration's panel and Studio code, driving a
display over the PC's own Bluetooth, without Home Assistant.

    python desktop/pixel_studio.py [--port 8765] [--no-browser] [--home FOLDER]

A local web server (127.0.0.1 only) serves the panel (www/idotmatrix-studio.js)
in a page with a Bluetooth bar on top, answers its websocket commands with
studio.py's own handlers, and opens the browser on it. studio.py, journal.py,
routines.py and schedule.py run unchanged on a small stand-in for the parts of
Home Assistant they use (desktop/homeassistant); the coordinator is
desktop/overrides/coordinator.py. Gallery: Documents/Pixel Studio.
"""
from __future__ import annotations

import argparse
import asyncio
import colorsys
import importlib
import inspect
import json
import logging
import os
import sys
import types
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from aiohttp import web

DESKTOP = Path(__file__).resolve().parent
INTEGRATION = DESKTOP.parent / "custom_components" / "idotmatrix"
# Built as an .exe (PyInstaller): idmcore is then a real bundled package.
FROZEN = getattr(sys, "frozen", False)
DEFAULT_PORT = 8765
SIZES = (64, 32, 16)
ADMIN = SimpleNamespace(is_admin=True, id="desktop", name="Pixel Studio")
# Made here: aiohttp names a key after the module making it, which it finds only at import
# (not from start() run in a thread of its own, as on the phone).
ORIGINS = web.AppKey("origins", set)

_LOGGER = logging.getLogger("pixel_studio")


def load_integration():
    """Studio's modules as the package ``idmcore``, on the Home Assistant stand-in.

    From the source tree the package is the integration folder (its
    ``__init__`` needs Home Assistant and is skipped), with desktop/overrides
    in front of it for coordinator.py."""
    if str(DESKTOP) not in sys.path:
        sys.path.insert(0, str(DESKTOP))  # desktop/homeassistant
    if not FROZEN and "idmcore" not in sys.modules:
        package = types.ModuleType("idmcore")
        package.__path__ = [str(DESKTOP / "overrides"), str(INTEGRATION)]
        sys.modules["idmcore"] = package
    # The Store tab needs the official app's key, which is never shipped.
    sys.modules.setdefault("idmcore.store_ws", None)
    return importlib.import_module("idmcore.studio")


def default_folders() -> tuple[Path, Path]:
    """(data folder, media folder holding the gallery)."""
    if home := os.environ.get("PIXEL_STUDIO_HOME"):
        return Path(home, "data"), Path(home, "media")
    appdata = Path(os.environ.get("APPDATA") or Path.home() / ".config") / "Pixel Studio"
    documents = Path.home() / "Documents"
    return appdata, (documents if documents.is_dir() else Path.home()) / "Pixel Studio"


def test_pattern(size: int, frames_to_gif) -> bytes:
    """A moving rainbow, to check a display answers."""
    from PIL import Image

    frames = []
    for step in range(12):
        image = Image.new("RGB", (size, size))
        pixels = image.load()
        for y in range(size):
            for x in range(size):
                r, g, b = colorsys.hsv_to_rgb(((x + y) / (2 * size) + step / 12) % 1, 1, 1)
                pixels[x, y] = (int(r * 255), int(g * 255), int(b * 255))
        frames.append(image)
    return frames_to_gif(frames, 100, colors=64)


class Desktop:
    """The display chosen in the Bluetooth bar, kept in settings.json."""

    def __init__(self, hass, studio_module, settings_path: Path) -> None:
        from idmcore.coordinator import IDotMatrixCoordinator
        from idmcore.const import DOMAIN

        self.hass = hass
        self.studio_module = studio_module
        self.settings_path = settings_path
        self.domain = DOMAIN
        self.coordinator_class = IDotMatrixCoordinator
        self.last_error: str | None = None
        try:
            self.settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.settings = {}

    @property
    def coordinator(self):
        return next((value for value in self.hass.data.get(self.domain, {}).values()
                     if isinstance(value, self.coordinator_class)), None)

    def restore(self) -> None:
        display = self.settings.get("display")
        if display:
            self.use_display(display["address"], display.get("name") or display["address"], display.get("size", 64),
                             save=False)

    def use_display(self, address: str, name: str, size: int, *, save: bool = True):
        domain_data = self.hass.data.setdefault(self.domain, {})
        current = self.coordinator
        if current is not None and current.entry.entry_id == address:
            current.entry.title = name
            current.text_settings["screen_size"] = int(size)
        else:
            if current is not None:
                domain_data.pop(current.entry.entry_id, None)
                self.hass.async_create_task(current.async_disconnect())
            current = domain_data[address] = self.coordinator_class(self.hass, address, name, size)
            studio = domain_data.get("_studio")
            if studio is not None:
                studio.sync_frames()
        if save:
            self.settings["display"] = {"address": address, "name": name, "size": int(size)}
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(self.settings, indent=1), encoding="utf-8")
        return current

    def state(self) -> dict:
        coordinator = self.coordinator
        return {
            "display": self.settings.get("display") if coordinator else None,
            "connected": bool(coordinator and coordinator.connected),
            "error": self.last_error,
        }


def _desktop(hass) -> Desktop:
    return hass.data["desktop"]


def desktop_commands():
    """The Bluetooth bar's websocket commands (desktop/*)."""
    import voluptuous as vol
    from homeassistant.components import websocket_api
    from homeassistant.exceptions import HomeAssistantError
    from idmcore.client.connectionManager import ConnectionManager
    from idmcore.weather import frames_to_gif

    @websocket_api.websocket_command({vol.Required("type"): "desktop/state"})
    def ws_state(hass, connection, msg):
        connection.send_result(msg["id"], _desktop(hass).state())

    @websocket_api.websocket_command({vol.Required("type"): "desktop/scan"})
    async def ws_scan(hass, connection, msg):
        devices = await ConnectionManager.scan()
        connection.send_result(msg["id"], {"devices": [{"address": a, "name": n} for a, n in devices]})

    @websocket_api.websocket_command({
        vol.Required("type"): "desktop/connect",
        vol.Required("address"): str,
        vol.Optional("name"): str,
        vol.Required("size"): vol.In(SIZES),
    })
    async def ws_connect(hass, connection, msg):
        desktop = _desktop(hass)
        coordinator = desktop.use_display(msg["address"], msg.get("name") or msg["address"], msg["size"])
        try:
            await coordinator.async_connect()
        except HomeAssistantError as err:
            desktop.last_error = str(err)
            raise
        desktop.last_error = None
        connection.send_result(msg["id"], desktop.state())

    @websocket_api.websocket_command({vol.Required("type"): "desktop/disconnect"})
    async def ws_disconnect(hass, connection, msg):
        coordinator = _desktop(hass).coordinator
        if coordinator is not None:
            await coordinator.async_disconnect()
        connection.send_result(msg["id"], _desktop(hass).state())

    @websocket_api.websocket_command({vol.Required("type"): "desktop/test"})
    async def ws_test(hass, connection, msg):
        desktop = _desktop(hass)
        coordinator = desktop.coordinator
        if coordinator is None:
            raise HomeAssistantError("Choisis d'abord un cadre")
        size = coordinator.text_settings["screen_size"]
        path = Path(hass.config.path(f"test-{size}px.gif"))
        data = await hass.async_add_executor_job(test_pattern, size, frames_to_gif)
        await hass.async_add_executor_job(path.write_bytes, data)
        desktop.studio_module._start_display(hass, str(path))
        connection.send_result(msg["id"], {"file": path.name, "size_bytes": len(data)})

    return [ws_state, ws_scan, ws_connect, ws_disconnect, ws_test]


class Connection:
    """One page's websocket: results and events in the order they were sent."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.user = ADMIN
        self.subscriptions: dict[int, object] = {}
        self._queue: asyncio.Queue = asyncio.Queue()
        self._writer = asyncio.ensure_future(self._write())

    async def _write(self) -> None:
        while True:
            payload = await self._queue.get()
            try:
                await self.ws.send_str(json.dumps(payload, default=str))
            except (ConnectionError, RuntimeError):
                return

    def send_message(self, payload: dict) -> None:
        self._queue.put_nowait(payload)

    def send_result(self, msg_id, result=None) -> None:
        self.send_message({"id": msg_id, "type": "result", "success": True, "result": result})

    def send_error(self, msg_id, code: str, message: str, **_details) -> None:
        self.send_message({"id": msg_id, "type": "result", "success": False,
                           "error": {"code": code, "message": message}})

    def close(self) -> None:
        for unsubscribe in self.subscriptions.values():
            unsubscribe()
        self.subscriptions.clear()
        self._writer.cancel()


async def _call(hass, connection, handler, msg) -> None:
    import voluptuous as vol
    from homeassistant.exceptions import HomeAssistantError

    try:
        result = handler(hass, connection, msg)
        if inspect.isawaitable(result):
            await result
    except HomeAssistantError as err:
        connection.send_error(msg["id"], "home_assistant_error", str(err))
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_format", str(err))
    except Exception as err:  # noqa: BLE001 - the page shows it instead of waiting forever
        _LOGGER.exception("Command %s failed", msg.get("type"))
        connection.send_error(msg["id"], "unknown_error", str(err) or type(err).__name__)


def dispatch(hass, connection: Connection, msg: dict) -> None:
    """Answer one message of Home Assistant's websocket protocol (the parts the panel uses)."""
    import voluptuous as vol

    msg_id, kind = msg.get("id"), msg.get("type")
    if kind == "subscribe_events":
        def forward(event_type, data):
            connection.send_message({"id": msg_id, "type": "event", "event": {
                "event_type": event_type, "data": data, "origin": "LOCAL",
                "time_fired": datetime.now(timezone.utc).isoformat()}})
        connection.subscriptions[msg_id] = hass.bus.async_listen(msg.get("event_type"), forward)
        connection.send_result(msg_id)
        return
    if kind == "unsubscribe_events":
        unsubscribe = connection.subscriptions.pop(msg.get("subscription"), None)
        if unsubscribe:
            unsubscribe()
        connection.send_result(msg_id)
        return
    if kind == "auth/sign_path":  # media URLs need no signature on the desktop
        connection.send_result(msg_id, {"path": msg.get("path")})
        return
    handler = hass.data.get("websocket_commands", {}).get(kind)
    if handler is None:
        connection.send_error(msg_id, "unknown_command", f"Commande inconnue : {kind}")
        return
    try:
        msg = handler.ws_schema(msg)
    except vol.Invalid as err:
        connection.send_error(msg_id, "invalid_format", str(err))
        return
    hass.async_create_task(_call(hass, connection, handler, msg))


async def start(port: int = DEFAULT_PORT, data_dir: Path | None = None, media_dir: Path | None = None):
    """Start the server; returns (runner, url, hass)."""
    from aiohttp import WSMsgType

    studio_module = load_integration()
    from homeassistant.components import websocket_api
    from homeassistant.components.http import KEY_HASS
    from homeassistant.core import HomeAssistant

    default_data, default_media = default_folders()
    data_dir, media_dir = Path(data_dir or default_data), Path(media_dir or default_media)
    data_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    hass = HomeAssistant(str(data_dir), str(media_dir))
    www = Path(studio_module.__file__).parent / "www"

    @web.middleware
    async def same_origin_only(request, handler):
        # Another web page open in the browser must not drive the display or
        # write to the gallery: browsers name the page a request comes from.
        origin = request.headers.get("Origin")
        if origin and origin not in request.app[ORIGINS]:
            return web.json_response({"message": "Origine refusée"}, status=403)
        return await handler(request)

    app = web.Application(middlewares=[same_origin_only], client_max_size=256 * 1024 * 1024)
    app[KEY_HASS] = hass
    app[ORIGINS] = set()

    def register_view(view) -> None:
        for method in ("get", "post", "put", "delete"):
            handler = getattr(view, method, None)
            if handler is None:
                continue

            async def route(request, handler=handler):
                request["hass_user"] = ADMIN
                return await handler(request)

            app.router.add_route(method.upper(), view.url, route)

    hass.http = SimpleNamespace(register_view=register_view)
    desktop = hass.data["desktop"] = Desktop(hass, studio_module, data_dir / "settings.json")
    for handler in desktop_commands():
        websocket_api.async_register_command(hass, handler)
    desktop.restore()
    await studio_module.async_setup_studio(hass, "/static")

    no_cache = {"Cache-Control": "no-cache"}

    async def index(_request):
        return web.FileResponse(DESKTOP / "index.html", headers=no_cache)

    async def static(request):
        path = (www / request.match_info["name"]).resolve()
        if path.parent != www.resolve() or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers=no_cache)

    async def media(request):
        root = media_dir.resolve()
        path = (root / request.match_info["path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path)

    async def websocket(request):
        ws = web.WebSocketResponse(max_msg_size=64 * 1024 * 1024, heartbeat=30)
        await ws.prepare(request)
        connection = Connection(ws)
        try:
            async for message in ws:
                if message.type != WSMsgType.TEXT:
                    continue
                try:
                    msg = json.loads(message.data)
                except ValueError:
                    continue
                if isinstance(msg, dict):
                    dispatch(hass, connection, msg)
        finally:
            connection.close()
        return ws

    app.router.add_get("/", index)
    app.router.add_get("/static/{name}", static)
    app.router.add_get("/media/local/{path:.+}", media)
    app.router.add_get("/api/websocket", websocket)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
    except OSError:  # port taken (another Pixel Studio?): any free one
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
    port = site._server.sockets[0].getsockname()[1]
    app[ORIGINS].update({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})
    if desktop.coordinator is not None:  # the last display: connect in the background
        async def reconnect():
            try:
                await desktop.coordinator.async_connect()
            except Exception as err:  # noqa: BLE001 - shown in the bar
                desktop.last_error = str(err)
        hass.async_create_task(reconnect())
    return runner, f"http://127.0.0.1:{port}/", hass


async def stop(runner, hass) -> None:
    desktop = hass.data.get("desktop")
    coordinator = desktop.coordinator if desktop else None
    if coordinator is not None:
        try:
            await asyncio.wait_for(coordinator.async_disconnect(), 5)
        except Exception:  # noqa: BLE001
            pass
    await hass.async_stop()
    await runner.cleanup()


async def already_running(port: int) -> str | None:
    """The URL of a Pixel Studio already serving on ``port`` (a second double click)."""
    import aiohttp

    url = f"http://127.0.0.1:{port}/"
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as session:
            async with session.get(url) as response:
                return url if 'id="bt"' in await response.text() else None
    except (aiohttp.ClientError, asyncio.TimeoutError, UnicodeDecodeError):
        return None


async def serve(args) -> None:
    if url := await already_running(args.port):
        print(f"Pixel Studio est deja ouvert : {url}")
        if not args.no_browser:
            webbrowser.open(url)
        return
    home = Path(args.home) if args.home else None
    runner, url, hass = await start(args.port, home and home / "data", home and home / "media")
    print(f"Pixel Studio tourne sur {url}")
    print(f"Galerie : {hass.config.media_dirs['local']}")
    print("Garde cette fenetre ouverte pendant que tu l'utilises ; ferme-la pour quitter.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        await asyncio.Event().wait()
    finally:
        await stop(runner, hass)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur")
    parser.add_argument("--home", help="dossier des donnees et de la galerie (sinon AppData et Documents)")
    parser.add_argument("-v", "--verbose", action="store_true", help="journal detaille")
    args = parser.parse_args(argv)
    # Before the client library's own logger setup (DEBUG for everything).
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(serve(args))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
