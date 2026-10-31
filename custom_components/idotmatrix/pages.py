"""Pages that take turns with the weather on the Météo view (meteo.py).

The agenda of the day (a list, or a timeline), the saint of the day and the
world days (two public Google calendars, as iCalendar files), a thought,
a proverb, a useless fact or a motivational phrase (built in, a new one
each hour), and the special days (holidays, Christmas, Easter, Valentine's
Day, birthdays...) with a picture of their own. The time stays on top of
every page; they only replace the weather under it.

Pure Python: the integration, Pixel Studio for Windows and the Android app
fetch the calendars their own way and hand the text here.
"""
from __future__ import annotations

import json
import pkgutil
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo
from pathlib import Path

SAINTS_ICS = ("https://calendar.google.com/calendar/ical/jn78u2932bao8q997th2g7riik%40group.calendar.google.com"
              "/public/basic.ics")
WORLD_DAYS_ICS = ("https://calendar.google.com/calendar/ical/di3mf9lcgr5ham66dhdhsc05vg%40group.calendar.google.com"
                  "/public/basic.ics")


# ---------------------------------------------------------------------------
# iCalendar
# ---------------------------------------------------------------------------

@dataclass
class Event:
    summary: str
    start: date | datetime
    end: date | datetime | None = None
    rrule: dict | None = None
    exdates: tuple = ()

    @property
    def all_day(self) -> bool:
        return not isinstance(self.start, datetime)


@dataclass
class Occurrence:
    """An event on a given day: its start and end there (None all day)."""

    summary: str
    start: datetime | None
    end: datetime | None


def _unfold(text: str) -> list[str]:
    lines = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def _unescape(value: str) -> str:
    return re.sub(r"\\([,;\\nN])", lambda m: "\n" if m.group(1) in "nN" else m.group(1), value)


def _when(params: str, value: str, local: tzinfo) -> date | datetime | None:
    value = value.strip()
    try:
        if "VALUE=DATE" in params.upper() and "DATE-TIME" not in params.upper() or len(value) == 8:
            return date(int(value[:4]), int(value[4:6]), int(value[6:8]))
        moment = datetime(int(value[:4]), int(value[4:6]), int(value[6:8]),
                          int(value[9:11]), int(value[11:13]), int(value[13:15] or 0))
    except (ValueError, IndexError):
        return None
    if value.endswith("Z"):
        return moment.replace(tzinfo=timezone.utc)
    zone = re.search(r"TZID=([^;:]+)", params)
    if zone:
        try:
            from zoneinfo import ZoneInfo

            return moment.replace(tzinfo=ZoneInfo(zone.group(1).strip('"')))
        except Exception:  # noqa: BLE001 - an unknown zone: taken as local
            pass
    return moment.replace(tzinfo=local)


def parse_ics(text: str, local: tzinfo | None = None) -> list[Event]:
    """The events of an iCalendar file (VEVENT: SUMMARY, DTSTART, DTEND, RRULE, EXDATE)."""
    local = local or datetime.now().astimezone().tzinfo
    events, current = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            current = {"exdates": []}
        elif line == "END:VEVENT":
            if current and current.get("start") is not None:
                events.append(Event(current.get("summary", ""), current["start"], current.get("end"),
                                    current.get("rrule"), tuple(current["exdates"])))
            current = None
        elif current is not None and ":" in line:
            head, value = line.split(":", 1)
            name, _, params = head.partition(";")
            if name == "SUMMARY":
                current["summary"] = _unescape(value).strip()
            elif name == "DTSTART":
                current["start"] = _when(params, value, local)
            elif name == "DTEND":
                current["end"] = _when(params, value, local)
            elif name == "RRULE":
                current["rrule"] = dict(part.split("=", 1) for part in value.split(";") if "=" in part)
            elif name == "EXDATE":
                for item in value.split(","):
                    if (when := _when(params, item, local)) is not None:
                        current["exdates"].append(when if not isinstance(when, datetime) else when.date())
    return events


_DAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _occurs(event: Event, day: date) -> bool:
    """Whether a (maybe repeating) event starts on ``day``."""
    first = event.start.date() if isinstance(event.start, datetime) else event.start
    if day < first or day in event.exdates:
        return False
    rule = event.rrule
    if not rule:
        return day == first
    if until := rule.get("UNTIL"):
        try:
            if day > date(int(until[:4]), int(until[4:6]), int(until[6:8])):
                return False
        except ValueError:
            pass
    interval = int(rule.get("INTERVAL", 1) or 1)
    freq = rule.get("FREQ")
    count = int(rule["COUNT"]) if rule.get("COUNT", "").isdigit() else None
    if freq == "YEARLY":
        n = day.year - first.year
        ok = (day.month, day.day) == (first.month, first.day) and n % interval == 0
    elif freq == "MONTHLY":
        n = (day.year - first.year) * 12 + day.month - first.month
        ok = day.day == first.day and n % interval == 0
    elif freq == "WEEKLY":
        weekdays = [_DAYS[d[-2:]] for d in rule.get("BYDAY", "").split(",") if d[-2:] in _DAYS] or [first.weekday()]
        n = ((day - first).days + first.weekday()) // 7
        ok = day.weekday() in weekdays and n % interval == 0
    elif freq == "DAILY":
        n = (day - first).days
        ok = n % interval == 0
    else:
        return day == first
    if ok and count is not None and n // interval >= count:
        return False
    return ok


def events_on(events: list[Event], day: date, local: tzinfo | None = None) -> list[Occurrence]:
    """What happens on ``day``: all-day events first, then by time."""
    local = local or datetime.now().astimezone().tzinfo
    found = []
    for event in events:
        start = event.start.astimezone(local) if isinstance(event.start, datetime) else event.start
        if isinstance(start, datetime):
            shifted = Event(event.summary, start.date(), None, event.rrule, event.exdates)
            if _occurs(shifted, day):
                begin = datetime.combine(day, start.timetz())
                length = (event.end - event.start) if isinstance(event.end, datetime) else timedelta(hours=1)
                found.append(Occurrence(event.summary, begin, begin + length))
        elif _occurs(event, day) or (event.end and not event.rrule and start <= day < event.end):
            found.append(Occurrence(event.summary, None, None))
    return sorted(found, key=lambda o: (o.start is not None, o.start or datetime.min.replace(tzinfo=timezone.utc)))


def names_of(occurrences: list[Occurrence]) -> list[str]:
    """« Amandine, Hermine » -> ["Amandine", "Hermine"] (the saints calendar's way)."""
    names = []
    for occurrence in occurrences:
        names += [n.strip() for n in occurrence.summary.split(",") if n.strip()]
    return names


# ---------------------------------------------------------------------------
# Special days
# ---------------------------------------------------------------------------

@dataclass
class Special:
    key: str        # the picture
    title: str      # big
    line: str = ""  # small, under it
    colors: tuple = ((255, 80, 80), (80, 200, 120))  # the theme


