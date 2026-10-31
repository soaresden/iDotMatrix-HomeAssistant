import base64
import hashlib
import io
import json
import os
import urllib.parse
from types import SimpleNamespace

import pytest
from PIL import Image, ImageSequence

from custom_components.idotmatrix import gif_store, store_ws
from custom_components.idotmatrix.const import DOMAIN


@pytest.fixture(autouse=True)
def _test_store_key(monkeypatch):
    """The real key stays out of the repository: any 32-byte key exercises the code."""
    monkeypatch.setattr(gif_store, "_KEY", b"k" * 32)
from custom_components.idotmatrix.studio import Studio
from custom_components.idotmatrix.weather import frames_to_gif


def _pillow_gif(size=64, frames=3, colors=((255, 0, 0), (0, 0, 255), (0, 255, 0))) -> bytes:
    """A GIF as Pillow writes it: one palette per frame, white often first."""
    images = [Image.new("RGB", (size, size), colors[i % len(colors)]) for i in range(frames)]
    images[0].paste((255, 255, 255), (0, 0, size // 2, size // 2))
    buf = io.BytesIO()
    images[0].save(buf, format="GIF", save_all=True, append_images=images[1:], duration=[70, 80, 90][:frames], loop=0)
    return buf.getvalue()


def _device_gif(size=64) -> bytes:
    frames = [Image.new("RGB", (size, size), (i * 80, 0, 0)) for i in range(3)]
    return frames_to_gif(frames, [50, 60, 70], colors=16)


def _store_blob(data: bytes) -> str:
    """A store file as the vendor serves it (reverse of DecryptHelper)."""
    inner = urllib.parse.quote_plus(base64.b64encode(data).decode()[::-1])
    return "J" * 32 + inner + "K" * 32


def _listing(records, total_pages=3) -> str:
    reply = {"status": 0, "msg": "请求成功", "data": {
        "pageNo": 1, "pageSize": 10, "records": records, "totalCount": len(records), "totalPage": total_pages}}
    return gif_store.encrypt(json.dumps(reply))


def _record(url, width=64, height=64, file_id=23987, tags=()):
    """A record as the server sent it on 2026-10-28."""
    return {"app_id": 140, "bindtime": "2024-06-12 16:46:14", "category_id": 7, "category_name": "日常_IDM",
            "file_id": file_id, "file_path": url, "format": "gif", "height": height, "imageheight": height,
            "imagewidth": width, "label": "ALL", "search_tags": list(tags), "sort": 100, "type": "动画",
            "uploadtime": "2024-06-12 16:44:58", "width": width}


# ---------------------------------------------------------------------------
# Signing and encryption
# ---------------------------------------------------------------------------

def test_query_is_url_encoded_like_java_with_separators_kept():
    assert gif_store.java_url_encode("a b*~&c=d?e,é") == "a+b*%7E&c=d?e%2C%C3%A9"
    assert gif_store.sorted_query({"b": "2", "a": "x y"}) == "a=x+y&b=2"


def test_body_round_trips_through_the_app_cipher():
    text = "appid=140&category_name=%E6%97%A5%E5%B8%B8_IDM"
    encrypted = gif_store.encrypt(text)
    assert encrypted != text and base64.b64decode(encrypted)
    assert gif_store.decrypt(encrypted) == text


def test_request_is_signed_over_params_random_timestamp_and_app_key():
    params = gif_store.list_params("daily", 2, 64)
    url, body = gif_store.build_request(params, now=1700000000.9, random="AbCd1234")
    query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
    assert url.startswith(gif_store.STORE_URL + "?")
    assert (query["timestamp"], query["random"]) == ("1700000000", "AbCd1234")
    signed = {**params, "random": "AbCd1234", "timestamp": "1700000000", "app_key": gif_store._KEY.decode()}
    expected = hashlib.md5(gif_store.sorted_query(signed).encode()).hexdigest()
    assert query["sign"] == expected and len(expected) == 32
    # The body carries the parameters only, not the signing extras.
    assert gif_store.decrypt(body) == gif_store.sorted_query(params)


def test_list_params_ask_for_animations_of_one_tab_at_the_screen_size():
    params = gif_store.list_params("holiday", 3, 64)
    assert params["category_name"] == "节日_IDM"
    assert (params["type"], params["width"], params["height"], params["page"]) == ("动画", "64", "64", "3")
    with pytest.raises(gif_store.StoreError):
        gif_store.list_params("../admin", 1, 64)


def test_listing_keeps_items_for_this_screen_and_names_them_by_tags_or_number():
    body = _listing([
        _record("https://images.example/download/675bdcdf140896.72616562"),
        _record("https://images.example/download/675bdcdf140916.66657444", file_id=23988, tags=["coeur", "love"]),
        _record("https://images.example/download/small", 32, 32),
        _record("ftp://images.example/download/odd"),
        _record("https://images.example/download/bad", "x"),
    ])
    listing = gif_store.parse_listing(body, 64)
    assert [item.as_dict() for item in listing["items"]] == [
        {"url": "https://images.example/download/675bdcdf140896.72616562", "name": "store_23987", "width": 64,
         "height": 64, "format": "gif", "tags": [], "uploaded": "2024-06-12"},
        {"url": "https://images.example/download/675bdcdf140916.66657444", "name": "coeur love", "width": 64,
         "height": 64, "format": "gif", "tags": ["coeur", "love"], "uploaded": "2024-06-12"}]
    assert (listing["page"], listing["total_pages"], listing["total"]) == (1, 3, 5)


def test_listing_errors_are_reported():
    with pytest.raises(gif_store.StoreError, match="Unreadable"):
        gif_store.parse_listing("<html>403 Forbidden</html>", 64)
    with pytest.raises(gif_store.StoreError, match="sign error"):
        gif_store.parse_listing(gif_store.encrypt(json.dumps({"status": 500, "msg": "sign error"})), 64)


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def test_store_files_decode_to_the_gif_inside():
    gif = _pillow_gif()
    assert gif_store.decode_file(_store_blob(gif)) == gif
    with pytest.raises(gif_store.StoreError):
        gif_store.decode_file("x" * 40)
    with pytest.raises(gif_store.StoreError, match="not a GIF"):
        gif_store.decode_file(_store_blob(b"\x89PNG not a gif"))


def test_any_screen_sized_gif_is_sent_as_is_like_the_official_app():
    ready = gif_store.gif_layout(_device_gif())
    assert (ready["local_palettes"], ready["first_color"]) == (0, (0, 0, 0))
    assert gif_store.device_ready(_device_gif(), 64)
    assert not gif_store.device_ready(_device_gif(32), 64)
    # Local palettes and frame deltas stay: re-encoding full frames made a
    # 15 KB store GIF 384 KB (18 minutes over Bluetooth).
    assert gif_store.gif_layout(_pillow_gif())["local_palettes"]
    assert gif_store.device_ready(_pillow_gif(), 64)
    assert gif_store.device_gif(_pillow_gif(), 64) == _pillow_gif()


def test_describe_reports_size_frames_and_timing():
    info = gif_store.describe(_device_gif(), 64)
    assert info == {"size_bytes": len(_device_gif()), "frames": 3, "duration_ms": 180, "width": 64, "height": 64,
                    "local_palettes": 0, "device_ready": True}


def test_screen_sized_gifs_are_kept_byte_for_byte_others_are_resized():
    ready = _device_gif()
    assert gif_store.device_gif(ready, 64) is ready
    fixed = gif_store.device_gif(_pillow_gif(32), 64)
    assert gif_store.device_ready(fixed, 64)
    with Image.open(io.BytesIO(fixed)) as image:
        frames = [(frame.size, frame.info["duration"]) for frame in ImageSequence.Iterator(image)]
    assert frames == [((64, 64), 70), ((64, 64), 80), ((64, 64), 90)]


# ---------------------------------------------------------------------------
# Websocket commands (the vendor's server mocked)
# ---------------------------------------------------------------------------

class _Server:
    def __init__(self, records, files):
        self.records, self.files, self.calls = records, files, []

    async def __call__(self, hass, method, url, body=None):
        self.calls.append((method, url))
        if method == "POST":
            assert gif_store.decrypt(body).startswith("appid=140&")
            return _listing(self.records).encode()
        return _store_blob(self.files[url]).encode()


@pytest.fixture
def store_env(tmp_path, monkeypatch):
    from custom_components.idotmatrix import studio as studio_module

    hass = SimpleNamespace(data={}, config=SimpleNamespace(
        media_dirs={"local": str(tmp_path)}, path=lambda *p: str(tmp_path.joinpath(*p)), config_dir=str(tmp_path)))
    studio = Studio(hass)
    os.makedirs(studio.folder)
    studio.save_meta = lambda: None
    tasks, displayed, results = [], [], []

    async def executor(func, *args):
        return func(*args)

    hass.data[DOMAIN] = {"_studio": studio}
    hass.async_add_executor_job = executor
    hass.async_create_background_task = lambda coro, *a, **k: tasks.append(coro)
    monkeypatch.setattr(studio_module, "_screen_size", lambda hass, entry_id=None: 64)
    monkeypatch.setattr(studio_module, "_seconds_per_packet", lambda hass, entry_id=None: 1.0)
    monkeypatch.setattr(studio_module, "_start_display", lambda hass, path, entry_id=None: displayed.append(path))
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True, name="Denis"), send_result=lambda _id, r: results.append(r),
                                 send_error=lambda _id, code, message: results.append(("error", message)))

    async def run(command, msg):
        command(hass, connection, {"id": 1, **msg})
        await tasks.pop()
        return results.pop()

    return SimpleNamespace(module=store_ws, studio=studio, run=run, displayed=displayed, monkeypatch=monkeypatch)


