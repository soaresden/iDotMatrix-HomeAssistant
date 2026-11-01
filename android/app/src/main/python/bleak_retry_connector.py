"""bleak_retry_connector as the Studio's client uses it: a connection tried a few times."""
from __future__ import annotations

import asyncio

from bleak import BleakClient
from bleak.exc import BleakError

BleakClientWithServiceCache = BleakClient


async def establish_connection(client_class, device, name, disconnected_callback=None, max_attempts: int = 3,
                               **_kwargs):
    # Each attempt already waits up to 20 s for the display (Frame.kt): two are enough.
    attempts = max(1, min(2, max_attempts))
    for attempt in range(attempts):
        client = client_class(device, disconnected_callback=disconnected_callback)
        try:
            await client.connect()
            return client
        except BleakError:
            if attempt + 1 == attempts:
                raise
            await asyncio.sleep(1.0)
    raise BleakError(f"{name}: connection failed")
