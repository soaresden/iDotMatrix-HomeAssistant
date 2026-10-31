"""Exercise BLE discovery and retry behavior without contacting a device."""
import asyncio
import logging
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import homeassistant  # Initialize Home Assistant before BLE validation dependencies.
import bleak_retry_connector
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.service import BleakGATTService, BleakGATTServiceCollection
from bleak.exc import BleakError

from custom_components.idotmatrix.client.connectionManager import ConnectionManager
from custom_components.idotmatrix.client.const import UUID_READ_DATA, UUID_WRITE_DATA


def fake_client(*, has_write=True, write_size=509, properties=("write", "write-without-response")):
    """Use a real Bleak service collection so missing UUIDs return None."""
    services = BleakGATTServiceCollection()
    service = BleakGATTService(None, 1, "0000fa00-0000-1000-8000-00805f9b34fb")
    services.add_service(service)
    for handle, uuid in enumerate((UUID_READ_DATA, UUID_WRITE_DATA) if has_write else (UUID_READ_DATA,), 2):
        services.add_characteristic(BleakGATTCharacteristic(
            None, handle, uuid, list(properties), lambda: write_size, service,
        ))
    client = SimpleNamespace(
        is_connected=True, services=services, clear_cache=AsyncMock(return_value=True),
        write_gatt_char=AsyncMock(),
    )
    client.disconnect = AsyncMock(side_effect=lambda: setattr(client, "is_connected", False))
    return client


@pytest.fixture
def manager(monkeypatch):
    # Avoid the library singleton so tests cannot affect another coordinator.
    manager = object.__new__(ConnectionManager)
    ConnectionManager.__init__(manager)
    manager.address = "AA:BB:CC:DD:EE:FF"
    manager.hass = Mock()
    device = SimpleNamespace(address=manager.address, name="IDM-Test")
    monkeypatch.setitem(sys.modules, "homeassistant.components.bluetooth", SimpleNamespace(
        async_ble_device_from_address=Mock(return_value=device),
    ))
    monkeypatch.setattr(bleak_retry_connector, "establish_connection", AsyncMock())
    manager.TRANSFER_RESTART_DELAY = 0
    return manager


@pytest.mark.asyncio
async def test_missing_write_characteristic_clears_cache_and_retries_send(manager):
    stale, fresh = fake_client(has_write=False), fake_client()
    manager.client = stale
    bleak_retry_connector.establish_connection.return_value = fresh
    assert await manager.send(b"command") is True
    stale.write_gatt_char.assert_not_awaited()
    stale.clear_cache.assert_awaited_once()
    stale.disconnect.assert_awaited_once()
    assert bleak_retry_connector.establish_connection.call_args.kwargs["use_services_cache"] is False
    fresh.write_gatt_char.assert_awaited_once()


@pytest.mark.asyncio
async def test_connect_validates_services_and_recovers_stale_cache(manager):
    stale, fresh = fake_client(has_write=False), fake_client()
    bleak_retry_connector.establish_connection.side_effect = [stale, fresh]
    await manager.connect()
    assert manager.client is fresh
    stale.clear_cache.assert_awaited_once()
    stale.disconnect.assert_awaited_once()
    calls = bleak_retry_connector.establish_connection.call_args_list
    assert [call.kwargs["use_services_cache"] for call in calls] == [True, False]
    assert all(call.args[0] is bleak_retry_connector.BleakClientWithServiceCache for call in calls)
    assert all(call.kwargs["disconnected_callback"] == manager._on_disconnected for call in calls)
    stale.write_gatt_char.assert_not_awaited()
    fresh.write_gatt_char.assert_not_awaited()


@pytest.mark.asyncio
async def test_connected_client_is_validated_before_reuse(manager):
    stale, fresh = fake_client(has_write=False), fake_client()
    manager.client = stale
    bleak_retry_connector.establish_connection.return_value = fresh
    await manager.connect()
    assert manager.client is fresh
    stale.clear_cache.assert_awaited_once()


@pytest.mark.asyncio
async def test_valid_connected_client_is_reused_without_discovery(manager):
    manager.client = fake_client()
    await manager.connect()
    bleak_retry_connector.establish_connection.assert_not_awaited()
    manager.client.clear_cache.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("cache_result", [False, BleakError("cache clear unsupported")])
