import io
import random
import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw, ImageSequence

from custom_components.idotmatrix.media import ConvertOptions, convert
from custom_components.idotmatrix.service_validation import service_schema
from custom_components.idotmatrix.weather import frames_to_gif

# Imported after Home Assistant so it resolves to the same validation library.
import voluptuous as vol  # noqa: E402


def _frames(gif: bytes) -> list[tuple[Image.Image, int]]:
    with Image.open(io.BytesIO(gif)) as image:
        assert image.info["loop"] == 0
        return [(f.convert("RGB"), f.info["duration"]) for f in ImageSequence.Iterator(image)]


def _animation(path, size=(120, 90), count=12, duration=80, noise=False):
    rng = random.Random(1)
    frames = []
    for i in range(count):
        frame = Image.new("RGB", size, (0, 0, 40))
        draw = ImageDraw.Draw(frame)
        x = i * size[0] // count
        draw.ellipse((x, 20, x + 30, 50), fill=(255, 120, 0))
        if noise:
            for _ in range(size[0] * size[1] // 3):
                frame.putpixel((rng.randrange(size[0]), rng.randrange(size[1])),
                               tuple(rng.randrange(256) for _ in range(3)))
        frames.append(frame)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=duration, loop=0)
    return path


def test_photo_becomes_single_square_frame(tmp_path):
    src = tmp_path / "photo.jpg"
    Image.radial_gradient("L").resize((640, 480)).convert("RGB").save(src)
    result = convert(str(src), ConvertOptions(size=64))
    frames = _frames(result.data)
    assert len(frames) == result.frames == 1
    assert frames[0][0].size == (64, 64)


@pytest.mark.parametrize("size", [16, 32, 64])
def test_animation_keeps_motion_and_timing(tmp_path, size):
    src = _animation(tmp_path / "anim.gif")
    result = convert(str(src), ConvertOptions(size=size))
    frames = _frames(result.data)
    assert all(img.size == (size, size) for img, _ in frames)
    assert len(frames) == 12
    assert result.duration_ms == sum(ms for _, ms in frames) == 12 * 80


def test_budget_lowers_colors_then_frame_rate(tmp_path):
    src = _animation(tmp_path / "noise.gif", count=24, noise=True)
    roomy = convert(str(src), ConvertOptions(max_bytes=1024 * 1024))
    tight = convert(str(src), ConvertOptions(max_bytes=40 * 1024))
    assert (roomy.colors, roomy.frame_step) == (64, 1)
    assert tight.size_bytes <= 40 * 1024
    assert (tight.colors, tight.frame_step) < (roomy.colors, roomy.frame_step) or tight.frame_step > 1
    # Dropped frames keep the overall duration (time folds into kept frames).
    assert tight.duration_ms == roomy.duration_ms


def test_budget_shortens_clip_as_last_resort(tmp_path):
    src = _animation(tmp_path / "noise.gif", count=24, noise=True)
    result = convert(str(src), ConvertOptions(max_bytes=4 * 1024))
    assert result.size_bytes <= 4 * 1024
    assert result.duration_ms < 24 * 80


def test_time_window_selects_frames(tmp_path):
    src = _animation(tmp_path / "anim.gif", count=10, duration=100)
    result = convert(str(src), ConvertOptions(start=0.3, end=0.6))
    assert result.frames == 3
    assert result.duration_ms == 300


def test_identical_frames_are_merged(tmp_path):
    src = tmp_path / "still.gif"
    still = Image.new("RGB", (64, 64), (200, 0, 0))
    still.save(src, save_all=True, append_images=[still.copy(), still.copy()], duration=100, loop=0)
    result = convert(str(src), ConvertOptions())
    assert result.frames == 1
    assert result.duration_ms == 300


def test_transparency_and_dark_greys_are_switched_off(tmp_path):
    src = tmp_path / "icon.png"
    icon = Image.new("RGBA", (64, 64), (255, 255, 255, 0))
    ImageDraw.Draw(icon).rectangle((0, 0, 31, 63), fill=(10, 10, 10, 255))
    ImageDraw.Draw(icon).rectangle((32, 0, 63, 63), fill=(0, 200, 0, 255))
    icon.save(src)
    frame = _frames(convert(str(src), ConvertOptions(saturation=1, contrast=1)).data)[0][0]
    assert frame.getpixel((10, 10)) == (0, 0, 0)  # 10/255 grey under black_level
    assert frame.getpixel((50, 10))[1] > 150