def easter(year: int) -> date:
    """Easter Sunday (Gregorian, anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    return date(year, month, (h + m - 7 * n + 114) % 31 + 1)


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def _last_sunday(year: int, month: int) -> date:
    last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


GOLD, RED, GREEN, PINK, BLUE, ORANGE, WHITE = ((255, 200, 60), (230, 50, 50), (60, 190, 90), (255, 110, 170),
                                              (80, 140, 255), (255, 140, 30), (235, 235, 240))


def special_days(day: date, birthdays: list[dict] | None = None) -> list[Special]:
    """The special days on ``day`` (France): holidays, celebrations, the birthdays given."""
    y = day.year
    e = easter(y)
    mothers = _last_sunday(y, 5)
    if mothers == e + timedelta(days=49):  # Pentecost: one week later
        mothers += timedelta(days=7)
    fixed = {
        (1, 1): Special("fireworks", "BONNE ANNEE", str(y), (GOLD, BLUE)),
        (1, 6): Special("crown", "EPIPHANIE", "GALETTE DES ROIS", (GOLD, ORANGE)),
        (2, 2): Special("crepe", "CHANDELEUR", "CREPES !", (GOLD, ORANGE)),
        (2, 14): Special("heart", "ST VALENTIN", "", (PINK, RED)),
        (3, 17): Special("clover", "ST PATRICK", "", (GREEN, GOLD)),
        (4, 1): Special("fish", "POISSON", "D'AVRIL", (BLUE, ORANGE)),
        (5, 1): Special("muguet", "1ER MAI", "FETE DU TRAVAIL", (GREEN, WHITE)),
        (5, 8): Special("flag", "8 MAI 1945", "VICTOIRE", (BLUE, RED)),
        (6, 21): Special("note", "FETE DE LA", "MUSIQUE", (PINK, BLUE)),
        (7, 14): Special("flag", "14 JUILLET", "FETE NATIONALE", (BLUE, RED)),
        (8, 15): Special("star", "15 AOUT", "ASSOMPTION", (BLUE, WHITE)),
        (10, 31): Special("pumpkin", "HALLOWEEN", "", (ORANGE, (140, 60, 200))),
        (11, 1): Special("candle", "TOUSSAINT", "", (GOLD, WHITE)),
        (11, 11): Special("bleuet", "11 NOVEMBRE", "ARMISTICE", (BLUE, RED)),
        (12, 24): Special("tree", "REVEILLON", "DE NOEL", (GREEN, RED)),
        (12, 25): Special("tree", "JOYEUX NOEL", "", (RED, GREEN)),
        (12, 31): Special("fireworks", "REVEILLON", "DU NOUVEL AN", (GOLD, BLUE)),
    }
    moving = {
        e: Special("egg", "JOYEUSES", "PAQUES", (PINK, GOLD)),
        e + timedelta(days=1): Special("egg", "LUNDI DE", "PAQUES", (PINK, GOLD)),
        e + timedelta(days=39): Special("star", "ASCENSION", "", (BLUE, WHITE)),
        e + timedelta(days=49): Special("star", "PENTECOTE", "", (GOLD, WHITE)),
        e + timedelta(days=50): Special("star", "LUNDI DE", "PENTECOTE", (GOLD, WHITE)),
        mothers: Special("flower", "BONNE FETE", "MAMAN", (PINK, GREEN)),
        _nth_sunday(y, 6, 3): Special("tie", "BONNE FETE", "PAPA", (BLUE, GOLD)),
        e - timedelta(days=47): Special("mask", "MARDI GRAS", "", (PINK, GOLD)),
    }
    found = []
    if day in moving:
        found.append(moving[day])
    if (day.month, day.day) in fixed:
        found.append(fixed[(day.month, day.day)])
    for name, age in birthdays_on(day, birthdays):
        found.append(Special("cake", "JOYEUX ANNIV", f"{name} {age}".strip(), (PINK, GOLD)))
    return found


def birthdays_on(day: date, birthdays: list[dict] | None) -> list[tuple[str, str]]:
    """(name, « 16 ANS » or "") of the birthdays on ``day`` (dates 2010-10-31, 10-31 or --10-31)."""
    found = []
    for birthday in birthdays or []:
        parts = str(birthday.get("date") or "").lstrip("-").split("-")
        try:
            month, dom = int(parts[-2]), int(parts[-1])
        except (ValueError, IndexError):
            continue
        if (month, dom) == (day.month, day.day):
            age = f"{day.year - int(parts[0])} ANS" if len(parts) == 3 and parts[0].isdigit() else ""
            found.append(((birthday.get("name") or "").strip(), age))
    return found


# ---------------------------------------------------------------------------
# Built-in texts (a new one each hour)
# ---------------------------------------------------------------------------

def _load_texts() -> dict:
    """The texts and where each comes from (texts_fr.json, next to this file)."""
    # Through the package's loader: also inside the Android app (Chaquopy) and the exe (PyInstaller).
    try:
        data = pkgutil.get_data(__package__, "texts_fr.json") if __package__ else None
    except (ValueError, ImportError, OSError):  # a package loaded by hand (the exe's idmcore): the file
        data = None
    raw = data.decode("utf-8") if data else Path(__file__).with_name("texts_fr.json").read_text(encoding="utf-8")
    return {kind: texts for kind, texts in json.loads(raw).items() if not kind.startswith("_")}


TEXTS = _load_texts()
# kind -> (header, items): thought, proverb, fact, motivation, humor, wellbeing, word.
TEXT_KINDS = {kind: (texts["header"], texts["items"]) for kind, texts in TEXTS.items()}


def _text_item(kind: str, now: datetime) -> dict:
    """This hour's text (the word: today's), the same all hour (all day) long."""
    items = TEXT_KINDS[kind][1]
    turn = now.toordinal() if TEXTS[kind].get("every") == "day" else now.toordinal() * 24 + now.hour
    return items[turn * 7919 % len(items)]


def text_of_hour(kind: str, now: datetime) -> tuple[str, str, str]:
    """(header, text, author) for this hour: each hour another one, the same all hour long."""
    item = _text_item(kind, now)
    return TEXT_KINDS[kind][0], item["text"], item.get("author", "")


def word_of_day(now: datetime) -> tuple[str, str]:
    """(word, what it means) for today."""
    item = _text_item("word", now)
    return item["word"], item["text"]


# ---------------------------------------------------------------------------
# The pages to show
# ---------------------------------------------------------------------------

@dataclass
class Extras:
    """What the pages need that comes from outside: today's agenda, saints, world days."""

    agenda: list[Occurrence] | None = None
    saints: list[str] | None = None
    world_days: list[str] | None = None
    birthdays: list[dict] | None = None  # the phone's contacts': [{name, date}]


WORLD_DAYS_SHOWN = 2