async def test_store_lists_a_category_then_shows_and_imports_its_gifs(store_env):
    m = store_env.module
    ready, pillow = "https://images.example/download/675bdcdf140896.72616562", "https://images.example/download/b2"
    server = _Server([_record(ready), _record(pillow, file_id=24000, tags=["chat"])],
                     {ready: _device_gif(), pillow: _pillow_gif()})
    store_env.monkeypatch.setattr(m, "_store_request", server)

    listing = await store_env.run(m.ws_store_list, {"type": "idotmatrix/studio/store_list", "group": "daily", "page": 1})
    assert [i["name"] for i in listing["items"]] == ["store_23987", "chat"]
    assert (listing["size"], listing["total_pages"]) == (64, 3)

    item = await store_env.run(m.ws_store_item, {"type": "idotmatrix/studio/store_item", "url": pillow})
    assert (item["frames"], item["device_ready"]) == (3, True)
    assert base64.b64decode(item["gif"]) == _pillow_gif()

    kept = await store_env.run(m.ws_store_import, {"type": "idotmatrix/studio/store_import", "url": ready})
    assert (kept["file"], kept["reencoded"], kept["size_bytes"]) == ("store_23987.gif", False, len(_device_gif()))
    with open(store_env.studio.gallery_path("store_23987.gif"), "rb") as handle:
        assert handle.read() == _device_gif()

    shown = await store_env.run(m.ws_store_import, {"type": "idotmatrix/studio/store_import", "url": pillow,
                                                    "title": "Chat du store", "display": True})
    assert (shown["file"], shown["reencoded"]) == ("chat_du_store.gif", False)
    assert store_env.displayed == [store_env.studio.gallery_path("chat_du_store.gif")]
    assert store_env.studio.meta["chat_du_store.gif"]["source"] == "Store · chat"
    assert store_env.studio.meta["chat_du_store.gif"]["user"] == "Denis"
    # Asked again (another browser, ▶ after + Galerie): the gallery's copy, no duplicate.
    again = await store_env.run(m.ws_store_import, {"type": "idotmatrix/studio/store_import", "url": ready})
    assert (again["file"], again["existing"]) == ("store_23987.gif", True)
    assert sorted(os.listdir(store_env.studio.folder)) == ["chat_du_store.gif", "store_23987.gif"]
    listing = await store_env.run(m.ws_store_list, {"type": "idotmatrix/studio/store_list", "group": "daily", "page": 1})
    assert [i["gallery"] for i in listing["items"]] == ["store_23987.gif", "chat_du_store.gif"]
    # Each file was downloaded once, then served from memory.
    assert [c for c in server.calls if c[0] == "GET"] == [("GET", pillow), ("GET", ready)]