async def test_cache_clear_failure_still_disconnects_and_rediscovers(manager, cache_result):
    stale, fresh = fake_client(has_write=False), fake_client()
    manager.client = stale
    if isinstance(cache_result, Exception):
        stale.clear_cache.side_effect = cache_result
    else:
        stale.clear_cache.return_value = cache_result
    bleak_retry_connector.establish_connection.return_value = fresh
    await manager.connect()
    assert manager.client is fresh
    stale.disconnect.assert_awaited_once()
    assert bleak_retry_connector.establish_connection.call_args.kwargs["use_services_cache"] is False


@pytest.mark.asyncio
async def test_cancelled_cache_clear_releases_failed_connection(manager):
    stale = fake_client(has_write=False)
    stale.clear_cache.side_effect = asyncio.CancelledError()
    manager.client = stale
    with pytest.raises(asyncio.CancelledError):
        await manager.connect()
    stale.disconnect.assert_awaited_once()
    assert manager.client is None
    bleak_retry_connector.establish_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_unresolved_services_trigger_fresh_discovery(manager):
    class UnresolvedClient:
        is_connected = True
        clear_cache = AsyncMock(return_value=True)
        disconnect = AsyncMock()

        @property
        def services(self):
            raise BleakError("Service Discovery has not been performed yet")

    manager.client = UnresolvedClient()
    fresh = fake_client()
    bleak_retry_connector.establish_connection.return_value = fresh
    await manager.connect()
    assert manager.client is fresh
    UnresolvedClient.clear_cache.assert_awaited_once()
    UnresolvedClient.disconnect.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["connect", "send"])
async def test_persistently_missing_characteristic_is_diagnostic_and_bounded(manager, operation):
    stale, incompatible = fake_client(has_write=False), fake_client(has_write=False)
    if operation == "connect":
        bleak_retry_connector.establish_connection.side_effect = [stale, incompatible]
    else:
        manager.client = stale
        bleak_retry_connector.establish_connection.return_value = incompatible
    with pytest.raises(BleakError, match=UUID_WRITE_DATA) as error:
        if operation == "connect":
            await manager.connect()
        else:
            await manager.send(b"command")
    assert UUID_READ_DATA in str(error.value)
    assert "firmware" in str(error.value)
    assert bleak_retry_connector.establish_connection.await_count == (2 if operation == "connect" else 1)
    assert manager.client is None
    incompatible.disconnect.assert_awaited_once()
    stale.write_gatt_char.assert_not_awaited()
    incompatible.write_gatt_char.assert_not_awaited()


@pytest.mark.asyncio
async def test_partial_transfer_is_never_replayed(manager, monkeypatch):
    manager.client = fake_client(write_size=3)
    manager.client.write_gatt_char.side_effect = [None, BleakError("write failed")]
    reconnect = AsyncMock()
    monkeypatch.setattr(manager, "_force_reconnect", reconnect)
    with pytest.raises(BleakError, match="write failed"):
        await manager.send(b"abcdefghi")
    assert manager.client.write_gatt_char.await_count == 2
    reconnect.assert_not_awaited()


@pytest.mark.asyncio
async def test_first_write_failure_reconnects_once_without_reusing_cache(manager):
    stale, fresh = fake_client(), fake_client()
    stale.write_gatt_char.side_effect = BleakError("link lost")
    manager.client = stale
    bleak_retry_connector.establish_connection.return_value = fresh
    assert await manager.send(b"command") is True
    stale.clear_cache.assert_not_awaited()
    stale.disconnect.assert_awaited_once()
    fresh.write_gatt_char.assert_awaited_once()
    assert bleak_retry_connector.establish_connection.await_count == 1
    assert bleak_retry_connector.establish_connection.call_args.kwargs["use_services_cache"] is False


@pytest.mark.asyncio
async def test_connection_failure_propagates_without_claiming_success(manager):
    bleak_retry_connector.establish_connection.side_effect = BleakError("out of connection slots")
    with pytest.raises(BleakError, match="out of connection slots"):
        await manager.connect()
    assert manager.client is None


@pytest.mark.asyncio
async def test_cancelled_write_does_not_reconnect(manager, monkeypatch):
    manager.client = fake_client()
    manager.client.write_gatt_char.side_effect = asyncio.CancelledError()
    reconnect = AsyncMock()
    monkeypatch.setattr(manager, "_force_reconnect", reconnect)
    with pytest.raises(asyncio.CancelledError):
        await manager.send(b"command")
    reconnect.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("response,reported_size", [(True, 1024), (False, 20)])
