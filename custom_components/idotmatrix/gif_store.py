"""The official iDotMatrix app's store of ready-made animations.

The Android app (``com.tech.idotmatrix`` 2.1.7, ``HomeRepository.getCloudMaterial``)
lists the store with one signed call to the vendor's server:

* the parameters are sorted, joined as ``k=v&...`` and URL-encoded the Java
  way; ``sign`` is the MD5 of that string with ``random``, ``timestamp`` and
  the app's key added, sent in the query string;
* the body is the same string (without those three) AES-256-CBC encrypted
  and Base64'd, sent as text; the reply is encrypted the same way;
* each record's ``file_path`` is a plain URL whose body is the file in
  Base64, reversed, URL-encoded and wrapped in 32 junk characters per side.

There is no account involved; the key and IV are the app's own. The
server's front end filters clients, so requests present themselves as the
app's HTTP client. It may stop answering at any app update: the panel then
shows an error and nothing else depends on it.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import secrets
import string
import time
import urllib.parse
from dataclasses import dataclass

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from PIL import Image, ImageSequence

from .media import _flatten, _resize, gif_layout
from .weather import frames_to_gif

STORE_URL = "https://manage.heaton.com.cn/api/rm/getMaterialUnderCategory"
USER_AGENT = "okhttp/5.1.0"
APP_ID = "140"


def _store_key() -> bytes:
    """The app's key, kept out of the repository: ``store_key.txt`` next to this file."""
    try:
        with open(os.path.join(os.path.dirname(__file__), "store_key.txt"), "rb") as fh:
            return fh.read().strip()
    except OSError:
        return b""


_KEY = _store_key()
_IV = b"0" * 16
PAGE_SIZE = 10
TIMEOUT_S = 20
MAX_FILE_BYTES = 2 * 1024 * 1024

# The app's five tabs; the server names them in Chinese.
GROUPS = {
    "daily": "日常",
    "emoji": "表情",
    "holiday": "节日",
    "creative": "创意",
    "business": "商业",
}
_ANIMATION = "动画"


class StoreError(Exception):
    """The store did not answer as the app expects."""


@dataclass
class StoreItem:
    url: str
    name: str
    width: int
    height: int
    format: str
    tags: list[str]
    uploaded: str

    def as_dict(self) -> dict:
        return {"url": self.url, "name": self.name, "width": self.width, "height": self.height,
                "format": self.format, "tags": self.tags, "uploaded": self.uploaded}


# ---------------------------------------------------------------------------
# Request signing and encryption
# ---------------------------------------------------------------------------

def java_url_encode(text: str) -> str:
    """``URLEncoder.encode`` with ``&``, ``=`` and ``?`` put back, as the app does."""
    encoded = urllib.parse.quote_plus(text, safe="*").replace("~", "%7E")
    return encoded.replace("%26", "&").replace("%3D", "=").replace("%3F", "?")


def sorted_query(params: dict[str, str]) -> str:
    return java_url_encode("&".join(f"{key}={params[key]}" for key in sorted(params)))


def sign(params: dict[str, str], random: str, timestamp: str) -> str:
    signed = {**params, "random": random, "timestamp": timestamp, "app_key": _KEY.decode()}
    return hashlib.md5(sorted_query(signed).encode()).hexdigest()


def _cipher() -> Cipher:
    if not _KEY:
        raise StoreError("Clé du store absente : ajoute store_key.txt à côté de gif_store.py")
    return Cipher(algorithms.AES(_KEY), modes.CBC(_IV))


def encrypt(text: str) -> str:
    padder = padding.PKCS7(128).padder()
    data = padder.update(text.encode()) + padder.finalize()
    encryptor = _cipher().encryptor()
    return base64.b64encode(encryptor.update(data) + encryptor.finalize()).decode()


def decrypt(text: str) -> str:
    decryptor = _cipher().decryptor()
    data = decryptor.update(base64.b64decode(text.strip())) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(data) + unpadder.finalize()).decode()


def list_params(group: str, page: int, size: int) -> dict[str, str]:
    """The animations of one tab for a square screen, as the app asks for them.

    ``label`` and ``filter_tags`` normally carry the connected device's
    vendor and product ids; the app sends them empty when it knows none.
    """
    if group not in GROUPS:
        raise StoreError(f"Unknown store category: {group}")
    return {
        "appid": APP_ID, "sort": "1", "page": str(page), "count": str(PAGE_SIZE),
        "category_name": f"{GROUPS[group]}_IDM", "type": _ANIMATION,
        "width": str(size), "height": str(size),
        "label": "ALL,", "filter_tags": "IDM_", "file_lang": "none,en",
    }