async def test_store_only_fetches_urls_it_listed(store_env):
    m = store_env.module
    server = _Server([], {})
    store_env.monkeypatch.setattr(m, "_store_request", server)
    result = await store_env.run(m.ws_store_item, {"type": "idotmatrix/studio/store_item",
                                                   "url": "http://homeassistant.local:8123/api/secret"})
    assert result[0] == "error" and "Unknown store item" in result[1]
    assert server.calls == []


async def test_a_refused_store_shows_as_an_error(store_env):
    m = store_env.module

    async def refuse(hass, method, url, body=None):
        raise gif_store.StoreError("The store refused the request (HTTP 403)")

    store_env.monkeypatch.setattr(m, "_store_request", refuse)
    result = await store_env.run(m.ws_store_list, {"type": "idotmatrix/studio/store_list", "group": "emoji", "page": 1})
    assert result == ("error", "The store refused the request (HTTP 403)")


async def test_store_downloads_are_read_to_the_end(monkeypatch):
    from custom_components.idotmatrix import studio as studio_module

    chunks = [b"first-", b"second-", b"third"]

    class _Content:
        async def read(self, _n=-1):  # what arrived so far: the bug read only this
            return chunks[0]

        async def iter_chunked(self, _size):
            for chunk in chunks:
                yield chunk

    class _Response:
        status = 200
        content = _Content()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    session = SimpleNamespace(request=lambda *a, **k: _Response())
    monkeypatch.setattr(store_ws, "async_get_clientsession", lambda hass: session)
    assert await store_ws._store_request(None, "GET", "https://images.example/x") == b"first-second-third"


