"""The phone in the Studio: its calendars, and its contacts' birthdays, offered as Home
Assistant calendars (calendar.phone_<id>, calendar.phone_birthdays). The Météo tab lists
them with Home Assistant's; the agenda reads them through calendar.get_events, answered
here by Phone.kt.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

from java import jclass

from homeassistant.exceptions import HomeAssistantError

_phone = jclass("org.idotmatrix.pixelmeteo.Phone")
PREFIX = "calendar.phone_"
BIRTHDAYS = "calendar.phone_birthdays"


class PhoneStates:
    """``hass.states`` with the phone's calendars only (no weather, zones or home)."""

    home_assistant = False  # meteo.py: no Home Assistant weather to offer

    def __init__(self) -> None:
        self._calendars: tuple[float, list] = (0.0, [])

    def _list(self) -> list:
        read, states = self._calendars
        if time.time() - read > 60:
            try:
                found = json.loads(str(_phone.calendars()))
            except Exception:  # noqa: BLE001 - no permission yet...
                found = []
            states = [SimpleNamespace(entity_id=f"{PREFIX}{c['id']}", state="off", attributes={
                "friendly_name": f"{c['name']} ({c['account']})" if c.get("account") and c["account"] != c["name"]
                else c["name"]}) for c in found]
            states.append(SimpleNamespace(entity_id=BIRTHDAYS, state="off",
                                          attributes={"friendly_name": "Anniversaires des contacts"}))
            self._calendars = (time.time(), states)
        return states

    def async_all(self, domain: str | None = None) -> list:
        return self._list() if domain in (None, "calendar") else []

    def get(self, entity_id: str):
        return next((s for s in self._list() if s.entity_id == entity_id), None)


def _birthdays_between(start: datetime, end: datetime) -> list[dict]:
    """The contacts born on a day from start to end, as all-day events."""
    out = []
    for person in json.loads(str(_phone.birthdays())):
        text = str(person.get("date") or "")
        month_day = text[-5:]  # 2010-10-31 or --10-31
        year = text[:4] if len(text) == 10 and text[:4].isdigit() else None
        day = start.date()
        while day <= end.date():
            if f"{day:%m-%d}" == month_day:
                age = f" ({day.year - int(year)} ans)" if year else ""
                out.append({"summary": f"🎂 {person['name']}{age}", "start": day.isoformat(),
                            "end": (day + timedelta(days=1)).isoformat()})
            day += timedelta(days=1)
    return out


class PhoneServices:
    """``hass.services``: calendar.get_events on the phone's calendars."""

    async def async_call(self, domain, service, data=None, blocking=False, return_response=False, **_kwargs):
        if (domain, service) != ("calendar", "get_events"):
            raise HomeAssistantError(f"{domain}.{service} n'existe pas sur le téléphone")
        data = data or {}
        ids = data.get("entity_id") or []
        ids = [ids] if isinstance(ids, str) else list(ids)
        start = datetime.fromisoformat(str(data["start_date_time"]))
        end = datetime.fromisoformat(str(data["end_date_time"]))
        calendars = [i[len(PREFIX):] for i in ids if i.startswith(PREFIX) and i != BIRTHDAYS]
        events = []
        if calendars:
            found = json.loads(str(await asyncio.to_thread(
                _phone.events, json.dumps(calendars), int(start.timestamp() * 1000), int(end.timestamp() * 1000))))
            for e in found:
                if e.get("all_day"):  # Android keeps all-day events at UTC midnight
                    day = datetime.utcfromtimestamp(e["begin"] / 1000).date()
                    events.append({"summary": e["title"], "start": day.isoformat(),
                                   "end": (day + timedelta(days=1)).isoformat()})
                else:
                    events.append({"summary": e["title"],
                                   "start": datetime.fromtimestamp(e["begin"] / 1000).astimezone().isoformat(),
                                   "end": datetime.fromtimestamp(e["end"] / 1000).astimezone().isoformat()})
        if BIRTHDAYS in ids:
            events += await asyncio.to_thread(_birthdays_between, start, end)
        return {"calendar.phone": {"events": events}}


def install_phone(hass) -> None:
    """The phone's calendars in the Studio (meteo.py reads ``hass.states``, ``hass.services``)."""
    hass.states = PhoneStates()
    hass.services = PhoneServices()