async def test_valid_transfer_keeps_chunk_limits_and_write_mode(manager, response, reported_size):
    manager.client = fake_client(write_size=reported_size)
    payload = bytes(range(256)) * 4
    assert await manager.send(payload, response=response)
    calls = manager.client.write_gatt_char.call_args_list
    assert b"".join(call.args[1] for call in calls) == payload
    assert all(len(call.args[1]) <= min(reported_size, 509) for call in calls)
    assert all(call.kwargs["response"] is response for call in calls)


@pytest.mark.asyncio
async def test_debug_logs_capture_recovery_and_progress_without_payloads(manager, caplog):
    caplog.set_level(logging.DEBUG, logger=manager.logging.name)
    device = SimpleNamespace(address=manager.address, name="IDM-Test", details={
        "source": "proxy-test", "path": "/org/bluez/hci0/dev_test",
        "manufacturer_data": "private-advertisement-content",
    })
    bluetooth = sys.modules["homeassistant.components.bluetooth"]
    bluetooth.async_ble_device_from_address.return_value = device
    bluetooth.async_last_service_info = Mock(return_value=SimpleNamespace(source="proxy-test", rssi=-64))
    stale, fresh = fake_client(has_write=False), fake_client(write_size=3)
    fresh.backend_id, fresh.mtu_size = "esphome", 512
    bleak_retry_connector.establish_connection.side_effect = [stale, fresh]
    await manager.connect()
    await manager.send(b"private-display-content")
    logs = caplog.text
    assert "homeassistant=" in logs and "bleak-retry-connector=" in logs
    assert "attempt=1/2 service_cache=True" in logs
    assert "attempt=2/2 service_cache=False" in logs
    assert "selected_source=proxy-test" in logs and "rssi=-64" in logs
    assert "backend=esphome mtu=512" in logs
    assert UUID_WRITE_DATA in logs and "properties=" in logs
    assert "BLE cache clear" in logs and "success=True" in logs
    assert "BLE write complete" in logs and "chunk_size=3" in logs
    assert "private-display-content" not in logs
    assert "private-advertisement-content" not in logs


@pytest.mark.asyncio
async def test_debug_write_failure_records_exact_progress_and_traceback(manager, caplog):
    caplog.set_level(logging.DEBUG, logger=manager.logging.name)
    manager.client = fake_client(write_size=3)
    manager.client.write_gatt_char.side_effect = [None, BleakError("radio failure")]
    with pytest.raises(BleakError, match="radio failure"):
        await manager.send(b"abcdefghi")
    assert "chunk=2/3 offset=3 size=3 completed_chunks=1" in caplog.text
    assert "partial transfer" in caplog.text
    assert any(record.exc_info for record in caplog.records if "BLE chunk failed" in record.message)
    assert "abcdefghi" not in caplog.text


@pytest.mark.asyncio
async def test_optional_debug_metadata_failure_does_not_break_connection(manager, caplog):
    class ClientWithUnavailableMetadata(SimpleNamespace):
        @property
        def backend_id(self):
            raise BleakError("backend unavailable")

        @property
        def mtu_size(self):
            raise BleakError("MTU unavailable")

    caplog.set_level(logging.DEBUG, logger=manager.logging.name)
    client = ClientWithUnavailableMetadata(**vars(fake_client()))
    bleak_retry_connector.establish_connection.return_value = client
    bluetooth = sys.modules["homeassistant.components.bluetooth"]
    bluetooth.async_last_service_info = Mock(side_effect=RuntimeError("routing info unavailable"))
    await manager.connect()
    assert await manager.send(b"command") is True
    assert "backend=unavailable mtu=unavailable" in caplog.text
    assert "routing details unavailable" in caplog.text


@pytest.mark.asyncio
async def test_optional_diagnostics_are_not_read_with_debug_disabled(manager, caplog):
    caplog.set_level(logging.INFO, logger=manager.logging.name)
    bluetooth = sys.modules["homeassistant.components.bluetooth"]
    bluetooth.async_last_service_info = Mock(side_effect=AssertionError("debug lookup should be skipped"))
    bleak_retry_connector.establish_connection.return_value = fake_client()
    await manager.connect()
    bluetooth.async_last_service_info.assert_not_called()
    assert manager._debug_versions is None
    assert not any(record.levelno == logging.DEBUG for record in caplog.records)


def test_disconnect_callback_logs_link_state(manager, caplog):
    caplog.set_level(logging.DEBUG, logger=manager.logging.name)
    client = fake_client()
    client.is_connected = False
    manager._on_disconnected(client)
    assert "disconnect callback" in caplog.text
    assert "connected=False" in caplog.text


