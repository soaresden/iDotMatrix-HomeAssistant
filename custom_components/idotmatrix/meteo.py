"""Météo: the time and the day ahead on the display, for Pixel Studio.

The screen shows the time in large digits, today's conditions (icon,
temperature now, high and low, chance of rain) and a strip with the next
hours or the next days, under the name of the place. Several places
(profiles) can take turns every few seconds, and the seconds can tick.
One GIF is sent each minute holding that whole minute, one image per
second (or per place when the seconds are off): the display plays it by
itself, so there is no Bluetooth traffic in between. Each later image only
redraws what changed (the seconds, or the place when it turns), so it
takes one or two 4 KB packets (0.6 to 1.2 s). The forecast
behind it is fetched every 15 to 60 minutes from a Home Assistant weather
entity (``weather.get_forecasts``) or from Open-Meteo (free, no key) for a
zone, Home Assistant's home or a place typed in and geocoded; Open-Meteo is
the only source of the Windows build, which has no Home Assistant.

Reuses the weather dashboard's icons, pixel font and device-safe GIF
encoder (weather.py).
"""
from __future__ import annotations

import asyncio
import io
import logging
import math
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import voluptuous as vol
from PIL import Image, ImageChops, ImageDraw

from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

from . import emoji
from . import pages as pages_mod
from .weather import (
    PAL,
    _cloud,
    WeatherData,
    _draw_text,
    _render_icon,
    _temp_color,
    _text_width,
    frames_to_gif,
    normalize_condition,
)

try:  # Home Assistant's time zone; the Windows build uses the PC's
    from homeassistant.util import dt as dt_util
except ImportError:  # pragma: no cover - desktop build
    dt_util = None

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
# The label of the minute sends, for the panel and the log (they are not files).
SEND_LABEL = "météo"
PACKET_BYTES = 4096
ICS_MAX_AGE = 6 * 3600  # calendar files (saints, world days, an agenda) fetched again after
HOUR_STEP = 3      # the strip's hours: in 3, 6, 9 and 12 hours
HOUR_SLOTS = 4
DAY_SLOTS = 3
CLOCK_COLOR = (120, 190, 255)
NO_WEATHER = "none"  # a placeholder forecast's condition: no icon
NAME_COLOR = (230, 225, 200)
DATE_COLOR = (150, 160, 180)
DIM = (110, 115, 130)
WEEKDAYS = ("LU", "MA", "ME", "JE", "VE", "SA", "DI")

_COORDINATES = vol.Schema({
    vol.Required("name"): vol.All(str, vol.Length(min=1, max=120)),
    vol.Required("latitude"): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
    vol.Required("longitude"): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
})


def _needs_its_place(cfg: dict) -> dict:
    """An entity, a zone or a place goes with the source that names it."""
    needed = {"entity": "entity_id", "zone": "zone", "place": "place"}.get(cfg["source"])
    if needed and not cfg.get(needed):
        raise vol.Invalid("Choisis d'où vient la météo")
    return cfg


PROFILE_KEYS = ("source", "entity_id", "zone", "place", "label")
MAX_PROFILES = 12  # a city per screen

PROFILE_SCHEMA = vol.All(vol.Schema({
    # home: Home Assistant's weather entity, else Open-Meteo at its home location.
    vol.Optional("source", default="home"): vol.In(("home", "entity", "zone", "place")),
    vol.Optional("entity_id"): vol.Any(None, vol.Match(r"^weather\.\w+$")),
    vol.Optional("zone"): vol.Any(None, vol.Match(r"^zone\.\w+$")),
    vol.Optional("place"): vol.Any(None, _COORDINATES),
    # The name written on the screen (else the place's own).
    vol.Optional("label"): vol.Any(None, vol.All(str, vol.Length(max=40))),
}), _needs_its_place)


def _one_place_at_the_top(cfg) -> dict:
    """A view saved with one place (before profiles) gets it as its only profile."""
    if not isinstance(cfg, dict):
        raise vol.Invalid("expected a dictionary")
    cfg = dict(cfg)
    single = {key: cfg.pop(key) for key in PROFILE_KEYS if key in cfg}
    if not cfg.get("profiles"):
        cfg["profiles"] = [single]
    return cfg


# The parts a screen is made of: the weather view's, and the pages' blocks (pages.py).
WEATHER_PARTS = ("clock", "seconds", "date", "name", "today", "strip", "days", "sun")
# The strips a screen can have besides « En bas » (whose kind the view sets): each always this kind.
EXTRA_STRIPS = ("days", "sun")
PAGE_PARTS = ("special", "birthdays", "agenda", "saint", "world_days", *pages_mod.TEXT_KINDS, "countdown",
              "reminders", "notes")
WEEKEND_STARTS = (4, 18)  # Friday, 18:00
SLIDE_SECONDS = 3  # names that do not fit at once take turns this often
# The pages' switches, as the screens set them (the calendars are fetched for those switched on).
_PAGE_SWITCHES = {"special": "special_days", "birthdays": "birthday_page", "agenda": "agenda", "saint": "saints",
                  "world_days": "world_days", **{kind: kind for kind in pages_mod.TEXT_KINDS}}
MAX_SCREENS = 20
# « + »: an empty screen, or one of these to start from (then edited at will).
SCREEN_PRESETS = {
    "empty": [],
    "weather": ["clock", "date", "name", "today", "strip"],
    **{kind: ["clock", kind] for kind in PAGE_PARTS},
}


def countdown_text(target: str | None, now: datetime) -> tuple[str, bool] | None:
    """What a countdown says at ``now`` (« J-61 », « 1 J 5 H », « 5 H 12 »...) and whether its
    moment has come (the day itself, the weekend going on); None when it is over or unset."""
    if not target:
        return None
    if target == "weekend":
        day, hour = WEEKEND_STARTS
        start = (now - timedelta(days=(now.weekday() - day) % 7)).replace(hour=hour, minute=0, second=0, microsecond=0)
        if start > now:
            start -= timedelta(days=7)
        if now < start + timedelta(days=2, hours=24 - hour):  # Friday evening to Sunday night
            return "", True
        start += timedelta(days=7)
    else:
        try:
            start = datetime.fromisoformat(target)
        except ValueError:
            return None
        start = start.replace(tzinfo=now.tzinfo)
        if start.date() == now.date() and ("T" not in target or now >= start):
            return "", True
        if start < now:
            return None
    left = start - now
    days = left.days
    if target != "weekend" and (days >= 2 or (days >= 1 and "T" not in target)):
        return f"J-{(start.date() - now.date()).days}", False
    hours, minutes = left.seconds // 3600, left.seconds % 3600 // 60
    return (f"{days} J {hours} H" if days else f"{hours} H {minutes:02d}"), False


def _screens_switch_pages(cfg: dict) -> dict:
    """With screens filled by hand, the pages on are those on a screen, and only those."""
    if cfg.get("screens"):
        kinds = {part for screen in cfg["screens"] for part in screen["parts"]}
        for kind, switch in _PAGE_SWITCHES.items():
            cfg[switch] = kind in kinds
        cfg["agenda"] = bool({"agenda", "reminders"} & kinds)  # « N'oubliez pas » lists the agenda too
    return cfg


def reminders_on(day: date, reminders: list[dict] | None) -> list[str]:
    """The reminders typed in for ``day``: each week on its days (0 Monday), or on its date."""
    found = []
    for reminder in reminders or []:
        when = reminder.get("date") or ""
        if when:
            parts = when.split("-")
            if [int(p) for p in parts[-2:]] != [day.month, day.day] or (len(parts) == 3 and int(parts[0]) != day.year):
                continue
        elif day.weekday() not in (reminder.get("days") or range(7)):
            continue
        found.append(reminder["text"])
    return found


PART_SCHEMA = vol.Schema({
    vol.Optional("dx", default=0): vol.All(vol.Coerce(int), vol.Range(min=-63, max=63)),
    vol.Optional("dy", default=0): vol.All(vol.Coerce(int), vol.Range(min=-63, max=63)),
    vol.Optional("size"): vol.All(vol.Coerce(int), vol.Range(min=1, max=3)),
    vol.Optional("hidden", default=False): bool,
    # The name only: where it sits on its row.
    vol.Optional("align"): vol.In(("left", "center", "right")),
    # A line of that colour around it (black letters show with one: a black LED is off).
    vol.Optional("outline"): vol.Any(None, vol.Match(r"^#[0-9a-fA-F]{6}$")),
    # The countdown's words (« Vacances aux Maldives »), the name's own text on this screen.
    vol.Optional("title"): vol.Any(None, vol.All(str, vol.Length(max=40))),
    vol.Optional("date"): vol.Any(None, vol.Match(r"^(weekend|\d{4}-\d{2}-\d{2}(T\d{2}:\d{2})?)$")),
})

WEATHER_SCHEMA = vol.All(_one_place_at_the_top, vol.Schema({
    vol.Required("profiles"): vol.All([PROFILE_SCHEMA], vol.Length(min=1, max=MAX_PROFILES)),
    # The screens in turn, in this order, each for its own time (none: each place's weather,
    # then the pages switched on, as before).
    vol.Optional("screens"): vol.Any(None, vol.All([{
        # Its parts (drawn in this order), each placed like the layout's.
        vol.Optional("parts", default=dict): {vol.In(WEATHER_PARTS + PAGE_PARTS): PART_SCHEMA},
        # Whose weather its weather parts show.
        vol.Optional("place", default=0): vol.All(vol.Coerce(int), vol.Range(min=0, max=MAX_PROFILES - 1)),
        vol.Optional("seconds", default=15): vol.All(vol.Coerce(int), vol.Range(min=1, max=600)),
        # Only between these hours (from 6 to 10: the morning; from 22 to 6 goes over midnight).
        vol.Optional("from"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=0, max=23))),
        vol.Optional("to"): vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=0, max=24))),
    }], vol.Length(max=MAX_SCREENS))),
    # Notes typed in (or shared to the app from Keep...): just text.
    vol.Optional("notes", default=list): vol.All([vol.All(str, vol.Length(min=1, max=200))], vol.Length(max=30)),
    # « N'oubliez pas » : reminders each week on some days (0 Monday), or on a date (2026-12-24, 12-24).
    vol.Optional("reminders", default=list): vol.All([{
        vol.Required("text"): vol.All(str, vol.Length(min=1, max=60)),
        vol.Optional("days"): vol.Any(None, [vol.All(vol.Coerce(int), vol.Range(min=0, max=6))]),
        vol.Optional("date"): vol.Any(None, vol.Match(r"^(\d{4}-)?\d{2}-\d{2}$")),
    }], vol.Length(max=40)),
    # The saint's page: its title, and « À » / « AUX » after it (or not).
    vol.Optional("saint_title", default="BONNE FÊTE"): vol.All(str, vol.Length(max=24)),
    vol.Optional("saint_to", default=True): bool,
    # How long each place stays before the next one, in seconds.
    vol.Optional("switch_seconds", default=15): vol.All(vol.Coerce(int), vol.Range(min=1, max=600)),
    # Each place's screen shows the time there (its own time zone), with its weather.
    vol.Optional("city_time", default=True): bool,
    # The mixing desk: how long each page stays, in seconds (weather:0, weather:1, agenda, special...).
    vol.Optional("durations", default=dict): {vol.All(str, vol.Length(max=20)): vol.All(vol.Coerce(int), vol.Range(min=1, max=600))},
    vol.Optional("seconds", default=True): bool,
    # Today's icon moves (rain falling, the sun's rays): images every half second.
    vol.Optional("animate", default=True): bool,
    vol.Optional("clock_color", default="#78beff"): vol.Match(r"^#[0-9a-fA-F]{6}$"),
    # The time in figures, or on two cards that flip each minute (HTC Sense).
    vol.Optional("clock_style", default="digits"): vol.In(("digits", "flip")),
    # The seconds: figures, a bar filling up, or a ring with the figures in it (auto: figures, a bar on cards).
    vol.Optional("seconds_style", default="auto"): vol.In(("auto", "digits", "bar", "ring")),
    vol.Optional("seconds_color"): vol.Any(None, vol.Match(r"^#[0-9a-fA-F]{6}$")),
    # Pages taking turns with the weather (pages.py).
    vol.Optional("special_days", default=True): bool,
    # The birthdays on a page of their own, not with the special days.
    vol.Optional("birthday_page", default=False): bool,
    vol.Optional("birthdays", default=list): vol.All([{
        vol.Required("name"): vol.All(str, vol.Length(min=1, max=40)),
        vol.Required("date"): vol.Match(r"^(\d{4}-)?\d{2}-\d{2}$"),
    }], vol.Length(max=50)),
    vol.Optional("agenda", default=False): bool,
    vol.Optional("agenda_style", default="list"): vol.In(("list", "timeline")),
    # The agenda's heading (empty: none), the day at its right, each appointment's time.
    vol.Optional("agenda_title", default="AGENDA"): vol.All(str, vol.Length(max=20)),
    vol.Optional("agenda_day", default=True): bool,
    vol.Optional("agenda_time", default=True): bool,
    # The world days' heading (empty: « J. MONDIALE » or « J. INTERNATIONALE » as the day says).
    vol.Optional("world_days_title", default=""): vol.All(str, vol.Length(max=24)),
    # How fast a title too long slides (5, 10, 16 or 24 LEDs a second).
    vol.Optional("scroll_speed", default="normal"): vol.In(("slow", "normal", "fast", "faster")),
    vol.Optional("agenda_calendars", default=list): [vol.Match(r"^calendar\.\w+$")],
    vol.Optional("agenda_ics", default=list): vol.All([vol.Match(r"^(https?|webcal)://")], vol.Length(max=5)),
    vol.Optional("saints", default=False): bool,
    vol.Optional("world_days", default=False): bool,
    vol.Optional("thought", default=False): bool,
    vol.Optional("proverb", default=False): bool,
    vol.Optional("fact", default=False): bool,
    vol.Optional("motivation", default=False): bool,
    vol.Optional("humor", default=False): bool,
    vol.Optional("wellbeing", default=False): bool,
    vol.Optional("word", default=False): bool,
    # Android: the phone's calendars to show (their ids), read with the calendar permission.
    vol.Optional("agenda_device", default=list): [vol.All(vol.Coerce(str), vol.Length(max=20))],
    # Appointments typed in the app (with the phone's): a title, a day, a time (none: all day).
    vol.Optional("events", default=list): vol.All([{
        vol.Required("title"): vol.All(str, vol.Length(min=1, max=60)),
        vol.Required("date"): vol.Match(r"^\d{4}-\d{2}-\d{2}$"),
        vol.Optional("time"): vol.Any(None, vol.Match(r"^\d{2}:\d{2}$")),
    }], vol.Length(max=100)),
    # Today's saints and world days picked in the app (for that date only).
    vol.Optional("pick"): vol.Any(None, {
        vol.Required("date"): vol.Match(r"^\d{4}-\d{2}-\d{2}$"),
        vol.Optional("saints", default=list): [vol.All(str, vol.Length(max=80))],
        vol.Optional("world_days", default=list): [vol.All(str, vol.Length(max=200))],
    }),
    # Pixel Météo: the birthdays of the phone's contacts too.
    vol.Optional("contacts_birthdays", default=False): bool,
    # Today's details left out: the icon, the temperature, the high and low, the drop.
    vol.Optional("today_hide", default=list): [vol.In(("icon", "temp", "minmax", "drop"))],
    # What the drop by today's weather counts: the chance of rain, or the humidity.
    vol.Optional("drop", default="rain"): vol.In(("rain", "humidity")),
    # Each part moved (in LEDs), resized (1 small, 2 big) or hidden.
    vol.Optional("layout"): vol.Any(None, {vol.Optional(part): PART_SCHEMA for part in WEATHER_PARTS + ("page",)}),
    # Under today: the next hours, the next days, or sunrise and sunset.
    vol.Optional("strip", default="hours"): vol.In(("hours", "days", "sun")),
    # The strip's 4 hours: every N hours from now, or these hours of the day.
    vol.Optional("hours_step", default=3): vol.All(vol.Coerce(int), vol.In((1, 2, 3, 4, 6))),
    vol.Optional("hours_at"): vol.Any(None, vol.All([vol.All(vol.Coerce(int), vol.Range(min=0, max=23))],
                                                    vol.Length(min=1, max=HOUR_SLOTS))),
    vol.Optional("hour24", default=True): bool,
    # Formats typed in (empty: the usual ones). Date: dddd ddd ww dd d mmmm mmm mm m yyyy yy;
    # time: HH H hh h mm ss tt.
    vol.Optional("date_format", default=""): vol.All(str, vol.Length(max=30)),
    vol.Optional("time_format", default=""): vol.All(str, vol.Length(max=20)),
    # Brightness by day and by night (the first place's sunrise and sunset), in %.
    vol.Optional("brightness"): vol.Any(None, {
        vol.Required("day"): vol.All(vol.Coerce(int), vol.Range(min=5, max=100)),
        vol.Required("night"): vol.All(vol.Coerce(int), vol.Range(min=5, max=100)),
    }),
}), _screens_switch_pages)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Slot:
    """One column of the strip: an hour ahead or a day ahead."""

    label: str
    condition: str
    temperature: float | None = None  # hours
    high: float | None = None         # days
    low: float | None = None