def build_request(params: dict[str, str], now: float | None = None,
                  random: str | None = None) -> tuple[str, str]:
    """URL and encrypted body of a signed store call."""
    timestamp = str(int(now if now is not None else time.time()))
    random = random or "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
    query = urllib.parse.urlencode({"sign": sign(params, random, timestamp),
                                    "timestamp": timestamp, "random": random})
    return f"{STORE_URL}?{query}", encrypt(sorted_query(params))


def parse_listing(body: str, size: int) -> dict:
    """Decrypt a listing reply into items for this screen and the paging."""
    try:
        reply = json.loads(decrypt(body))
    except (ValueError, KeyError) as err:
        raise StoreError(f"Unreadable store reply: {err}") from err
    data = reply.get("data")
    if not isinstance(data, dict):
        raise StoreError(reply.get("msg") or "The store returned no data")
    items = []
    for record in data.get("records") or []:
        if not isinstance(record, dict):
            continue
        url = record.get("file_path") or ""
        if not url.startswith("https://") and not url.startswith("http://"):
            continue
        try:
            width, height = int(record.get("width") or size), int(record.get("height") or size)
        except ValueError:
            continue
        if (width, height) != (size, size):
            continue
        tags = [str(tag) for tag in record.get("search_tags") or [] if str(tag).strip()]
        items.append(StoreItem(
            url, item_name(record, tags), width, height, str(record.get("format") or "gif").lower(),
            tags, str(record.get("uploadtime") or "")[:10],
        ))
    return {
        "items": items,
        "page": int(data.get("pageNo") or 1),
        "total_pages": int(data.get("totalPage") or 0),
        "total": int(data.get("totalCount") or 0),
    }


def item_name(record: dict, tags: list[str]) -> str:
    """Records have no title (their URLs end in a random id): search tags when
    there are some, else the store's file number."""
    if tags:
        return " ".join(tags[:3])
    if record.get("file_id"):
        return f"store_{record['file_id']}"
    path = urllib.parse.unquote(urllib.parse.urlparse(record.get("file_path") or "").path)
    return os.path.splitext(os.path.basename(path))[0] or "store"


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def decode_file(body: str) -> bytes:
    """The GIF inside a store file (``DecryptHelper.getDecryptedFile``)."""
    if len(body) <= 64:
        raise StoreError("Store file too short")
    inner = urllib.parse.unquote_plus(body[32:-32])
    try:
        data = base64.b64decode("".join(inner[::-1].split()))
    except ValueError as err:
        raise StoreError(f"Unreadable store file: {err}") from err
    if not data.startswith((b"GIF87a", b"GIF89a")):
        raise StoreError("The store file is not a GIF")
    return data


def device_ready(data: bytes, size: int) -> bool:
    """Sent as is: a GIF of the screen's size, whatever its palettes.

    The official app sends the decoded file straight to the device
    (``GifAgreement.sendImageData`` on ``CloudMaterial.getData``). Its files
    only store what changes between frames, so re-encoding them as full
    frames makes them 20 to 30 times bigger (15 KB became 384 KB, about
    18 minutes over the Pi's Bluetooth instead of under one).
    """
    with Image.open(io.BytesIO(data)) as image:
        return image.format == "GIF" and image.size == (size, size)


def describe(data: bytes, size: int) -> dict:
    """What the panel shows about a store GIF before it is imported."""
    with Image.open(io.BytesIO(data)) as image:
        durations = [int(frame.info.get("duration") or 100) for frame in ImageSequence.Iterator(image)]
        width, height = image.size
    layout = gif_layout(data)
    return {
        "size_bytes": len(data),
        "frames": len(durations),
        "duration_ms": sum(durations),
        "width": width,
        "height": height,
        "local_palettes": layout["local_palettes"],
        "device_ready": device_ready(data, size),
    }


def looping(data: bytes) -> bytes:
    """The GIF set to loop forever, as the panel plays it.

    Many store files are GIF87a without the NETSCAPE extension, so browsers
    (the thumbnails, the gallery) played them once and stopped.
    """
    if len(data) < 13 or b"NETSCAPE2.0" in data[:4096]:
        return data
    packed = data[10]
    start = 13 + ((2 << (packed & 7)) * 3 if packed & 0x80 else 0)
    return b"GIF89a" + data[6:start] + b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00" + data[start:]


def device_gif(data: bytes, size: int) -> bytes:
    """The store GIF itself (set to loop) at the screen's size, else resized and re-encoded."""
    if device_ready(data, size):
        return looping(data)
    frames, durations = [], []
    with Image.open(io.BytesIO(data)) as image:
        for frame in ImageSequence.Iterator(image):
            still = _flatten(frame)
            if still.size != (size, size):
                still = _resize(still, (size, size))
            frames.append(still)
            durations.append(max(20, int(frame.info.get("duration") or 100)))
    return frames_to_gif(frames, durations, colors=256)