def _scripted_device(manager, statuses, *, lossy_from=None, failing_from=None, fast_status=None, **client):
    """Answer each transfer packet (b"a", b"b"...) with its status (None = stay silent).

    Unacknowledged writes from packet ``lossy_from`` on are lost on the way
    (the device never hears them); from ``failing_from`` on they raise;
    ``fast_status`` answers every unacknowledged one instead.
    Returns the (packet, response) pairs sent.
    """
    handler = {}
    manager.client = fake_client(**client)
    manager.client.start_notify = AsyncMock(side_effect=lambda uuid, cb: handler.__setitem__("cb", cb))
    manager.client.stop_notify = AsyncMock()
    sent = []

    async def send(data, response=True):
        position = data[0] - ord("a")
        if not response and failing_from is not None and position >= failing_from:
            raise BleakError("write without response failed")
        sent.append((data, response))
        if not response and lossy_from is not None and position >= lossy_from:
            return True
        status = statuses[position] if position < len(statuses) else None
        if not response and fast_status is not None:
            status = fast_status
        if status is not None:
            handler["cb"](None, bytearray([5, 0, 1, 0, status]))
        return True

    manager.send = send
    return sent


@pytest.mark.asyncio
async def test_transfer_waits_for_each_packet_until_done(manager):
    from custom_components.idotmatrix.client.connectionManager import TRANSFER_DONE, TRANSFER_NEXT
    sent = _scripted_device(manager, [TRANSFER_NEXT, TRANSFER_NEXT, TRANSFER_DONE])
    assert await manager.send_transfer([b"a", b"b", b"c"], timeout=0.5) is True
    # Like the Android app: no write response awaited inside a packet.
    assert sent == [(b"a", False), (b"b", False), (b"c", False)]
    assert manager.fast_transfers is True
    manager.client.start_notify.assert_awaited_once()
    manager.client.stop_notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_lossy_link_resends_the_file_with_acknowledged_writes(manager):
    from custom_components.idotmatrix.client.connectionManager import TRANSFER_DONE, TRANSFER_NEXT
    statuses = [TRANSFER_NEXT, TRANSFER_NEXT, TRANSFER_DONE]
    sent = _scripted_device(manager, statuses, lossy_from=1)
    assert await manager.send_transfer([b"a", b"b", b"c"], timeout=0.05) is True
    # Fast twice (a lost answer is usually a one-off), then acknowledged for this file.
    assert sent == [(b"a", False), (b"b", False), (b"a", False), (b"b", False), (b"a", True), (b"b", True), (b"c", True)]
    # The next file starts fast again: acknowledged writes are many times slower.
    sent.clear()
    assert await manager.send_transfer([b"a", b"b", b"c"], timeout=0.05) is True
    assert sent[0] == (b"a", False)


@pytest.mark.asyncio
async def test_each_transfer_is_reported_with_its_attempts_and_timings(manager, monkeypatch):
    from custom_components.idotmatrix.client.connectionManager import TRANSFER_DONE, TRANSFER_NEXT
    reports = []
    monkeypatch.setattr(ConnectionManager, "transfer_log", lambda address, label, report: reports.append((label, report)))
    _scripted_device(manager, [TRANSFER_NEXT, TRANSFER_DONE], lossy_from=1)
    manager.transfer_label = "chat.gif"
    assert await manager.send_transfer([b"a", b"bb"], timeout=0.05) is True
    label, report = reports[0]
    assert label == "chat.gif" and (report["packets"], report["bytes"]) == (2, 3)
    assert [a["mode"] for a in report["attempts"]] == ["fast", "fast", "acknowledged"]
    assert "no answer to packet 2/2" in report["attempts"][0]["failed"]
    # [seconds writing, seconds waiting for the device] per packet.
    assert len(report["attempts"][2]["packets"]) == 2
    assert all(p[1] is not None for p in report["attempts"][2]["packets"])
    assert report["seconds"] >= 0 and "error" not in report


@pytest.mark.asyncio
async def test_failed_fast_write_resends_the_file_with_acknowledged_writes(manager):
    from custom_components.idotmatrix.client.connectionManager import TRANSFER_DONE, TRANSFER_NEXT
    sent = _scripted_device(manager, [TRANSFER_NEXT, TRANSFER_DONE], failing_from=1)
    assert await manager.send_transfer([b"a", b"b"], timeout=0.05) is True
    assert sent == [(b"a", False), (b"a", False), (b"a", True), (b"b", True)]


