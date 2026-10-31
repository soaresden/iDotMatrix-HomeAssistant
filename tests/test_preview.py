import io

from PIL import Image, ImageSequence

from custom_components.idotmatrix.preview import (
    PREVIEW_SIZE,
    UNLIT,
    color_preview,
    file_preview,
    image_preview,
    render_led_preview,
)
from custom_components.idotmatrix.weather import frames_to_gif


def _open(data: bytes) -> list[tuple[Image.Image, int]]:
    with Image.open(io.BytesIO(data)) as image:
        return [(f.convert("RGB"), f.info.get("duration")) for f in ImageSequence.Iterator(image)]


def test_still_becomes_round_leds_on_dark_board():
    frames = _open(color_preview((255, 0, 0), 64))
    assert len(frames) == 1
    frame = frames[0][0]
    scale = PREVIEW_SIZE // 64
    assert frame.size == (PREVIEW_SIZE, PREVIEW_SIZE)
    assert frame.getpixel((scale // 2, scale // 2)) == (255, 0, 0)  # LED centre
    assert frame.getpixel((0, 0)) == (0, 0, 0)  # gap between LEDs


def test_unlit_pixels_stay_faintly_visible():
    frame = _open(image_preview(Image.new("RGB", (32, 32), (0, 0, 0))))[0][0]
    scale = PREVIEW_SIZE // 32
    assert frame.getpixel((scale // 2, scale // 2)) == UNLIT


def test_animation_keeps_frames_and_timing():
    gif = frames_to_gif(
        [Image.new("RGB", (64, 64), c) for c in ((255, 0, 0), (0, 0, 255), (0, 255, 0))],
        [100, 250, 400],
    )
    frames = _open(render_led_preview(gif))
    assert [ms for _, ms in frames] == [100, 250, 400]
    centre = PREVIEW_SIZE // 64 // 2
    assert frames[1][0].getpixel((centre, centre))[2] > 200


def test_file_preview(tmp_path):
    path = tmp_path / "icon.png"
    Image.new("RGB", (16, 16), (0, 200, 0)).save(path)
    frame = _open(file_preview(str(path)))[0][0]
    assert frame.size == (PREVIEW_SIZE, PREVIEW_SIZE)
