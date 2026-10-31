from datetime import date, datetime, timedelta, timezone

from custom_components.idotmatrix import meteo, pages
from custom_components.idotmatrix.weather import WeatherData

TZ = timezone(timedelta(hours=1))

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;VALUE=DATE:20090709
DTEND;VALUE=DATE:20090710
RRULE:FREQ=YEARLY;WKST=MO
SUMMARY:Amandine\, Hermine\, Irma
END:VEVENT
BEGIN:VEVENT
DTSTART:20261031T083000Z
DTEND:20261031T093000Z
SUMMARY:Dentiste
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=Europe/Paris:20260105T180000
DTEND;TZID=Europe/Paris:20260105T193000
RRULE:FREQ=WEEKLY;BYDAY=MO,SA
SUMMARY:Foot du
  lundi
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261031
SUMMARY:🌍 Journée mondiale des villes
END:VEVENT
END:VCALENDAR
"""


def test_a_calendar_file_gives_the_events_of_a_day():
    events = pages.parse_ics(ICS, TZ)
    assert len(events) == 4
    saturday = pages.events_on(events, date(2026, 10, 31), TZ)
    assert [o.summary for o in saturday] == ["🌍 Journée mondiale des villes", "Dentiste", "Foot du lundi"]
    assert saturday[1].start.hour == 9  # 08:30 UTC is 09:30 here
    assert pages.names_of(pages.events_on(events, date(2031, 7, 9), TZ)) == ["Amandine", "Hermine", "Irma"]
    assert pages.events_on(events, date(2026, 11, 3), TZ) == []  # a Tuesday


def test_special_days_and_easter():
    assert pages.easter(2026) == date(2026, 4, 5) and pages.easter(2027) == date(2027, 3, 28)
    assert [s.title for s in pages.special_days(date(2026, 12, 25))] == ["JOYEUX NOEL"]
    assert [s.title for s in pages.special_days(date(2026, 4, 6))] == ["LUNDI DE"]  # Easter Monday
    assert [s.line for s in pages.special_days(date(2026, 5, 31))] == ["MAMAN"]  # last Sunday of May
    assert [s.line for s in pages.special_days(date(2026, 6, 21))] == ["PAPA", "MUSIQUE"]
    birthday = pages.special_days(date(2026, 10, 31), [{"name": "Léa", "date": "2010-10-31"}])
    assert [s.key for s in birthday] == ["pumpkin", "cake"] and birthday[1].line == "Léa 16 ANS"
    assert pages.special_days(date(2026, 3, 3)) == []


def test_texts_change_each_hour_and_fit_the_screen():
    now = datetime(2026, 10, 31, 14, 0, tzinfo=TZ)
    for kind in ("thought", "proverb", "fact", "motivation"):
        header, text, _author = pages.text_of_hour(kind, now)
        assert text and header
        lines = pages.wrap(meteo._small_text(text), 62, meteo._small_width)
        assert len(lines) <= 7, (kind, text)
    assert {pages.text_of_hour("fact", now + timedelta(hours=h))[1] for h in range(5)} != {pages.text_of_hour("fact", now)[1]}


def test_the_pages_take_turns_with_the_weather():
    now = datetime(2026, 10, 31, 14, 0, 12, tzinfo=TZ)
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    cfg = meteo.WEATHER_SCHEMA({"agenda": True, "saints": True, "fact": True, "agenda_ics": ["webcal://x.test/a.ics"]})
    saints = "BEGIN:VEVENT\nDTSTART;VALUE=DATE:20091031\nRRULE:FREQ=YEARLY\nSUMMARY:Amandine\\, Hermine\\, Irma\nEND:VEVENT\n"
    texts = {pages.SAINTS_ICS: saints, "https://x.test/a.ics": ICS}
    extras = pages.build_extras(cfg, texts, now)
    assert [o.summary for o in extras.agenda][:2] == ["🌍 Journée mondiale des villes", "Dentiste"]
    assert extras.saints == ["Amandine", "Hermine", "Irma"]
    turns = meteo.page_list([forecast], cfg, extras, now)
    assert [t["kind"] for t in turns] == ["weather", "special", "agenda", "saint", "fact"]  # Halloween too
    images = {meteo.render_meteo(forecast, now, cfg, label="Lyon", page=t).tobytes() for t in turns}
    assert len(images) == len(turns)
    # The time stays on every page.
    for t in turns:
        assert meteo.render_meteo(forecast, now, cfg, label="Lyon", page=t).crop((0, 0, 64, 14)).getbbox() is not None
    # 15 s each: four turns in a minute.
    data = meteo.render_meteo_minute([forecast], now.replace(second=0), {**cfg, "seconds": False, "animate": False},
                                     64, ["Lyon"], extras)
    from PIL import Image
    import io
    with Image.open(io.BytesIO(data)) as image:
        assert image.n_frames >= 4  # four turns (the agenda's lines also move within its own)
    png, boxes = meteo.preview_of([forecast], now.replace(second=20), cfg, 64, extras)
    assert [p["key"] for p in boxes.pop("_pages")] == ["weather:0", "special", "agenda", "saint", "fact"]
    assert boxes.pop("_page") == 1
    assert "page" in boxes and "today" not in boxes  # the block of that page, no weather parts


def test_the_mixing_desk_gives_each_page_its_time():
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    cfg = meteo.WEATHER_SCHEMA({"fact": True, "special_days": False, "durations": {"weather:0": 30, "fact": 10}})
    turns = meteo.page_list([forecast], cfg, None, datetime(2026, 11, 3, 12, 0, tzinfo=TZ))
    at = lambda s: turns[meteo.turn_at(turns, cfg, datetime(2026, 11, 3, 12, 0, s, tzinfo=TZ))]["kind"]  # noqa: E731
    # A loop of 40 s from midnight: 12:00:00 is 43200 s, 43200 % 40 = 0.
    assert [at(s) for s in (0, 29, 30, 39)] == ["weather", "weather", "fact", "fact"]
    assert at(40 % 60) == "weather"


def test_the_block_of_a_page_has_three_sizes():
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    now = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)
    page = {"kind": "fact"}
    sizes = [meteo.element_boxes(forecast, now, meteo.WEATHER_SCHEMA({"layout": {"page": {"size": n}}}), 64, "Lyon", page)["page"]
             for n in (1, 2, 3)]
    assert sizes[0][3] < sizes[1][3]  # no heading: the text ends higher
    assert sizes[2] != sizes[1]  # big letters


def test_screens_filled_by_hand_take_turns_each_for_its_time():
    forecasts = [meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0),
                 meteo.Forecast("Nice", WeatherData("rainy", 15), fetched=1.0)]
    weather = {part: {} for part in meteo.SCREEN_PRESETS["weather"]}
    cfg = meteo.WEATHER_SCHEMA({"profiles": [{"source": "home"}, {"source": "home"}], "screens": [
        {"parts": weather, "place": 1, "seconds": 20},
        {"parts": {"clock": {}, "saint": {"size": 3}}, "seconds": 10},
        {"parts": {}, "seconds": 30}]})  # an empty screen, to fill
    assert cfg["saints"] and not cfg["special_days"] and not cfg["humor"]  # the screens switch the pages
    now = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)
    turns = meteo.page_list(forecasts, cfg, pages.Extras(saints=["Hubert"]), now)
    assert [(t["screen"], t["index"], t["seconds"], list(t["pages"])) for t in turns] == [
        (0, 1, 20, []), (1, 0, 10, ["saint"]), (2, 0, 30, [])]
    assert [meteo.page_title(t, ["Lyon", "Nice"]) for t in turns] == ["Nice", "Saint du jour", "Vide"]
    # No saint today: a screen of pages with nothing to show is skipped (the time alone is not enough).
    assert [t["screen"] for t in meteo.page_list(forecasts, cfg, pages.Extras(), now)] == [0, 2]
    at = lambda s: turns[meteo.turn_at(turns, cfg, now.replace(second=s))]["screen"]  # noqa: E731
    assert [at(0), at(19), at(20), at(29), at(30), at(59)] == [0, 0, 1, 1, 2, 2]
    # Each screen draws its own parts, placed its own way.
    saint, empty = (meteo.render_meteo(forecasts[0], now, cfg, label="Lyon", page=t) for t in turns[1:])
    assert saint.getbbox() is not None and empty.getbbox() is None
    boxes = meteo.element_boxes(forecasts[0], now, cfg, 64, "Lyon", turns[1])
    assert set(boxes) == {"clock", "seconds", "saint"}  # the seconds go with the clock


def test_birthdays_apart_a_countdown_and_reminders_in_the_morning():
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    now = datetime(2026, 11, 3, 8, 0, tzinfo=TZ)  # a Tuesday
    cfg = meteo.WEATHER_SCHEMA({
        "birthdays": [{"name": "Léa", "date": "2010-11-03"}],
        "reminders": [{"text": "Sortir les poubelles", "days": [1]}, {"text": "Pain", "date": "11-04"}],
        "notes": ["Bravo pour ton contrôle de maths !"],
        "screens": [
            {"parts": {"special": {}}},
            {"parts": {"birthdays": {}}},
            {"parts": {"countdown": {"title": "Vacances aux Maldives", "date": "2026-12-31"}}},
            {"parts": {"countdown": {"date": "weekend"}}},
            {"parts": {"notes": {"size": 3}}},
            {"parts": {"reminders": {}}, "from": 6, "to": 10}]})
    extras = pages.Extras(birthdays=[{"name": "Tom", "date": "--11-03"}], agenda=[])
    turns = meteo.page_list([forecast], cfg, extras, now)
    # The birthdays on their own screen, none with the special days (none else today).
    assert [list(t["pages"]) for t in turns] == [["birthdays"], ["countdown"], ["countdown"], ["notes"], ["reminders"]]
    assert turns[0]["pages"]["birthdays"]["people"] == [("Léa", "16 ANS"), ("Tom", "")]
    assert turns[4]["pages"]["reminders"]["items"] == ["Sortir les poubelles"]
    assert meteo.countdown_text("2026-12-31", now) == ("J-58", False)
    assert meteo.countdown_text("weekend", now) == ("3 J 10 H", False)  # to Friday 18:00
    assert meteo.countdown_text("weekend", datetime(2026, 11, 7, 12, 0, tzinfo=TZ)) == ("", True)
    assert meteo.countdown_text("weekend", datetime(2026, 11, 6, 17, 30, tzinfo=TZ)) == ("0 H 30", False)
    assert meteo.countdown_text("weekend", datetime(2026, 11, 9, 0, 0, tzinfo=TZ)) == ("4 J 18 H", False)  # Monday
    assert meteo.countdown_text("2026-11-03", now) == ("", True)
    assert meteo.countdown_text("2026-11-02", now) is None
    for t in turns:
        assert meteo.render_meteo(forecast, now, cfg, label="Lyon", page=t).getbbox() is not None
    # At noon the morning's reminders are gone.
    assert [list(t["pages"]) for t in meteo.page_list([forecast], cfg, extras, now.replace(hour=12))][-1] == ["notes"]


def test_the_saints_title_is_typed_in_and_a_or_aux_apart():
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    now = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)
    page = {"kind": "saint", "names": ["Hubert"]}
    draw = lambda **cfg: meteo.render_meteo(forecast, now, meteo.WEATHER_SCHEMA(cfg), page=page).tobytes()  # noqa: E731
    assert draw() != draw(saint_to=False) != draw(saint_title="JOYEUSE FÊTE", saint_to=False)
    assert draw(saint_title="", saint_to=False) != draw()


def test_enlarged_text_keeps_every_word_and_black_shows_with_an_outline():
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    now = datetime(2026, 11, 3, 14, 0, tzinfo=TZ)
    assert not meteo._fits("LES LOUTRES DE MER SE TIENNENT PAR LA MAIN POUR DORMIR.", 62, 47, True)
    assert meteo._text_level(["LES LOUTRES DE MER SE TIENNENT PAR LA MAIN POUR DORMIR."], 62, 47, 3, 7) == (False, True)
    assert meteo._text_level(["GENTILLESSE"], 62, 47, 3, 7) == (False, True)  # too wide in big letters: never cut
    assert meteo._text_level(["CONNAIS-TOI TOI-MEME."], 62, 41, 3, 7) == (True, True)
    black = meteo.WEATHER_SCHEMA({"clock_color": "#000000"})
    outlined = meteo.WEATHER_SCHEMA({"clock_color": "#000000", "layout": {"clock": {"outline": "#ffffff"}}})
    plain = meteo.render_meteo(forecast, now, black).crop((0, 0, 64, 15))
    ringed = meteo.render_meteo(forecast, now, outlined).crop((0, 0, 64, 15))
    assert max(plain.convert("L").getdata()) <= 1  # black letters alone: LEDs off
    assert (255, 255, 255) in set(ringed.getdata())  # the outline draws them
    assert "clock" in meteo.element_boxes(forecast, now, black, 64, None)  # still there, to pick


def test_every_text_says_where_it_comes_from_and_the_word_changes_each_day():
    for kind, (header, items) in pages.TEXT_KINDS.items():
        assert header and items, kind
        for item in items:
            assert item["text"] and item["source"], (kind, item)
        if kind == "thought":
            assert all(item["author"] for item in items)
    now = datetime(2026, 11, 3, 8, 0, tzinfo=TZ)
    word, meaning = pages.word_of_day(now)
    assert word and meaning
    assert pages.word_of_day(now.replace(hour=22)) == (word, meaning)  # all day long
    assert len({pages.word_of_day(now + timedelta(days=d))[0] for d in range(7)}) > 1
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    cfg = meteo.WEATHER_SCHEMA({"screens": [{"parts": {"clock": {}, "word": {}}}]})
    assert cfg["word"]
    turn = meteo.page_list([forecast], cfg, None, now)[0]
    assert list(turn["pages"]) == ["word"] and meteo.page_title(turn, ["Lyon"]) == "Mot du jour"
    assert meteo.render_meteo(forecast, now, cfg, page=turn).crop((0, 16, 64, 64)).getbbox() is not None


def test_each_city_shows_its_own_time_and_the_cities_change_every_few_seconds():
    here = datetime(2026, 11, 3, 12, 0, 7, tzinfo=TZ)
    tokyo = meteo.Forecast("Tokyo", WeatherData("sunny", 18), fetched=1.0, zone=timezone(timedelta(hours=9)))
    assert meteo.city_now(tokyo, here, {}).hour == 20
    assert meteo.city_now(tokyo, here, {"city_time": False}).hour == 12
    lyon = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)  # Home Assistant's: here
    assert meteo.city_now(lyon, here, {}) == here
    cfg = meteo.WEATHER_SCHEMA({"switch_seconds": 3, "screens": [{"parts": {"clock": {}}, "seconds": 3}]})
    assert cfg["switch_seconds"] == 3 and cfg["screens"][0]["seconds"] == 3
    shown = lambda f: meteo.render_meteo(f, here, cfg, page=meteo.page_list([f], cfg, None, here)[0]).tobytes()  # noqa: E731
    assert shown(tokyo) != shown(lyon)  # 20:00 there, 12:00 here
    two = meteo.WEATHER_SCHEMA({"profiles": [{"source": "home"}, {"source": "home"}], "screens": [
        {"parts": {"clock": {}, "today": {}}, "place": 0, "seconds": 3},
        {"parts": {"clock": {}, "today": {}}, "place": 1, "seconds": 3}]})
    turns = meteo.page_list([lyon, tokyo], two, None, here)
    assert [turns[meteo.turn_at(turns, two, here.replace(second=s))]["index"] for s in (0, 2, 3, 5, 6)] == [0, 0, 1, 1, 0]


def test_a_screen_can_name_its_city_its_own_way():
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    now = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)
    cfg = meteo.WEATHER_SCHEMA({"screens": [{"parts": {"name": {}}}, {"parts": {"name": {"title": "Chez Mamie"}}}]})
    first, second = meteo.page_list([forecast], cfg, None, now)
    shown = lambda t: meteo.render_meteo(forecast, now, cfg, label="Lyon", page=t)  # noqa: E731
    assert shown(first).tobytes() != shown(second).tobytes()
    assert shown(first).tobytes() == meteo.render_meteo(forecast, now, meteo.WEATHER_SCHEMA(
        {"screens": [{"parts": {"name": {}}}]}), label="Lyon", page=first).tobytes()


def test_many_saints_take_turns_and_the_seconds_go_with_the_clock():
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    now = datetime(2026, 11, 3, 12, 0, 0, tzinfo=TZ)
    cfg = meteo.WEATHER_SCHEMA({"screens": [{"parts": {"clock": {}, "saint": {}}}]})
    names = ["Hubert", "Sylvie", "Martin", "Charles", "Léonard", "Malo", "Théodore"]
    turn = meteo.page_list([forecast], cfg, pages.Extras(saints=names), now)[0]
    slides = {meteo.render_meteo(forecast, now.replace(second=s), cfg, page=turn).crop((0, 24, 64, 64)).tobytes()
              for s in range(0, 9, 3)}
    assert len(slides) >= 2  # too many for one screen: they take turns every 3 s
    # The seconds are drawn with the clock without being a part of their own.
    plain = meteo.WEATHER_SCHEMA({"seconds": False, "screens": [{"parts": {"clock": {}}}]})
    t1 = meteo.page_list([forecast], cfg, None, now)[0]
    t2 = meteo.page_list([forecast], plain, None, now)[0]
    assert "seconds" in meteo.element_boxes(forecast, now, cfg, 64, None, t1)
    assert "seconds" not in meteo.element_boxes(forecast, now, plain, 64, None, t2)


def test_world_days_say_journee_mondiale_then_what():
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    now = datetime(2026, 11, 13, 12, 0, tzinfo=TZ)
    cfg = meteo.WEATHER_SCHEMA({"screens": [{"parts": {"world_days": {}}}]})
    turn = meteo.page_list([forecast], cfg, pages.Extras(world_days=["🌍 Journée mondiale de la gentillesse"]), now)[0]
    other = meteo.page_list([forecast], cfg, pages.Extras(world_days=["Fête de la science"]), now)[0]
    one, two = (meteo.render_meteo(forecast, now, cfg, page=t).crop((0, 16, 64, 23)).tobytes() for t in (turn, other))
    assert one != two  # « JOURNEE MONDIALE » over the first, « AUJOURD'HUI » over the other


def test_texts_are_short_and_today_lists_are_picked_in_the_app():
    for kind, (_header, items) in pages.TEXT_KINDS.items():
        assert all(len(item["text"]) <= 60 for item in items), kind  # 64 LEDs wide
    now = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)
    extras = pages.Extras(saints=["Hubert", "Sylvie", "Martin"], world_days=["A", "B", "C", "D"])
    base = {"saints": True, "world_days": True, "special_days": False}
    pages_of = lambda cfg: {p["kind"]: p for p in pages.extra_pages(cfg, extras, now)}  # noqa: E731
    shown = pages_of(base)
    assert shown["saint"]["names"] == ["Hubert", "Sylvie", "Martin"] and shown["world_days"]["items"] == ["A", "B"]
    picked = pages_of({**base, "pick": {"date": "2026-11-03", "saints": ["Sylvie"], "world_days": ["D", "C"]}})
    assert picked["saint"]["names"] == ["Sylvie"] and picked["world_days"]["items"] == ["C", "D"]
    stale = pages_of({**base, "pick": {"date": "2026-11-02", "saints": ["Sylvie"], "world_days": ["D"]}})
    assert stale["saint"]["names"] == ["Hubert", "Sylvie", "Martin"]  # yesterday's pick: all again


def test_the_agenda_shows_the_whole_day_those_over_struck_through():
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    now = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)
    cfg = meteo.WEATHER_SCHEMA({"screens": [{"parts": {"agenda": {}}}]})
    morning = pages.Occurrence("Dentiste", now.replace(hour=9), now.replace(hour=10))
    evening = pages.Occurrence("Foot", now.replace(hour=18), now.replace(hour=19))
    page = lambda items: meteo.page_list([forecast], cfg, pages.Extras(agenda=items), now)[0]  # noqa: E731
    img = meteo.render_meteo(forecast, now, cfg, page=page([morning, evening]))
    struck = [img.getpixel((x, 0 + 16 + 8 + 2)) for x in range(1, 40)]  # the morning's row, through its middle
    assert sum(1 for p in struck if p == (170, 170, 180)) > 20  # a line through the past one
    later = [img.getpixel((x, 16 + 8 + 6 + 2)) for x in range(1, 40)]
    assert (170, 170, 180) not in later  # the coming one is not struck
    many = [pages.Occurrence(f"RDV {h}", now.replace(hour=h), None) for h in range(8, 20)]
    slides = {meteo.render_meteo(forecast, now.replace(second=s), cfg, page=page(many)).tobytes() for s in (0, 3, 6)}
    assert len(slides) >= 2  # more than fit: they take turns


def test_appointments_typed_in_join_the_agenda_of_their_day():
    now = datetime(2026, 11, 3, 8, 0, tzinfo=TZ)
    cfg = meteo.WEATHER_SCHEMA({"screens": [{"parts": {"agenda": {}}}], "events": [
        {"title": "Piscine", "date": "2026-11-03", "time": "17:30"},
        {"title": "Anniversaire Tom", "date": "2026-11-03"},
        {"title": "Demain", "date": "2026-11-04", "time": "09:00"}]})
    extras = pages.build_extras(cfg, {}, now, [pages.Occurrence("Dentiste", now.replace(hour=9), None)])
    assert [o.summary for o in extras.agenda] == ["Anniversaire Tom", "Dentiste", "Piscine"]
    assert extras.agenda[2].start.hour == 17 and extras.agenda[2].start.minute == 30


def test_the_agenda_shows_two_lines_going_up_and_long_titles_slide():
    assert [meteo._bounce(10, t) for t in range(8)] == [0, 0, 6, 10, 10, 10, 4, 0]  # still, slide, still, back
    assert meteo._slide_time(60, meteo.SCROLL_SPEEDS["fast"]) < meteo._slide_time(60, meteo.SCROLL_SPEEDS["slow"])
    assert meteo.WEATHER_SCHEMA({"scroll_speed": "faster"})["scroll_speed"] == "faster"
    assert meteo._bounce(0, 5) == 0
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0)
    now = datetime(2026, 11, 3, 12, 0, 0, tzinfo=TZ)
    cfg = meteo.WEATHER_SCHEMA({"screens": [{"parts": {"agenda": {}}}]})
    items = [pages.Occurrence("Préparer les pastas pesto pour toute la famille", now.replace(hour=21), None),
             pages.Occurrence("Foot", now.replace(hour=18), None), pages.Occurrence("Piscine", now.replace(hour=19), None)]
    turn = meteo.page_list([forecast], cfg, pages.Extras(agenda=items), now)[0]
    frame = lambda s: meteo.render_meteo(forecast, now.replace(second=s), cfg, page=turn)  # noqa: E731
    rows = lambda img: img.crop((0, 24, 64, 36)).tobytes()  # noqa: E731  the two lines
    assert rows(frame(0)) != rows(frame(3))  # three appointments: they go up every 3 s
    third_row = frame(0).crop((0, 36, 64, 42))
    assert third_row.getbbox() is None  # only two lines


def test_a_screen_can_have_several_strips_of_different_kinds():
    Slot = meteo.Slot
    forecast = meteo.Forecast("Lyon", WeatherData("sunny", 12), fetched=1.0,
                              days=[Slot("SA", "rainy", high=14, low=6), Slot("DI", "sunny", high=16, low=7)])
    now = datetime(2026, 11, 3, 12, 0, tzinfo=TZ)
    cfg = meteo.WEATHER_SCHEMA({"strip": "hours", "screens": [
        {"parts": {"strip": {}, "days": {"dy": -20}, "sun": {"dy": -40}}}]})
    turn = meteo.page_list([forecast], cfg, None, now)[0]
    boxes = meteo.element_boxes(forecast, now, cfg, 64, "Lyon", turn)
    assert {"days", "sun"} <= set(boxes) and boxes["days"] != boxes["sun"]  # each its own part, placed its own way
    hours_only = meteo.WEATHER_SCHEMA({"strip": "hours", "screens": [{"parts": {"strip": {}}}]})
    assert "days" not in meteo.element_boxes(forecast, now, hours_only, 64, "Lyon",
                                             meteo.page_list([forecast], hours_only, None, now)[0])
    assert meteo.page_title(turn, ["Lyon"]) == "Lyon"