@pytest.mark.asyncio
async def test_damaged_fast_packet_resends_instead_of_failing(manager):
    from custom_components.idotmatrix.client.connectionManager import TRANSFER_DONE, TRANSFER_INVALID
    sent = _scripted_device(manager, [TRANSFER_DONE], fast_status=TRANSFER_INVALID)
    assert await manager.send_transfer([b"a"], timeout=0.05) is True
    assert sent == [(b"a", False), (b"a", False), (b"a", True)]


@pytest.mark.asyncio
async def test_link_without_unacknowledged_writes_uses_acknowledged_ones(manager):
    from custom_components.idotmatrix.client.connectionManager import TRANSFER_DONE, TRANSFER_NEXT
    sent = _scripted_device(manager, [TRANSFER_NEXT, TRANSFER_DONE], properties=("write",))
    assert await manager.send_transfer([b"a", b"b"], timeout=0.5) is True
    assert sent == [(b"a", True), (b"b", True)]


@pytest.mark.asyncio
async def test_transfer_reports_full_storage_and_stops(manager):
    from custom_components.idotmatrix.client.connectionManager import (
        TRANSFER_NEXT, TRANSFER_NO_SPACE, TransferRejectedError,
    )
    sent = _scripted_device(manager, [TRANSFER_NEXT, TRANSFER_NO_SPACE])
    with pytest.raises(TransferRejectedError, match="space"):
        await manager.send_transfer([b"a", b"b", b"c"], timeout=0.5)
    # A full display is a real answer, not a lost write: no resend.
    assert [packet for packet, _ in sent] == [b"a", b"b"]
    assert manager.fast_transfers is True
    manager.client.stop_notify.assert_awaited_once()


@pytest.mark.asyncio
async def test_transfer_to_silent_firmware_still_sends_everything(manager):
    sent = _scripted_device(manager, [])
    assert await manager.send_transfer([b"a", b"b", b"c"], timeout=0.05) is True
    assert sent == [(b"a", False), (b"a", False), (b"a", True), (b"b", True), (b"c", True)]


@pytest.mark.asyncio
async def test_transfer_that_stops_answering_midway_fails(manager):
    from custom_components.idotmatrix.client.connectionManager import TRANSFER_NEXT, TransferRejectedError
    _scripted_device(manager, [TRANSFER_NEXT])
    with pytest.raises(TransferRejectedError, match="stopped answering"):
        await manager.send_transfer([b"a", b"b", b"c"], timeout=0.05)


@pytest.mark.asyncio
async def test_cancelled_fast_transfer_is_not_resent(manager):
    from custom_components.idotmatrix.client.connectionManager import TRANSFER_NEXT, TransferRejectedError
    sent = _scripted_device(manager, [TRANSFER_NEXT, TRANSFER_NEXT])
    original = manager.send

    async def send(data, response=True):
        manager.abort_requested = True
        return await original(data, response)
    manager.send = send
    with pytest.raises(TransferRejectedError, match="cancelled"):
        await manager.send_transfer([b"a", b"b"], timeout=0.05)
    assert sent == [(b"a", False)]


def test_each_display_gets_its_own_manager(monkeypatch):
    monkeypatch.setattr(ConnectionManager, "_instances", {})
    unbound = ConnectionManager()  # used before any display was set up
    first = ConnectionManager.for_address("AA:AA:AA:AA:AA:AA")
    second = ConnectionManager.for_address("BB:BB:BB:BB:BB:BB")
    assert first is unbound and second is not first
    assert (first.address, second.address) == ("AA:AA:AA:AA:AA:AA", "BB:BB:BB:BB:BB:BB")
    assert ConnectionManager.for_address("BB:BB:BB:BB:BB:BB") is second
    # Outside a device call, the library still reaches the first display.
    assert ConnectionManager() is first


@pytest.mark.asyncio
async def test_modules_reach_the_display_of_the_running_device_call(monkeypatch):
    from custom_components.idotmatrix.client.modules.common import Common

    monkeypatch.setattr(ConnectionManager, "_instances", {})
    first = ConnectionManager.for_address("AA:AA:AA:AA:AA:AA")
    second = ConnectionManager.for_address("BB:BB:BB:BB:BB:BB")
    common = Common()  # built before the call, resolved when sending

    async def device_call():
        ConnectionManager.bind(second)
        return common.conn

    assert await asyncio.create_task(device_call()) is second
    assert common.conn is first  # the binding stays inside that call
    assert Common(second).conn is second


