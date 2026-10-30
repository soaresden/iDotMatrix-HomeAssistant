import asyncio
from contextvars import ContextVar, Token
from bleak import BleakClient, BleakScanner, AdvertisementData
from bleak.exc import BleakError, BleakCharacteristicNotFoundError
from .const import UUID_READ_DATA, UUID_WRITE_DATA, BLUETOOTH_DEVICE_NAME
import logging
from time import monotonic
from typing import List, Optional


class MissingWriteCharacteristicError(BleakError):
    """The connected device has not exposed the iDotMatrix write endpoint."""


class TransferRejectedError(Exception):
    """The device refused a file transfer (e.g. no storage left for it)."""


class _FastTransferFailed(Exception):
    """A transfer sent with unacknowledged writes lost data on the way."""


# Verdicts the device sends on the notify characteristic after each 4 KB
# transfer packet: [length, 0, type, 0, status] (Android app, GifAgreement).
TRANSFER_INVALID = 0
TRANSFER_NEXT = 1
TRANSFER_NO_SPACE = 2
TRANSFER_DONE = 3


# The manager of the display a coordinator is driving, set for the duration
# of its device calls so library modules built without one reach that display.
_current: ContextVar["ConnectionManager | None"] = ContextVar("idotmatrix_connection", default=None)


class ConnectionRegistry(type):
    """One manager per display address.

    ``ConnectionManager()`` is the manager bound to the running device call,
    or else the first one, as when the library only drove a single display.
    """
    logging = logging.getLogger(__name__)
    _instances: dict = {}  # address (None while unbound) -> manager

    def __call__(cls) -> "ConnectionManager":
        current = _current.get()
        if current is not None:
            return current
        if not cls._instances:
            cls._instances[None] = super().__call__()
        return next(iter(cls._instances.values()))

    def for_address(cls, address: str | None) -> "ConnectionManager":
        """The manager of one display, adopting a still unbound one."""
        if not address:
            return cls()
        manager = cls._instances.get(address)
        if manager is None:
            manager = cls._instances.pop(None, None) or super().__call__()
            manager.address = address
            cls._instances[address] = manager
        return manager

    def bind(cls, manager: "ConnectionManager") -> Token:
        """Route ``ConnectionManager()`` to this manager in the current context."""
        return _current.set(manager)