@dataclass
class Hour:
    """One hour of the forecast; its time is aware, in the place's time zone."""

    time: datetime
    condition: str
    temperature: float | None = None


@dataclass
class Forecast:
    place: str
    now: WeatherData
    rain: int | None = None        # chance of rain in the next 12 hours, %
    rain_mm: float | None = None   # when the source gives no chance (met.no)
    hours: list[Hour] = field(default_factory=list)  # from this hour on: the strip picks its 4
    days: list[Slot] = field(default_factory=list)
    fetched: float = 0.0
    # Sunrises and sunsets ahead: (aware time, "rise" or "set"), in order.
    sun: list[tuple[datetime, str]] = field(default_factory=list)
    # The place's own time zone (Open-Meteo's), None: here's.
    zone: timezone | None = None

    def summary(self) -> dict:
        """What the panel says about it."""
        return {
            "place": self.place, "condition": self.now.condition,
            "temperature": self.now.temperature, "unit": self.now.temp_unit,
            "high": self.now.high, "low": self.now.low, "rain": self.rain, "rain_mm": self.rain_mm,
            "humidity": self.now.humidity,
            "fetched": self.fetched,
        }


# Open-Meteo's WMO weather codes -> the dashboard's conditions.
_WMO = {
    0: "sunny", 1: "sunny", 2: "partlycloudy", 3: "cloudy", 45: "fog", 48: "fog",
    51: "rainy", 53: "rainy", 55: "rainy", 56: "snowy-rainy", 57: "snowy-rainy",
    61: "rainy", 63: "rainy", 65: "pouring", 66: "snowy-rainy", 67: "snowy-rainy",
    71: "snowy", 73: "snowy", 75: "snowy", 77: "snowy", 80: "rainy", 81: "rainy", 82: "pouring",
    85: "snowy", 86: "snowy", 95: "lightning-rainy", 96: "hail", 99: "hail",
}


def placeholder(place: str) -> Forecast:
    """No forecast to be had (no network yet): the time still shows, the weather as dashes."""
    return Forecast(place, WeatherData(NO_WEATHER), fetched=0.0)


def placeholders(cfg: dict) -> list[Forecast]:
    """One placeholder per place of the view, named as the screen would name it."""
    out = []
    for profile in cfg["profiles"]:
        place = profile.get("place") or {}
        out.append(placeholder(profile.get("label") or place.get("name") or profile.get("entity_id")
                               or profile.get("zone") or "Maison"))
    return out


def wmo_condition(code, is_day=1) -> str:
    condition = _WMO.get(int(code), "exceptional") if code is not None else "unknown"
    return "clear-night" if condition == "sunny" and not is_day else condition


def _at(values: list | None, index: int):
    return values[index] if values and 0 <= index < len(values) else None


def _max(values) -> int | None:
    known = [v for v in values if v is not None]
    return round(max(known)) if known else None


def parse_open_meteo(data: dict, place: str) -> Forecast:
    """An Open-Meteo forecast (times are the place's own, ``timezone=auto``)."""
    current = data.get("current") or {}
    hourly = data.get("hourly") or {}
    daily = data.get("daily") or {}
    if current.get("time") is None:
        raise ValueError("Open-Meteo did not send the current weather")
    unit = (data.get("current_units") or {}).get("temperature_2m") or "°C"
    now = WeatherData(
        condition=wmo_condition(current.get("weather_code"), current.get("is_day", 1)),
        temperature=current.get("temperature_2m"), temp_unit=unit,
        humidity=current.get("relative_humidity_2m"), wind_speed=current.get("wind_speed_10m"),
        high=_at(daily.get("temperature_2m_max"), 0), low=_at(daily.get("temperature_2m_min"), 0),
    )
    zone = timezone(timedelta(seconds=int(data.get("utc_offset_seconds") or 0)))

    def at(text: str) -> datetime:
        return datetime.fromisoformat(text).replace(tzinfo=zone)

    times = hourly.get("time") or []
    this_hour = current["time"][:13]
    start = next((i for i, t in enumerate(times) if t[:13] >= this_hour), len(times))
    rain = _max((hourly.get("precipitation_probability") or [])[start:start + 12])
    if rain is None:
        rain = _at(daily.get("precipitation_probability_max"), 0)
    hours = [Hour(at(times[i]), wmo_condition(_at(hourly.get("weather_code"), i), _at(hourly.get("is_day"), i)),
                  _at(hourly.get("temperature_2m"), i)) for i in range(start, len(times))]
    sun = sorted([(at(t), "rise") for t in daily.get("sunrise") or [] if t]
                 + [(at(t), "set") for t in daily.get("sunset") or [] if t])
    days = []
    for i, day in enumerate((daily.get("time") or [])[1:DAY_SLOTS + 1], start=1):
        days.append(Slot(WEEKDAYS[date.fromisoformat(day).weekday()], wmo_condition(_at(daily.get("weather_code"), i)),
                         high=_at(daily.get("temperature_2m_max"), i), low=_at(daily.get("temperature_2m_min"), i)))
    return Forecast(place, now, rain=rain, hours=hours, days=days, fetched=time.time(), sun=sun, zone=zone)


def _local(value) -> datetime | None:
    """A forecast time as local time, aware."""
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt_util is not None:
        return dt_util.as_local(moment)
    return moment.astimezone()


def parse_ha(state: str, attributes: dict, hourly: list[dict], daily: list[dict], now: datetime,
             place: str, is_night: bool = False, sun: list | None = None) -> Forecast:
    """A Home Assistant weather entity and its forecasts (``weather.get_forecasts``)."""
    today = now.date()
    high = low = None
    days = []
    for entry in daily:
        when = _local(entry.get("datetime"))
        if when is None:
            continue
        if when.date() <= today:
            if when.date() == today:
                high, low = entry.get("temperature"), entry.get("templow")
            continue
        if len(days) < DAY_SLOTS:
            days.append(Slot(WEEKDAYS[when.weekday()], normalize_condition(entry.get("condition")),
                             high=entry.get("temperature"), low=entry.get("templow")))
    ahead = [(when, entry) for entry in hourly
             if (when := _local(entry.get("datetime"))) is not None and when > now - timedelta(hours=1)]
    if high is None and ahead:
        temps = [e.get("temperature") for w, e in ahead if w.date() == today and e.get("temperature") is not None]
        high, low = (max(temps), min(temps)) if temps else (None, None)
    next_12 = [e for w, e in ahead if w < now + timedelta(hours=12)]
    rain = _max(e.get("precipitation_probability") for e in next_12)
    if rain is None and daily:
        rain = _max([daily[0].get("precipitation_probability")])
    rain_mm = None
    if rain is None:
        amounts = [e.get("precipitation") for e in next_12 if e.get("precipitation") is not None]
        rain_mm = round(sum(amounts), 1) if amounts else None
    hours = [Hour(when, normalize_condition(entry.get("condition")), entry.get("temperature")) for when, entry in ahead]
    weather = WeatherData(
        condition=normalize_condition(state, is_night), temperature=attributes.get("temperature"),
        temp_unit=attributes.get("temperature_unit") or "°C", humidity=attributes.get("humidity"),
        wind_speed=attributes.get("wind_speed"), high=high, low=low,
    )
    return Forecast(place, weather, rain=rain, rain_mm=rain_mm, hours=hours, days=days, fetched=time.time(),
                    sun=sorted(sun or []))


def ha_sun(attributes: dict) -> list[tuple[datetime, str]]:
    """Sunrises and sunsets from Home Assistant's sun.sun: the next ones and those of the 3 days after."""
    events = []
    for key, kind in (("next_rising", "rise"), ("next_setting", "set")):
        when = _local(attributes.get(key)) if attributes.get(key) else None
        if when is not None:
            events += [(when + timedelta(days=d), kind) for d in range(4)]
    return sorted(events)


def hour_slots(forecast: Forecast, now: datetime, cfg: dict) -> list[Slot]:
    """The strip's 4 hours: every ``hours_step`` hours from now, or the next of each of ``hours_at``."""
    ahead = [h for h in forecast.hours if h.time > now - timedelta(hours=1)]
    picked = []
    if cfg.get("hours_at"):
        for hour in cfg["hours_at"]:
            match = next((h for h in ahead if h.time > now and h.time.hour == hour), None)
            if match is not None and match not in picked:
                picked.append(match)
        picked.sort(key=lambda h: h.time)
    else:
        step = cfg.get("hours_step", HOUR_STEP)
        for k in range(1, HOUR_SLOTS + 1):
            target = (now + timedelta(hours=k * step)).replace(minute=0, second=0, microsecond=0)
            match = next((h for h in ahead if h.time >= target), None)
            if match is None:
                break
            picked.append(match)
    return [Slot(f"{h.time.hour}H", h.condition, temperature=h.temperature) for h in picked[:HOUR_SLOTS]]


def next_sun(forecast: Forecast, now: datetime) -> tuple[datetime | None, datetime | None]:
    """The next sunrise and the next sunset."""
    rise = next((t for t, kind in forecast.sun if kind == "rise" and t > now), None)
    sunset = next((t for t, kind in forecast.sun if kind == "set" and t > now), None)
    return rise, sunset


def is_daytime(forecast: Forecast, now: datetime) -> bool | None:
    """Whether the sun is up at the place (None when its sunrise and sunset are unknown)."""
    rise, sunset = next_sun(forecast, now)
    if rise is None or sunset is None:
        return None
    return sunset < rise


# ---------------------------------------------------------------------------
# Screen
# ---------------------------------------------------------------------------

# A 3×5 font for the strip, where the 5×7 one does not fit four columns.
_SMALL = {
    "0": ("111", "101", "101", "101", "111"), "1": ("01", "11", "01", "01", "01"),
    "2": ("111", "001", "111", "100", "111"), "3": ("111", "001", "011", "001", "111"),
    "4": ("101", "101", "111", "001", "001"), "5": ("111", "100", "111", "001", "111"),
    "6": ("111", "100", "111", "101", "111"), "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"), "9": ("111", "101", "111", "001", "111"),
    "A": ("010", "101", "111", "101", "101"), "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"), "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"), "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"), "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"), "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"), "L": ("100", "100", "100", "100", "111"),
    "M": ("10001", "11011", "10101", "10001", "10001"), "N": ("1001", "1101", "1011", "1001", "1001"),
    "O": ("010", "101", "101", "101", "010"), "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "110", "011"), "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"), "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"), "V": ("101", "101", "101", "101", "010"),
    "W": ("10001", "10001", "10101", "11011", "10001"), "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"), "Z": ("111", "001", "010", "100", "111"),
    "°": ("11", "11", "00", "00", "00"), "%": ("101", "001", "010", "100", "101"),
    "-": ("000", "000", "111", "000", "000"), "/": ("001", "001", "010", "100", "100"),
    ".": ("0", "0", "0", "0", "1"), "'": ("1", "1", "0", "0", "0"), ":": ("0", "1", "0", "1", "0"),
    " ": ("0", "0", "0", "0", "0"),
}


def _small_width(text: str) -> int:
    return sum(len(_SMALL.get(ch, _SMALL[" "])[0]) + 1 for ch in text) - 1 if text else 0


def _draw_small(d: ImageDraw.ImageDraw, x: int, y: int, text: str, color: tuple) -> int:
    for ch in text:
        rows = _SMALL.get(ch, _SMALL[" "])
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit == "1":
                    d.point((x + c, y + r), fill=color)
        x += len(rows[0]) + 1
    return x