@pytest.mark.asyncio
async def test_connecting_asks_bluez_for_the_mtu_so_packets_go_in_large_writes(manager):
    """BlueZ reports a 23-byte MTU until asked: 4 KB packets then took 205 writes."""
    size = [20]
    services = BleakGATTServiceCollection()
    service = BleakGATTService(None, 1, "0000fa00-0000-1000-8000-00805f9b34fb")
    services.add_service(service)
    for handle, uuid in enumerate((UUID_READ_DATA, UUID_WRITE_DATA), 2):
        services.add_characteristic(BleakGATTCharacteristic(
            None, handle, uuid, ["write", "write-without-response"], lambda: size[0], service))

    async def acquire():
        size[0] = 509 - 0  # what BlueZ reports once the MTU is known

    client = SimpleNamespace(is_connected=True, services=services, clear_cache=AsyncMock(return_value=True),
                             write_gatt_char=AsyncMock(), _backend=SimpleNamespace(_acquire_mtu=acquire))
    client.disconnect = AsyncMock()
    bleak_retry_connector.establish_connection.return_value = client
    await manager.connect()
    assert manager._write_size() == 509
    await manager.send(b"x" * 4096)
    assert client.write_gatt_char.await_count == 9  # 4096 / 509, not 205 writes of 20 bytes


@pytest.mark.asyncio
async def test_a_failed_mtu_request_keeps_the_connection(manager):
    client = fake_client(write_size=20)
    client._backend = SimpleNamespace(_acquire_mtu=AsyncMock(side_effect=BleakError("no AcquireWrite")))
    bleak_retry_connector.establish_connection.return_value = client
    await manager.connect()
    assert manager.client is client and manager._write_size() == 20


@pytest.mark.asyncio
async def test_small_writes_keep_the_apps_byte_rate_instead_of_its_pause_per_write(manager, monkeypatch):
    """20-byte writes used to wait 20 ms each, like the app's 509-byte ones: 4.6 s per 4 KB."""
    from custom_components.idotmatrix.client import connectionManager as module

    monkeypatch.setattr(ConnectionManager, "WRITE_BURST", False)  # the one-by-one pace

    pauses = []
    real_sleep = asyncio.sleep

    async def sleep(seconds):
        pauses.append(seconds)
        await real_sleep(0)

    monkeypatch.setattr(module.asyncio, "sleep", sleep)
    manager.client = fake_client(write_size=20)
    await manager.send(b"x" * 4096, response=False)  # how transfer packets go out
    assert manager.client.write_gatt_char.await_count == 205
    assert sum(pauses) == pytest.approx(0.02 * 4096 / 509, rel=0.05)  # ~0.16 s, not 4.1 s


@pytest.mark.asyncio
async def test_time_per_packet_is_learnt_from_real_files_only(manager):
    from custom_components.idotmatrix.client.connectionManager import TRANSFER_DONE, TRANSFER_NEXT
    _scripted_device(manager, [TRANSFER_NEXT, TRANSFER_DONE])
    await manager.send_transfer([b"a", b"b"], timeout=0.5)
    assert manager.seconds_per_packet is None  # a first image alone says little
    _scripted_device(manager, [TRANSFER_NEXT] * 9 + [TRANSFER_DONE])
    await manager.send_transfer([bytes([ord("a") + i]) for i in range(10)], timeout=0.5)
    assert manager.seconds_per_packet is not None and manager.seconds_per_packet < 1


@pytest.mark.asyncio
async def test_burst_mode_starts_every_write_of_a_packet_in_order_before_awaiting(manager, monkeypatch):
    monkeypatch.setattr(ConnectionManager, "WRITE_BURST", True)
    manager.client = fake_client(write_size=3)
    started, gate = [], asyncio.Event()

    async def write(uuid, chunk, response):
        started.append((bytes(chunk), response))
        await gate.wait()

    manager.client.write_gatt_char = AsyncMock(side_effect=write)
    sending = asyncio.ensure_future(manager.send(b"abcdefgh", response=False))
    for _ in range(5):
        await asyncio.sleep(0)
    # All three writes are with the stack at once, in order, none finished yet.
    assert started == [(b"abc", False), (b"def", False), (b"gh", False)]
    gate.set()
    assert await sending is True
    # Acknowledged writes (commands) never go in bursts.
    started.clear()
    gate.set()
    assert await manager.send(b"abcdefgh", response=True) is True
    assert [r for _, r in started] == [True, True, True]
