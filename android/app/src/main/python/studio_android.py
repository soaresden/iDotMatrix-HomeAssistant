"""Pixel Studio on the phone: the PC app's server (desktop/pixel_studio.py, built in as the
``desktop`` package) in the app's service, on 127.0.0.1; the app's page shows it.

The Studio itself is the integration's (built in as ``idmcore``), Bluetooth goes through
Android's (python/bleak, Ble.kt), the phone's calendars are offered as Home Assistant
calendars (phone.py).
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path

_LOGGER = logging.getLogger("pixel_studio")
_state: dict = {}
PORT = 8765


def start(data_dir: str, media_dir: str) -> str:
    """Start the server (once) and return its address; waits until it answers."""
    if "url" in _state:
        return _state["url"]
    ready = threading.Event()

    def run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def main() -> None:
            import idmcore  # noqa: F401 - the Studio's package, built in (pixel_studio makes none then)
            from desktop import pixel_studio

            runner, url, hass = await pixel_studio.start(PORT, Path(data_dir), Path(media_dir))
            from phone import install_phone  # after start: Home Assistant's stand-in is on the path then

            install_phone(hass)
            _state.update(url=url, hass=hass, loop=loop, runner=runner)
            ready.set()
            await asyncio.Event().wait()

        try:
            loop.run_until_complete(main())
        except BaseException as err:  # noqa: BLE001 - said to the app instead of a silent hang
            _LOGGER.exception("Pixel Studio stopped")
            _state["error"] = f"{type(err).__name__}: {err}"
            ready.set()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    threading.Thread(target=run, name="pixel-studio", daemon=True).start()
    ready.wait(120)
    if "error" in _state:
        raise RuntimeError(_state.pop("error"))
    if "url" not in _state:
        raise RuntimeError("Le Studio n'a pas démarré")
    return _state["url"]


def call(kind: str, payload: str = "{}") -> str:
    """One of the Studio's websocket commands, from the app (the notification, the old
    settings brought over); its result as JSON. Blocks until answered."""
    hass, loop = _state["hass"], _state["loop"]

    async def ask():
        from desktop import pixel_studio

        done = loop.create_future()

        class Answer:
            user = pixel_studio.ADMIN
            subscriptions: dict = {}

            def send_message(self, message):
                if not done.done():
                    done.set_result(message)

            def send_result(self, msg_id, result=None):
                self.send_message({"success": True, "result": result})

            def send_error(self, msg_id, code, message, **_details):
                self.send_message({"success": False, "error": message})

        pixel_studio.dispatch(hass, Answer(), {"id": 1, "type": kind, **json.loads(payload)})
        return await asyncio.wait_for(done, 60)

    answer = asyncio.run_coroutine_threadsafe(ask(), loop).result(70)
    return json.dumps(answer, default=str)


def _ask(kind: str, **payload) -> dict:
    """A command's result; HomeAssistantError-like failures as RuntimeError."""
    answer = json.loads(call(kind, json.dumps(payload)))
    if not answer.get("success"):
        raise RuntimeError(answer.get("error") or kind)
    return answer.get("result") or {}


def _phone_file() -> Path:
    return Path(_state["hass"].config.path("phone.json"))


def _phone_data() -> dict:
    try:
        return json.loads(_phone_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _phone_save(**values) -> None:
    _phone_file().write_text(json.dumps({**_phone_data(), **values}), encoding="utf-8")


def status() -> str:
    """What the notification says: {display, connected, screen_on, routine, state} as JSON."""
    try:
        st = _ask("idotmatrix/studio/status")
    except Exception as err:  # noqa: BLE001
        return json.dumps({"error": str(err)})
    return json.dumps({"display": st.get("display"), "connected": st.get("connected"), "screen_on": st.get("screen_on"),
                       "routine": st.get("routine_name"), "state": (st.get("routine") or {}).get("state")})


def screen(on: bool) -> None:
    """The display's screen off (the routine showing stops: remembered) or on again (it starts again)."""
    if not on:
        active = (_ask("idotmatrix/studio/status").get("routine") or {}).get("active")
        _ask("idotmatrix/studio/screen", on=False)  # the frame away: said, nothing remembered
        _phone_save(was_showing=active)
        return
    _ask("idotmatrix/studio/screen", on=True)
    was = _phone_data().get("was_showing")
    if was:
        _phone_save(was_showing=None)
        _ask("idotmatrix/studio/routine_start", routine_id=was)


def bring_over(config_json: str, device_json: str, refresh: int) -> str:
    """Pixel Météo's view (before the Studio) as a Studio weather view, on its display, started.
    Once: returns what was done."""
    from phone import BIRTHDAYS, PREFIX

    if _phone_data().get("brought_over"):
        return "déjà fait"
    done = []
    routine = None
    if config_json:
        cfg = json.loads(config_json)
        calendars = [f"{PREFIX}{i}" for i in cfg.pop("agenda_device", None) or []]
        if cfg.pop("contacts_birthdays", False):
            calendars.append(BIRTHDAYS)
        cfg["agenda_calendars"] = list(dict.fromkeys(list(cfg.get("agenda_calendars") or []) + calendars))
        routine = {"id": "meteo-telephone", "name": "Météo", "files": [], "order": "sequence", "mode": "weather",
                   "interval": max(900, min(3600, int(refresh or 1800))), "weather": cfg}
        _ask("idotmatrix/studio/routine_save", routine=routine)
        done.append("vue météo")
    _phone_save(brought_over=True)  # the view is kept: the display, if away, is chosen again by hand
    if device_json:
        device = json.loads(device_json)
        try:
            _ask("desktop/connect", address=device["address"], name=device.get("name") or device["address"],
                 size=int(device.get("size") or 64))
            done.append("cadre")
        except Exception:  # noqa: BLE001 - away or off (or slow to say so): still the display chosen
            done.append("cadre (absent)")
        if routine:
            try:
                _ask("idotmatrix/studio/routine_start", routine_id=routine["id"])
                done.append("lancée")
            except Exception:  # noqa: BLE001
                pass
    return ", ".join(done) or "rien"


def add_note(text: str) -> str:
    """A text shared to the app (a Keep note...): a note on the weather view showing (else the first)."""
    routines = _ask("idotmatrix/studio/routines")
    views = [r for r in routines.get("routines") or [] if r.get("mode") == "weather"]
    if not views:
        raise RuntimeError("Fais d'abord une vue météo dans le Studio")
    active = (routines.get("status") or {}).get("active")
    view = next((r for r in views if r["id"] == active), views[0])
    weather = dict(view["weather"])
    weather["notes"] = [*(weather.get("notes") or []), text[:200]]
    _ask("idotmatrix/studio/routine_save", routine={**view, "weather": weather})
    return view["name"]
