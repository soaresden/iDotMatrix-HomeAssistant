"""Pixel Studio's Store tab: the official app's catalogue, through Home Assistant.

Optional: without this module (or ``gif_store``), the integration works and the
panel hides the tab. It is kept out of public copies of the integration, as it
talks to the vendor's own server.
"""
from __future__ import annotations

import base64
import os

import aiohttp
import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import gif_store
from . import studio as pixel_studio

MAX_STORE_FILES = 300


async def _store_request(hass: HomeAssistant, method: str, url: str, body: str | None = None) -> bytes:
    headers = {"User-Agent": gif_store.USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "text/plain; charset=utf-8"
    try:
        async with async_get_clientsession(hass).request(
            method, url, data=body, headers=headers, timeout=aiohttp.ClientTimeout(total=gif_store.TIMEOUT_S),
        ) as response:
            if response.status != 200:
                raise gif_store.StoreError(f"The store refused the request (HTTP {response.status})")
            # Read to the end: one read() only returns what has arrived so far,
            # which cut files short ("Incorrect padding", "not a GIF").
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                size += len(chunk)
                if size > gif_store.MAX_FILE_BYTES * 4:
                    raise gif_store.StoreError("Store file too large")
                chunks.append(chunk)
            data = b"".join(chunks)
    except (aiohttp.ClientError, TimeoutError) as err:
        raise gif_store.StoreError(f"The store cannot be reached: {err}") from err
    return data


async def _store_file(hass: HomeAssistant, url: str) -> bytes:
    """A listed store GIF, downloaded once per run."""
    studio = pixel_studio._studio(hass)
    if url not in studio.store_urls:
        raise gif_store.StoreError("Unknown store item: open its category again")
    if url not in studio.store_files:
        body = await _store_request(hass, "GET", url)
        data = await hass.async_add_executor_job(gif_store.decode_file, body.decode(errors="replace"))
        if len(data) > gif_store.MAX_FILE_BYTES:
            raise gif_store.StoreError("Store file too large")
        while len(studio.store_files) >= MAX_STORE_FILES:
            studio.store_files.pop(next(iter(studio.store_files)))
        studio.store_files[url] = data
    return studio.store_files[url]


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/store_list",
    vol.Required("group"): vol.In(list(gif_store.GROUPS)),
    vol.Optional("page", default=1): vol.All(int, vol.Range(min=1, max=1000)),
    pixel_studio._DISPLAY: str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_store_list(hass, connection, msg):
    """One page of a store category, for the display's screen size."""
    try:
        size = pixel_studio._screen_size(hass, msg.get("entry_id"))
        url, body = gif_store.build_request(gif_store.list_params(msg["group"], msg["page"], size))
        reply = await _store_request(hass, "POST", url, body)
        listing = gif_store.parse_listing(reply.decode(errors="replace"), size)
    except (HomeAssistantError, gif_store.StoreError) as err:
        pixel_studio._error(connection, msg, err)
        return
    studio = pixel_studio._studio(hass)
    studio.store_urls.update((item.url, item.name) for item in listing["items"])
    connection.send_result(msg["id"], {
        **listing, "size": size,
        "items": [{**item.as_dict(), "gallery": studio.store_file(item.url)} for item in listing["items"]],
    })


@websocket_api.websocket_command({vol.Required("type"): "idotmatrix/studio/store_favorites"})
@websocket_api.require_admin
@callback
def ws_store_favorites(hass, connection, msg):
    """The starred store animations, newest first."""
    favorites = pixel_studio._studio(hass).store_favorites
    connection.send_result(msg["id"], {"items": [{**item, "url": url} for url, item in reversed(favorites.items())]})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/store_favorite",
    vol.Required("url"): str,
    vol.Required("favorite"): bool,
    vol.Optional("item", default=dict): {
        vol.Optional("name"): vol.All(str, vol.Length(max=80)),
        vol.Optional("width"): int, vol.Optional("height"): int,
        vol.Optional("format"): vol.All(str, vol.Length(max=10)),
        vol.Optional("tags"): [vol.All(str, vol.Length(max=40))],
        vol.Optional("uploaded"): vol.All(str, vol.Length(max=20)),
    },
})
@websocket_api.require_admin
@callback
def ws_store_favorite(hass, connection, msg):
    """Star or unstar a store animation (only ones the store listed)."""
    studio = pixel_studio._studio(hass)
    url = msg["url"]
    if msg["favorite"]:
        if url not in studio.store_urls:
            pixel_studio._error(connection, msg, HomeAssistantError("Unknown store animation"))
            return
        studio.store_favorites.pop(url, None)
        studio.store_favorites[url] = {"name": studio.store_urls[url], **msg["item"]}
    else:
        studio.store_favorites.pop(url, None)
    studio.save_meta()
    connection.send_result(msg["id"], {})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/store_item",
    vol.Required("url"): str,
    pixel_studio._DISPLAY: str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_store_item(hass, connection, msg):
    """A store GIF for the thumbnail, with its size and layout."""
    try:
        size = pixel_studio._screen_size(hass, msg.get("entry_id"))
        data = await _store_file(hass, msg["url"])
        info = await hass.async_add_executor_job(gif_store.describe, data, size)
    except (HomeAssistantError, gif_store.StoreError, OSError) as err:
        pixel_studio._error(connection, msg, err)
        return
    connection.send_result(msg["id"], {**info, "gif": base64.b64encode(gif_store.looping(data)).decode()})