def test_fit_pads_with_black_bars(tmp_path):
    src = tmp_path / "wide.png"
    Image.new("RGB", (200, 100), (0, 0, 255)).save(src)
    frame = _frames(convert(str(src), ConvertOptions(fit="fit")).data)[0][0]
    assert frame.getpixel((32, 2)) == (0, 0, 0)
    assert frame.getpixel((32, 32))[2] > 200


def test_crop_region_is_respected(tmp_path):
    src = tmp_path / "halves.png"
    halves = Image.new("RGB", (200, 100), (255, 0, 0))
    ImageDraw.Draw(halves).rectangle((100, 0, 199, 99), fill=(0, 0, 255))
    halves.save(src)
    frame = _frames(convert(str(src), ConvertOptions(crop=(0.5, 0, 0.5, 1))).data)[0][0]
    assert frame.getpixel((5, 5))[2] > 200 and frame.getpixel((5, 5))[0] < 50


def test_boomerang_plays_back_and_forth(tmp_path):
    src = _animation(tmp_path / "anim.gif", count=6)
    assert convert(str(src), ConvertOptions(boomerang=True)).frames == 10


def test_unreadable_file_reports_error(tmp_path):
    src = tmp_path / "broken.mp4"
    src.write_bytes(b"not a video")
    with pytest.raises(ValueError):
        convert(str(src), ConvertOptions(), ffmpeg=shutil.which("ffmpeg") or "ffmpeg-missing")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_video_is_sampled_with_ffmpeg(tmp_path):
    src = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
         "-t", "3", "-pix_fmt", "yuv420p", str(src)],
        check=True,
    )
    result = convert(str(src), ConvertOptions(start=1, end=2, fps=10))
    frames = _frames(result.data)
    assert frames[0][0].size == (64, 64)
    assert 8 <= len(frames) <= 10


def test_frames_to_gif_accepts_per_frame_durations():
    frames = [Image.new("RGB", (8, 8), c) for c in ((255, 0, 0), (0, 255, 0))]
    assert [ms for _, ms in _frames(frames_to_gif(frames, [100, 400]))] == [100, 400]


def test_convert_media_schema():
    schema = service_schema("convert_media")
    data = schema({"source": "/media/a.mp4", "pixel_size": "64", "crop": [0, 0, 0.5, 1]})
    assert data["pixel_size"] == 64 and data["display"] is False
    for bad in ({"source": "/media/a.mp4", "crop": [0, 0, 2, 1]},
                {"source": "/media/a.mp4", "pixel_size": 48},
                {"source": "/media/a.mp4", "fps": 0}):
        with pytest.raises(vol.Invalid):
            schema(bad)



def test_nearly_identical_frames_are_merged_without_losing_time():
    from custom_components.idotmatrix.media import encode_frames

    base = Image.new("RGB", (64, 64), (0, 0, 120))
    nudged = base.copy()
    nudged.putpixel((3, 3), (255, 255, 255))           # 1 pixel of 4096: invisible
    moved = base.copy()
    moved.paste((255, 128, 0), (10, 10, 30, 30))       # a sprite: kept
    frames = [(base, 100), (nudged, 100), (base, 100), (moved, 100)]
    merged = encode_frames(frames, ConvertOptions(max_bytes=None))
    assert (merged.frames, merged.duration_ms) == (2, 400)
    every = encode_frames(frames, ConvertOptions(max_bytes=None, merge_similar=False))
    assert every.frames == 4


def test_fast_sources_come_down_to_about_30_fps_and_keep_their_length():
    from custom_components.idotmatrix.media import encode_frames

    def frame(i):
        image = Image.new("RGB", (64, 64), (0, 0, 0))
        image.paste((255, 255, 255), (i % 60, 0, i % 60 + 4, 64))   # a bar sweeping across
        return image

    sixty = encode_frames([(frame(i), 17) for i in range(60)], ConvertOptions(max_bytes=None))
    assert 28 <= sixty.frames <= 32 and sixty.duration_ms == 60 * 17
    thirty = encode_frames([(frame(i * 2), 33) for i in range(30)], ConvertOptions(max_bytes=None))
    assert thirty.frames == 30


