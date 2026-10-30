import aiohttp


def async_get_clientsession(hass) -> aiohttp.ClientSession:
    session = hass.data.get("aiohttp_session")
    if session is None or session.closed:
        session = hass.data["aiohttp_session"] = aiohttp.ClientSession()
    return session