@websocket_api.websocket_command({
    vol.Required("type"): "idotmatrix/studio/store_import",
    vol.Required("url"): str,
    vol.Optional("title"): vol.All(str, vol.Length(min=1, max=80)),
    vol.Optional("folder"): vol.All(str, vol.Length(max=60)),
    vol.Optional("display", default=False): bool,
    vol.Optional("device"): vol.All(str, vol.Length(max=40)),
    pixel_studio._DISPLAY: str,
})
@websocket_api.require_admin
@websocket_api.async_response
async def ws_store_import(hass, connection, msg):
    """Copy a store GIF into the gallery (re-encoded if the panel needs it).

    Imported once: asking again (another browser, ▶ after + Galerie) uses the
    gallery's copy instead of making a duplicate.
    """
    studio = pixel_studio._studio(hass)
    name = studio.store_urls.get(msg["url"]) or "store"
    title = msg.get("title") or name
    existing = studio.store_file(msg["url"])
    if existing:
        try:
            path = studio.gallery_path(existing)
            size_bytes = await hass.async_add_executor_job(os.path.getsize, path)
        except (HomeAssistantError, OSError):
            studio.meta[existing].pop("store_url", None)  # deleted by hand: import it again
        else:
            if msg.get("display"):
                pixel_studio._start_display(hass, path, msg.get("entry_id"))
            connection.send_result(msg["id"], {
                "file": existing, "size_bytes": size_bytes, "reencoded": False, "existing": True,
                "estimate_s": pixel_studio.estimate_seconds(size_bytes, pixel_studio._seconds_per_packet(hass, msg.get("entry_id"))),
            })
            return
    try:
        size = pixel_studio._screen_size(hass, msg.get("entry_id"))
        data = await _store_file(hass, msg["url"])

        def save() -> tuple[str, bytes, bool]:
            gif = gif_store.device_gif(data, size)
            file = pixel_studio.unique_file(studio.folder, pixel_studio.slugify_name(title))
            with open(os.path.join(studio.folder, file), "wb") as handle:
                handle.write(gif)
            return file, gif, not gif_store.device_ready(data, size)

        file, gif, reencoded = await hass.async_add_executor_job(save)
    except (HomeAssistantError, gif_store.StoreError, OSError, ValueError) as err:
        pixel_studio._error(connection, msg, err)
        return
    studio.meta[file] = {
        "title": title, "favorite": False, "clip": None,
        "source": f"Store · {name}", "folder": (msg.get("folder") or "").strip(),
        "device": msg.get("device") or None, "user": connection.user.name, "store_url": msg["url"],
    }
    studio.save_meta()
    if msg.get("display"):
        pixel_studio._start_display(hass, studio.gallery_path(file), msg.get("entry_id"))
    connection.send_result(msg["id"], {
        "file": file, "size_bytes": len(gif), "reencoded": reencoded,
        "estimate_s": pixel_studio.estimate_seconds(len(gif), pixel_studio._seconds_per_packet(hass, msg.get("entry_id"))),
    })


COMMANDS = (ws_store_favorite, ws_store_favorites, ws_store_import, ws_store_item, ws_store_list,)
