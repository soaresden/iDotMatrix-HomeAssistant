import asyncio
import io
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageSequence

from custom_components.idotmatrix import meteo, routines
from custom_components.idotmatrix.meteo import (
    PACKET_BYTES,
    WEATHER_SCHEMA,
    Forecast,
    Hour,
    Slot,
    WeatherService,
    brightness_for,
    hour_slots,
    is_daytime,
    labels_of,
    next_sun,
    parse_ha,
    parse_open_meteo,
    png_of,
    render_meteo,
    render_meteo_minute,
    screen_name,
    wmo_condition,
)
from custom_components.idotmatrix.routines import ROUTINE_SCHEMA, RoutineRunner
from custom_components.idotmatrix.weather import WeatherData
from homeassistant.exceptions import HomeAssistantError

import voluptuous as vol  # noqa: E402

UTC = timezone.utc
NOON = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)  # an ordinary Tuesday: no special day's page


def _forecast(place="Lyon", **extra) -> Forecast:
    hours = [Hour(NOON + timedelta(hours=h), ("rainy", "partlycloudy", "clear-night", "cloudy")[h % 4], 10 + h)
             for h in range(36)]
    sun = [(NOON.replace(hour=7, minute=20) + timedelta(days=d), "rise") for d in range(3)] + \
          [(NOON.replace(hour=17, minute=28) + timedelta(days=d), "set") for d in range(3)]
    return Forecast(**{
        "place": place, "now": WeatherData("rainy", 12.4, high=15, low=-3), "rain": 40, "hours": hours,
        "days": [Slot("SA", "sunny", high=17, low=6), Slot("DI", "snowy", high=2, low=-8),
                 Slot("LU", "lightning-rainy", high=21, low=14)],
        "sun": sorted(sun), "fetched": time.time(), **extra,
    })


OPEN_METEO = {
    "utc_offset_seconds": 0,
    "current_units": {"temperature_2m": "°C"},
    "current": {"time": "2026-10-31T14:15", "temperature_2m": 12.6, "relative_humidity_2m": 80,
                "weather_code": 61, "is_day": 1, "wind_speed_10m": 9},
    "hourly": {
        "time": [f"2026-10-31T{h:02d}:00" for h in range(24)] + [f"2026-11-01T{h:02d}:00" for h in range(24)],
        "temperature_2m": list(range(48)),
        "weather_code": [0] * 48,
        "precipitation_probability": [5] * 14 + [70] + [10] * 33,
        "is_day": [0] * 7 + [1] * 11 + [0] * 13 + [1] * 11 + [0] * 6,
    },
    "daily": {
        "time": ["2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03"],
        "weather_code": [61, 3, 71, 95],
        "temperature_2m_max": [15.2, 11, 2, 9], "temperature_2m_min": [6.1, 4, -8, 1],
        "precipitation_probability_max": [90, 20, 60, 80],
        "sunrise": ["2026-10-31T07:20", "2026-11-01T07:22", "2026-11-02T07:23", "2026-11-03T07:25"],
        "sunset": ["2026-10-31T17:28", "2026-11-01T17:26", "2026-11-02T17:25", "2026-11-03T17:24"],
    },
}


def test_open_meteo_gives_today_the_hours_the_days_and_the_sun():
    forecast = parse_open_meteo(OPEN_METEO, "Lyon")
    now = datetime(2026, 10, 31, 14, 15, tzinfo=UTC)
    assert (forecast.now.condition, forecast.now.temperature, forecast.now.high, forecast.now.low) == ("rainy", 12.6, 15.2, 6.1)
    # The chance of rain over the next 12 hours, not the whole day's.
    assert forecast.rain == 70
    slots = hour_slots(forecast, now, {})
    assert [(s.label, s.temperature) for s in slots] == [("17H", 17), ("20H", 20), ("23H", 23), ("2H", 26)]
    assert slots[2].condition == "clear-night"  # clear, at night
    # 2026-11-01 is a Sunday.
    assert [(s.label, s.condition, s.high, s.low) for s in forecast.days] == [
        ("DI", "cloudy", 11, 4), ("LU", "snowy", 2, -8), ("MA", "lightning-rainy", 9, 1)]
    rise, sunset = next_sun(forecast, now)
    assert (rise.strftime("%d %H:%M"), sunset.strftime("%d %H:%M")) == ("01 07:22", "31 17:28")
    assert is_daytime(forecast, now) is True
    assert is_daytime(forecast, now.replace(hour=20)) is False