def _small_text(text: str) -> str:
    """Capitals without accents, in the small font's letters."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()
    return "".join(ch if ch in _SMALL else " " for ch in text)


def screen_name(text: str | None, width: int = 64) -> str:
    """A place's name as the small font writes it: capitals, no accents, cut to fit (emoji left out).

    « Forecast Maison » (met.no's entity) is « MAISON », « Lyon, Rhône, France » is « LYON ».
    """
    return "".join(part for part, is_emoji in _name_parts(text, width, 0) if not is_emoji).strip()


def _name_parts(text: str | None, width: int, emoji_size: int, big: bool = False) -> list[tuple[str, bool]]:
    """The name as runs of small-font text and emoji (``emoji_size`` wide, 0: none), cut to ``width``."""
    text = (text or "").split(",")[0].strip()
    if text.lower().startswith("forecast "):
        text = text[9:]
    parts = []
    for piece, is_emoji in emoji.split(text):
        if not is_emoji:
            parts.append((_small_text(piece), False))
        elif emoji_size and emoji.picture(piece, emoji_size) is not None:
            parts.append((piece, True))
    while parts and not parts[0][1] and not parts[0][0].strip():
        parts.pop(0)
    if parts and not parts[0][1]:
        parts[0] = (parts[0][0].lstrip(), False)

    measure = _text_width if big else _small_width

    def wide(items):
        return sum((emoji_size if e else measure(t)) + 1 for t, e in items) - 1 if items else 0

    while parts and wide(parts) > width:
        last, is_emoji = parts[-1]
        if is_emoji or len(last) <= 1:
            parts.pop()
        else:
            parts[-1] = (last[:-1].rstrip(), False)
    return [(t, e) for t, e in parts if e or t]


def _draw_name(img: Image.Image, y: int, text: str | None, size: int, emoji_size: int, big: bool = False,
               align: str = "center", width: int | None = None) -> None:
    """The place's name on row ``y`` (5 px of text, 7 when ``big``; emoji centred on it), centred,
    or along the left or right edge."""
    if big and _name_parts(text, width or size, emoji_size, True) != _name_parts(text, 999, emoji_size, True):
        big = False  # cut in big letters: the whole name in small ones
    parts = _name_parts(text, width or size, emoji_size, big)
    measure = _text_width if big else _small_width
    total = sum((emoji_size if e else measure(t)) + 1 for t, e in parts) - 1 if parts else 0
    d = ImageDraw.Draw(img)
    x = 1 if align == "left" else size - total - 1 if align == "right" else (size - total) // 2
    for piece, is_emoji in parts:
        if is_emoji:
            emoji.paste(img, x, y + 2 - emoji_size // 2, piece, emoji_size)
            x += emoji_size + 1
        elif big:
            x = _draw_text(d, x, y - 1, piece, NAME_COLOR) + 1
        else:
            x = _draw_small(d, x, y, piece, NAME_COLOR) + 1


def _deg(value: float | None) -> str:
    return "--" if value is None else f"{round(value)}°"


def _num(value: float | None) -> str:
    return "-" if value is None else str(round(value))


DAYS_FULL = ("LUNDI", "MARDI", "MERCREDI", "JEUDI", "VENDREDI", "SAMEDI", "DIMANCHE")
MONTHS_FULL = ("JANVIER", "FEVRIER", "MARS", "AVRIL", "MAI", "JUIN", "JUILLET", "AOUT", "SEPTEMBRE", "OCTOBRE",
               "NOVEMBRE", "DECEMBRE")


def format_date(fmt: str, now: datetime) -> str:
    """dddd LUNDI, ddd LUN, ww LU, dd 03, d 3, mmmm NOVEMBRE, mmm NOV, mm 11, m 11, yyyy 2026, yy 26."""
    values = {
        "dddd": DAYS_FULL[now.weekday()], "ddd": DAYS_FULL[now.weekday()][:3], "ww": WEEKDAYS[now.weekday()],
        "dd": f"{now.day:02d}", "d": str(now.day), "mmmm": MONTHS_FULL[now.month - 1],
        "mmm": MONTHS[now.month - 1], "mm": f"{now.month:02d}", "m": str(now.month),
        "yyyy": str(now.year), "yy": f"{now.year % 100:02d}",
    }
    return re.sub(r"dddd|ddd|ww|dd|d|mmmm|mmm|mm|m|yyyy|yy", lambda m: values[m.group(0)], fmt).upper()


def format_time(fmt: str, now: datetime) -> str:
    """HH 09, H 9 (24 h), hh 09, h 9 (12 h), mm minutes, ss seconds, tt AM/PM."""
    twelve = now.hour % 12 or 12
    values = {"HH": f"{now.hour:02d}", "H": str(now.hour), "hh": f"{twelve:02d}", "h": str(twelve),
              "mm": f"{now.minute:02d}", "ss": f"{now.second:02d}", "tt": "AM" if now.hour < 12 else "PM"}
    return re.sub(r"HH|H|hh|h|mm|ss|tt", lambda m: values[m.group(0)], fmt)


def ticks(cfg: dict) -> bool:
    """Whether the screen changes each second: the seconds shown, on their own or in the time."""
    return bool(cfg.get("seconds", True) or "ss" in (cfg.get("time_format") or ""))


def _clock_text(now: datetime, hour24: bool) -> str:
    hour = now.hour if hour24 else (now.hour % 12 or 12)
    return f"{hour:02d}:{now.minute:02d}" if hour24 else f"{hour}:{now.minute:02d}"


# The image of an animated icon that says it best as a still (the bolt shows on 3).
_STILL_FRAME = {"lightning": 3, "lightning-rainy": 3, "rainy": 4, "pouring": 4}
# Conditions whose 16 px icon moves (``phase`` 0-3): rain, snow and hail fall, the bolt
# flashes, the sun's rays turn.
ANIMATED = {"sunny", "rainy", "pouring", "snowy", "snowy-rainy", "hail", "lightning", "lightning-rainy"}
PHASES = 4


def _sun16(d: ImageDraw.ImageDraw, cx: int, cy: int, phase: int, small: bool = False) -> None:
    """A pixel-drawn sun: a round core with a bright spot and 8 rays that take turns growing."""
    r = 2 if small else 3
    straight, diagonal = (2, 1) if phase % 2 == 0 else (1, 2)
    if small:
        straight = diagonal = 1
    ray = PAL["sun_ray"]
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        for k in range(straight):
            d.point((cx + dx * (r + 2 + k), cy + dy * (r + 2 + k)), fill=ray)
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        for k in range(diagonal):
            d.point((cx + dx * (r + 1 + k), cy + dy * (r + 1 + k)), fill=ray)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=PAL["sun_core"])
    d.point((cx - 1, cy - 1), fill=PAL["sun_hi"])
    if not small:
        d.point((cx - 2, cy - 1), fill=PAL["sun_hi"])
        d.point((cx - 1, cy - 2), fill=PAL["sun_hi"])


def _cloud16(img: Image.Image, color: tuple, x: int = 4, y: int = 1, w: int = 24) -> None:
    """The dashboard's cloud (drawn at 32 px), laid over a 16 px icon."""
    big = Image.new("RGB", (32, 32), (0, 0, 0))
    _cloud(ImageDraw.Draw(big), x, y, w, color)
    small = big.resize((16, 16), Image.NEAREST)
    img.paste(small, (0, 0), small.convert("L").point(lambda v: 255 if v else 0))


SYNODIC_MONTH = 29.530588853  # days from one new moon to the next
NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)  # a known new moon