def _sprite_clip(count=40):
    """A detailed still background with a small sprite walking across it."""
    rng = random.Random(7)
    background = Image.new("RGB", (64, 64))
    draw = ImageDraw.Draw(background)
    for _ in range(300):
        x, y = rng.randrange(64), rng.randrange(64)
        draw.rectangle((x, y, x + 2, y + 2), fill=(rng.randrange(256), rng.randrange(256), rng.randrange(256)))
    frames = []
    for i in range(count):
        frame = background.copy()
        ImageDraw.Draw(frame).rectangle((i, 30, i + 7, 37), fill=(255, 220, 0))
        frames.append(frame)
    return frames


def test_frames_after_the_first_only_hold_what_changed():
    from custom_components.idotmatrix.media import gif_layout

    frames = _sprite_clip()
    gif = frames_to_gif(frames, 80, colors=256)
    with Image.open(io.BytesIO(gif)) as image:
        boxes = [frame.tile[0][1] for frame in ImageSequence.Iterator(image)]
    assert boxes[0] == (0, 0, 64, 64)
    # Each later frame is only the box the sprite moved through.
    assert all(right - left <= 9 and bottom - top <= 8 for left, top, right, bottom in boxes[1:])
    # Still what the device needs: one palette (no local ones), black first.
    layout = gif_layout(gif)
    assert (layout["local_palettes"], layout["global_palette"]) == (0, True)
    assert layout["first_color"] == (0, 0, 0)
    # Several times smaller than full frames of the same pictures.
    full_frame = len(frames_to_gif(frames[:1], 80, colors=256))
    assert len(gif) * 4 < full_frame * len(frames)


def test_noise_within_the_tolerance_is_not_sent_again():
    rng = random.Random(3)
    base = _sprite_clip(1)[0]
    # The same picture with a little sensor noise on every pixel of every frame.
    noisy = []
    for _ in range(20):
        frame = base.copy()
        frame.putdata([tuple(max(0, min(255, c + rng.randint(-6, 6))) for c in px) for px in frame.getdata()])
        noisy.append(frame)
    exact = frames_to_gif(noisy, 80, colors=256)
    light = frames_to_gif(noisy, 80, colors=256, fuzz=24)
    assert len(light) < len(exact) * 0.9
    # Never further from the source than the tolerance (plus the palette's own rounding).
    first = _frames(frames_to_gif(noisy[:1], 80, colors=256))[0][0]
    for got, _ in _frames(light):
        worst = max(abs(a - b) for a, b in zip(got.tobytes(), first.tobytes()))
        assert worst <= 24 + 24


def test_delta_frames_decode_to_the_same_animation():
    frames = _sprite_clip(12)
    gif = frames_to_gif(frames, 80, colors=256)
    # Each frame alone through the same encoder: what the delta frames must rebuild.
    singles = [_frames(frames_to_gif([f], 80, colors=256))[0][0] for f in frames]
    decoded = [f for f, _ in _frames(gif)]
    # Shared palette vs per-frame palette can differ by a shade: compare loosely.
    for got, want in zip(decoded, singles):
        diff = sum(abs(a - b) for a, b in zip(got.tobytes(), want.tobytes())) / len(got.tobytes())
        assert diff < 2


def test_big_gifs_send_their_first_image_ahead(tmp_path):
    import os

    from custom_components.idotmatrix.coordinator import FIRST_FRAME_AHEAD_BYTES, first_frame_still

    small = tmp_path / "small.gif"
    Image.new("RGB", (64, 64), (0, 0, 255)).save(small)
    assert first_frame_still(str(small)) is None
    big = tmp_path / "big.gif"
    frames = [Image.effect_noise((64, 64), 80).convert("RGB") for _ in range(40)]
    frames[0].save(big, save_all=True, append_images=frames[1:], duration=100)
    assert os.path.getsize(big) > FIRST_FRAME_AHEAD_BYTES
    still = first_frame_still(str(big))
    try:
        with Image.open(still) as image:
            assert getattr(image, "n_frames", 1) == 1 and image.size == (64, 64)
        assert os.path.getsize(still) <= 2 * 4096  # pure noise, the worst case: two packets at most
    finally:
        os.remove(still)
