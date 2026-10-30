"""Exercise the real coordinator against Home Assistant with simulated BLE."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.idotmatrix import coordinator as module
from custom_components.idotmatrix.client.modules.gif import Gif
from custom_components.idotmatrix.coordinator import IDotMatrixCoordinator
from custom_components.idotmatrix.weather import WeatherData


@pytest.fixture
async def coordinator(tmp_path):
    hass = HomeAssistant(str(tmp_path))
    entry = SimpleNamespace(options={}, entry_id="test", data={}, async_on_unload=Mock(), pref_disable_polling=False)
    c = IDotMatrixCoordinator(hass, entry)
    yield c
    await c.async_shutdown()


@pytest.mark.asyncio
async def test_entity_listener_schedules_home_assistant_polling(coordinator):
    listener = Mock()
    unsubscribe = coordinator.async_add_listener(listener)
    try:
        assert coordinator._unsub_refresh is not None
        coordinator.async_set_updated_data({"connected": True})
        listener.assert_called_once_with()
        assert coordinator._unsub_refresh is not None
    finally:
        unsubscribe()


@pytest.mark.asyncio
async def test_disconnect_and_reconnect_update_subscribed_entities(coordinator, monkeypatch):
    c = coordinator
    conn = module.ConnectionManager()
    monkeypatch.setattr(conn, "disconnect", AsyncMock())
    monkeypatch.setattr(conn, "connect", AsyncMock())
    monkeypatch.setattr(conn, "client", SimpleNamespace(is_connected=True))
    listener = Mock()
    unsubscribe = c.async_add_listener(listener)
    try:
        await c.async_disconnect_device()
        assert c.data == {"connected": False}
        assert c._suspended is True
        await c.async_reconnect_device()
        assert c.data == {"connected": True}
        assert c._suspended is False
        assert listener.call_count == 2
        conn.disconnect.assert_awaited_once()
        conn.connect.assert_awaited_once()
    finally:
        unsubscribe()


@pytest.mark.asyncio
async def test_reconnect_reports_discovery_failure_and_disconnected_state(coordinator, monkeypatch):
    from bleak.exc import BleakError
    from homeassistant.exceptions import HomeAssistantError
    connect = AsyncMock(side_effect=BleakError("Missing required write characteristic FA02"))
    monkeypatch.setattr(module.ConnectionManager(), "connect", connect)
    coordinator.async_set_updated_data({"connected": True})
    with pytest.raises(HomeAssistantError, match="Missing required write characteristic FA02"):
        await coordinator.async_reconnect_device()
    assert coordinator.data == {"connected": False}


@pytest.mark.asyncio
async def test_stopped_render_cannot_replace_new_display(coordinator, monkeypatch):
    c = coordinator
    started, release = asyncio.Event(), asyncio.Event()
    real_executor = c.hass.async_add_executor_job
    async def executor(fn, *args):
        if fn is module.render_weather_gif:
            started.set()
            await release.wait()
            return b"GIF89a"
        return await real_executor(fn, *args)
    monkeypatch.setattr(c.hass, "async_add_executor_job", executor)
    c._get_weather_data = AsyncMock(return_value=WeatherData("sunny", 20))
    c._weather_cfg = {"weather_entity": "weather.test"}
    upload = AsyncMock(return_value=True)
    monkeypatch.setattr(module.IDMGif, "uploadSingleRaw", upload)
    c._carousel_active = False
    task = asyncio.create_task(c.async_show_weather(c._weather_cfg))
    await started.wait()
    await c.async_stop_weather_mode()
    await c._device_call(AsyncMock(return_value=True))
    release.set()
    assert await task is False
    upload.assert_not_awaited()
    assert c._weather_signature is None


@pytest.mark.asyncio
async def test_refresh_scheduled_before_stop_does_not_start(coordinator):
    c = coordinator
    cfg = {"weather_entity": "weather.test"}
    c._weather_cfg = cfg
    c._get_weather_data = AsyncMock()
    task = asyncio.create_task(c.async_show_weather(cfg))
    await c.async_stop_weather_mode()
    assert await task is False
    c._get_weather_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_text_waits_for_whole_upload(coordinator, monkeypatch):
    c = coordinator
    c.text_settings["current_text"] = "Hello"
    c.display_mode = "text"
    write = AsyncMock()
    monkeypatch.setattr(module.Text, "setMode", write)
    c.async_save_settings = AsyncMock()
    async with c._device_lock:
        task = asyncio.create_task(c.async_update_device())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        write.assert_not_awaited()
    await task
    write.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_write_is_drained_before_return(coordinator):
    c = coordinator
    started, release = asyncio.Event(), asyncio.Event()
    async def write():
        started.set()
        await release.wait()
        return True
    task = asyncio.create_task(c._device_call(write))
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not c._device_tasks


@pytest.mark.asyncio
async def test_shutdown_rejects_queued_writes(coordinator):
    c = coordinator
    write = AsyncMock()
    async with c._device_lock:
        queued = asyncio.create_task(c._device_call(write))
        await asyncio.sleep(0)
        shutdown = asyncio.create_task(c.async_shutdown())
        await asyncio.sleep(0)
    await shutdown
    assert await queued is False
    write.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [("uploadSingleRaw", ("unused.gif",)), ("uploadBatch", (["unused.gif"],))])
async def test_upload_cancellation_propagates(method, args):
    gif = Gif(SimpleNamespace(connect=AsyncMock(side_effect=asyncio.CancelledError())))
    with pytest.raises(asyncio.CancelledError):
        await getattr(gif, method)(*args)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_at", [0, 1])
async def test_batch_aborts_on_failed_setup(fail_at):
    results = [True] * fail_at + [False]
    gif = Gif(SimpleNamespace(connect=AsyncMock(), send=AsyncMock(side_effect=results)))
    assert await gif.uploadBatch(["never-read.gif"]) is False
    assert gif.conn.send.await_count == fail_at + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "unavailable"])
async def test_nonfinite_sensor_is_unavailable(coordinator, value):
    coordinator.hass.states.async_set("sensor.co2", value)
    assert coordinator._read_float_state("sensor.co2") is None


@pytest.mark.asyncio
async def test_invalid_path_reports_service_error(coordinator):
    from homeassistant.exceptions import HomeAssistantError
    with pytest.raises(HomeAssistantError, match="Path does not exist"):
        await coordinator.async_display_gif("/no-such-idotmatrix-file.gif")


@pytest.mark.asyncio
async def test_queued_designer_callback_does_not_stop_new_mode(coordinator, monkeypatch):
    c = coordinator
    monkeypatch.setattr(c.hass, "async_create_task", asyncio.create_task)
    c.async_update_device = AsyncMock()
    task = c._schedule_display_refresh(c.async_update_device())
    await c.async_stop_weather_mode()
    await task
    c.async_update_device.assert_not_awaited()


@pytest.mark.asyncio
async def test_shutdown_cancels_pending_refresh(coordinator):
    c = coordinator
    started = asyncio.Event()
    async def render():
        started.set()
        await asyncio.Event().wait()
    task = c._schedule_display_refresh(render())
    await started.wait()
    await c.async_shutdown()
    assert task.cancelled()
    assert not c._refresh_tasks


@pytest.mark.asyncio
async def test_disconnect_blocks_automatic_reconnection(coordinator, monkeypatch):
    from homeassistant.exceptions import HomeAssistantError
    c = coordinator
    disconnect = AsyncMock()
    monkeypatch.setattr(module.ConnectionManager(), "disconnect", disconnect)
    await c.async_disconnect_device()
    disconnect.assert_awaited_once()
    write = AsyncMock()
    with pytest.raises(HomeAssistantError, match="Reconnect"):
        await c._device_call(write)
    write.assert_not_awaited()


@pytest.mark.asyncio
async def test_shutdown_releases_bluetooth(coordinator, monkeypatch):
    disconnect = AsyncMock()
    monkeypatch.setattr(module.ConnectionManager(), "disconnect", disconnect)
    await coordinator.async_shutdown()
    disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_fullscreen_color_stops_dashboard_and_uses_native_command(coordinator, monkeypatch):
    write = AsyncMock(return_value=True)
    monkeypatch.setattr(module.FullscreenColor, "setMode", write)
    coordinator._weather_cfg = {"weather_entity": "weather.test"}
    assert await coordinator.async_show_color([255, 0, 0])
    write.assert_awaited_once_with(255, 0, 0)
    assert coordinator._weather_cfg is None


@pytest.mark.asyncio
async def test_repeated_images_do_not_clear_or_resend_identical_pixels(coordinator, monkeypatch):
    from PIL import Image
    mode, upload = AsyncMock(return_value=True), AsyncMock(return_value=True)
    monkeypatch.setattr(module.IDMImage, "setMode", mode)
    monkeypatch.setattr(module.IDMImage, "uploadProcessed", upload)
    await coordinator._upload_image(Image.new("RGB", (32, 32), "red"), 32)
    await coordinator._upload_image(Image.new("RGB", (32, 32), "red"), 32)
    await coordinator._upload_image(Image.new("RGB", (32, 32), "blue"), 32)
    mode.assert_awaited_once()
    assert upload.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", [False, True])
async def test_perfect_fit_restores_previous_text_mode(coordinator, previous):
    from custom_components.idotmatrix.switch import IDotMatrixAutosize
    from custom_components.idotmatrix.const import CONF_MAC
    entry = SimpleNamespace(data={CONF_MAC: "AA:BB:CC:DD:EE:FF"})
    switch = IDotMatrixAutosize(coordinator, entry)
    switch.async_write_ha_state = Mock()
    coordinator.async_update_device = AsyncMock()
    coordinator.text_settings["multiline"] = previous
    await switch.async_turn_on()
    assert coordinator.text_settings["multiline"] is True
    await switch.async_turn_on()  # repeated requests must not lose the snapshot
    await switch.async_turn_off()
    assert coordinator.text_settings["multiline"] is previous


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [16, 32, 64])
async def test_perfect_fit_renders_visible_text(coordinator, size):
    settings = dict(coordinator.text_settings, autosize=True, screen_size=size)
    image = await coordinator.hass.async_add_executor_job(coordinator._render_multiline_image, "Hello", settings)
    assert image.size == (size, size)
    assert image.getbbox() is not None


@pytest.mark.asyncio
async def test_registered_services_validate_and_report_failures(tmp_path, monkeypatch):
    import custom_components.idotmatrix as integration
    from custom_components.idotmatrix.storage import DesignStorage
    from custom_components.idotmatrix.const import CONF_MAC, DOMAIN
    from homeassistant.exceptions import HomeAssistantError
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = SimpleNamespace(async_forward_entry_setups=AsyncMock())
    entry = SimpleNamespace(entry_id="service-test", options={}, data={CONF_MAC: "AA:BB:CC:DD:EE:FF"}, async_on_unload=Mock(), add_update_listener=Mock())
    monkeypatch.setattr(IDotMatrixCoordinator, "async_load_settings", AsyncMock())
    monkeypatch.setattr(IDotMatrixCoordinator, "async_config_entry_first_refresh", AsyncMock())
    monkeypatch.setattr(DesignStorage, "async_load", AsyncMock())
    assert await integration.async_setup_entry(hass, entry)
    c = hass.data[DOMAIN][entry.entry_id]
    c.async_show_color = AsyncMock(return_value=True)
    c.async_start_co2_mode = AsyncMock(return_value=False)
    await hass.services.async_call(DOMAIN, "show_color", {"color": [255, 0, 0]}, blocking=True)
    c.async_show_color.assert_awaited_once_with([255, 0, 0])
    c.async_start_bitcoin_mode = AsyncMock(return_value=True)
    c.async_show_bitcoin = AsyncMock(return_value=True)
    c._stop_modes_for_message = AsyncMock()
    c.async_stop_message_mode = AsyncMock()
    for follow in (True, False):
        await hass.services.async_call(DOMAIN, "show_bitcoin", {
            "price_entity": "sensor.ethereum_price", "logo": "ethereum.png", "follow": follow,
        }, blocking=True)
        expected = {"price_entity": "sensor.ethereum_price", "change_entity": None, "logo": "ethereum.png", "pixel_size": None}
        if follow:
            c.async_start_bitcoin_mode.assert_awaited_once_with(expected)
        else:
            c.async_show_bitcoin.assert_awaited_once_with(expected, force=True)
    with pytest.raises(HomeAssistantError, match="Display upload failed"):
        await hass.services.async_call(DOMAIN, "show_co2", {"co2_entity": "sensor.test"}, blocking=True)
    import voluptuous as vol
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "display_gif", {"path": "x", "rotation_interval": 300}, blocking=True)
    await c.async_shutdown()


@pytest.mark.asyncio
async def test_stop_gif_service_resets_native_carousel(coordinator, monkeypatch):
    reset = AsyncMock(return_value=True)
    monkeypatch.setattr(module.Common, "reset", reset)
    coordinator._gif_cfg = {"path": "/media/gifs"}
    coordinator._carousel_active = True
    await coordinator.async_stop_gif_display()
    reset.assert_awaited_once()
    assert coordinator._gif_cfg is None
    assert coordinator._carousel_active is False


@pytest.mark.asyncio
async def test_single_uploads_only_reset_the_panel_when_a_carousel_may_run(coordinator, monkeypatch):
    """The reset shows the panel's gradient for the whole upload: after a
    restart it is only sent when the saved state says a carousel ran."""
    from PIL import Image
    from custom_components.idotmatrix.weather import frames_to_gif

    reset = AsyncMock(return_value=True)
    upload = AsyncMock(return_value=True)
    monkeypatch.setattr(module.Common, "reset", reset)
    monkeypatch.setattr(module.IDMGif, "uploadSingleRaw", upload)
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    gif = frames_to_gif([Image.new("RGB", (32, 32), (200, 0, 0))], 100)

    coordinator.text_settings.pop("carousel_active", None)  # never saved: unknown
    assert await coordinator._upload_single(gif)
    assert reset.await_count == 1
    # The new state goes with the settings that survive a restart.
    assert coordinator.text_settings["carousel_active"] is False
    assert await coordinator._upload_single(gif)
    assert reset.await_count == 1


@pytest.mark.asyncio
async def test_card_design_selects_designer_and_preserves_size_and_trigger(coordinator, monkeypatch):
    from custom_components.idotmatrix.const import DISPLAY_MODE_DESIGN
    coordinator.display_mode = 'text'
    coordinator._async_update_device_locked = AsyncMock()
    tracking = Mock(return_value=Mock())
    monkeypatch.setattr(module, 'async_track_state_change_event', tracking)
    await coordinator.async_set_face_config({'layers':[{'template':'Hello'}], 'screen_size':64, 'trigger_entity':'sensor.time'})
    assert coordinator.display_mode == DISPLAY_MODE_DESIGN
    assert coordinator.text_settings['screen_size'] == 64
    assert coordinator.text_settings['trigger_entity'] == 'sensor.time'
    assert 'sensor.time' in tracking.call_args.args[1]


@pytest.mark.asyncio
async def test_design_preferences_restore_after_restart(coordinator):
    coordinator._store.async_load = AsyncMock(return_value={'display_mode':'design', 'trigger_entity':'sensor.time','screen_size':64})
    await coordinator.async_load_settings()
    assert coordinator.display_mode == 'design'
    assert coordinator.text_settings['screen_size'] == 64


@pytest.mark.asyncio
async def test_saved_design_metadata_roundtrip(coordinator):
    from custom_components.idotmatrix.storage import DesignStorage
    storage = DesignStorage(coordinator.hass)
    storage._async_schedule_save = Mock()
    storage.save_design('Clock', [{'template':'Hi'}], 64, 'sensor.time')
    saved = storage.get_design('Clock')
    assert saved['screen_size'] == 64
    assert saved['trigger_entity'] == 'sensor.time'
    assert saved['layers'] == [{'template':'Hi'}]