def test_the_strip_hours_are_every_n_hours_or_the_ones_chosen():
    forecast = parse_open_meteo(OPEN_METEO, "Lyon")
    now = datetime(2026, 10, 31, 14, 15, tzinfo=UTC)
    assert [s.label for s in hour_slots(forecast, now, {"hours_step": 1})] == ["15H", "16H", "17H", "18H"]
    # The next of each chosen hour, in the order they come.
    assert [s.label for s in hour_slots(forecast, now, {"hours_at": [8, 12, 18, 21]})] == ["18H", "21H", "8H", "12H"]


def test_wmo_codes():
    assert [wmo_condition(c) for c in (0, 2, 3, 45, 63, 65, 73, 96)] == [
        "sunny", "partlycloudy", "cloudy", "fog", "rainy", "pouring", "snowy", "hail"]
    assert wmo_condition(0, is_day=0) == "clear-night"
    assert wmo_condition(None) == "unknown"


def test_a_home_assistant_entity_and_its_forecasts():
    now = datetime(2026, 10, 31, 14, 20, tzinfo=UTC)
    iso = lambda dt: dt.isoformat()  # noqa: E731
    hourly = [{"datetime": iso(now.replace(minute=0) + timedelta(hours=h)), "condition": "cloudy",
               "temperature": 10 + h, "precipitation": 0.5 if h == 2 else 0} for h in range(24)]
    daily = [{"datetime": iso(now.replace(hour=11, minute=0) + timedelta(days=d)), "condition": "rainy",
              "temperature": 15 + d, "templow": 5 + d} for d in range(5)]
    sun = meteo.ha_sun({"next_rising": "2026-11-01T06:20:00+00:00", "next_setting": "2026-10-31T16:28:00+00:00"})
    forecast = parse_ha("partlycloudy", {"temperature": 12.3, "temperature_unit": "°C", "humidity": 70},
                        hourly, daily, now, "Maison", sun=sun)
    assert (forecast.now.condition, forecast.now.high, forecast.now.low) == ("partlycloudy", 15, 5)
    assert [s.temperature for s in hour_slots(forecast, now, {})] == [13, 16, 19, 22]
    assert [(s.high, s.low) for s in forecast.days] == [(16, 6), (17, 7), (18, 8)]
    # met.no gives no chance of rain: the amount over the next 12 hours instead.
    assert (forecast.rain, forecast.rain_mm) == (None, 0.5)
    assert is_daytime(forecast, now) is True


def _frames(data: bytes) -> list:
    with Image.open(io.BytesIO(data)) as image:
        return [(frame.convert("RGB"), frame.info.get("duration")) for frame in ImageSequence.Iterator(image)]


def _cfg(**extra) -> dict:
    return WEATHER_SCHEMA({"profiles": [{"source": "place", "place": {"name": "Lyon", "latitude": 45.7, "longitude": 4.8}},
                                        {"source": "place", "label": "Mamie",
                                         "place": {"name": "Marseille", "latitude": 43.3, "longitude": 5.4}}],
                           **extra})


def test_a_minute_ticks_its_seconds_and_turns_places_every_15_seconds():
    forecasts = [_forecast("Lyon"), _forecast("Marseille")]
    cfg = _cfg(animate=False)
    data = render_meteo_minute(forecasts, NOON.replace(second=10), cfg, 64, labels_of(cfg, forecasts))
    frames = _frames(data)
    assert len(frames) == 50 and {ms for _, ms in frames} == {1000}  # 10 s to 59 s
    # Two packets at most: later images only redraw what changed.
    assert len(data) <= 2 * PACKET_BYTES
    # Second 14 -> 15: the place turns (the name, more than the seconds, changes).
    before, after = frames[4][0], frames[5][0]
    assert before.crop((0, 15, 64, 20)).tobytes() != after.crop((0, 15, 64, 20)).tobytes()
    assert frames[3][0].crop((0, 15, 64, 20)).tobytes() == before.crop((0, 15, 64, 20)).tobytes()


