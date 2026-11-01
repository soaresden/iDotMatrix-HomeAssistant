"""The parts of the bleak library the Studio's client uses (client/connectionManager.py),
over Android's Bluetooth: Ble.kt, called from Python threads (each call blocks).

Writes are serialized in the order they were started (the client starts a packet's
writes all at once); the display's answers are read by a small loop while notifications
are on.
"""
from __future__ import annotations

import asyncio
import json

from java import jclass

from .exc import BleakCharacteristicNotFoundError, BleakError

__all__ = ["AdvertisementData", "BLEDevice", "BleakClient", "BleakError", "BleakScanner"]

_ble = jclass("org.idotmatrix.pixelmeteo.Ble")

WRITE_UUID = "0000fa02-0000-1000-8000-00805f9b34fb"
NOTIFY_UUID = "0000fa03-0000-1000-8000-00805f9b34fb"


def _message(err: Exception) -> str:
    getter = getattr(err, "getMessage", None)
    try:
        return str(getter()) if getter else str(err)
    except Exception:  # noqa: BLE001
        return str(err)


async def _call(fn, *args):
    """A Ble.kt call in a thread; its Java errors as BleakError."""
    try:
        return await asyncio.to_thread(fn, *args)
    except BleakError:
        raise
    except Exception as err:  # noqa: BLE001 - FrameError and the like
        raise BleakError(_message(err)) from None


class AdvertisementData:
    def __init__(self, local_name: str | None) -> None:
        self.local_name = local_name


class BLEDevice:
    def __init__(self, address: str, name: str | None = None) -> None:
        self.address = address
        self.name = name or address
        self.details: dict = {}

    def __repr__(self) -> str:
        return f"BLEDevice({self.address}, {self.name})"


class BleakGATTCharacteristic:
    def __init__(self, uuid: str, handle: int, properties: list[str], write_size: int) -> None:
        self.uuid = uuid
        self.handle = handle
        self.properties = properties
        self.max_write_without_response_size = write_size


class BleakGATTService:
    def __init__(self, uuid: str, characteristics: list[BleakGATTCharacteristic]) -> None:
        self.uuid = uuid
        self.handle = 0
        self.characteristics = characteristics


class BleakGATTServiceCollection:
    """The display's two characteristics, as Frame.kt found them."""

    def __init__(self, write_size: int) -> None:
        chars = [BleakGATTCharacteristic(WRITE_UUID, 1, ["write", "write-without-response"], write_size),
                 BleakGATTCharacteristic(NOTIFY_UUID, 2, ["notify"], write_size)]
        self.services = {0: BleakGATTService("000000fa-0000-1000-8000-00805f9b34fb", chars)}
        self.characteristics = {c.handle: c for c in chars}

    def get_characteristic(self, uuid):
        uuid = str(getattr(uuid, "uuid", uuid)).lower()
        return next((c for c in self.characteristics.values() if c.uuid == uuid), None)

    def __iter__(self):
        return iter(self.services.values())


class BleakClient:
    def __init__(self, address_or_ble_device, disconnected_callback=None, **_kwargs) -> None:
        self.address = getattr(address_or_ble_device, "address", address_or_ble_device)
        self._disconnected_callback = disconnected_callback
        self._services: BleakGATTServiceCollection | None = None
        self._writes = asyncio.Lock()
        self._notify: asyncio.Task | None = None
        self.mtu_size = 23
        self.backend_id = "android"

    @property
    def is_connected(self) -> bool:
        return bool(_ble.connected(self.address))

    @property
    def services(self) -> BleakGATTServiceCollection:
        if self._services is None:
            raise BleakError("Services not discovered")
        return self._services

    async def connect(self, **_kwargs) -> bool:
        size = int(await _call(_ble.connect, self.address))
        self.mtu_size = size + 3
        self._services = BleakGATTServiceCollection(size)
        return True

    async def disconnect(self) -> bool:
        await self.stop_notify(NOTIFY_UUID)
        await _call(_ble.disconnect, self.address)
        return True

    async def clear_cache(self) -> bool:
        await _call(_ble.forgetServices, self.address)
        return True

    async def write_gatt_char(self, char_specifier, data, response: bool = False) -> None:
        async with self._writes:  # in the order the writes were started
            await _call(_ble.write, self.address, bytes(data), bool(response))

    async def start_notify(self, char_specifier, callback, **_kwargs) -> None:
        await self.stop_notify(char_specifier)
        await _call(_ble.dropReplies, self.address)

        async def listen():
            while True:
                data = await _call(_ble.reply, self.address, 250)
                if data is not None:
                    callback(char_specifier, bytearray(bytes(data)))

        self._notify = asyncio.ensure_future(listen())

    async def stop_notify(self, char_specifier) -> None:
        task, self._notify = self._notify, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, BleakError):
                pass

    async def read_gatt_char(self, char_specifier) -> bytearray:
        raise BleakError("Lecture non prise en charge sur le téléphone")


class BleakScanner:
    @staticmethod
    async def _found(timeout: float) -> list[dict]:
        return json.loads(str(await _call(_ble.scan, float(timeout))))

    @staticmethod
    async def discover(timeout: float = 6.0, return_adv: bool = False, **_kwargs):
        found = await BleakScanner._found(timeout)
        if not return_adv:
            return [BLEDevice(d["address"], d["name"]) for d in found]
        return {d["address"]: (BLEDevice(d["address"], d["name"]), AdvertisementData(d["name"])) for d in found}

    @staticmethod
    async def find_device_by_address(address: str, timeout: float = 10.0, **_kwargs):
        # Android connects by address without seeing it first; a display that is off
        # or away is found out when connecting.
        return BLEDevice(address)

    @staticmethod
    async def find_device_by_filter(filterfunc, timeout: float = 10.0, **_kwargs):
        for d in await BleakScanner._found(timeout):
            device = BLEDevice(d["address"], d["name"])
            if filterfunc(device, AdvertisementData(d["name"])):
                return device
        return None
