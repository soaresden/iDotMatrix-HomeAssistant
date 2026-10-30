"""The Pixel Studio log: how a GIF's bytes are spent, frame by frame."""
from PIL import Image

from custom_components.idotmatrix.journal import gif_stats
from custom_components.idotmatrix.weather import frames_to_gif


def test_gif_stats_reports_each_frame_and_its_redrawn_box():
    frames = []
    for i in range(4):
        img = Image.new("RGB", (64, 64), (0, 0, 40))
        img.paste((255, 200, 0), (i * 8, 10, i * 8 + 8, 18))  # a small square moving right
        frames.append(img)
    data = frames_to_gif(frames, [100, 100, 100, 250], colors=16)
    stats = gif_stats(data)
    assert (stats["width"], stats["height"], stats["frames_count"]) == (64, 64, 4)
    assert stats["first_frame_bytes"] + stats["delta_bytes_total"] + stats["header_bytes"] < len(data)
    assert [f[2] for f in stats["frames"]] == [100, 100, 100, 250]
    # Later frames only redraw around the square, not the whole screen.
    assert stats["full_screen_deltas"] == 0 and stats["delta_area_median"] < 10


def test_gif_stats_ignores_what_is_not_a_gif():
    assert gif_stats(b"not a gif") == {}


async def test_a_warning_logged_during_a_transfer_reaches_the_log_without_breaking_it():
    import asyncio
    import logging
    from types import SimpleNamespace

    from custom_components.idotmatrix.journal import Journal

    journal = object.__new__(Journal)
    journal.hass = SimpleNamespace(loop=asyncio.get_running_loop())
    journal._handler = None
    added = []
    journal.add = lambda kind, message, **data: added.append((kind, message, data))
    journal.capture_warnings("custom_components.idotmatrix.test_journal")
    try:
        # Used to raise TypeError inside the logging call, aborting the transfer that logged.
        logging.getLogger("custom_components.idotmatrix.test_journal.ble").warning("Fast transfer to %s failed", "AA")
        await asyncio.sleep(0)
    finally:
        journal.release("custom_components.idotmatrix.test_journal")
    assert added == [("warning", "Fast transfer to AA failed", {"logger": "custom_components.idotmatrix.test_journal.ble"})]