def moon_phase(when: datetime) -> float:
    """How far the moon is in its cycle at ``when``: 0 new, 0.25 first quarter, 0.5 full, 0.75 last quarter."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return ((when - NEW_MOON).total_seconds() / 86400 / SYNODIC_MONTH) % 1


def _moon16(d: ImageDraw.ImageDraw, when: datetime, phase: int) -> None:
    """The real moon of ``when`` (its lit part, as seen from France: growing on the right), and stars."""
    p = moon_phase(when)
    cx, cy, r = 8, 8, 5.6
    for y in range(16):
        dy = y - cy
        if abs(dy) > r:
            continue
        half = math.sqrt(r * r - dy * dy)
        edge = half * math.cos(2 * math.pi * p)  # the shadow's edge on this row
        for x in range(16):
            dx = x - cx
            if abs(dx) > half:
                continue
            lit = dx > edge if p < 0.5 else dx < -edge
            d.point((x, y), fill=PAL["moon"] if lit else (32, 32, 44))
    for k, (sx, sy) in enumerate(((1, 2), (14, 3), (13, 14))):  # stars twinkling in turn
        d.point((sx, sy), fill=(230, 230, 255) if (phase + k) % PHASES < 2 else (90, 90, 120))


def _icon16(condition: str, phase: int = 0, when: datetime | None = None) -> Image.Image:
    """The 16×16 weather icon; animated ones change with ``phase`` (0-3); a clear night shows the
    moon of ``when`` (its real phase)."""
    img = Image.new("RGB", (16, 16), (0, 0, 0))
    d = ImageDraw.Draw(img)
    if condition == NO_WEATHER:
        return img
    if condition == "clear-night" and when is not None:
        _moon16(d, when, phase)
        return img
    if condition in ("sunny", "clear"):
        _sun16(d, 8, 8, phase)
    elif condition == "partlycloudy":
        _sun16(d, 5, 5, 0, small=True)
        _cloud16(img, PAL["cloud_lt"], x=8, y=13, w=21)
    elif condition in ("rainy", "pouring", "snowy", "snowy-rainy", "hail"):
        _cloud16(img, PAL["cloud_md"] if condition in ("pouring", "hail") else PAL["cloud_lt"])
        # Three drops (five when pouring) falling one step per phase, each from its own height.
        columns = (3, 6, 9, 12, 14) if condition == "pouring" else (4, 8, 12)
        for k, x in enumerate(columns):
            y = 10 + (phase + k * 3) % PHASES + (1 if condition == "pouring" else 0)
            if condition == "snowy" or (condition == "snowy-rainy" and k == 1):
                d.point((x, y), fill=PAL["snow"])
                if (phase + k) % 2 == 0:
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        d.point((x + dx, y + dy), fill=(150, 165, 190))
            elif condition == "hail":
                d.rectangle([x, y, x + 1, y + 1], fill=PAL["hail"])
            else:
                d.line([(x, y), (x, min(15, y + 1))], fill=PAL["rain"])
    elif condition in ("lightning", "lightning-rainy"):
        flash = phase in (1, 2)
        _cloud16(img, PAL["cloud_md"] if flash else PAL["cloud_dk"])
        bolt = PAL["bolt"] if flash else PAL["bolt_dim"]
        d.polygon([(8, 9), (11, 9), (9, 12), (11, 12), (6, 16), (7, 13), (5, 13)], fill=bolt)
        if condition == "lightning-rainy":
            for k, x in enumerate((3, 13)):
                y = 10 + (phase + k * 2) % PHASES
                d.line([(x, y), (x, y + 1)], fill=PAL["rain"])
    else:
        frames = 16 if condition.startswith("lightning") else 12
        return _render_icon(condition, _STILL_FRAME.get(condition, 0), frames).resize((16, 16), Image.NEAREST)
    return img


def _rain_text(forecast: Forecast, drop: str = "rain") -> str | None:
    if drop == "humidity":
        return None if forecast.now.humidity is None else f"{round(forecast.now.humidity)}%"
    if forecast.rain is not None:
        return f"{forecast.rain}%"
    if forecast.rain_mm:
        return f"{forecast.rain_mm:g}MM"
    return None


def render_meteo(forecast: Forecast, now: datetime, cfg: dict | None = None, size: int = 64,
                 label: str | None = None, second: int | None = None, phase: int = 0,
                 flip_from: datetime | None = None, flip_step: int | None = None,
                 page: dict | None = None) -> Image.Image:
    """The screen at ``now``: the time, today and the strip (64×64; smaller panels get less).

    ``label``: the place's name, written under the time. ``second``: drawn small
    after the time (64×64 only). ``phase``: the step of today's icon animation (0-3).
    ``flip_from``/``flip_step``: the flip clock's cards turning from that time (step 0-3).
    """
    cfg = cfg or {}
    now = city_now(forecast, now, cfg)  # the time there, with the weather there
    if flip_from is not None:
        flip_from = city_now(forecast, flip_from, cfg)
    hour24 = cfg.get("hour24", True)
    img = Image.new("RGB", (size, size), (0, 0, 0))
    d = ImageDraw.Draw(img)
    today = forecast.now
    clock = _clock_text(now, hour24)
    if size < 32:
        _draw_small(d, (size - _small_width(clock.replace(":", ""))) // 2, 1, clock.replace(":", ""),
                    _rgb(cfg.get("clock_color"), CLOCK_COLOR))
        if today.temperature is not None:
            text = _deg(today.temperature)
            _draw_small(d, (size - _small_width(text)) // 2, 9, text, _temp_color(today.temperature, today.temp_unit))
        return img
    if size < 64:
        _draw_text(d, (size - _text_width(clock)) // 2, 1, clock, _rgb(cfg.get("clock_color"), CLOCK_COLOR))
        img.paste(_icon16(today.condition, phase, now), (0, 10))
        if today.temperature is not None:
            _draw_text(d, 17, 11, _deg(today.temperature), _temp_color(today.temperature, today.temp_unit))
        if rain := _rain_text(forecast):
            _draw_small(d, 17, 20, rain, PAL["humid"])
        if label:  # no room for both: the place's name says which one it is
            _draw_name(img, 27, label, size, 5)
            return img
        parts = [(_num(today.high), PAL["hi"]), ("/", DIM), (_num(today.low), PAL["lo"])]
        x = (size - _small_width("".join(p for p, _ in parts))) // 2
        for text, color in parts:
            x = _draw_small(d, x, 27, text, color)
        return img

    # 64×64: the parts (the time, the name, today, the strip), each drawn on its
    # own layer at its usual place, then moved, resized or hidden as the view says.
    composed, _boxes = _compose(forecast, now, cfg, size, label, second, phase, flip_from, flip_step, page)
    return composed


ELEMENTS = ("clock", "seconds", "date", "name", "today", "strip")
MONTHS = ("JAN", "FEV", "MAR", "AVR", "MAI", "JUN", "JUL", "AOU", "SEP", "OCT", "NOV", "DEC")
# Each part's sizes: (smallest, biggest), and its usual size (by clock style).
SIZES = {"clock": (1, 2), "seconds": (1, 3), "date": (1, 2), "name": (1, 2), "today": (1, 3), "strip": (1, 2),
         "days": (1, 2), "sun": (1, 2),
         "page": (1, 3), **{kind: (1, 3) for kind in PAGE_PARTS}}


def default_size(part: str, cfg: dict) -> int:
    flip = cfg.get("clock_style") == "flip"
    return {"clock": 2, "seconds": 1, "date": 1, "name": 1, "today": 2, "strip": 1 if flip else 2,
            "days": 1 if flip else 2, "sun": 1 if flip else 2}.get(part, 2)


def part_size(part: str, cfg: dict) -> int:
    low, high = SIZES[part]
    size = ((cfg.get("layout") or {}).get(part) or {}).get("size") or default_size(part, cfg)
    return max(low, min(high, int(size)))


def _layers(forecast: Forecast, now: datetime, cfg: dict, size: int, label: str | None, second: int | None,
            phase: int, flip_from: datetime | None, flip_step: int | None,
            page: dict | None = None) -> list[tuple[str, Image.Image]]:
    """Each part of the 64×64 screen on its own layer, where it goes by default."""
    layout = cfg.get("layout") or {}
    flip = cfg.get("clock_style") == "flip"
    named = label is not None
    hour24 = cfg.get("hour24", True)
    color = _rgb(cfg.get("clock_color"), CLOCK_COLOR)
    if flip and cfg.get("clock_color", "#78beff").lower() == "#78beff":
        color = FLIP_CARD  # white cards, like HTC Sense, unless a colour was chosen
    elif cfg.get("clock_color", "#78beff").lower() == "#78beff" and cfg.get("special_days", True):
        # A special day dresses the time in its colour (unless a colour was chosen).
        specials = pages_mod.special_days(now.date(), cfg.get("birthdays"))
        if specials:
            color = specials[0].colors[0]
    # Where each part starts: the flip cards are taller, so the rest goes lower.
    name_y, today_y, strip_y = (24, 30, 48) if flip else (15, 21, 37) if named else (None, 17, 37)
    layers = []

    seconds_style = cfg.get("seconds_style", "auto")
    if seconds_style == "auto":
        seconds_style = "bar" if flip else "digits"
    clock, d = _layer(size)
    if flip:
        small = part_size("clock", cfg) == 1
        bottom = _draw_flip_clock(clock, now, hour24, color, flip_from, flip_step, small)
        # Where the seconds go: a bar under the cards, figures or a ring at the right.
        anchor = {"bar": (0, bottom + 1), "digits": (size - 8, bottom + 2), "ring": (size - 12, bottom + 2)}
    else:
        scale = part_size("clock", cfg)
        text = format_time(cfg["time_format"], now) if cfg.get("time_format") else _clock_text(now, hour24)
        w = _text_width(text, scale)
        while w > size and scale > 1:  # a long format (with the seconds...) in smaller digits
            scale -= 1
            w = _text_width(text, scale)
        top = 0 if named else 1
        room = {"digits": 9, "ring": 12, "bar": 0}[seconds_style] if second is not None else 0
        x = (size - w - room) // 2
        _draw_text(d, x, top, text, color, scale)
        anchor = {"digits": (x + w + 2, top + 7 * scale - 5), "ring": (x + w + 1, top + 7 * scale - 11),
                  "bar": (0, top + 7 * scale + 1)}
    layers.append(("clock", clock))

    if second is not None and cfg.get("seconds", True) and "ss" not in (cfg.get("time_format") or ""):
        layer, d = _layer(size)
        # Figures and bar a little dimmer than the time; the ring as bright, it is thin.
        seconds_color = _rgb(cfg.get("seconds_color"),
                             color if seconds_style == "ring" else _drawn(tuple(c * 3 // 5 for c in color)))
        _draw_seconds(layer, d, second, seconds_style, anchor[seconds_style], part_size("seconds", cfg),
                      seconds_color, size)
        layers.append(("seconds", layer))

    if page is not None and page.get("kind") == "screen":
        for kind, block in page["pages"].items():
            layer, d = _layer(size)
            _draw_page(layer, block, now, cfg, size, 24 if flip else 16, color, part_size(kind, cfg))
            layers.append((kind, layer))
    elif page is not None and page.get("kind") != "weather":
        layer, d = _layer(size)
        _draw_page(layer, page, now, cfg, size, 24 if flip else 16, color, part_size("page", cfg))
        layers.append(("page", layer))
        return layers

    # The date, at the right of the name's row; the name then starts at the left.
    dated = not (layout.get("date") or {}).get("hidden") and ((page or {}).get("kind") != "screen" or "date" in layout)
    date_width = 0
    if named or flip or (page or {}).get("kind") == "screen":
        layer, d = _layer(size)
        if cfg.get("date_format"):
            text = format_date(cfg["date_format"], now)
        else:
            text = format_date("ww d mmm" if part_size("date", cfg) >= 2 else "ww d", now)
        date_width = _small_width(text)
        _draw_small(d, size - date_width - 1, name_y if name_y is not None else 15, text, DATE_COLOR)
        layers.append(("date", layer))
    if named:
        layer, d = _layer(size)
        spec = layout.get("name") or {}
        align = spec.get("align") or ("left" if dated else "center")
        # Side by side with the date unless one of them was moved or the name centred on purpose.
        shared = dated and align == "left" and not any((layout.get(p) or {}).get("dy") for p in ("name", "date"))
        # This screen's own name for it (« title »), else the place's.
        _draw_name(layer, name_y, spec.get("title") or label, size, 7, big=part_size("name", cfg) >= 2, align=align,
                   width=size - date_width - 5 if shared else size)
        layers.append(("name", layer))

    layer, d = _layer(size)
    drip = second % 4 if (second is not None and cfg.get("animate", True)) else 0
    _draw_today(layer, forecast, today_y, size, phase, part_size("today", cfg), cfg.get("drop", "rain"), drip,
                set(cfg.get("today_hide") or ()), when=now)
    if not named and not flip:
        for px in range(0, size, 2):
            d.point((px, 35), fill=(35, 38, 48))
    layers.append(("today", layer))

    # « En bas » (the view's kind), and on a screen the other strips put on it, each its own kind.
    strips = [("strip", cfg)]
    if (page or {}).get("kind") == "screen":
        strips += [(kind, {**cfg, "strip": kind}) for kind in EXTRA_STRIPS if kind in layout]
    for name, strip_cfg in strips:
        layer, d = _layer(size)
        if part_size(name, cfg) == 1:
            _draw_compact_strip(d, forecast, now, strip_cfg, size, strip_y, hour24)
        elif strip_cfg.get("strip") == "sun":
            _draw_sun_strip(d, forecast, now, size, hour24)
        else:
            _draw_strip(layer, d, forecast, now, strip_cfg, size, named)
        layers.append((name, layer))
    return layers


def _draw_seconds(img: Image.Image, d: ImageDraw.ImageDraw, second: int, style: str, at: tuple[int, int],
                  level: int, color: tuple, size: int) -> None:
    """The seconds: figures (small or big), a bar 1-3 LEDs thick, or a ring filling up around the figures."""
    x, y = at
    if style == "bar":
        d.rectangle([0, y, round((second + 1) * size / 60) - 1, y + level - 1], fill=color)
    elif style == "ring":
        diameter = (11, 15, 19)[level - 1]
        dim = tuple(c // 4 for c in color)
        box = [x, y, x + diameter - 1, y + diameter - 1]
        d.ellipse(box, outline=dim)
        if second:
            d.arc(box, -90, -90 + second * 6, fill=color, width=1 if level == 1 else 2)
        text = f"{second:02d}"
        if level >= 3:
            _draw_text(d, x + (diameter - _text_width(text)) // 2, y + (diameter - 7) // 2, text, color)
        else:
            _draw_small(d, x + (diameter - _small_width(text)) // 2, y + (diameter - 5) // 2, text, color)
    elif level >= 2:
        _draw_text(d, x, y - 2, f"{second:02d}", color)
    else:
        _draw_small(d, x, y, f"{second:02d}", color)


def _layer(size: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (size, size), (0, 0, 0))
    return image, ImageDraw.Draw(image)


def _compose(forecast: Forecast, now: datetime, cfg: dict, size: int, label: str | None, second: int | None,
             phase: int, flip_from: datetime | None = None, flip_step: int | None = None, page: dict | None = None):
    """The screen and where each part ended up: {part: (x0, y0, x1, y1)}."""
    screen = page is not None and page.get("kind") == "screen"
    if screen:  # its own parts, placed its own way
        cfg = {**cfg, "layout": page["parts"]}
    layout = cfg.get("layout") or {}
    img = Image.new("RGB", (size, size), (0, 0, 0))
    boxes = {}
    for name, layer in _layers(forecast, now, cfg, size, label, second, phase, flip_from, flip_step, page):
        spec = layout.get(name) or {}
        on_screen = name in layout or (name == "seconds" and "clock" in layout)  # the seconds go with the clock
        if spec.get("hidden") or (screen and not on_screen):
            continue
        dx, dy = int(spec.get("dx", 0)), int(spec.get("dy", 0))
        r, g, b = layer.split()
        mask = ImageChops.lighter(ImageChops.lighter(r, g), b).point(lambda v: 255 if v else 0)
        if spec.get("outline"):  # every LED around the part, in that colour, under it
            ring = ImageChops.subtract(_grown(mask), mask)
            img.paste(Image.new("RGB", layer.size, _rgb(spec["outline"], (255, 255, 255))), (dx, dy), ring)
            mask = ImageChops.lighter(mask, ring)
            layer = layer.copy()
        img.paste(layer, (dx, dy), ImageChops.subtract(mask, ring) if spec.get("outline") else mask)
        box = mask.getbbox()
        if box:
            boxes[name] = (box[0] + dx, box[1] + dy, box[2] + dx, box[3] + dy)
    return img, boxes


def _grown(mask: Image.Image) -> Image.Image:
    """The mask and the LEDs touching it on a side (not the corners: a thin outline, letters apart)."""
    grown = mask.copy()
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        shifted = Image.new("L", mask.size, 0)
        shifted.paste(mask, (dx, dy))  # not offset(): it wraps round the edges
        grown = ImageChops.lighter(grown, shifted)
    return grown


def element_boxes(forecast: Forecast, now: datetime, cfg: dict, size: int, label: str | None,
                  page: dict | None = None) -> dict:
    """Where each part of the screen is, for the panels to pick and drag them (``page``: another page's)."""
    if size < 64:
        return {}
    now = city_now(forecast, now, cfg)
    second = now.second if ticks(cfg) else None
    return _compose(forecast, now, cfg, size, label, second, 0, page=page)[1]


def city_now(forecast: Forecast, now: datetime, cfg: dict) -> datetime:
    """``now`` as the clock of the forecast's place shows it (its own time zone), unless switched off."""
    if forecast.zone is None or not cfg.get("city_time", True) or now.tzinfo is None:
        return now
    return now.astimezone(forecast.zone)


def _draw_today(img: Image.Image, forecast: Forecast, y: int, size: int, phase: int, level: int = 2,
                drop: str = "rain", drip: int = 0, hide: set | frozenset = frozenset(),
                when: datetime | None = None) -> None:
    """Today: icon, temperature now, chance of rain, high and low.

    ``level`` 1: a 10 px icon and small figures; 2: the 16 px icon; 3: the 32 px one.
    """
    d = ImageDraw.Draw(img)
    today = forecast.now
    if hide:  # the details left out are drawn as if unknown
        today = WeatherData(NO_WEATHER if "icon" in hide else today.condition,
                            None if "temp" in hide else today.temperature, today.temp_unit, today.humidity,
                            today.wind_speed, None if "minmax" in hide else today.high,
                            None if "minmax" in hide else today.low)
        if "drop" in hide:
            forecast = Forecast(forecast.place, today)
        else:
            forecast = Forecast(forecast.place, today, rain=forecast.rain, rain_mm=forecast.rain_mm)
    if level == 1:
        if today.condition != NO_WEATHER:
            frames = 16 if today.condition.startswith("lightning") else 12
            icon = _render_icon(today.condition, phase * frames // PHASES, frames).resize((10, 10), Image.BOX)
            img.paste(icon, (0, y))
        if today.temperature is not None:
            _draw_small(d, 12, y, _deg(today.temperature), _temp_color(today.temperature, today.temp_unit))
        if today.high is not None or today.low is not None:
            x = 12
            for text, color in ((_num(today.high), PAL["hi"]), ("/", DIM), (_num(today.low), PAL["lo"])):
                x = _draw_small(d, x, y + 6, text, color)
        if rain := _rain_text(forecast, drop):
            _draw_small(d, size - _small_width(rain) - 1, y, rain, PAL["humid"])
        return
    if level >= 3:
        if today.condition == NO_WEATHER:
            return
        frames = 16 if today.condition.startswith("lightning") else 12
        img.paste(_render_icon(today.condition, phase * frames // PHASES, frames), (0, y))
        x0 = 33
        if today.temperature is not None:
            _draw_text(d, x0, y + 1, _deg(today.temperature), _temp_color(today.temperature, today.temp_unit))
        if rain := _rain_text(forecast, drop):
            _draw_small(d, x0, y + 10, rain, PAL["humid"])
        if today.high is not None:
            _draw_text(d, x0, y + 17, f"↑{_num(today.high)}", PAL["hi"])
        if today.low is not None:
            _draw_text(d, x0, y + 25, f"↓{_num(today.low)}", PAL["lo"])
        return
    img.paste(_icon16(today.condition, phase, when), (0, y))
    if today.temperature is not None:
        _draw_text(d, 18, y + 1, _deg(today.temperature), _temp_color(today.temperature, today.temp_unit))
    if rain := _rain_text(forecast, drop):
        x = size - _small_width(rain) - 1
        _draw_small(d, x, y + 2, rain, PAL["humid"])
        # A drop before it, that drips: it swells, falls a little, then forms again.
        dy = (0, 0, 1, 2)[drip]
        top = PAL["humid"] if drip < 3 else tuple(c // 2 for c in PAL["humid"])
        d.line([(x - 4, y + 1 + dy), (x - 4, y + 2 + dy)], fill=top)
        d.rectangle([x - 5, y + 3 + dy, x - 3, y + 5 + min(dy, 1)], fill=PAL["humid"])
        d.point((x - 4, y + 6 + min(dy, 1)), fill=PAL["humid"])
    x = 18
    if today.high is not None:
        x = _draw_text(d, x, y + 9, f"↑{_num(today.high)}", PAL["hi"]) + 3
    if today.low is not None:
        _draw_text(d, x, y + 9, f"↓{_num(today.low)}", PAL["lo"])


def _draw_strip(img: Image.Image, d: ImageDraw.ImageDraw, forecast: Forecast, now: datetime, cfg: dict,
                size: int, named: bool) -> None:
    """The next hours or the next days: label, icon, temperature."""
    days = cfg.get("strip") == "days"
    slots = forecast.days if days else hour_slots(forecast, now, cfg)
    count = DAY_SLOTS if days else HOUR_SLOTS
    width = size // count
    unit = forecast.now.temp_unit
    for i, slot in enumerate(slots[:count]):
        center = i * width + width // 2
        _draw_small(d, center - _small_width(slot.label) // 2, 38, slot.label, DIM)
        img.paste(_icon16(slot.condition, 0, now), (center - 8, 43 if named else 44))
        if days:
            parts = [(_num(slot.high), PAL["hi"]), ("/", DIM), (_num(slot.low), PAL["lo"])]
            x = center - _small_width("".join(p for p, _ in parts)) // 2
            for text, color in parts:
                x = _draw_small(d, x, 59, text, color)
        elif slot.temperature is not None:
            text = _deg(slot.temperature)
            _draw_small(d, center - _small_width(text) // 2, 59, text, _temp_color(slot.temperature, unit))


def _draw_compact_strip(d: ImageDraw.ImageDraw, forecast: Forecast, now: datetime, cfg: dict, size: int,
                        y: int, hour24: bool) -> None:
    """Under the flip cards, two lines: the hours (or days, or the sun) and their temperatures."""
    if cfg.get("strip") == "sun":
        rise, sunset = next_sun(forecast, now)
        for i, (arrow, when) in enumerate((("↑", rise), ("↓", sunset))):
            text = "--:--" if when is None else _clock_text(when, hour24)
            x = i * (size // 2) + 2
            _draw_text(d, x, y + 4, arrow, PAL["sun_core"] if i == 0 else (255, 130, 40))
            _draw_small(d, x + 7, y + 5, text, NAME_COLOR)
        return
    days = cfg.get("strip") == "days"
    slots = forecast.days if days else hour_slots(forecast, now, cfg)
    count = DAY_SLOTS if days else HOUR_SLOTS
    width = size // count
    for i, slot in enumerate(slots[:count]):
        center = i * width + width // 2
        _draw_small(d, center - _small_width(slot.label) // 2, y + 1, slot.label, DIM)
        if days:
            text = f"{_num(slot.high)}/{_num(slot.low)}"
            _draw_small(d, center - _small_width(text) // 2, y + 9, text, PAL["hi"])
        elif slot.temperature is not None:
            text = _deg(slot.temperature)
            _draw_small(d, center - _small_width(text) // 2, y + 9,
                        text, _temp_color(slot.temperature, forecast.now.temp_unit))


# HTC Sense's flip clock: two cards, the hours and the minutes, split across the middle.
FLIP_CARD = (225, 225, 230)
FLIP_DIGIT = (20, 20, 24)
CARD_W, CARD_H, SPLIT = 31, 21, 10
FLIP_STEPS = 4
FLIP_STEP_MS = 90


def _card(text: str, color: tuple, small: bool = False) -> Image.Image:
    """One card: lighter top, darker bottom, the split line, two digits (``small``: half size)."""
    width, height, scale = (15, 11, 1) if small else (CARD_W, CARD_H, 2)
    split = height // 2
    card = Image.new("RGB", (width, height), (0, 0, 0))
    d = ImageDraw.Draw(card)
    lower = tuple(max(0, c - 35) for c in color)
    d.rounded_rectangle([0, 0, width - 1, height - 1], radius=1 if small else 2, fill=color)
    d.rectangle([1, split + 1, width - 2, height - 2], fill=lower)
    w = _text_width(text, scale)
    digit = FLIP_DIGIT if sum(color) > 300 else (240, 240, 245)
    _draw_text(d, (width - w) // 2, (height - 7 * scale) // 2, text, digit, scale)
    d.line([(0, split), (width - 1, split)], fill=(0, 0, 0))
    for x in (0, width - 1):  # the hinges
        d.point((x, split - 1), fill=(0, 0, 0))
        d.point((x, split + 1), fill=(0, 0, 0))
    return card


def _flip_texts(now: datetime, hour24: bool) -> tuple[str, str]:
    hour = now.hour if hour24 else (now.hour % 12 or 12)
    return f"{hour:02d}" if hour24 else f"{hour}", f"{now.minute:02d}"


def _flip_card(old: Image.Image, new: Image.Image, step: int) -> Image.Image:
    """A card turning from ``old`` to ``new``: the old top half folds down onto the split
    (steps 0-1), then the new bottom half unfolds below it (steps 2-3)."""
    width, height = new.size
    split = height // 2
    out = Image.new("RGB", (width, height), (0, 0, 0))
    out.paste(new.crop((0, 0, width, split)), (0, 0))               # the new top shows behind
    out.paste(old.crop((0, split, width, height)), (0, split))      # the old bottom still shows
    if step < FLIP_STEPS // 2:
        h = max(1, round(split * (1 - (step + 1) / (FLIP_STEPS // 2 + 1))))
        flap = old.crop((0, 0, width, split)).resize((width, h), Image.NEAREST)
        out.paste(flap, (0, split - h))
    else:
        h = max(1, round((height - split - 1) * (step - FLIP_STEPS // 2 + 1) / (FLIP_STEPS // 2 + 1)))
        flap = new.crop((0, split + 1, width, height)).resize((width, h), Image.NEAREST)
        out.paste(flap, (0, split + 1))
    return out


def _draw_flip_clock(img: Image.Image, now: datetime, hour24: bool, color: tuple,
                     flip_from: datetime | None = None, flip_step: int | None = None, small: bool = False) -> int:
    """The two cards; while ``flip_step`` runs, those that changed since ``flip_from`` turn.

    Returns the cards' last row.
    """
    new = _flip_texts(now, hour24)
    old = _flip_texts(flip_from, hour24) if flip_from is not None else new
    width = 15 if small else CARD_W
    left = (img.width - 2 * width - 2) // 2
    for i, x in enumerate((left, left + width + 2)):
        card = _card(new[i], color, small)
        if flip_step is not None and old[i] != new[i]:
            card = _flip_card(_card(old[i], color, small), card, flip_step)
        img.paste(card, (x, 0))
    return card.height - 1


def _draw_sun_strip(d: ImageDraw.ImageDraw, forecast: Forecast, now: datetime, size: int, hour24: bool) -> None:
    """Sunrise and sunset: a sun on the horizon with an arrow, and the time."""
    rise, sunset = next_sun(forecast, now)
    for i, (label, when, up) in enumerate((("LEVER", rise, True), ("COUCHER", sunset, False))):
        center = i * (size // 2) + size // 4
        _draw_small(d, center - _small_width(label) // 2, 38, label, DIM)
        d.pieslice([center - 7, 47, center + 7, 61], 180, 360, fill=PAL["sun_core"] if up else (255, 130, 40))
        for angle in (200, 240, 270, 300, 340):
            rad = angle * 3.14159 / 180
            d.point((center + round(10 * math.cos(rad)), 54 + round(10 * math.sin(rad))), fill=PAL["sun_ray"])
        d.line([(center - 10, 54), (center + 10, 54)], fill=DIM)
        ax = center + 9
        if up:
            d.line([(ax, 44), (ax, 49)], fill=NAME_COLOR)
            d.line([(ax - 2, 46), (ax, 44), (ax + 2, 46)], fill=NAME_COLOR)
        else:
            d.line([(ax, 44), (ax, 49)], fill=NAME_COLOR)
            d.line([(ax - 2, 47), (ax, 49), (ax + 2, 47)], fill=NAME_COLOR)
        # In the place's own time (Home Assistant's sun is already in its time zone).
        text = "--:--" if when is None else _clock_text(when, hour24)
        _draw_small(d, center - _small_width(text) // 2, 57 + 2, text, NAME_COLOR)


def _rgb(color: str | None, default: tuple) -> tuple:
    try:
        return _drawn(tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)))
    except (TypeError, ValueError):
        return default


def _drawn(color: tuple) -> tuple:
    """Black as the nearest colour a layer still counts as drawn (its LEDs stay off all the same)."""
    return color if any(color) else (1, 1, 1)


ANIMATION_MS = 500


def page_list(forecasts: list[Forecast], cfg: dict, extras, now: datetime, every: bool = False) -> list[dict]:
    """What takes turns on the screen: the screens filled by hand, each for its ``seconds`` (one
    whose parts are all pages with nothing today — no saint... — is skipped), else each place's
    weather then the other pages of the day. ``every``: the screens skipped now too (to edit them),
    marked ``off``."""
    if not cfg.get("screens"):
        places = [{"kind": "weather", "index": i} for i in range(len(forecasts))]
        return places + pages_mod.extra_pages(cfg, extras, now)
    today = {}
    for n, screen in enumerate(cfg["screens"]):  # each screen's countdown counts to its own date
        spec = (screen.get("parts") or {}).get("countdown")
        if spec is not None and countdown_text(spec.get("date"), now) is not None:
            today[f"countdown:{n}"] = {"kind": "countdown", "title": spec.get("title") or "", "date": spec.get("date")}
    for block in pages_mod.extra_pages(cfg, extras, now):
        today.setdefault(block["kind"], block)  # the first special day of several
    turns = []
    for n, screen in enumerate(cfg["screens"]):
        parts = screen.get("parts") or {}
        blocks = {kind: today[kind] for kind in parts if kind in today}
        if f"countdown:{n}" in today and "countdown" in parts:
            blocks["countdown"] = today[f"countdown:{n}"]
        if "notes" in parts and cfg.get("notes"):
            blocks["notes"] = {"kind": "notes", "items": list(cfg["notes"])}
        if "reminders" in parts:
            items = reminders_on(now.date(), cfg.get("reminders"))
            items += [o for o in (getattr(extras, "agenda", None) or [])]
            if items:
                blocks["reminders"] = {"kind": "reminders", "items": items}
        # Out of its hours, or its pages have nothing today (no saint...) and no weather: skipped.
        off = not blocks and any(kind in PAGE_PARTS for kind in parts) and not {"name", "today", "strip", *EXTRA_STRIPS} & set(parts)
        start, end = screen.get("from"), screen.get("to")
        if start is not None and end is not None and start != end:
            off = off or not (start <= now.hour < end if start < end else (now.hour >= start or now.hour < end))
        if off and not every:
            continue
        turns.append({"kind": "screen", "screen": n, "index": min(screen.get("place", 0), len(forecasts) - 1),
                      "seconds": screen.get("seconds", 15), "parts": parts, "pages": blocks, "off": off})
    return turns or [{"kind": "weather", "index": 0}]


def render_meteo_minute(forecasts: list[Forecast], start: datetime, cfg: dict, size: int = 64,
                        labels: list[str | None] | None = None, extras=None) -> bytes:
    """The GIF of the rest of ``start``'s minute, which the display plays by itself.

    One image per second when the seconds show (else one per place, each for
    ``switch_seconds``), every half second when today's icon moves (rain
    falling, the sun's rays...). Images that do not change are merged, and later
    ones only redraw what changed.
    """
    labels = labels or [f.place for f in forecasts]
    switch = cfg.get("switch_seconds", 15)
    ticking = ticks(cfg) and size >= 64
    animated = cfg.get("animate", True) and any(f.now.condition in ANIMATED for f in forecasts)
    # Pages of different lengths (the mixing desk) may turn on any second: images each second at
    # least, those that do not change merged.
    step = ANIMATION_MS if animated else 1000
    minute = start.replace(second=0, microsecond=0)

    turns = page_list(forecasts, cfg, extras, start) if size >= 64 else page_list(forecasts, {}, None, start)

    def shown(second: int) -> int:  # which page, counted from midnight so it carries on across minutes
        return turn_at(turns, cfg, minute.replace(second=second))

    def draw(second: int, **kwargs) -> Image.Image:
        page = turns[shown(second)]
        i = page.get("index", 0)
        return render_meteo(forecasts[i], minute.replace(second=second), cfg, size, label=labels[i],
                            second=second if ticking else None, page=page, **kwargs)

    frames, durations = [], []
    ms = start.second * 1000
    if cfg.get("clock_style") == "flip" and size >= 64:
        # The new minute arrives: the cards that changed flip over, then the minute goes on.
        for turn in range(FLIP_STEPS):
            frames.append(draw(start.second, phase=0, flip_from=minute - timedelta(minutes=1), flip_step=turn))
            durations.append(FLIP_STEP_MS)
        ms += FLIP_STEPS * FLIP_STEP_MS
    while ms < 60000:
        after = min(60000, (ms // step + 1) * step)
        second = ms // 1000
        frame = draw(second, phase=(ms // ANIMATION_MS) % PHASES if animated else 0)
        if frames and frame.tobytes() == frames[-1].tobytes():
            durations[-1] += after - ms
        else:
            frames.append(frame)
            durations.append(after - ms)
        ms = after
    data = b""
    for colors in (64, 32):
        data = frames_to_gif(frames, durations, colors=colors)
        if len(data) <= 3 * PACKET_BYTES:
            break
    return data


def local_now() -> datetime:
    return dt_util.now() if dt_util is not None else datetime.now().astimezone()


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def _client_error() -> type:
    # Imported when fetching only: the Android app reuses this module without aiohttp.
    import aiohttp

    return aiohttp.ClientError


def _place_name(result: dict) -> str:
    parts = [result.get("name"), result.get("admin1"), result.get("country")]
    seen = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


class WeatherService:
    """Forecasts for the Studio's weather views, cached so the minute sends cost nothing."""

    def __init__(self, hass) -> None:
        self.hass = hass
        self._cache: dict[tuple, Forecast] = {}
        self._locks: dict[tuple, asyncio.Lock] = {}
        self._ics: dict[str, tuple[float, str]] = {}
        self._ics_failed: dict[str, float] = {}
        self._ics_errors: dict[str, str] = {}  # why a calendar file was not fetched, to say so
        self._agenda: dict = {}

    @property
    def _states(self):
        # The Windows build has no Home Assistant states: Open-Meteo only.
        return getattr(self.hass, "states", None)

    def default_entity(self) -> str | None:
        """Home Assistant's own weather (met.no's « forecast_home » when it is there)."""
        states = self._states
        if states is None:
            return None
        ids = sorted(state.entity_id for state in states.async_all("weather"))
        return next((i for i in ids if i in ("weather.forecast_home", "weather.home")), ids[0] if ids else None)

    def sources(self) -> dict:
        """What the panel offers: weather entities, zones and Home Assistant's home."""
        states = self._states
        if states is None:
            return {"home_assistant": False, "entities": [], "zones": [], "home": None, "calendars": []}

        def name(state) -> str:
            return state.attributes.get("friendly_name") or state.entity_id

        config = self.hass.config
        return {
            "home_assistant": True,
            "entities": [{"entity_id": s.entity_id, "name": name(s)} for s in states.async_all("weather")],
            "zones": [{"entity_id": s.entity_id, "name": name(s)} for s in states.async_all("zone")
                      if s.attributes.get("latitude") is not None],
            "home": {"name": getattr(config, "location_name", None) or "Maison", "entity_id": self.default_entity()},
            "calendars": [{"entity_id": s.entity_id, "name": name(s)} for s in states.async_all("calendar")],
        }

    def _key(self, cfg: dict) -> tuple:
        place = cfg.get("place") or {}
        return (cfg["source"], cfg.get("entity_id"), cfg.get("zone"), place.get("latitude"), place.get("longitude"))

    async def forecasts(self, cfg: dict, max_age: float = 1800) -> list[Forecast]:
        """The forecast of each of the view's places."""
        return list(await asyncio.gather(*(self.forecast(profile, max_age) for profile in cfg["profiles"])))

    async def forecast(self, cfg: dict, max_age: float = 1800) -> Forecast:
        """One place's forecast (a profile), fetched again once older than ``max_age`` seconds."""
        key = self._key(cfg)
        async with self._locks.setdefault(key, asyncio.Lock()):
            cached = self._cache.get(key)
            if cached is not None and time.time() - cached.fetched < max_age:
                return cached
            try:
                forecast = await self._fetch(cfg)
            except Exception as err:  # noqa: BLE001 - sorted below
                if cached is not None:
                    # No network for now: the last forecast, however old, rather than nothing.
                    _LOGGER.debug("Weather for %s: keeping the forecast of %s (%s)", cached.place, cached.fetched, err)
                    return cached
                if isinstance(err, HomeAssistantError):
                    raise
                if isinstance(err, (_client_error(), asyncio.TimeoutError)):
                    raise HomeAssistantError(f"Météo injoignable : {err or type(err).__name__}") from err
                if isinstance(err, (KeyError, TypeError, ValueError)):
                    raise HomeAssistantError(f"Réponse météo illisible : {err}") from err
                raise
            self._cache[key] = forecast
            return forecast

    async def _fetch(self, cfg: dict) -> Forecast:
        source = cfg["source"]
        states = self._states
        if source == "entity" or (source == "home" and self.default_entity()):
            return await self._from_entity(cfg.get("entity_id") if source == "entity" else self.default_entity())
        if source == "place":
            place = cfg["place"]
            return await self._from_open_meteo(place["latitude"], place["longitude"], place["name"])
        if states is None:
            raise HomeAssistantError("Sans Home Assistant, choisis un lieu")
        if source == "zone":
            zone = states.get(cfg["zone"])
            if zone is None or zone.attributes.get("latitude") is None:
                raise HomeAssistantError(f"Zone introuvable : {cfg['zone']}")
            return await self._from_open_meteo(zone.attributes["latitude"], zone.attributes["longitude"],
                                               zone.attributes.get("friendly_name") or cfg["zone"])
        config = self.hass.config
        return await self._from_open_meteo(config.latitude, config.longitude,
                                           getattr(config, "location_name", None) or "Maison")

    async def extras(self, cfg: dict) -> pages_mod.Extras:
        """Today's agenda, saints and world days: calendar files (fetched every 6 hours, kept
        without network) and Home Assistant's calendars (asked again every 15 minutes)."""
        texts = {}
        for url in pages_mod.ics_urls(cfg):
            fetched, text = self._ics.get(url, (0.0, ""))
            if time.time() - fetched > ICS_MAX_AGE and time.time() - self._ics_failed.get(url, 0) > 300:
                try:
                    text = await self._get_text(url)
                    self._ics[url] = (time.time(), text)
                    self._ics_errors.pop(url, None)
                except Exception as err:  # noqa: BLE001 - the last copy stays
                    self._ics_failed[url] = time.time()
                    self._ics_errors[url] = str(getattr(err, "status", "") or err)
                    _LOGGER.debug("Calendar %s: %s", url, err)
            texts[url] = text
        now = local_now()
        agenda = None
        if cfg.get("agenda") and cfg.get("agenda_calendars") and self._states is not None:
            key = (tuple(cfg["agenda_calendars"]), now.date())
            cached = self._agenda.get(key)
            if cached is None or time.time() - cached[0] > 900:
                cached = (time.time(), await self._ha_agenda(cfg["agenda_calendars"], now))
                self._agenda = {key: cached}
            agenda = cached[1]
        return pages_mod.build_extras(cfg, texts, now, agenda)

    def forget_calendars(self) -> None:
        """Calendar files and Home Assistant's calendars read again at the next minute (a title changed...)."""
        self._ics = {url: (0.0, text) for url, (_t, text) in self._ics.items()}
        self._ics_failed = {}
        self._agenda = {}

    def ics_status(self, cfg: dict) -> list[dict]:
        """Each iCal link of the agenda: read (with its number of events) or why not."""
        out = []
        for url in cfg.get("agenda_ics") or []:
            fetched, text = self._ics.get(pages_mod.http_url(url), (0.0, ""))
            error = self._ics_errors.get(pages_mod.http_url(url))
            out.append({"url": url, "ok": bool(fetched) and not error, "events": text.count("BEGIN:VEVENT"),
                        "error": error, "public": "/public/" in url})
        return out

    async def _ha_agenda(self, calendars: list[str], now: datetime) -> list:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            response = await self.hass.services.async_call(
                "calendar", "get_events",
                {"entity_id": list(calendars), "start_date_time": start.isoformat(),
                 "end_date_time": (start + timedelta(days=1)).isoformat()},
                blocking=True, return_response=True,
            )
        except Exception as err:  # noqa: BLE001 - no agenda rather than no clock
            _LOGGER.debug("Calendars %s: %s", calendars, err)
            return []
        items = []
        for result in (response or {}).values():
            for event in result.get("events") or []:
                begin, end = event.get("start"), event.get("end")
                if begin and "T" not in str(begin):
                    items.append(pages_mod.Occurrence(event.get("summary") or "", None, None))
                else:
                    items.append(pages_mod.Occurrence(event.get("summary") or "", _local(begin),
                                                      _local(end) if end else None))
        return items

    async def _get_text(self, url: str) -> str:
        import aiohttp
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(self.hass)
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
            response.raise_for_status()
            return await response.text(errors="replace")

    async def _get_json(self, url: str, params: dict) -> dict:
        import aiohttp
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(self.hass)
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as response:
            response.raise_for_status()
            return await response.json()

    async def _from_open_meteo(self, latitude: float, longitude: float, place: str) -> Forecast:
        data = await self._get_json(FORECAST_URL, {
            "latitude": latitude, "longitude": longitude, "timezone": "auto", "forecast_days": DAY_SLOTS + 1,
            "current": "temperature_2m,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
            "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,"
                     "sunrise,sunset",
        })
        return parse_open_meteo(data, place)

    async def _from_entity(self, entity_id: str) -> Forecast:
        state = self._states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            raise HomeAssistantError(f"{entity_id} est indisponible")
        forecasts = {}
        for kind in ("hourly", "daily"):
            try:
                response = await self.hass.services.async_call(
                    "weather", "get_forecasts", {"entity_id": entity_id, "type": kind},
                    blocking=True, return_response=True,
                )
            except HomeAssistantError:  # this entity has no forecast of that kind
                response = None
            forecasts[kind] = ((response or {}).get(entity_id) or {}).get("forecast") or []
        sun = self._states.get("sun.sun")
        return parse_ha(state.state, dict(state.attributes), forecasts["hourly"], forecasts["daily"], local_now(),
                        state.attributes.get("friendly_name") or entity_id,
                        is_night=bool(sun and sun.state == "below_horizon"),
                        sun=ha_sun(dict(sun.attributes)) if sun else None)

    async def geocode(self, query: str) -> list[dict]:
        """Places matching what was typed (Open-Meteo's geocoding, in French)."""
        try:
            data = await self._get_json(GEOCODE_URL, {"name": query, "count": 6, "language": "fr", "format": "json"})
        except (_client_error(), asyncio.TimeoutError) as err:
            raise HomeAssistantError(f"Recherche du lieu impossible : {err or type(err).__name__}") from err
        return [{"name": _place_name(r), "latitude": r["latitude"], "longitude": r["longitude"]}
                for r in data.get("results") or [] if r.get("latitude") is not None]

    async def show(self, coordinator, forecasts: list[Forecast], cfg: dict, lead: float = 1.5, extras=None) -> int:
        """Send the rest of this minute, as it will be once it arrives (``lead`` seconds); returns its size."""
        size = int(coordinator.text_settings.get("screen_size", 64))
        start = local_now() + timedelta(seconds=lead)
        data = await self.hass.async_add_executor_job(
            render_meteo_minute, forecasts, start, cfg, size, labels_of(cfg, forecasts), extras)
        if not await coordinator.async_show_still(data, label=SEND_LABEL):
            raise HomeAssistantError("Envoi de la météo au cadre échoué")
        return len(data)

    async def set_brightness(self, coordinator, percent: int) -> None:
        from .client.modules.common import Common

        if await coordinator._device_call(Common().setBrightness, percent) is False:
            raise HomeAssistantError("Réglage de la luminosité échoué")
        coordinator.text_settings["brightness"] = round(percent * 255 / 100)
        coordinator.async_update_listeners()


def labels_of(cfg: dict, forecasts: list[Forecast]) -> list[str]:
    """The name written for each place: its own label, else the place's name."""
    return [profile.get("label") or forecast.place for profile, forecast in zip(cfg["profiles"], forecasts)]


def brightness_for(cfg: dict, forecasts: list[Forecast], now: datetime) -> int | None:
    """The view's day or night brightness, by the first place's sun (None: leave it alone)."""
    levels = cfg.get("brightness")
    if not levels or not forecasts:
        return None
    day = is_daytime(forecasts[0], now)
    return None if day is None else levels["day" if day else "night"]


def seconds_to_next_minute(now: datetime | None = None) -> float:
    now = now or datetime.now()
    return max(1.0, 60 - now.second - now.microsecond / 1e6 + 0.2)


def png_of(forecasts: list[Forecast], now: datetime, cfg: dict, size: int) -> bytes:
    """The screen at ``now`` (its place, its second) as a PNG, for the panel's LED preview."""
    return preview_of(forecasts, now, cfg, size)[0]


def page_key(page: dict) -> str:
    """A page's name in the mixing desk's durations: weather:0, agenda, special... (screen:2)"""
    if page["kind"] == "screen":
        return f"screen:{page['screen']}"
    return f"weather:{page['index']}" if page["kind"] == "weather" else page["kind"]


def turn_at(turns: list[dict], cfg: dict, moment: datetime) -> int:
    """Which page shows at ``moment``: the pages loop, each for its own time (``durations``, in
    seconds, else ``switch_seconds``), counted from midnight so it carries on from minute to minute."""
    switch = cfg.get("switch_seconds", 15)
    durations = cfg.get("durations") or {}
    lengths = [max(1, int(t.get("seconds") or durations.get(page_key(t), switch))) for t in turns]
    t = (moment.hour * 3600 + moment.minute * 60 + moment.second) % sum(lengths)
    for i, length in enumerate(lengths):
        if t < length:
            return i
        t -= length
    return 0


PART_NAMES = {"clock": "Heure", "seconds": "Secondes", "date": "Date", "name": "Ville", "today": "Météo du jour",
              "strip": "En bas", "days": "Prochains jours", "sun": "Lever / coucher", "special": "Fêtes", "birthdays": "Anniversaires", "countdown": "Compte à rebours",
              "reminders": "N'oubliez pas", "notes": "Notes",
              "agenda": "Agenda",
              "saint": "Saint du jour",
              "world_days": "Journées mondiales", "thought": "Philosophie", "proverb": "Dicton",
              "fact": "Savoir inutile", "motivation": "Courage", "humor": "Citation marrante", "wellbeing": "Bien-être",
              "word": "Mot du jour"}


def page_title(page: dict, labels: list) -> str:
    """What a page is, for the panels' page numbers."""
    if page["kind"] == "screen":
        named = [PART_NAMES[p] for p in page["parts"] if p in PAGE_PARTS] or (
            [str(labels[page["index"]] or "Météo").split(",")[0]] if {"today", "strip", "name", *EXTRA_STRIPS} & set(page["parts"])
            else [PART_NAMES[p] for p in page["parts"]][:2])
        return ", ".join(named) or "Vide"
    if page["kind"] == "weather":
        return str(labels[page["index"]] or "Météo").split(",")[0]
    if page["kind"] == "special":
        return f"{page['special'].title} {page['special'].line}".strip().title()
    return {"birthdays": "Anniversaires", "agenda": "Agenda", "saint": "Saint du jour", "world_days": "Journées mondiales",
            "thought": "Philosophie",
            "proverb": "Dicton", "fact": "Savoir inutile", "motivation": "Courage", "humor": "Citation marrante",
            "wellbeing": "Bien-être", "word": "Mot du jour"}.get(page["kind"], page["kind"])


def preview_of(forecasts: list[Forecast], now: datetime, cfg: dict, size: int, extras=None,
               pin: int | None = None) -> tuple[bytes, dict]:
    """The screen at ``now`` as a PNG, and where each of its parts is (to pick and drag them).

    ``pin``: show that page (its number in the turns; with screens, the screen's number, even one
    with nothing now) whatever the time, to edit it.
    """
    minute = now.replace(second=0, microsecond=0)
    turns = page_list(forecasts, cfg, extras, now) if size >= 64 else page_list(forecasts, {}, None, now)
    current = turn_at(turns, cfg, now)
    page = turns[current]
    if cfg.get("screens") and size >= 64:  # every screen numbered, the one asked for or the one on now
        every = page_list(forecasts, cfg, extras, now, every=True)
        wanted = pin if pin is not None and 0 <= pin < len(every) else page.get("screen", 0)
        page = next((t for t in every if t["screen"] == wanted), page)
        turns = every
    elif pin is not None and 0 <= pin < len(turns):
        page = turns[pin]
    i = page.get("index", 0)
    ticking = ticks(cfg) and size >= 64
    phase = (now.second * 1000 + now.microsecond // 1000) // ANIMATION_MS % PHASES if cfg.get("animate", True) else 0
    label = labels_of(cfg, forecasts)[i]
    image = render_meteo(forecasts[i], now, cfg, size, label=label, second=now.second if ticking else None, phase=phase,
                         page=page)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    # The parts to pick and drag: the weather's, or the time and the block of another page.
    boxes = element_boxes(forecasts[i], now, cfg, size, label, page)
    labels = labels_of(cfg, forecasts)
    boxes["_pages"] = [{"title": page_title(t, labels), "key": page_key(t), "screen": t.get("screen"),
                        "off": t.get("off", False)} for t in turns]
    boxes["_page"] = turns.index(page)
    return buffer.getvalue(), boxes


# ---------------------------------------------------------------------------
# The other pages (pages.py): agenda, saint, world days, texts, special days
# ---------------------------------------------------------------------------

AGENDA_COLORS = ((90, 160, 255), (255, 150, 70), (120, 210, 120), (230, 110, 200), (240, 210, 80))


def _small_lines(d: ImageDraw.ImageDraw, x: int, y: int, lines: list[str], color: tuple, bottom: int) -> int:
    """Lines of the small font from row ``y``; returns the next free row."""
    for line in lines:
        if y + 5 > bottom:
            break
        _draw_small(d, x, y, line, color)
        y += 6
    return y


def _fits(text: str, width: int, rows: int, big: bool) -> bool:
    """Whether ``text`` goes in ``rows`` rows of ``width``, no word cut, in big (5×7) or small letters."""
    measure, line = (_text_width, 9) if big else (_small_width, 6)
    if any(measure(word) > width for word in text.split()):
        return False
    return len(pages_mod.wrap(text, width, measure)) * line - (line - (7 if big else 5)) <= rows


def _text_level(texts: list[str], width: int, room: int, level: int, heading: int) -> tuple[bool, bool]:
    """(big letters, heading) for texts sharing ``room`` rows: the biggest that keeps every word,
    the heading (``heading`` rows) dropped before the letters shrink. Level 1: small, no heading."""
    tries = [(True, True), (True, False)] if level >= 3 else []
    tries += [(False, True), (False, False)] if level >= 2 else [(False, False)]
    for big, headed in tries:
        rows = room - (heading if headed else 0)
        line = 9 if big else 6
        needed = sum(len(pages_mod.wrap(t, width, _text_width if big else _small_width)) * line for t in texts)
        if needed - (line - (7 if big else 5)) <= rows and all(_fits(t, width, rows, big) for t in texts):
            return big, headed
    return False, False  # too long anyway: small letters, as much as goes in


def _big_lines(d: ImageDraw.ImageDraw, y: int, text: str, color: tuple, size: int, bottom: int) -> int:
    """Text in the 5×7 letters, line after line from row ``y``; returns the next free row."""
    for line in pages_mod.wrap(text, size - 2, _text_width):
        if y + 7 > bottom:
            break
        _draw_text(d, 1, y, line, color)
        y += 9
    return y


def _wrap_small(text: str, width: int) -> list[str]:
    return pages_mod.wrap(_small_text(text).strip(), width, _small_width)


def _draw_page(img: Image.Image, page: dict, now: datetime, cfg: dict, size: int, top: int, color: tuple,
               level: int = 2) -> None:
    """A page under the time: ``top`` is its first row. ``level`` 1: compact (no heading, small
    pictures), 2: as usual, 3: big letters."""
    d = ImageDraw.Draw(img)
    kind = page["kind"]
    bottom = size
    if kind == "special":
        _draw_special(img, page["special"], top, size, level)
    elif kind == "agenda":
        _draw_agenda(d, page["items"], page.get("style", "list"), now, cfg, size, top, color, level, img)
    elif kind == "word":  # the word in gold, big if it fits, then what it means
        word, meaning = pages_mod.word_of_day(now)
        word, meaning = _small_text(word).strip(), _small_text(meaning).strip()
        heading = 7 if level >= 2 else 0
        big = level >= 2 and _text_width(word) <= size - 2
        y = top + 1
        if level >= 2:
            _draw_small(d, (size - _small_width("LE MOT DU JOUR")) // 2, y, "LE MOT DU JOUR", DIM)
            y += heading
        if big:
            _draw_text(d, (size - _text_width(word)) // 2, y, word, pages_mod.GOLD)
            y += 9
        else:
            y = _small_lines(d, 1, y, _wrap_small(word, size - 2), pages_mod.GOLD, bottom) + 1
        fits, _headed = _text_level([meaning], size - 2, bottom - y, 3 if level >= 3 else 2, 0)
        y = (_big_lines(d, y, meaning, NAME_COLOR, size, bottom) if fits
             else _small_lines(d, 1, y, _wrap_small(meaning, size - 2), NAME_COLOR, bottom))
    elif kind == "notes":
        texts = [_small_text(note).strip() for note in page["items"]]
        big, headed = _text_level(texts, size - 2, bottom - top - 1 - 2 * (len(texts) - 1), level, 7)
        y = top + 1
        if headed:
            _draw_small(d, (size - _small_width("NOTES")) // 2, y, "NOTES", DIM)
            y += 7
        for n, text in enumerate(texts):
            tint = (NAME_COLOR, pages_mod.GOLD)[n % 2]
            y = (_big_lines(d, y, text, tint, size, bottom) if big
                 else _small_lines(d, 1, y, _wrap_small(text, size - 2), tint, bottom)) + 2
    elif kind == "reminders":
        hour24 = cfg.get("hour24", True)
        texts = []
        for item in page["items"]:
            if isinstance(item, str):
                texts.append(_small_text(item).strip())
            else:  # an agenda event: its time first
                at = "" if item.start is None else (f"{item.start.hour}H{item.start.minute:02d}" if hour24 else
                                                      f"{(item.start.hour - 1) % 12 + 1}{'AM' if item.start.hour < 12 else 'PM'}")
                texts.append(_small_text(f"{at} {item.summary}").strip())
        big, headed = _text_level(texts, size - 2, bottom - top - 1 - 2 * (len(texts) - 1), level, 13)
        y = top + 1
        if headed:
            for line in ("AUJOURD'HUI", "N'OUBLIEZ PAS"):
                _draw_small(d, (size - _small_width(line)) // 2, y, line, DIM)
                y += 6
            y += 1
        for n, text in enumerate(texts):
            tint = AGENDA_COLORS[n % len(AGENDA_COLORS)]
            y = (_big_lines(d, y, text, tint, size, bottom) if big
                 else _small_lines(d, 1, y, _wrap_small(text, size - 2), tint, bottom)) + 2
    elif kind == "countdown":
        said = countdown_text(page.get("date"), now)
        if said is None:
            return
        count, arrived = said
        weekend = page.get("date") == "weekend"
        title = _small_text(page.get("title") or ("LE WEEK-END" if weekend else "")).strip()
        if arrived:
            texts = ["C'EST LE WEEK-END !" if weekend else (f"C'EST {title} !" if title else "C'EST AUJOURD'HUI !")]
        else:
            texts = [f"AVANT {title}"] if title else []
        y = top + 1
        if not arrived:  # the count, as big as the size says
            scale = 2 if level >= 3 and _text_width(count, 2) <= size - 2 else 1
            if level == 1:
                _draw_small(d, (size - _small_width(count)) // 2, y, count, color)
                y += 7
            else:
                _draw_text(d, (size - _text_width(count, scale)) // 2, y, count, color, scale)
                y += 7 * scale + 3
        big, _headed = _text_level(texts, size - 2, bottom - y, 3 if arrived and level >= 2 else level - 1 or 1, 0)
        for text in texts:
            for line in pages_mod.wrap(text, size - 2, _text_width if big else _small_width):
                if y + (7 if big else 5) > bottom:
                    break
                w = _text_width(line) if big else _small_width(line)
                (_draw_text if big else _draw_small)(d, (size - w) // 2, y, line, pages_mod.GOLD if arrived else NAME_COLOR)
                y += 9 if big else 6
    elif kind == "birthdays":
        y = top
        if level >= 2:  # the cake and « JOYEUX ANNIV », then whose
            cake = _special_icon("cake", (pages_mod.PINK, pages_mod.GOLD)).resize((16, 16), Image.NEAREST)
            img.paste(cake, ((size - 16) // 2, y), cake.convert("L").point(lambda v: 255 if v else 0))
            y += 17
            _draw_small(d, (size - _small_width("JOYEUX ANNIV")) // 2, y, "JOYEUX ANNIV", pages_mod.PINK)
            y += 7
        texts = [_small_text(f"{name} {age}").strip() for name, age in page["people"]]
        big, _headed = _text_level(texts, size - 2, bottom - y, level, 0)
        for n, text in enumerate(texts):
            tint = (pages_mod.GOLD, NAME_COLOR)[n % 2]
            lines = pages_mod.wrap(text, size - 2, _text_width if big else _small_width)
            for line in lines:
                if y + (7 if big else 5) > bottom:
                    break
                w = _text_width(line) if big else _small_width(line)
                (_draw_text if big else _draw_small)(d, (size - w) // 2, y, line, tint)
                y += 9 if big else 6
    elif kind == "saint":
        names = [_small_text(n).strip() for n in page["names"]]
        y = top + 1
        if level >= 2:
            title = _small_text(cfg.get("saint_title", "BONNE FÊTE")).strip()
            to = ("AUX" if len(names) > 1 else "A") if cfg.get("saint_to", True) else ""
            lines = [f"{title} {to}".strip()]
            if title and to and _small_width(lines[0]) > size - 2:
                lines = [title, to]
            for line in filter(None, lines):
                _draw_small(d, (size - _small_width(line)) // 2, y, line, DIM)
                y += 6
            y += 2 if y > top + 1 else 0
        # As many names as fit; more of them take turns every few seconds (a slideshow).
        def height(name: str) -> int:
            if level >= 2 and _text_width(name) <= size - 2:
                return 9
            return len(pages_mod.wrap(name, size - 2, _small_width)) * 6
        groups, room = [[]], bottom - y
        for name in names:
            if groups[-1] and sum(map(height, groups[-1])) + height(name) - 2 > room:
                groups.append([])
            groups[-1].append(name)
        shown = groups[(now.second // SLIDE_SECONDS) % len(groups)]
        if len(groups) > 1:  # which slide: dots in the corner
            for k in range(len(groups)):
                d.point((size - 2 - 2 * (len(groups) - 1 - k), bottom - 1),
                        fill=NAME_COLOR if groups[k] is shown else DIM)
        for name in shown:
            big = level >= 2 and _text_width(name) <= size - 2  # a long name in small letters, whole
            if big and y + 7 <= bottom:
                _draw_text(d, (size - _text_width(name)) // 2, y, name, NAME_COLOR)
                y += 9
            else:
                y = _small_lines(d, 1, y, pages_mod.wrap(name, size - 2, _small_width), NAME_COLOR, bottom)
    elif kind == "world_days":
        # « JOURNÉE MONDIALE » as the heading, the rest under it with its article: « DE LA GENTILLESSE ».
        kinds = [re.match(r"^\W*journ[ée]e (mondiale|internationale)\b", item, flags=re.I) for item in page["items"]]
        texts = [_small_text(item[m.end():] if m else item).strip() for item, m in zip(page["items"], kinds)]
        heading = _small_text(cfg.get("world_days_title") or
                              (f"J. {kinds[0].group(1)}" if kinds and kinds[0] else "AUJOURD'HUI")).strip()
        big, headed = _text_level(texts, size - 2, bottom - top - 1 - 2 * (len(texts) - 1), level, 7)
        y = top + 1
        if headed:
            _draw_small(d, (size - _small_width(heading)) // 2, y, heading, DIM)
            y = top + 8
        for n, text in enumerate(texts):
            tint = AGENDA_COLORS[n % len(AGENDA_COLORS)]
            if big:
                y = _big_lines(d, y, text, tint, size, bottom) + 2
            else:
                y = _small_lines(d, 1, y, _wrap_small(text, size - 2), tint, bottom) + 2
    else:
        header, text, author = pages_mod.text_of_hour(kind, now)
        text = _small_text(text).strip()
        room = bottom - top - 1 - (6 if author else 0)
        big, headed = _text_level([text], size - 2, room, level, 7)
        y = top + 1
        if headed:
            _draw_small(d, (size - _small_width(_small_text(header))) // 2, y, _small_text(header), DIM)
            y = top + 8
        if big:
            y = _big_lines(d, y, text, NAME_COLOR, size, bottom - (6 if author else 0))
        else:
            y = _small_lines(d, 1, y, _wrap_small(text, size - 2), NAME_COLOR, bottom - (6 if author else 0))
        if author:
            signed = _small_text(author)
            _draw_small(d, size - _small_width(signed) - 1, min(y, bottom - 5), signed,
                        color if max(color) > 1 else AGENDA_COLORS[0])  # not black: no outline here


def _bounce(overflow: int, t: int, speed: int = 6, hold: int = 2) -> int:
    """How far a text ``overflow`` LEDs too wide is shifted at second ``t``: still a moment at its
    start, sliding left, still at its end, sliding back (to read it all)."""
    if overflow <= 0:
        return 0
    moving = -(-overflow // speed)
    k = t % (2 * (hold + moving))
    if k < hold:
        return 0
    if k < hold + moving:
        return min(overflow, (k - hold + 1) * speed)
    if k < 2 * hold + moving:
        return overflow
    return max(0, overflow - (k - 2 * hold - moving + 1) * speed)


AGENDA_ROWS = 2  # appointments shown at once; more go up one by one
SLIDE_HOLD = 1  # seconds still at each end of a sliding text
SCROLL_SPEEDS = {"slow": 5, "normal": 10, "fast": 16, "faster": 24}  # LEDs a second


def _speed(cfg: dict) -> int:
    return SCROLL_SPEEDS.get(cfg.get("scroll_speed", "normal"), 10)


def _slide_time(overflow: int, speed: int = 10) -> int:
    """Seconds to read a text ``overflow`` LEDs too wide once: still, sliding, still at its end."""
    return 0 if overflow <= 0 else 2 * SLIDE_HOLD + -(-overflow // speed)


def _slide(overflow: int, t: int, speed: int = 10) -> int:
    """The shift, ``t`` seconds after it showed, of a text read once (``_slide_time``)."""
    if overflow <= 0 or t < SLIDE_HOLD:
        return 0
    return min(overflow, (t - SLIDE_HOLD + 1) * speed)


def _draw_agenda(d: ImageDraw.ImageDraw, items: list, style: str, now: datetime, cfg: dict, size: int, top: int,
                 color: tuple, level: int = 2, img: Image.Image | None = None) -> None:
    hour24 = cfg.get("hour24", True)
    day = f"{pages_mod.ascii_upper(('LU', 'MA', 'ME', 'JE', 'VE', 'SA', 'DI')[now.weekday()])} {now.day}"
    heading = _small_text(cfg.get("agenda_title", "AGENDA")).strip()
    if heading:
        _draw_small(d, 1, top + 1, heading, DIM)
    if cfg.get("agenda_day", True):
        _draw_small(d, size - _small_width(day) - 1, top + 1, day, DIM)
    if not items:
        message = _small_text("Rien de prévu")
        _draw_small(d, (size - _small_width(message)) // 2, top + 20, message, NAME_COLOR)
        return
    timed = [o for o in items if o.start is not None]
    all_day = [o for o in items if o.start is None]
    y = top + 8
    if style == "timeline":
        # 7 h to 23 h across the screen, a block per event, the time now in red.
        first, last = 7, 23
        span = (last - first) * 60

        def x_of(moment: datetime) -> int:
            minutes = (moment.hour - first) * 60 + moment.minute
            return max(0, min(size - 1, round(minutes * (size - 1) / span)))

        for h in (8, 12, 16, 20):
            label = str(h)
            x = x_of(now.replace(hour=h, minute=0))
            _draw_small(d, x - _small_width(label) // 2, y, label, DIM)
            d.point((x, y + 6), fill=DIM)
        bar = y + 8
        d.rectangle([0, bar, size - 1, bar + 4], fill=(30, 32, 40))
        for n, o in enumerate(timed):
            local = o.start.astimezone(now.tzinfo) if now.tzinfo else o.start
            end = (o.end or o.start + timedelta(hours=1)).astimezone(now.tzinfo) if now.tzinfo else o.end
            d.rectangle([x_of(local), bar, max(x_of(local), x_of(end) - 1), bar + 4],
                        fill=AGENDA_COLORS[n % len(AGENDA_COLORS)])
        if first <= now.hour < last:
            x = x_of(now)
            d.line([(x, bar - 2), (x, bar + 6)], fill=(255, 60, 60))
        y = bar + 8
        upcoming = [o for o in timed if (o.end or o.start) > now] or timed[-1:]
        shown = all_day + upcoming
    else:
        shown = all_day + timed
    # The whole day, two at a time; a title too long slides to be read; more go up one by one, each
    # pair staying until its titles have slid through; those over struck through.
    t = now.hour * 3600 + now.minute * 60 + now.second
    speed = _speed(cfg)
    big = level >= 3
    height, line = (7, 9) if big else (5, 6)
    rows = []
    for o in shown:
        past = False
        if o.start is None:
            when, tint = "-", DIM
        else:
            local = o.start.astimezone(now.tzinfo) if now.tzinfo else o.start
            when = _clock_text(local, hour24)
            past = (o.end or o.start + timedelta(hours=1)) <= now
            tint = DIM if past else color
        if not cfg.get("agenda_time", True):
            when = ""
        title = _small_text(o.summary).strip()
        width = _text_width(title) if big else _small_width(title)
        x = _small_width(when) + 4 if when else 1
        rows.append((when, tint, title, width, x, past))
    over = [max(0, width - (size - x)) for _w, _t, _ti, width, x, _p in rows]
    first, local_t = 0, t
    if len(rows) > AGENDA_ROWS:  # each pair stays until its titles have slid through
        stays = [max(SLIDE_SECONDS, *(_slide_time(over[(i + k) % len(rows)], speed) for k in range(AGENDA_ROWS)))
                 for i in range(len(rows))]
        local_t = t % sum(stays)
        while local_t >= stays[first]:
            local_t -= stays[first]
            first += 1
    for k in range(min(AGENDA_ROWS, len(rows))):
        n = (first + k) % len(rows)
        when, tint, title, width, x, past = rows[n]
        if y + height > size:
            break
        if when:
            _draw_small(d, 1, y + (height - 5) // 2, when, tint)
        room = size - x
        strip = Image.new("RGB", (max(1, width), height), (0, 0, 0))
        (_draw_text if big else _draw_small)(ImageDraw.Draw(strip), 0, 0, title, DIM if past else NAME_COLOR)
        shift = _slide(over[n], local_t, speed) if len(rows) > AGENDA_ROWS else _bounce(over[n], t, speed, SLIDE_HOLD)
        shown_part = strip.crop((shift, 0, shift + room, height))
        if img is not None:
            img.paste(shown_part, (x, y), shown_part.convert("L").point(lambda v: 255 if v else 0))
        if past:  # over: struck through
            d.line([(1, y + height // 2), (min(size - 1, x + min(room, width)), y + height // 2)], fill=(170, 170, 180))
        y += line
    if len(rows) > AGENDA_ROWS:  # which ones: a dot per appointment, the first shown lit
        for k in range(len(rows)):
            dot = size - 2 - 2 * (len(rows) - 1 - k)
            if dot >= 0:
                d.point((dot, size - 1), fill=NAME_COLOR if k == first else DIM)


def _draw_special(img: Image.Image, special, top: int, size: int, level: int = 2) -> None:
    """A special day: its picture, then its name (and a line under it)."""
    d = ImageDraw.Draw(img)
    room = size - top
    icon_size = 16 if level == 1 else 32 if (room >= 46 or level >= 3) else 16
    picture = _special_icon(special.key, special.colors)
    if icon_size == 16:
        picture = picture.resize((16, 16), Image.NEAREST)
    img.paste(picture, ((size - icon_size) // 2, top), picture.convert("L").point(lambda v: 255 if v else 0))
    y = top + icon_size + 1
    title = _small_text(special.title).strip()
    if _text_width(title) <= size - 2 and y + 7 <= size:
        _draw_text(d, (size - _text_width(title)) // 2, y, title, special.colors[0])
        y += 8
    else:
        _draw_small(d, (size - _small_width(title)) // 2, y, title, special.colors[0])
        y += 6
    if special.line and y + 5 <= size:
        line = _small_text(special.line).strip()
        while _small_width(line) > size - 2:
            line = line[:-1]
        _draw_small(d, (size - _small_width(line)) // 2, y, line, special.colors[1])


def _special_icon(key: str, colors: tuple) -> Image.Image:
    """The special days' pictures, drawn at 32×32."""
    img = Image.new("RGB", (32, 32), (0, 0, 0))
    d = ImageDraw.Draw(img)
    a, b = colors
    if key == "heart":
        d.ellipse([4, 6, 17, 19], fill=a)
        d.ellipse([15, 6, 28, 19], fill=a)
        d.polygon([(5, 15), (27, 15), (16, 28)], fill=a)
        d.ellipse([8, 9, 11, 12], fill=(255, 220, 235))
    elif key == "tree":
        d.polygon([(16, 2), (24, 12), (8, 12)], fill=(40, 160, 70))
        d.polygon([(16, 7), (27, 20), (5, 20)], fill=(40, 160, 70))
        d.polygon([(16, 12), (29, 27), (3, 27)], fill=(30, 140, 60))
        d.rectangle([14, 27, 18, 31], fill=(130, 80, 40))
        for x, y, c in ((11, 17, (230, 50, 50)), (20, 22, pages_mod.GOLD), (14, 23, (80, 140, 255)), (21, 15, (230, 50, 50))):
            d.rectangle([x, y, x + 1, y + 1], fill=c)
        d.polygon([(16, 0), (17, 2), (16, 4), (15, 2)], fill=pages_mod.GOLD)
    elif key == "egg":
        d.ellipse([7, 3, 25, 29], fill=a)
        for x in range(8, 25, 4):
            d.line([(x, 15), (x + 2, 13), (x + 4, 15)], fill=b, width=2)
        d.ellipse([12, 21, 15, 24], fill=(120, 200, 255))
    elif key == "cake":
        d.rectangle([5, 17, 26, 29], fill=(170, 100, 60))
        d.rectangle([5, 15, 26, 19], fill=a)
        d.rectangle([5, 23, 26, 24], fill=(255, 240, 240))
        for x in (9, 15, 21):
            d.rectangle([x, 9, x + 1, 14], fill=(120, 190, 255))
            d.ellipse([x - 1, 5, x + 2, 8], fill=pages_mod.GOLD)
    elif key == "fireworks":
        for cx, cy, c in ((11, 11, a), (22, 19, b), (9, 24, (230, 80, 200))):
            for k in range(8):
                rad = k * math.pi / 4
                d.line([(cx + 2 * math.cos(rad), cy + 2 * math.sin(rad)),
                        (cx + 7 * math.cos(rad), cy + 7 * math.sin(rad))], fill=c)
            d.point((cx, cy), fill=(255, 255, 255))
    elif key == "pumpkin":
        d.ellipse([3, 8, 29, 30], fill=(240, 130, 20))
        d.line([(16, 9), (16, 29)], fill=(200, 100, 10))
        d.rectangle([15, 3, 17, 8], fill=(60, 140, 50))
        d.polygon([(9, 15), (13, 15), (11, 12)], fill=(0, 0, 0))
        d.polygon([(19, 15), (23, 15), (21, 12)], fill=(0, 0, 0))
        d.polygon([(9, 21), (23, 21), (21, 25), (11, 25)], fill=(0, 0, 0))
    elif key == "flag":
        d.rectangle([3, 6, 11, 26], fill=(40, 70, 220))
        d.rectangle([12, 6, 20, 26], fill=(245, 245, 245))
        d.rectangle([21, 6, 29, 26], fill=(230, 40, 50))
    elif key == "fish":
        d.ellipse([4, 9, 23, 23], fill=a)
        d.polygon([(21, 16), (30, 8), (30, 24)], fill=b)
        d.ellipse([8, 13, 11, 16], fill=(255, 255, 255))
        d.point((9, 14), fill=(0, 0, 0))
    elif key == "muguet":
        d.line([(16, 30), (16, 6)], fill=(60, 160, 70))
        d.ellipse([3, 12, 14, 30], fill=(40, 130, 60))
        for y, side in ((7, 1), (11, -1), (15, 1), (19, -1), (23, 1)):
            d.ellipse([16 + side * 2 - 2, y, 16 + side * 2 + 3, y + 4], fill=(250, 250, 250))
    elif key == "note":
        d.ellipse([6, 20, 14, 27], fill=a)
        d.rectangle([13, 6, 14, 23], fill=a)
        d.ellipse([18, 17, 26, 24], fill=b)
        d.rectangle([25, 3, 26, 20], fill=b)
        d.line([(14, 6), (26, 3)], fill=a, width=2)
    elif key == "star":
        points = [(16 + 13 * math.cos(math.pi / 2 + k * math.pi / 5) * (1 if k % 2 == 0 else 0.45),
                   17 - 13 * math.sin(math.pi / 2 + k * math.pi / 5) * (1 if k % 2 == 0 else 0.45)) for k in range(10)]
        d.polygon(points, fill=a)
    elif key == "candle":
        d.rectangle([12, 12, 20, 30], fill=(240, 235, 220))
        d.ellipse([13, 3, 19, 11], fill=(255, 170, 40))
        d.ellipse([15, 6, 17, 10], fill=(255, 240, 150))
    elif key == "bleuet":
        for k in range(8):
            rad = k * math.pi / 4
            cx, cy = 16 + 8 * math.cos(rad), 13 + 8 * math.sin(rad)
            d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(70, 110, 240))
        d.ellipse([12, 9, 20, 17], fill=(40, 40, 120))
        d.line([(16, 22), (16, 31)], fill=(60, 150, 70), width=2)
    elif key == "crown":
        d.polygon([(4, 24), (4, 10), (10, 17), (16, 7), (22, 17), (28, 10), (28, 24)], fill=pages_mod.GOLD)
        for x, c in ((10, (230, 50, 50)), (16, (80, 140, 255)), (22, (60, 190, 90))):
            d.rectangle([x - 1, 19, x + 1, 21], fill=c)
    elif key == "crepe":
        d.ellipse([3, 6, 29, 28], fill=(235, 180, 80))
        for x, y in ((10, 12), (19, 10), (14, 20), (22, 19), (8, 19)):
            d.ellipse([x, y, x + 3, y + 2], fill=(190, 120, 40))
    elif key == "clover":
        for cx, cy in ((16, 9), (10, 17), (22, 17)):
            d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=(50, 170, 70))
        d.line([(16, 18), (19, 31)], fill=(40, 130, 50), width=2)
    elif key == "flower":
        for k in range(6):
            rad = k * math.pi / 3
            cx, cy = 16 + 7 * math.cos(rad), 12 + 7 * math.sin(rad)
            d.ellipse([cx - 5, cy - 5, cx + 5, cy + 5], fill=a)
        d.ellipse([12, 8, 20, 16], fill=pages_mod.GOLD)
        d.line([(16, 20), (16, 31)], fill=(60, 150, 70), width=2)
        d.ellipse([17, 24, 24, 28], fill=(60, 150, 70))
    elif key == "tie":
        d.polygon([(13, 3), (19, 3), (17, 8), (15, 8)], fill=b)
        d.polygon([(15, 8), (17, 8), (21, 25), (16, 30), (11, 25)], fill=a)
    elif key == "mask":
        d.ellipse([3, 9, 29, 25], fill=a)
        d.ellipse([8, 13, 14, 18], fill=(0, 0, 0))
        d.ellipse([18, 13, 24, 18], fill=(0, 0, 0))
        d.line([(3, 12), (0, 6)], fill=b, width=2)
    return img