def extra_pages(cfg: dict, extras: Extras | None, now: datetime) -> list[dict]:
    """The pages (besides the weather) to show today, in their order."""
    extras = extras or Extras()
    pages = []
    # The birthdays on a page of their own (« Anniversaires »), else with the special days.
    alone = cfg.get("birthday_page")
    if cfg.get("special_days", True):
        for special in special_days(now.date(), None if alone else cfg.get("birthdays")):
            pages.append({"kind": "special", "special": special})
    if alone:
        people = birthdays_on(now.date(), list(cfg.get("birthdays") or []) + list(extras.birthdays or []))
        if people:
            pages.append({"kind": "birthdays", "people": people})
    if cfg.get("agenda") and extras.agenda is not None:
        pages.append({"kind": "agenda", "items": extras.agenda, "style": cfg.get("agenda_style", "list")})
    # Today's saints and world days: the ones picked in the app for today, else all the saints and
    # the first world days (two at most).
    picked = cfg.get("pick") or {}
    picked = picked if picked.get("date") == now.date().isoformat() else {}
    saints = [n for n in extras.saints or [] if n in picked["saints"]] if picked.get("saints") else extras.saints
    days = [d for d in extras.world_days or [] if d in picked["world_days"]] if picked.get("world_days") else extras.world_days
    if cfg.get("saints") and saints:
        pages.append({"kind": "saint", "names": saints})
    if cfg.get("world_days") and days:
        pages.append({"kind": "world_days", "items": days[:WORLD_DAYS_SHOWN]})
    for kind in TEXT_KINDS:
        if cfg.get(kind):
            pages.append({"kind": kind})
    return pages


def ascii_upper(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().upper()


def wrap(text: str, width: int, measure) -> list[str]:
    """Words into lines no wider than ``width`` (a word too long is cut)."""
    lines, current = [], ""
    words = []
    for word in text.split():  # a word too long breaks after its hyphens first (SAINTE- CATHERINE)
        if measure(word) > width and "-" in word.strip("-"):
            pieces = word.split("-")
            words += [piece + "-" for piece in pieces[:-1]] + [pieces[-1]]
        else:
            words.append(word)
    for word in words:
        trial = f"{current}{word}" if current.endswith("-") else f"{current} {word}".strip()
        if measure(trial) <= width:
            current = trial
            continue
        if current:
            lines.append(current)
        while measure(word) > width and len(word) > 1:
            cut = len(word)
            while cut > 1 and measure(word[:cut]) > width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# From the calendars to the pages
# ---------------------------------------------------------------------------

_parsed: dict[str, tuple[int, list[Event]]] = {}


def http_url(url: str) -> str:
    """webcal:// links (calendar apps share them so) are plain https."""
    return "https://" + url[len("webcal://"):] if url.startswith("webcal://") else url


def ics_urls(cfg: dict) -> list[str]:
    """The calendar files the view needs."""
    urls = [http_url(u) for u in cfg.get("agenda_ics") or []] if cfg.get("agenda") else []
    if cfg.get("saints"):
        urls.append(SAINTS_ICS)
    if cfg.get("world_days"):
        urls.append(WORLD_DAYS_ICS)
    return urls


def events_of(url: str, text: str | None, local: tzinfo | None = None) -> list[Event]:
    """A calendar's events, parsed once per version of its file."""
    if not text:
        return []
    key = hash(text)
    cached = _parsed.get(url)
    if cached and cached[0] == key:
        return cached[1]
    events = parse_ics(text, local)
    _parsed[url] = (key, events)
    return events


def build_extras(cfg: dict, texts: dict[str, str], now: datetime, agenda: list[Occurrence] | None = None) -> Extras:
    """Today's agenda, saints and world days from the calendar files fetched (``texts``: url -> file),
    with the Home Assistant calendars' events of the day (``agenda``)."""
    day, local = now.date(), now.tzinfo
    extras = Extras()
    if cfg.get("agenda"):
        items = list(agenda or [])
        for url in cfg.get("agenda_ics") or []:
            items += events_on(events_of(http_url(url), texts.get(http_url(url)), local), day, local)
        for event in cfg.get("events") or []:  # typed in the app: today's
            if event.get("date") != day.isoformat():
                continue
            start = None
            if event.get("time"):
                hour, minute = (int(v) for v in event["time"].split(":"))
                start = datetime(day.year, day.month, day.day, hour, minute, tzinfo=local)
            items.append(Occurrence(event["title"], start, None))
        extras.agenda = sorted(items, key=lambda o: (o.start is not None, o.start or now))
    if cfg.get("saints"):
        extras.saints = names_of(events_on(events_of(SAINTS_ICS, texts.get(SAINTS_ICS), local), day, local))
    if cfg.get("world_days"):
        extras.world_days = [o.summary for o in events_on(events_of(WORLD_DAYS_ICS, texts.get(WORLD_DAYS_ICS), local),
                                                           day, local)]
    return extras