class ConnectionManager(metaclass=ConnectionRegistry):
    logging = logging.getLogger(__name__)
    # Called with (packets sent, total packets, address) during file
    # transfers to any display.
    transfer_listener = None
    # Called with (address, label, report) after each file transfer, done or
    # failed: packets, bytes, seconds, and per attempt the write mode and the
    # [write, wait for the device] seconds of each packet.
    transfer_log = None

    def __init__(self) -> None:
        self.address: Optional[str] = None
        self.client: Optional[BleakClient] = None
        self.hass = None
        self._debug_versions: str | None = None
        self._write_sequence = 0
        # Measured time per 4 KB transfer packet, to estimate upload times.
        self.seconds_per_packet: float | None = None
        # What the transfer in progress is (a gallery file, "live"...), for progress events.
        self.transfer_label: str | None = None
        # Set to stop the transfer in progress before its next packet (panel « File »).
        self.abort_requested = False
        # File transfers use unacknowledged writes (see send_transfer).
        self.fast_transfers = True

    def set_hass(self, hass):
        """Set Home Assistant instance for proxy support."""
        self.hass = hass

    async def _debug_environment(self):
        """Cache package metadata off the event loop for debug captures."""
        if not self.logging.isEnabledFor(logging.DEBUG):
            return

        def versions():
            from importlib.metadata import PackageNotFoundError, version
            result = []
            for package in ("homeassistant", "bleak", "bleak-retry-connector", "habluetooth", "bleak-esphome"):
                try:
                    result.append(f"{package}={version(package)}")
                except PackageNotFoundError:
                    result.append(f"{package}=not-installed")
            return ", ".join(result)

        try:
            if self._debug_versions is None:
                self._debug_versions = await asyncio.to_thread(versions)
            self.logging.debug("BLE environment: %s", self._debug_versions)
        except Exception:
            self.logging.debug("Could not collect BLE dependency versions", exc_info=True)

    def _debug_device(self, device):
        """Record selected device/advertisement routing without raw BLE data."""
        if not self.logging.isEnabledFor(logging.DEBUG):
            return
        try:
            details = getattr(device, "details", {})
            if not isinstance(details, dict):
                details = {}
            source, rssi = None, None
            if self.hass:
                from homeassistant.components import bluetooth
                lookup = getattr(bluetooth, "async_last_service_info", None)
                info = lookup(self.hass, self.address, connectable=True) if lookup else None
                if info:
                    source, rssi = info.source, info.rssi
            self.logging.debug(
                "BLE device address=%s name=%s selected_source=%s bluez_path=%s "
                "last_advertisement_source=%s rssi=%s",
                device.address, device.name, details.get("source"), details.get("path"), source, rssi,
            )
        except Exception:
            self.logging.debug("BLE device routing details unavailable for %s", self.address, exc_info=True)

    def _debug_client(self, phase, client=None, *, include_services=False):
        """Keep optional backend diagnostics from affecting connectivity."""
        if not self.logging.isEnabledFor(logging.DEBUG):
            return
        client = client if client is not None else self.client
        if client is None:
            self.logging.debug("BLE %s address=%s client=none", phase, self.address)
            return
        values = {}
        for attr in ("is_connected", "backend_id", "mtu_size"):
            try:
                values[attr] = getattr(client, attr, "unavailable")
            except Exception:
                values[attr] = "unavailable"
        self.logging.debug(
            "BLE %s address=%s client=%s.%s connected=%s backend=%s mtu=%s",
            phase, self.address, type(client).__module__, type(client).__name__,
            values["is_connected"], values["backend_id"], values["mtu_size"],
        )
        if not include_services:
            return
        try:
            services = client.services
            self.logging.debug(
                "BLE GATT address=%s services=%d characteristics=%d write_uuid=%s found=%s",
                self.address, len(services.services), len(services.characteristics),
                UUID_WRITE_DATA, services.get_characteristic(UUID_WRITE_DATA) is not None,
            )
            for service in services:
                self.logging.debug("BLE service address=%s uuid=%s handle=%s", self.address, service.uuid, service.handle)
                for char in service.characteristics:
                    self.logging.debug(
                        "BLE characteristic address=%s service=%s uuid=%s handle=%s properties=%s",
                        self.address, service.uuid, char.uuid, char.handle, char.properties,
                    )
        except Exception:
            self.logging.debug("BLE GATT details unavailable for %s", self.address, exc_info=True)

    def _on_disconnected(self, client):
        """Log asynchronous link loss as well as requested disconnects."""
        self._debug_client("disconnect callback", client)

    @staticmethod
    async def scan() -> List[tuple[str, str]]:
        # This basic scan might not find proxy devices if not integrated with HA scanning
        # But we primarily rely on HA config flow now.
        logging.info("scanning for iDotMatrix bluetooth devices...")
        devices = await BleakScanner.discover(return_adv=True)
        filtered_devices: List[tuple[str, str]] = []
        for key, (device, adv) in devices.items():
            if (
                isinstance(adv, AdvertisementData)
                and adv.local_name
                and str(adv.local_name).startswith(BLUETOOTH_DEVICE_NAME)
            ):
                logging.info(f"found device {key} with name {adv.local_name}")
                filtered_devices.append((device.address, adv.local_name))
        return filtered_devices

    STANDALONE_SCAN_TIMEOUT = 10.0

    @staticmethod
    async def find_device(address: str | None = None, timeout: float | None = None):
        """Look a display up with this computer's own adapter, without Home
        Assistant: by address, or else the first one advertising an iDotMatrix
        name (IDM-...). None when nothing answers within the timeout."""
        timeout = ConnectionManager.STANDALONE_SCAN_TIMEOUT if timeout is None else timeout
        if address:
            return await BleakScanner.find_device_by_address(address, timeout=timeout)
        return await BleakScanner.find_device_by_filter(
            lambda device, adv: str(adv.local_name or device.name or "").startswith(BLUETOOTH_DEVICE_NAME),
            timeout=timeout,
        )

    async def connectByAddress(self, address: str) -> None:
        self.address = address
        await self.connect()

    async def connectBySearch(self) -> None:
        devices = await self.scan()
        if devices:
            # connect to first device
            self.address = devices[0]
            await self.connect()
        else:
            self.logging.error("no target devices found.")

    async def connect(self, *, use_services_cache: bool = True) -> None:
        """Connect and validate GATT services, rediscovering once if needed."""
        if not self.address:
            raise ConnectionError("iDotMatrix device address is not set")

        from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

        await self._debug_environment()
        started = monotonic()
        attempts = 2 if use_services_cache else 1
        for attempt in range(attempts):
            cache_enabled = use_services_cache and attempt == 0
            self.logging.debug(
                "BLE connect address=%s attempt=%d/%d service_cache=%s reuse_connected=%s",
                self.address, attempt + 1, attempts, cache_enabled,
                bool(self.client and self.client.is_connected),
            )
            try:
                if not (self.client and self.client.is_connected):
                    device = None
                    if self.hass:
                        from homeassistant.components import bluetooth

                        # Wait for local/proxy advertisements, including after
                        # clearing a stale service cache.
                        for i in range(15):
                            device = bluetooth.async_ble_device_from_address(
                                self.hass, self.address, connectable=True
                            )
                            if device:
                                self.logging.debug("BLE advertisement available address=%s poll=%d/15", self.address, i + 1)
                                break
                            if i == 0:
                                self.logging.debug("BLE waiting for connectable advertisement address=%s", self.address)
                            if i < 14:
                                await asyncio.sleep(1.0)
                    else:
                        device = await self.find_device(self.address)

                    if not device:
                        raise ConnectionError(
                            f"Device {self.address} unavailable in Home Assistant Bluetooth mesh. "
                            "Ensure it is powered and within range of an adapter or proxy."
                            if self.hass else
                            f"Device {self.address} not found by this computer's Bluetooth adapter. "
                            "Ensure it is powered, in range and not connected to another controller "
                            "(Home Assistant, the phone app)."
                        )
                    self.logging.info("Connecting to %s (%s)", device.name, device.address)
                    self._debug_device(device)
                    self.client = await establish_connection(
                        BleakClientWithServiceCache, device, self.address,
                        max_attempts=3,
                        use_services_cache=cache_enabled,
                        disconnected_callback=self._on_disconnected,
                    )
                    self._debug_client("connection established", include_services=True)

                # is_connected alone does not prove the device is writable.
                self._write_characteristic()
                await self._acquire_mtu()
            except MissingWriteCharacteristicError as err:
                self.logging.debug("BLE service validation failed address=%s attempt=%d", self.address, attempt + 1, exc_info=True)
                if attempt + 1 == attempts:
                    self.logging.error("iDotMatrix GATT discovery failed: %s", err)
                    await self._discard_client()
                    raise
                self.logging.warning(
                    "%s; clearing the GATT cache and retrying discovery once", err,
                )
                await self._discard_client(clear_cache=True)
            except Exception as err:
                self.logging.debug("BLE connect failed address=%s attempt=%d elapsed=%.3fs", self.address, attempt + 1, monotonic() - started, exc_info=True)
                self.logging.error("Failed to connect to %s: %s", self.address, err)
                await self._discard_client()
                raise
            else:
                self.logging.info("Connected to %s with iDotMatrix write characteristic", self.address)
                self.logging.debug("BLE connection ready address=%s attempt=%d elapsed=%.3fs", self.address, attempt + 1, monotonic() - started)
                return

    async def _acquire_mtu(self) -> None:
        """Ask BlueZ for the negotiated MTU (best effort).

        BlueZ reports the default 23-byte MTU until asked, so 4 KB packets
        went out as ~205 writes of 20 bytes: 4.6 s per packet instead of
        about 0.6 s with 509-byte writes. Proxies and other backends have no
        such call and keep their own size.
        """
        acquire = getattr(getattr(self.client, "_backend", None), "_acquire_mtu", None)
        if acquire is None:
            return
        before = self._write_size()
        try:
            await acquire()
        except Exception as err:  # noqa: BLE001 - the transfer still works with small writes
            self.logging.debug("BLE MTU request failed address=%s: %s", self.address, err)
            return
        self.logging.debug("BLE write size address=%s before=%s after=%s", self.address, before, self._write_size())

    def _write_size(self) -> int | None:
        try:
            return min(self._write_characteristic().max_write_without_response_size, self.BLE_WRITE_SIZE)
        except Exception:  # noqa: BLE001 - only for reports
            return None

    def _write_characteristic(self):
        """Resolve the required endpoint and explain incomplete discovery."""
        if not (self.client and self.client.is_connected):
            raise ConnectionError("iDotMatrix is not connected")
        try:
            services = self.client.services
        except BleakError as err:
            raise MissingWriteCharacteristicError(
                f"GATT services are unresolved for {self.address}; "
                f"required write characteristic {UUID_WRITE_DATA}: {err}"
            ) from err
        characteristic = services.get_characteristic(UUID_WRITE_DATA)
        if characteristic is None:
            service_uuids = ", ".join(service.uuid for service in services) or "none"
            char_uuids = ", ".join(char.uuid for char in services.characteristics.values()) or "none"
            raise MissingWriteCharacteristicError(
                f"Device {self.address} is missing required iDotMatrix write characteristic "
                f"{UUID_WRITE_DATA}. Discovered services: {service_uuids}; "
                f"characteristics: {char_uuids}. If fresh discovery still fails, check "
                "the device address, model/firmware compatibility and Bluetooth adapter/proxy."
            )
        return characteristic

    async def disconnect(self) -> None:
        self._debug_client("disconnect requested")
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            self.logging.info(f"disconnected from {self.address}")
        self.client = None
        self.logging.debug("BLE disconnect complete address=%s", self.address)

    # Match the Android app's BLE write size (MTU 517 - ATT overhead = 509)
    BLE_WRITE_SIZE = 509
    WRITE_PAUSE_S = 0.02  # after each write without response of BLE_WRITE_SIZE bytes
    # The writes without response of one packet are all handed to the
    # Bluetooth stack at once (in order) instead of one after the other: each
    # write otherwise costs ~50 ms on a Pi whatever the pause or connection
    # interval. Measured on 2026-10-29: 734 KB in 56 s instead of 107-116 s,
    # no packet lost. Settable at run time (idotmatrix/studio/write_pause).
    WRITE_BURST = True

    # Default to acknowledged writes: through an ESPHome BLE proxy,
    # unacknowledged Write Commands are silently dropped under buffer
    # pressure (observed as e.g. Clock.setMode losing a style change and
    # the panel staying on the previous face).
    async def send(self, data, response=True):
        self._write_sequence += 1
        write_id = self._write_sequence
        if self.client and self.client.is_connected:
            progress = {"writes": 0}
            try:
                return await self._write_chunks(data, response, progress, write_id=write_id)
            except Exception as err:
                self.logging.debug(
                    "BLE write failed address=%s write_id=%d bytes=%d response=%s completed_chunks=%d",
                    self.address, write_id, len(data), response, progress["writes"], exc_info=True,
                )
                self._debug_client("write failure", include_services=True)
                # Retry once, but ONLY if nothing went out yet: resending
                # after a partial write would duplicate bytes and corrupt
                # the file the device is assembling. This covers the
                # reconnect race where a write is attempted before service
                # discovery resolves ("Characteristic ... was not found")
                # and stale connections discovered on the first write.
                if progress["writes"]:
                    self.logging.debug("BLE write not retried address=%s write_id=%d: partial transfer", self.address, write_id)
                    raise
                self.logging.warning(
                    "BLE write failed before any data was sent (%s); "
                    "reconnecting and retrying once", err,
                )
                await self._force_reconnect(clear_cache=isinstance(
                    err, (MissingWriteCharacteristicError, BleakCharacteristicNotFoundError)
                ))
                if not (self.client and self.client.is_connected):
                    raise
                return await self._write_chunks(data, response, {"writes": 0}, write_id=write_id, attempt=2)

        self.logging.debug("BLE write rejected address=%s write_id=%d: not connected", self.address, write_id)
        raise ConnectionError("iDotMatrix is not connected")

    # Pause before resending a whole file with acknowledged writes, so the
    # device drops the packet it was still assembling.
    TRANSFER_RESTART_DELAY = 1.0
    # Fast attempts of a file before it falls back to acknowledged writes:
    # a packet left unanswered is usually a one-off, and acknowledged writes
    # are many times slower (about 10 s per 4 KB packet against 0.6 s).
    FAST_ATTEMPTS = 2

    async def send_transfer(self, packets, timeout: float = 5.0) -> bool:
        """Send file transfer packets, waiting for the device after each one.

        Like the Android app, the next 4 KB packet only goes out once the
        device asks for it: it needs that time to store the previous one,
        and packets streamed back-to-back are silently dropped (the GIF
        then never shows). Raises TransferRejectedError when the device
        reports no space left or an invalid transfer. Firmware that never
        answers gets the remaining packets unpaced, as before.

        Also like the app, the 509-byte writes inside a packet do not wait
        for a write response, which makes uploads many times faster. A link
        that loses some of them (an ESPHome proxy under load) shows as a
        packet the device never confirms: the file is sent again from the
        start, fast once more, then with acknowledged writes. The next file
        starts fast again.
        """
        started = monotonic()
        report = {"packets": len(packets), "bytes": sum(len(p) for p in packets), "attempts": [],
                  "write_size": self._write_size(), "write_pause_s": type(self).WRITE_PAUSE_S,
                  "write_burst": type(self).WRITE_BURST}
        try:
            if self.fast_transfers and "write-without-response" in self._write_characteristic().properties:
                for number in range(1, self.FAST_ATTEMPTS + 1):
                    attempt = {"mode": "fast", "packets": []}
                    report["attempts"].append(attempt)
                    try:
                        return await self._send_packets(packets, timeout, fast=True, attempt=attempt)
                    except _FastTransferFailed as err:
                        attempt["failed"] = str(err)
                        self.logging.warning(
                            "Fast transfer to %s failed (%s); resending %s", self.address, err,
                            "fast again" if number < self.FAST_ATTEMPTS else "with acknowledged writes",
                        )
                        await asyncio.sleep(self.TRANSFER_RESTART_DELAY)
            attempt = {"mode": "acknowledged", "packets": []}
            report["attempts"].append(attempt)
            return await self._send_packets(packets, timeout, fast=False, attempt=attempt)
        except BaseException as err:
            report["error"] = str(err) or type(err).__name__
            raise
        finally:
            report["seconds"] = round(monotonic() - started, 3)
            hook = type(self).transfer_log
            if hook:
                try:
                    hook(self.address, self.transfer_label, report)
                except Exception:  # noqa: BLE001 - logging must not break a transfer
                    self.logging.debug("Transfer log hook failed", exc_info=True)

    async def _send_packets(self, packets, timeout: float, *, fast: bool, attempt: dict | None = None) -> bool:
        replies: asyncio.Queue[bytes] = asyncio.Queue()

        def on_notify(_sender, data):
            data = bytes(data)
            if len(data) >= 5 and data[1] == 0 and data[3] == 0:
                replies.put_nowait(data)

        await self.client.start_notify(UUID_READ_DATA, on_notify)
        started = monotonic()
        try:
            acknowledged = True
            for index, packet in enumerate(packets):
                if self.abort_requested:
                    raise TransferRejectedError(f"Transfer cancelled after packet {index}/{len(packets)}")
                while not replies.empty():
                    replies.get_nowait()
                sent_at = monotonic()
                timing = [None, None]  # seconds writing, seconds waiting for the device
                if attempt is not None:
                    attempt["packets"].append(timing)
                try:
                    await self.send(data=packet, response=not fast)
                except BleakError as err:
                    if fast:
                        raise _FastTransferFailed(f"write failed at packet {index + 1}: {err}") from err
                    raise
                # Read on the class: a plain function stored there would
                # otherwise be bound to this manager.
                listener = type(self).transfer_listener
                if listener:
                    listener(index + 1, len(packets), self.address)
                written_at = monotonic()
                timing[0] = round(written_at - sent_at, 3)
                if not acknowledged:
                    continue
                try:
                    status = (await asyncio.wait_for(replies.get(), timeout))[4]
                    timing[1] = round(monotonic() - written_at, 3)
                except asyncio.TimeoutError:
                    if fast:
                        raise _FastTransferFailed(f"no answer to packet {index + 1}/{len(packets)}") from None
                    if index:
                        raise TransferRejectedError(
                            f"Device stopped answering after packet {index + 1}/{len(packets)}"
                        ) from None
                    self.logging.debug("BLE transfer address=%s: device sends no acknowledgements", self.address)
                    acknowledged = False
                    continue
                self.logging.debug(
                    "BLE transfer address=%s packet=%d/%d status=%d",
                    self.address, index + 1, len(packets), status,
                )
                if status == TRANSFER_NO_SPACE:
                    raise TransferRejectedError("Not enough space on the device for this file")
                if status == TRANSFER_INVALID:
                    if fast:
                        raise _FastTransferFailed(f"packet {index + 1} arrived damaged")
                    raise TransferRejectedError("The device rejected the transfer as invalid")
                if status == TRANSFER_DONE:
                    # Learnt from real files (a first image alone says little).
                    if index + 1 >= 8:
                        measured = (monotonic() - started) / (index + 1)
                        old = self.seconds_per_packet
                        self.seconds_per_packet = measured if old is None else 0.7 * old + 0.3 * measured
                    return True
            if acknowledged:
                if fast:
                    raise _FastTransferFailed("the end of the file was not confirmed")
                raise TransferRejectedError("The device did not confirm the end of the transfer")
            return True
        finally:
            try:
                await self.client.stop_notify(UUID_READ_DATA)
            except Exception:  # noqa: BLE001 - the link may already be gone
                self.logging.debug("BLE stop_notify failed address=%s", self.address, exc_info=True)

    async def _write_chunks(self, data, response, progress, *, write_id=0, attempt=1):
        # Cap chunk size to real BLE MTU regardless of proxy-reported size.
        # ESPHome BLE proxies report a large WiFi-based MTU, but the actual
        # BLE radio to the device uses ~509-byte packets at ~25ms intervals.
        characteristic = self._write_characteristic()
        reported = characteristic.max_write_without_response_size
        chunk_size = min(reported, self.BLE_WRITE_SIZE)
        chunk_count = (len(data) + chunk_size - 1) // chunk_size
        started = monotonic()
        self.logging.debug(
            "BLE write start address=%s write_id=%d attempt=%d bytes=%d response=%s "
            "characteristic=%s handle=%s reported_write_size=%d chunk_size=%d chunks=%d",
            self.address, write_id, attempt, len(data), response, characteristic.uuid,
            characteristic.handle, reported, chunk_size, chunk_count,
        )
        if not response and type(self).WRITE_BURST:
            await self._write_burst(data, chunk_size, progress)
            self.logging.debug(
                "BLE burst write complete address=%s write_id=%d bytes=%d chunks=%d elapsed=%.3fs",
                self.address, write_id, len(data), progress["writes"], monotonic() - started,
            )
            return True
        for i in range(0, len(data), chunk_size):
            try:
                await self.client.write_gatt_char(UUID_WRITE_DATA, data[i:i+chunk_size], response=response)
            except (Exception, asyncio.CancelledError):
                self.logging.debug(
                    "BLE chunk failed address=%s write_id=%d attempt=%d chunk=%d/%d "
                    "offset=%d size=%d completed_chunks=%d elapsed=%.3fs",
                    self.address, write_id, attempt, progress["writes"] + 1, chunk_count,
                    i, min(chunk_size, len(data) - i), progress["writes"], monotonic() - started,
                    exc_info=True,
                )
                raise
            progress["writes"] += 1
            # Pace writes to match the BLE connection interval (~25ms).
            # The Android app's BLE stack provides this pacing via L2CAP
            # flow control; through an ESPHome proxy we must add it manually
            # to prevent flooding the proxy's BLE transmit buffer. Writes
            # without response go out every 20 ms, the app's own delay
            # (GifAgreement.curTime), for its 509-byte writes: the same byte
            # rate is kept when the link only takes 20-byte writes (a Pi's
            # BlueZ), which otherwise spent 4.6 s per 4 KB packet pausing.
            await asyncio.sleep(0.025 if response else self.WRITE_PAUSE_S * chunk_size / self.BLE_WRITE_SIZE)

        self.logging.debug(
            "BLE write complete address=%s write_id=%d attempt=%d bytes=%d chunks=%d elapsed=%.3fs",
            self.address, write_id, attempt, len(data), progress["writes"], monotonic() - started,
        )
        return True

    async def _write_burst(self, data, chunk_size, progress):
        """Hand every chunk to the stack at once: each write is started in order
        before any is awaited, so the stack can send several per connection
        event instead of one (about 50 ms each on a Pi)."""
        writes = [
            asyncio.ensure_future(self.client.write_gatt_char(UUID_WRITE_DATA, data[i:i + chunk_size], response=False))
            for i in range(0, len(data), chunk_size)
        ]
        try:
            for write in writes:
                await write
                progress["writes"] += 1
        except (Exception, asyncio.CancelledError):
            for write in writes:
                write.cancel()
            raise

    async def _discard_client(self, *, clear_cache: bool = False):
        """Release a failed client, invalidating backend/proxy services if needed."""
        client, self.client = self.client, None
        if client is None:
            return
        self._debug_client("discarding failed client", client)
        self.logging.debug("BLE recovery address=%s clear_cache=%s", self.address, clear_cache)
        try:
            if clear_cache:
                try:
                    cleared = await client.clear_cache()
                    self.logging.debug("BLE cache clear address=%s success=%s", self.address, cleared)
                    if not cleared:
                        self.logging.warning("GATT cache could not be cleared for %s", self.address)
                except Exception as err:
                    self.logging.debug("BLE cache clear failed address=%s", self.address, exc_info=True)
                    self.logging.warning("Could not clear GATT cache for %s: %s", self.address, err)
        finally:
            # Cache invalidation can fail or be cancelled; still release the link.
            try:
                await client.disconnect()
                self.logging.debug("BLE failed client released address=%s", self.address)
            except Exception as err:
                self.logging.debug("Failed client disconnect for %s: %s", self.address, err)

    async def _force_reconnect(self, *, clear_cache: bool = False):
        """Retry a failed write using fresh discovery, never a cached table."""
        self.logging.debug("BLE reconnect requested address=%s clear_cache=%s service_cache=False", self.address, clear_cache)
        await self._discard_client(clear_cache=clear_cache)
        await self.connect(use_services_cache=False)

    async def read(self) -> bytes:
        if self.client and self.client.is_connected:
            self.logging.debug("BLE read address=%s characteristic=%s", self.address, UUID_READ_DATA)
            data = await self.client.read_gatt_char(UUID_READ_DATA)
            self.logging.debug("BLE read complete address=%s bytes=%d", self.address, len(data))
            self.logging.info("data received")
            return data
