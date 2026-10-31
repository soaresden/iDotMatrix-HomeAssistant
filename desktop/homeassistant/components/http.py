"""components.http for the desktop app: the view base class Studio's encode view uses."""
from __future__ import annotations

from aiohttp import web

KEY_HASS = web.AppKey("hass", object)


class HomeAssistantView:
    url: str | None = None
    name: str | None = None
    requires_auth = True

    def json(self, result, status_code: int = 200, headers=None) -> web.Response:
        return web.json_response(result, status=status_code, headers=headers)

    def json_message(self, message: str, status_code: int = 200, message_code: str | None = None,
                     headers=None) -> web.Response:
        body = {"message": message} | ({"code": message_code} if message_code else {})
        return self.json(body, status_code, headers)