def test_without_seconds_one_image_per_place():
    forecasts = [_forecast("Lyon"), _forecast("Marseille")]
    cfg = _cfg(seconds=False, switch_seconds=15, animate=False)
    frames = _frames(render_meteo_minute(forecasts, NOON, cfg, 64, labels_of(cfg, forecasts)))
    assert [ms for _, ms in frames] == [15000] * 4
    single = WEATHER_SCHEMA({"seconds": False, "animate": False})
    assert [ms for _, ms in _frames(render_meteo_minute([_forecast()], NOON, single, 64, ["Lyon"]))] == [60000]
    # Small displays: no room for the seconds, one image a place.
    assert len(_frames(render_meteo_minute(forecasts, NOON, _cfg(animate=False), 32, ["Lyon", "Mamie"]))) == 4


def test_the_screen_shows_the_name_the_colour_and_the_time():
    first = render_meteo(_forecast(), NOON.replace(minute=34), {}, label="Lyon", second=5)
    later = render_meteo(_forecast(), NOON.replace(minute=35), {}, label="Lyon", second=5)
    assert first.tobytes() != later.tobytes()
    assert first.crop((0, 15, 64, 20)).getbbox() is not None  # the name
    orange = render_meteo(_forecast(), NOON, {"clock_color": "#ff8000"}, label="Lyon")
    assert (255, 128, 0) in {orange.getpixel((x, y)) for x in range(64) for y in range(14)}
    assert screen_name("Forecast Maison") == "MAISON"
    assert screen_name("Saint-Étienne, Loire, France") == "SAINT-ETIENNE"
    assert len(screen_name("Llanfairpwllgwyngyllgogerychwyrndrobwll")) < 20  # cut to fit
    sun = render_meteo(_forecast(), NOON, {"strip": "sun"}, label="Lyon")
    assert sun.crop((0, 38, 64, 64)).getbbox() is not None


def test_the_preview_shows_the_place_of_the_second():
    forecasts = [_forecast("Lyon"), _forecast("Marseille")]
    cfg = _cfg()
    first, second = (Image.open(io.BytesIO(png_of(forecasts, NOON.replace(second=s), cfg, 64))) for s in (3, 18))
    assert first.crop((0, 15, 64, 20)).tobytes() != second.crop((0, 15, 64, 20)).tobytes()


def test_weather_schema_profiles_and_options():
    # A view saved with one place gets it as its only profile.
    legacy = WEATHER_SCHEMA({"source": "place", "place": {"name": "Lyon", "latitude": "45.7", "longitude": 4.8}})
    assert legacy["profiles"][0]["place"]["latitude"] == 45.7 and "source" not in legacy
    defaults = WEATHER_SCHEMA({})
    assert defaults["profiles"] == [{"source": "home"}]
    assert (defaults["switch_seconds"], defaults["seconds"], defaults["hours_step"], defaults["clock_color"]) == (15, True, 3, "#78beff")
    for bad in ({"source": "place"}, {"source": "zone"}, {"source": "entity", "entity_id": "sensor.x"},
                {"strip": "weeks"}, {"clock_color": "red"}, {"switch_seconds": 0}, {"hours_at": [25]},
                {"brightness": {"day": 100, "night": 2}}, {"profiles": [{}] * 13}):
        with pytest.raises(vol.Invalid):
            WEATHER_SCHEMA(bad)


def test_brightness_follows_the_first_places_sun():
    cfg = WEATHER_SCHEMA({"brightness": {"day": 80, "night": 10}})
    assert brightness_for(cfg, [_forecast()], NOON) == 80
    assert brightness_for(cfg, [_forecast()], NOON.replace(hour=21)) == 10
    assert brightness_for(WEATHER_SCHEMA({}), [_forecast()], NOON) is None
    assert brightness_for(cfg, [_forecast(sun=[])], NOON) is None  # sun unknown: left alone


