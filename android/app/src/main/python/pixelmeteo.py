"""Pixel Météo's Python side: the Studio's weather module (meteo.py), unchanged.

The Android app (Kotlin) calls these functions through Chaquopy. The places
come from Open-Meteo (free, no key): a phone has no Home Assistant, so each
profile is a place typed in and geocoded. Forecasts are cached here; the
app asks for the GIF of each minute and sends it over Bluetooth itself.
"""
from __future__ import annotations

import base64
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from idm import meteo, pages

_cache: dict[tuple, meteo.Forecast] = {}
# When a place's fetch last failed: not asked again for a while, so a minute without
# network is not held up by a request that waits for its timeout.
_failed: dict[tuple, float] = {}
RETRY_AFTER = 300


def _get(url: str, params: dict) -> dict:
    request = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": "PixelMeteo/0.1"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def geocode(query: str) -> str:
    """Places matching a name, as JSON: [{name, latitude, longitude}]."""
    data = _get(meteo.GEOCODE_URL, {"name": query.strip(), "count": 6, "language": "fr", "format": "json"})
    return json.dumps([{"name": meteo._place_name(r), "latitude": r["latitude"], "longitude": r["longitude"]}
                       for r in data.get("results") or [] if r.get("latitude") is not None])


def _forecast(profile: dict, max_age: float, offline: bool = True) -> meteo.Forecast:
    """A place's forecast, fetched again once older than ``max_age`` seconds.

    Without network (``offline``), the last one however old, else a placeholder:
    the time goes on, the weather shows as dashes until it can be fetched.
    """
    place = profile.get("place")
    if profile.get("source") != "place" or not place:
        raise ValueError("Choisis une ville")
    key = (place["latitude"], place["longitude"])
    cached = _cache.get(key)
    if cached is not None and time.time() - cached.fetched < max_age:
        return cached
    if offline and time.time() - _failed.get(key, 0) < RETRY_AFTER:
        return cached or meteo.placeholder(profile.get("label") or place["name"])
    try:
        data = _get(meteo.FORECAST_URL, {
            "latitude": place["latitude"], "longitude": place["longitude"], "timezone": "auto",
            "forecast_days": meteo.DAY_SLOTS + 1,
            "current": "temperature_2m,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
            "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
        })
        forecast = _cache[key] = meteo.parse_open_meteo(data, place["name"])
        return forecast
    except Exception:  # noqa: BLE001 - no network, a bad answer...
        _failed[key] = time.time()
        if cached is not None:
            return cached
        if offline:
            return meteo.placeholder(profile.get("label") or place["name"])
        raise


# Calendar files (saints, world days, the agenda's): url -> (when fetched, text), kept without network.
_ics: dict[str, tuple[float, str]] = {}
ICS_MAX_AGE = 6 * 3600