def test_store_gifs_are_made_to_loop_forever():
    from PIL import Image as PILImage

    frames = [PILImage.new("RGB", (64, 64), (i * 80, 0, 0)) for i in range(3)]
    buffer = io.BytesIO()
    frames[0].save(buffer, format="GIF", save_all=True, append_images=frames[1:], duration=100)
    once = buffer.getvalue().replace(b"GIF89a", b"GIF87a", 1)
    assert b"NETSCAPE2.0" not in once
    looped = gif_store.looping(once)
    with PILImage.open(io.BytesIO(looped)) as image:
        assert image.info.get("loop") == 0 and getattr(image, "n_frames", 1) == 3
    assert gif_store.looping(looped) == looped


def test_store_favourites_only_take_listed_animations_and_list_newest_first():
    from custom_components.idotmatrix import studio as studio_module

    studio = SimpleNamespace(store_urls={"https://a": "coeur", "https://b": "chat"}, store_favorites={},
                             save_meta=lambda: None)
    hass = SimpleNamespace(data={DOMAIN: {"_studio": studio}})
    results = []
    connection = SimpleNamespace(user=SimpleNamespace(is_admin=True, name="Denis"), send_result=lambda _id, r: results.append(r),
                                 send_error=lambda _id, code, message: results.append(("error", message)))

    def star(url, favorite=True):
        store_ws.ws_store_favorite(hass, connection, {
            "id": 1, "type": "idotmatrix/studio/store_favorite", "url": url, "favorite": favorite, "item": {"width": 64}})
        return results.pop()

    assert star("https://elsewhere")[0] == "error"
    star("https://a")
    star("https://b")
    store_ws.ws_store_favorites(hass, connection, {"id": 2, "type": "idotmatrix/studio/store_favorites"})
    assert [(i["url"], i["name"]) for i in results.pop()["items"]] == [("https://b", "chat"), ("https://a", "coeur")]
    star("https://a", favorite=False)
    assert list(studio.store_favorites) == ["https://b"]