def test_a_weather_routine_shows_no_gif_and_refreshes_every_15_to_60_minutes():
    routine = ROUTINE_SCHEMA({"id": "w1", "name": "Météo", "interval": 1800, "mode": "weather", "weather": {}})
    assert routine["files"] == [] and routine["weather"]["strip"] == "hours"
    for bad in ({"weather": None}, {"interval": 60}, {"interval": 7200}):
        with pytest.raises(vol.Invalid):
            ROUTINE_SCHEMA({"id": "w1", "name": "Météo", "interval": 1800, "mode": "weather", "weather": {}, **bad})


class FakeHass:
    def async_create_background_task(self, coro, name):
        return asyncio.ensure_future(coro)

    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


async def test_the_weather_routine_sends_each_minute_and_waits_for_other_sends(monkeypatch):
    weather = SimpleNamespace(forecasts=AsyncMock(return_value=[_forecast(), _forecast("Marseille")]),
                              show=AsyncMock(return_value=4500), set_brightness=AsyncMock())
    busy = [True, True, False]
    waits = []

    async def fake_wait(self, seconds):
        waits.append(seconds)
        if len(waits) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(RoutineRunner, "_wait", fake_wait)
    monkeypatch.setattr(routines, "BUSY_POLL", 0)
    monkeypatch.setattr(routines, "local_now", lambda: NOON.replace(hour=21))
    statuses = []
    coordinator = AsyncMock()
    runner = RoutineRunner(FakeHass(), str, lambda: coordinator, statuses.append, weather=weather,
                           busy=lambda: busy.pop(0) if busy else False)
    runner.start(ROUTINE_SCHEMA({"id": "w1", "name": "Météo", "interval": 1800, "mode": "weather",
                                 "weather": {"brightness": {"day": 80, "night": 10}}}))
    with pytest.raises(asyncio.CancelledError):
        await runner._task
    # The forecasts once (cached for the interval), the minute each minute.
    assert weather.forecasts.await_count == 1 and weather.show.await_count == 2
    assert all(0 < w <= 60.2 for w in waits)
    # The night brightness, once (not again each minute).
    weather.set_brightness.assert_awaited_once_with(coordinator, 10)
    # The next minute is drawn from when the last one took to arrive.
    assert 0.5 <= weather.show.await_args_list[1].args[3] <= 10
    states = [s.get("state") for s in statuses]
    assert states.index("busy") < states.index("sending")  # waited for the other send
    assert "updated" in states and statuses[-1]["weather"]["place"] == "Lyon / Marseille"
    coordinator.async_display_gif.assert_not_called()
    assert runner.skip() is False  # nothing to skip to