def _fetch_ics(cfg: dict, max_age: float = ICS_MAX_AGE) -> None:
    for url in pages.ics_urls(cfg):
        fetched, _text = _ics.get(url, (0.0, ""))
        if time.time() - fetched < max_age or time.time() - _failed.get(url, 0) < RETRY_AFTER:
            continue
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "PixelMeteo/0.1"})
            with urllib.request.urlopen(request, timeout=30) as response:
                _ics[url] = (time.time(), response.read().decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 - kept as it was
            _failed[url] = time.time()


def _phone(agenda_json: str | None) -> dict:
    """What the app reads on the phone: {events: [...], birthdays: [...]} (an older app: the events)."""
    if not agenda_json:
        return {}
    data = json.loads(agenda_json)
    return data if isinstance(data, dict) else {"events": data}


def _device_agenda(agenda_json: str | None) -> list | None:
    """Today's events of the phone's calendars, as the app reads them: [{title, begin, end, all_day}] (ms)."""
    events = _phone(agenda_json).get("events")
    if not events:
        return None
    local = meteo.local_now().tzinfo
    items = []
    for event in events:
        if event.get("all_day"):
            items.append(pages.Occurrence(event.get("title") or "", None, None))
        else:
            begin = datetime.fromtimestamp(event["begin"] / 1000, local)
            end = datetime.fromtimestamp(event["end"] / 1000, local) if event.get("end") else None
            items.append(pages.Occurrence(event.get("title") or "", begin, end))
    return items


def _extras(cfg: dict, agenda_json: str | None = None) -> pages.Extras:
    """Today's pages from the calendar files at hand and the phone's calendars (no network here)."""
    extras = pages.build_extras(cfg, {url: text for url, (_t, text) in _ics.items()}, meteo.local_now(),
                                _device_agenda(agenda_json))
    extras.birthdays = _phone(agenda_json).get("birthdays") or None
    return extras


def _view(cfg_json: str) -> dict:
    return meteo.WEATHER_SCHEMA(json.loads(cfg_json))


def _forecasts(cfg: dict, max_age: float, offline: bool = True) -> list[meteo.Forecast]:
    return [_forecast(profile, max_age, offline) for profile in cfg["profiles"]]


def refresh(cfg_json: str, max_age: float) -> str:
    """Fetch what is older than ``max_age`` seconds; returns what the app shows about it."""
    cfg = _view(cfg_json)
    _fetch_ics(cfg)
    forecasts = _forecasts(cfg, max_age, offline=False)  # the app says when it fails
    return json.dumps([f.summary() for f in forecasts])


def minute_gif(cfg_json: str, size: int, lead: float, agenda_json: str = "", screen: int = -1) -> bytes:
    """The GIF of the rest of this minute, drawn from the second it will arrive (``lead`` s from now).
    ``screen``: that screen only (the app follows the one being set), else all in turn."""
    cfg = _view(cfg_json)
    if 0 <= screen < len(cfg.get("screens") or []):
        cfg = {**cfg, "screens": [{**cfg["screens"][screen], "from": None, "to": None}]}
    if any(url not in _ics for url in pages.ics_urls(cfg)):  # a calendar page just switched on
        _fetch_ics(cfg)
    forecasts = _forecasts(cfg, 3600 * 6)  # the cached ones: refresh() keeps them fresh
    start = meteo.local_now() + timedelta(seconds=lead)
    return meteo.render_meteo_minute(forecasts, start, cfg, int(size), meteo.labels_of(cfg, forecasts),
                                     _extras(cfg, agenda_json))


def brightness(cfg_json: str) -> int:
    """The day or night brightness for now (-1: leave it alone)."""
    cfg = _view(cfg_json)
    wanted = meteo.brightness_for(cfg, _forecasts(cfg, 3600 * 6), meteo.local_now())
    return -1 if wanted is None else wanted


def preview(cfg_json: str, size: int, max_age: float, minute: bool, agenda_json: str = "", page: int = -1) -> str:
    """The screen now (PNG), what each place says, and how heavy a minute is."""
    cfg = _view(cfg_json)
    forecasts = _forecasts(cfg, max_age)
    now = meteo.local_now()
    if minute:  # the settings changed: a calendar may have been switched on
        _fetch_ics(cfg)
    extras = _extras(cfg, agenda_json)
    png, boxes = meteo.preview_of(forecasts, now, cfg, int(size), extras, page if page >= 0 else None)
    titles, index = boxes.pop("_pages"), boxes.pop("_page")
    result = {"png": "data:image/png;base64," + base64.b64encode(png).decode(),
              "forecasts": [f.summary() for f in forecasts], "boxes": boxes, "titles": titles, "page": index,
              # Today's lists, to pick from in the app.
              "today": {"saints": extras.saints or [], "world_days": extras.world_days or [],
                        "date": now.date().isoformat(),
                        # What the phone's calendars give today (to see that they are read).
                        "agenda": [(f"{o.start.astimezone(now.tzinfo):%H:%M} " if o.start else "") + o.summary
                                   for o in _device_agenda(agenda_json) or []],
                        "calendars": len(cfg.get("agenda_device") or [])}}
    if minute:
        result["minute_bytes"] = len(meteo.render_meteo_minute(
            forecasts, now.replace(second=0), cfg, int(size), meteo.labels_of(cfg, forecasts), extras))
    result["pages"] = [p["kind"] for p in pages.extra_pages(cfg, extras, now)]
    return json.dumps(result)


def diagnose(cfg_json: str, size: int, agenda_json: str = "") -> str:
    """Everything the engine makes of the settings now, for the diagnostic zip: each step's result
    or its error, and an image of each screen (``images``: name -> PNG in base64)."""
    import traceback

    out: dict = {"heure": meteo.local_now().isoformat(), "erreurs": [], "images": {}}

    def step(name, work):
        try:
            out[name] = work()
        except Exception:  # noqa: BLE001 - every step's error goes in the report
            out["erreurs"].append(f"{name} :\n{traceback.format_exc()}")
            return None
        return out[name]

    out["recu_du_telephone"] = agenda_json or "(rien)"
    cfg = step("reglages_valides", lambda: _view(cfg_json))
    if cfg is None:
        return json.dumps(out, ensure_ascii=False, default=str)
    phone = step("agenda_du_telephone", lambda: [
        {"titre": o.summary, "debut": o.start, "fin": o.end} for o in _device_agenda(agenda_json) or []])
    out["calendriers_en_ligne"] = {url: {"il_y_a_s": round(time.time() - t), "taille": len(text)}
                                   for url, (t, text) in _ics.items()}
    out["echecs_reseau"] = {key if isinstance(key, str) else repr(key): round(time.time() - t) for key, t in _failed.items()}
    extras = step("extras", lambda: _extras(cfg, agenda_json))
    if extras is not None:
        out["extras"] = {"agenda": [{"titre": o.summary, "debut": o.start} for o in extras.agenda or []]
                         if extras.agenda is not None else None,
                         "saints": extras.saints, "journees": extras.world_days, "anniversaires": extras.birthdays}
    forecasts = step("previsions", lambda: [f.summary() for f in _forecasts(cfg, 3600 * 6)]) and _forecasts(cfg, 3600 * 6)
    now = meteo.local_now()
    step("pages_du_jour", lambda: pages.extra_pages(cfg, extras, now))
    if forecasts:
        turns = step("ecrans", lambda: [{"numero": t.get("screen"), "titre": meteo.page_title(t, meteo.labels_of(cfg, forecasts)),
                                         "rien_maintenant": t.get("off"), "parties": list(t.get("parts", {})),
                                         "pages": {k: str(v)[:500] for k, v in (t.get("pages") or {}).items()}}
                                        for t in meteo.page_list(forecasts, cfg, extras, now, every=True)])
        for n in range(len(cfg.get("screens") or [])):
            png = step(f"image_ecran_{n + 1}", lambda n=n: base64.b64encode(
                meteo.preview_of(forecasts, now, cfg, int(size), extras, n)[0]).decode())
            if png:
                out["images"][f"ecran-{n + 1}"] = png
                out.pop(f"image_ecran_{n + 1}", None)
        step("ecran_affiche_maintenant", lambda: meteo.turn_at(meteo.page_list(forecasts, cfg, extras, now), cfg, now))
    del phone
    return json.dumps(out, ensure_ascii=False, default=str)
