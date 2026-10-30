"""components.websocket_api for the desktop app: the command decorators.

A command keeps its type and full message schema; the desktop server
validates each message with it and calls the handler (awaiting it when it is
a coroutine, which is all ``async_response`` does in Home Assistant).
"""
from __future__ import annotations

import voluptuous as vol


def websocket_command(schema):
    fields, extra = (schema.schema, schema.extra) if isinstance(schema, vol.Schema) else (schema, vol.PREVENT_EXTRA)
    command = next(value for key, value in fields.items() if str(key) == "type")
    full = vol.Schema({vol.Required("id"): int, **fields}, extra=extra)

    def decorate(handler):
        handler.ws_command = command
        handler.ws_schema = full
        return handler

    return decorate


def require_admin(handler):
    return handler  # the desktop's only user is the person at the PC


def async_response(handler):
    return handler


def async_register_command(hass, handler) -> None:
    hass.data.setdefault("websocket_commands", {})[handler.ws_command] = handler