async def test_without_a_forecast_the_time_still_goes_out(monkeypatch):
    weather = SimpleNamespace(forecasts=AsyncMock(side_effect=HomeAssistantError("Météo injoignable")), show=AsyncMock())

    async def fake_wait(self, seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(RoutineRunner, "_wait", fake_wait)
    statuses = []
    runner = RoutineRunner(FakeHass(), str, AsyncMock, statuses.append, weather=weather)
    runner.start(ROUTINE_SCHEMA({"id": "w1", "name": "Météo", "interval": 900, "mode": "weather", "weather": {}}))
    with pytest.raises(asyncio.CancelledError):
        await runner._task
    # The time is sent anyway, with the place's name and no weather; the error is said.
    shown = weather.show.await_args.args[1]
    assert [f.now.condition for f in shown] == [meteo.NO_WEATHER]
    assert statuses[-1]["message"] == "Météo injoignable"


class _States:
    def __init__(self, states):
        self._states = {s.entity_id: s for s in states}

    def get(self, entity_id):
        return self._states.get(entity_id)

    def async_all(self, domain):
        return [s for i, s in self._states.items() if i.startswith(f"{domain}.")]


def _state(entity_id, state="sunny", **attributes):
    return SimpleNamespace(entity_id=entity_id, state=state, attributes=attributes)


async def test_service_caches_and_picks_home_assistants_own_weather(monkeypatch):
    hass = SimpleNamespace(states=_States([_state("weather.other"), _state("weather.forecast_home", friendly_name="Maison"),
                                           _state("zone.travail", "0", latitude=48.8, longitude=2.3, friendly_name="Travail")]),
                           config=SimpleNamespace(location_name="Chez nous", latitude=45.7, longitude=4.8))
    service = WeatherService(hass)
    assert service.default_entity() == "weather.forecast_home"
    sources = service.sources()
    assert sources["home"] == {"name": "Chez nous", "entity_id": "weather.forecast_home"}
    assert [z["entity_id"] for z in sources["zones"]] == ["zone.travail"]

    fetched = []

    async def fake_open_meteo(latitude, longitude, place):
        fetched.append((latitude, longitude, place))
        return _forecast(place)

    monkeypatch.setattr(service, "_from_open_meteo", fake_open_meteo)
    cfg = WEATHER_SCHEMA({"profiles": [{"source": "zone", "zone": "zone.travail"},
                                       {"source": "place", "place": {"name": "Nice", "latitude": 43.7, "longitude": 7.3}}]})
    assert [f.place for f in await service.forecasts(cfg)] == ["Travail", "Nice"]
    await service.forecasts(cfg)
    assert len(fetched) == 2  # the second time came from the cache
    await service.forecast(cfg["profiles"][0], max_age=0)
    assert len(fetched) == 3


async def test_without_home_assistant_only_a_place_works():
    service = WeatherService(SimpleNamespace())  # the Windows build: no states
    assert service.sources() == {"home_assistant": False, "entities": [], "zones": [], "home": None, "calendars": []}
    with pytest.raises(HomeAssistantError):
        await service.forecasts(WEATHER_SCHEMA({"source": "home"}))


async def test_show_sends_the_rest_of_the_minute_and_brightness_reaches_the_display():
    coordinator = SimpleNamespace(text_settings={"screen_size": 64}, async_show_still=AsyncMock(return_value=True),
                                  _device_call=AsyncMock(return_value=True), async_update_listeners=lambda: None)
    service = WeatherService(FakeHass())
    cfg = _cfg(strip="days")
    size = await service.show(coordinator, [_forecast(), _forecast("Marseille")], cfg)
    data = coordinator.async_show_still.await_args.args[0]
    assert size == len(data) <= 3 * PACKET_BYTES and len(_frames(data)) >= 1
    assert coordinator.async_show_still.await_args.kwargs["label"] == meteo.SEND_LABEL
    await service.set_brightness(coordinator, 40)
    assert coordinator._device_call.await_args.args[1] == 40 and coordinator.text_settings["brightness"] == 102
    coordinator.async_show_still.return_value = False
    with pytest.raises(HomeAssistantError):
        await service.show(coordinator, [_forecast()], cfg)


def test_today_icon_moves_every_half_second_when_it_rains():
    forecasts = [_forecast("Lyon")]  # rainy
    frames = _frames(render_meteo_minute(forecasts, NOON, WEATHER_SCHEMA({"seconds": False}), 64, ["Lyon"]))
    assert len(frames) == 120 and {ms for _, ms in frames} == {500}
    # The drops fall: two images in a row differ, only around the icon.
    a, b = frames[0][0], frames[1][0]
    assert a.crop((0, 21, 16, 37)).tobytes() != b.crop((0, 21, 16, 37)).tobytes()
    assert a.crop((16, 0, 64, 64)).tobytes() == b.crop((16, 0, 64, 64)).tobytes()
    # Still weather, or the animation off: images only when something changes.
    still = WEATHER_SCHEMA({"seconds": False, "animate": False})
    assert len(_frames(render_meteo_minute(forecasts, NOON, still, 64, ["Lyon"]))) == 1
    cloudy = _forecast("Lyon")
    cloudy.now.condition = "cloudy"
    assert len(_frames(render_meteo_minute([cloudy], NOON, WEATHER_SCHEMA({"seconds": False}), 64, ["Lyon"]))) == 1
    # Ticking and raining: within three packets.
    assert len(render_meteo_minute(forecasts, NOON, WEATHER_SCHEMA({}), 64, ["Lyon"])) <= 3 * PACKET_BYTES


def test_the_sun_is_drawn_with_rays_that_turn():
    from custom_components.idotmatrix.meteo import _icon16

    first, second = _icon16("sunny", 0), _icon16("sunny", 1)
    assert first.tobytes() != second.tobytes()
    assert first.getpixel((8, 8)) == (255, 205, 0)  # the core
    assert first.getpixel((8, 2)) != (0, 0, 0)  # a ray above it


def test_emoji_in_a_name_are_drawn_as_pictures(monkeypatch):
    from custom_components.idotmatrix import emoji

    red = Image.new("RGBA", (72, 72), (255, 0, 0, 255))
    monkeypatch.setattr(emoji, "_pictures", {"🏠": red, "🤣": None})
    assert emoji.split("🏠 Maison 🤣!") == [("🏠", True), (" Maison ", False), ("🤣", True), ("!", False)]
    assert emoji.split("👍🏽 ok ❤️") == [("👍🏽", True), (" ok ", False), ("❤️", True)]
    img = render_meteo(_forecast(), NOON, {}, label="🏠 Maison 🤣")
    reds = [(x, y) for x in range(64) for y in range(13, 22) if img.getpixel((x, y))[0] > 200 and img.getpixel((x, y))[1] < 60]
    assert len(reds) == 49  # a 7x7 house; the emoji that could not be had is left out
    assert screen_name("🏠 Maison") == "MAISON"


def test_parts_move_resize_and_hide():
    from custom_components.idotmatrix.meteo import element_boxes

    plain = element_boxes(_forecast(), NOON, WEATHER_SCHEMA({}), 64, "Lyon")
    assert set(plain) == {"clock", "seconds", "date", "name", "today", "strip"}
    moved = element_boxes(_forecast(), NOON, WEATHER_SCHEMA({"layout": {
        "name": {"dx": 3, "dy": -2}, "strip": {"hidden": True}, "clock": {"size": 1}}}), 64, "Lyon")
    assert moved["name"] == tuple(v + d for v, d in zip(plain["name"], (3, -2, 3, -2)))
    assert "strip" not in moved
    assert moved["clock"][3] - moved["clock"][1] < plain["clock"][3] - plain["clock"][1]  # smaller digits
    big = element_boxes(_forecast(), NOON, WEATHER_SCHEMA({"layout": {"today": {"size": 3}}}), 64, "Lyon")
    assert big["today"][3] - big["today"][1] > 20  # the 32 px icon
    mini = element_boxes(_forecast(), NOON, WEATHER_SCHEMA({"layout": {"today": {"size": 1}, "strip": {"size": 1}}}), 64, "Lyon")
    assert mini["today"][3] - mini["today"][1] < plain["today"][3] - plain["today"][1]
    assert mini["strip"][3] - mini["strip"][1] < plain["strip"][3] - plain["strip"][1]  # no icons
    hidden = render_meteo(_forecast(), NOON, WEATHER_SCHEMA({"layout": {p: {"hidden": True} for p in
                                                                         ("clock", "seconds", "date", "name", "today", "strip")}}), label="Lyon", second=5)
    assert hidden.getbbox() is None
    with pytest.raises(vol.Invalid):
        WEATHER_SCHEMA({"layout": {"clock": {"size": 4}}})


def test_the_flip_clock_turns_its_cards_when_the_minute_changes():
    cfg = WEATHER_SCHEMA({"clock_style": "flip", "seconds": False, "animate": False})
    start = datetime(2026, 11, 3, 13, 0, tzinfo=UTC)
    frames = _frames(render_meteo_minute([_forecast()], start, cfg, 64, ["Lyon"]))
    flips = [ms for _, ms in frames[:meteo.FLIP_STEPS]]
    assert flips == [meteo.FLIP_STEP_MS] * meteo.FLIP_STEPS
    # The cards (top rows) move during the flip, then show the new time.
    cards = [f.crop((0, 0, 64, 21)).tobytes() for f, _ in frames[:meteo.FLIP_STEPS + 1]]
    assert len(set(cards)) == meteo.FLIP_STEPS + 1
    still = render_meteo(_forecast(), start, cfg, label="Lyon")
    assert frames[-1][0].crop((0, 0, 64, 21)).tobytes() == still.crop((0, 0, 64, 21)).tobytes()
    # White cards by default, a chosen colour otherwise.
    assert still.getpixel((3, 3)) == meteo.FLIP_CARD
    assert render_meteo(_forecast(), start, {**cfg, "clock_color": "#ff8000"}, label="Lyon").getpixel((3, 3)) == (255, 128, 0)


def test_the_seconds_are_a_part_of_their_own():
    from custom_components.idotmatrix.meteo import element_boxes

    for style in ("digits", "bar", "ring"):
        cfg = WEATHER_SCHEMA({"seconds_style": style, "seconds_color": "#ff0000"})
        boxes = element_boxes(_forecast(), NOON.replace(second=30), cfg, 64, "Lyon")
        assert "seconds" in boxes
        img = render_meteo(_forecast(), NOON.replace(second=30), cfg, label="Lyon", second=30)
        x0, y0, x1, y1 = boxes["seconds"]
        assert (255, 0, 0) in {img.getpixel((x, y)) for x in range(x0, x1) for y in range(y0, y1)}
    thin, thick = (element_boxes(_forecast(), NOON.replace(second=30), WEATHER_SCHEMA(
        {"seconds_style": "bar", "layout": {"seconds": {"size": size}}}), 64, "Lyon")["seconds"] for size in (1, 3))
    assert (thin[3] - thin[1], thick[3] - thick[1]) == (1, 3)
    # Without the seconds, no such part.
    assert "seconds" not in element_boxes(_forecast(), NOON, WEATHER_SCHEMA({"seconds": False}), 64, "Lyon")


def test_the_name_aligns_left_centre_or_right():
    from custom_components.idotmatrix.meteo import element_boxes

    left, middle, right = (element_boxes(_forecast(), NOON, WEATHER_SCHEMA({"layout": {"name": {"align": a}}}), 64, "Lyon")["name"]
                           for a in ("left", "center", "right"))
    assert left[0] <= 1 and right[2] >= 63 and left[0] < middle[0] < right[0]


def test_the_drop_shows_the_humidity_and_drips():
    forecast = _forecast()
    forecast.now.humidity = 78
    rain = render_meteo(forecast, NOON, WEATHER_SCHEMA({}), label="Lyon", second=0)
    humid = render_meteo(forecast, NOON, WEATHER_SCHEMA({"drop": "humidity"}), label="Lyon", second=0)
    assert rain.crop((40, 21, 64, 30)).tobytes() != humid.crop((40, 21, 64, 30)).tobytes()
    later = render_meteo(forecast, NOON, WEATHER_SCHEMA({}), label="Lyon", second=2)
    assert rain.crop((40, 21, 64, 30)).tobytes() != later.crop((40, 21, 64, 30)).tobytes()  # it drips


async def test_without_network_the_time_goes_on():
    from custom_components.idotmatrix.meteo import placeholder, placeholders

    # Nothing fetched yet: a placeholder still shows the time and the name.
    cfg = WEATHER_SCHEMA({"source": "place", "label": "Mamie", "place": {"name": "Lyon", "latitude": 45.7, "longitude": 4.8}})
    assert [p.place for p in placeholders(cfg)] == ["Mamie"]
    img = render_meteo(placeholder("Lyon"), NOON, cfg, label="Lyon", second=3)
    assert img.crop((0, 0, 64, 14)).getbbox() is not None and img.crop((0, 21, 64, 64)).getbbox() is None
    # A fetch that fails keeps the last forecast, however old.
    service = WeatherService(SimpleNamespace())
    old = _forecast(fetched=1.0)

    async def broken(cfg):
        raise HomeAssistantError("Météo injoignable")

    service._fetch = broken
    service._cache[service._key(cfg["profiles"][0])] = old
    assert await service.forecast(cfg["profiles"][0], max_age=60) is old


def test_the_date_and_what_shows():
    from custom_components.idotmatrix.meteo import element_boxes

    boxes = element_boxes(_forecast(), NOON, WEATHER_SCHEMA({}), 64, "Lyon")
    assert boxes["date"][2] >= 62 and boxes["name"][0] <= 1  # the date at the right, the name at the left
    longer = element_boxes(_forecast(), NOON, WEATHER_SCHEMA({"layout": {"date": {"size": 2}}}), 64, "Lyon")
    assert longer["date"][0] < boxes["date"][0]  # « MA 3 NOV »
    alone = element_boxes(_forecast(), NOON, WEATHER_SCHEMA({"layout": {"date": {"hidden": True}}}), 64, "Lyon")
    assert "date" not in alone and alone["name"][0] > 10  # the name centred again
    # Today's details left out.
    full = render_meteo(_forecast(), NOON, WEATHER_SCHEMA({}), label="Lyon")
    bare = render_meteo(_forecast(), NOON, WEATHER_SCHEMA({"today_hide": ["icon", "minmax", "drop"]}), label="Lyon")
    assert bare.crop((0, 21, 16, 37)).getbbox() is None  # no icon
    assert bare.crop((18, 21, 40, 29)).tobytes() == full.crop((18, 21, 40, 29)).tobytes()  # the temperature stays


def test_date_and_time_formats_typed_in():
    from custom_components.idotmatrix.meteo import element_boxes, format_date, format_time

    t = datetime(2026, 11, 3, 9, 5, 7, tzinfo=UTC)
    assert format_date("dd/mm", t) == "03/11"
    assert format_date("mm/dd/yy", t) == "11/03/26"
    assert format_date("ddd d mmm", t) == "MAR 3 NOV"
    assert format_date("dddd d mmmm yyyy", t) == "MARDI 3 NOVEMBRE 2026"
    assert format_time("HH:mm:ss", t) == "09:05:07"
    assert format_time("h:mm tt", t.replace(hour=21)) == "9:05 PM"
    # With the seconds in the time, no separate seconds; the long time goes small to fit.
    cfg = WEATHER_SCHEMA({"time_format": "HH:mm:ss", "date_format": "dd/mm"})
    boxes = element_boxes(_forecast(), t, cfg, 64, "Lyon")
    assert "seconds" not in boxes and boxes["clock"][2] <= 64 and boxes["clock"][3] - boxes["clock"][1] <= 8
    frames = _frames(render_meteo_minute([_forecast()], t.replace(second=0), {**cfg, "seconds": False, "animate": False},
                                         64, ["Lyon"]))
    assert len(frames) == 60  # it ticks with the seconds in the time, even with the seconds part off


async def test_a_running_view_takes_new_settings_at_once():
    shows = []
    sending = asyncio.Event()

    async def show(coordinator, forecasts, cfg, lead, extras=None):
        shows.append(cfg)
        sending.set()

    weather = SimpleNamespace(forecasts=AsyncMock(return_value=[_forecast()]), show=show, set_brightness=AsyncMock(),
                              extras=AsyncMock(return_value=None))
    runner = RoutineRunner(FakeHass(), str, AsyncMock, lambda s: None, weather=weather)
    routine = ROUTINE_SCHEMA({"id": "w1", "name": "Météo", "interval": 1800, "mode": "weather", "weather": {}})
    runner.start(routine)
    await asyncio.wait_for(sending.wait(), 2)
    sending.clear()
    changed = ROUTINE_SCHEMA({**routine, "weather": {"clock_style": "flip"}})
    assert runner.update(changed) is True
    await asyncio.wait_for(sending.wait(), 2)  # not a minute later: at once
    assert shows[-1]["clock_style"] == "flip"
    # Another view, or one not running: started instead.
    assert runner.update({**changed, "id": "w2"}) is False
    runner.stop()
    assert runner.update(changed) is False


def test_a_clear_night_shows_the_real_moon():
    from datetime import timezone as tz
    from custom_components.idotmatrix import meteo
    eclipse = datetime(2024, 4, 8, 18, 21, tzinfo=tz.utc)  # a new moon (the total solar eclipse)
    full = datetime(2024, 3, 25, 7, 0, tzinfo=tz.utc)
    assert min(meteo.moon_phase(eclipse), 1 - meteo.moon_phase(eclipse)) < 0.02
    assert abs(meteo.moon_phase(full) - 0.5) < 0.02
    lit = lambda when: sum(1 for p in meteo._icon16("clear-night", 0, when).getdata() if p == meteo.PAL["moon"])  # noqa: E731
    first_quarter = eclipse + timedelta(days=7.4)
    assert lit(full) > lit(first_quarter) > lit(eclipse + timedelta(days=2)) > lit(eclipse) == 0
    quarter = meteo._icon16("clear-night", 0, first_quarter)
    assert quarter.getpixel((11, 8)) == meteo.PAL["moon"] and quarter.getpixel((5, 8)) != meteo.PAL["moon"]  # lit on the right
