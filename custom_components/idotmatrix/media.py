"""Convert user images, GIFs and videos into device-ready animated GIFs.

``display_gif`` streams files to the panel byte-for-byte, so anything it
plays must already match the screen resolution and stay small enough to
upload over BLE. This module turns arbitrary media into such a GIF:

1. frames are read with Pillow (stills, GIF, WebP, APNG) or extracted with
   ffmpeg (any video ffmpeg can decode), honouring a start/end window;
2. each frame is cropped / fitted to the square screen and its tones are
   tuned for an LED panel, where black means "off" and near-black greys
   only show up as dim noise;
3. a search over palette size and frame rate keeps the best quality that
   fits the byte budget, encoding through the same single-palette writer
   as the built-in dashboards (``weather.frames_to_gif``).

Dithering defaults to off: on a 64x64 panel error-diffusion noise shimmers
from frame to frame and compresses poorly, often doubling the file size.
"""
from __future__ import annotations

import glob
import math
import os
import subprocess
import tempfile
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageEnhance, ImageSequence

from .weather import frames_to_gif

FITS = ("crop", "fit", "stretch")

# Frame rate used to sample videos when no explicit fps is requested. The
# budget search thins it further when the result is too large.
VIDEO_FPS = 12

# Palette used when there is no size budget: the most a GIF palette holds.
MAX_COLORS = 256

# (palette size, keep 1 frame out of N), best quality first.
ATTEMPTS = (
    (64, 1), (48, 1), (32, 1), (32, 2), (24, 2), (32, 3), (24, 3), (16, 3), (16, 4), (16, 6),
)

# A frame this close to the last kept one is merged into it (its time is
# added to that frame's delay): on an LED panel a few pixels changing a
# little are invisible, but every frame costs bytes and Bluetooth time.
SIMILAR_LEVEL = 24        # summed RGB change for a pixel to count as changed
SIMILAR_SHARE = 0.004     # share of changed pixels still treated as the same image
# Frames starting sooner than this after the last kept one are folded into it:
# 30 fps sources keep every frame, faster ones come down to about 30 fps,
# which an LED panel shows just as smoothly.
MIN_FRAME_MS = 30

# GIF delays below 20 ms are clamped by most decoders; browsers treat 0 as 100.
_DEFAULT_FRAME_MS = 100


@dataclass
class ConvertOptions:
    """How a source file is turned into a device GIF."""

    size: int = 64
    fit: str = "crop"
    # Region of the source to keep, as fractions of its width/height:
    # (x, y, width, height). None keeps the whole frame.
    crop: tuple[float, float, float, float] | None = None
    start: float = 0.0
    end: float | None = None
    max_seconds: float = 12.0
    fps: float | None = None
    # None encodes at full quality, whatever the size.
    max_bytes: int | None = 96 * 1024
    brightness: float = 1.0
    contrast: float = 1.1
    saturation: float = 1.25
    gamma: float = 1.0
    # Pixels whose brightest channel is below this value are switched off.
    black_level: int = 16
    dither: bool = False
    boomerang: bool = False
    merge_similar: bool = True
    # Without a byte budget: palette size (None: the full 256 colours) and a
    # frame-rate cap (None: up to ~30 fps when merging).
    colors: int | None = None
    max_fps: float | None = None
    # A pixel within this much (per channel) of what the panel already shows
    # keeps it: it costs nothing in the delta frame (see weather._settle).
    fuzz: int = 0


@dataclass
class ConvertResult:
    """A converted GIF and the settings the budget search settled on."""

    data: bytes
    frames: int
    duration_ms: int
    colors: int
    frame_step: int

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def convert(path: str, options: ConvertOptions | None = None,
            ffmpeg: str = "ffmpeg") -> ConvertResult:
    """Convert the media file at ``path`` into a device-ready GIF.

    Blocking (decoding and encoding are CPU bound): run it in an executor.
    """
    opts = options or ConvertOptions()
    if opts.fit not in FITS:
        raise ValueError(f"Unknown fit mode: {opts.fit}")

    raw, cropped = load_frames(path, opts, ffmpeg)
    frames = [
        (_tone(_shape(img, opts.size, opts.fit, None if cropped else opts.crop), opts), ms)
        for img, ms in raw
    ]
    return encode_frames(frames, opts)


def encode_frames(frames: list[tuple[Image.Image, int]], opts: ConvertOptions) -> ConvertResult:
    """Encode screen-sized RGB frames (and their ms durations) within the budget.

    Without a budget (``max_bytes`` None) every frame is kept with a full palette.

    Used directly when the frames were prepared elsewhere (the Pixel Studio
    crops, trims and tunes them in the browser). Blocking: run in an executor.
    """
    frames = list(frames)
    if opts.boomerang and len(frames) > 2:
        frames += frames[-2:0:-1]
    if opts.max_bytes is None:
        return _encode(frames, opts.colors or MAX_COLORS, 1, opts)

    result = None
    for colors, step in ATTEMPTS:
        result = _encode(_thin(frames, step), colors, step, opts)
        if result.size_bytes <= opts.max_bytes or len(frames) == 1:
            return result

    # Even the leanest settings overflow: shorten the clip until it fits.
    colors, step = ATTEMPTS[-1]
    picked = _thin(frames, step)
    while result.size_bytes > opts.max_bytes and len(picked) > 1:
        picked = picked[: max(1, int(len(picked) * 0.8))]
        result = _encode(picked, colors, step, opts)
    return result


def load_frames(path: str, opts: ConvertOptions,
                ffmpeg: str = "ffmpeg") -> tuple[list[tuple[Image.Image, int]], bool]:
    """Read RGB frames and their durations (ms) inside the requested window.

    Returns the frames and whether ``opts.crop`` was already applied (ffmpeg
    crops videos before scaling them down). The last decode is cached so
    re-rendering with other tones or budgets (an editor preview) is quick.
    """
    key = (path, os.path.getmtime(path), opts.start, opts.end, opts.max_seconds,
           opts.fps, opts.size, opts.crop)
    if key in _frame_cache:
        return _frame_cache[key]
    try:
        with Image.open(path) as probe:
            probe.verify()
    except (OSError, SyntaxError, Image.UnidentifiedImageError):
        loaded = _load_video_frames(path, opts, ffmpeg), True
    else:
        loaded = _load_image_frames(path, opts), False
    # One decoded clip only: a Raspberry Pi has little memory to spare.
    _frame_cache.clear()
    _frame_cache[key] = loaded
    return loaded


_frame_cache: dict[tuple, tuple[list[tuple[Image.Image, int]], bool]] = {}


def _window_ms(opts: ConvertOptions) -> tuple[float, float]:
    start = max(0.0, opts.start) * 1000
    stop = start + opts.max_seconds * 1000
    if opts.end is not None:
        stop = min(stop, opts.end * 1000)
    if stop <= start:
        raise ValueError("The end of the clip must be after its start")
    return start, stop


def _load_image_frames(path: str, opts: ConvertOptions) -> list[tuple[Image.Image, int]]:
    start, stop = _window_ms(opts)
    frames = []
    elapsed = 0
    with Image.open(path) as img:
        for frame in ImageSequence.Iterator(img):
            ms = int(frame.info.get("duration") or img.info.get("duration") or 0)
            ms = ms if ms > 0 else _DEFAULT_FRAME_MS
            begins, elapsed = elapsed, elapsed + ms
            if elapsed <= start:
                continue
            if begins >= stop:
                break
            frames.append((_flatten(frame), ms))
    if not frames:
        raise ValueError("No frames in the selected time range")
    return frames


def _load_video_frames(path: str, opts: ConvertOptions,
                       ffmpeg: str) -> list[tuple[Image.Image, int]]:
    start, stop = _window_ms(opts)
    fps = opts.fps or VIDEO_FPS
    # Scale down to a few times the screen size: plenty for area averaging,
    # and it keeps the PNG round trip cheap on a Raspberry Pi.
    work = opts.size * 4
    filters = []
    if opts.crop:
        x, y, w, h = opts.crop
        filters.append(f"crop=iw*{w}:ih*{h}:iw*{x}:ih*{y}")
    filters += [f"fps={fps}", f"scale={work}:{work}:force_original_aspect_ratio=increase"]

    with tempfile.TemporaryDirectory(prefix="idotmatrix-") as tmp:
        cmd = [
            ffmpeg, "-v", "error", "-nostdin",
            "-ss", f"{start / 1000:.3f}", "-t", f"{(stop - start) / 1000:.3f}",
            "-i", path, "-vf", ",".join(filters),
            "-frames:v", str(math.ceil((stop - start) / 1000 * fps)),
            os.path.join(tmp, "%05d.png"),
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=300, check=False)
        except FileNotFoundError as err:
            raise ValueError(f"Unsupported image and ffmpeg not found: {ffmpeg}") from err
        if proc.returncode != 0:
            detail = proc.stderr.decode(errors="replace").strip().splitlines()
            raise ValueError(f"ffmpeg could not decode {path}: {detail[-1] if detail else proc.returncode}")

        ms = round(1000 / fps)
        frames = []
        for name in sorted(glob.glob(os.path.join(tmp, "*.png"))):
            with Image.open(name) as frame:
                frames.append((frame.convert("RGB"), ms))
    if not frames:
        raise ValueError("No frames in the selected time range")
    return frames


def _flatten(frame: Image.Image) -> Image.Image:
    """Composite any transparency onto black (unlit LEDs)."""
    rgba = frame.convert("RGBA")
    black = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    return Image.alpha_composite(black, rgba).convert("RGB")


def _resize(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    if size[0] >= img.width and size[1] >= img.height:
        # Upscaling (pixel art, icons): keep hard pixel edges.
        return img.resize(size, Image.Resampling.NEAREST)
    # Large reductions average whole blocks (no ringing halos on the LEDs).
    factor = img.width / size[0]
    method = Image.Resampling.BOX if factor >= 2 else Image.Resampling.LANCZOS
    return img.resize(size, method)


def _shape(img: Image.Image, size: int, fit: str,
           crop: tuple[float, float, float, float] | None) -> Image.Image:
    """Crop the requested region, then crop / fit / stretch to a square."""
    if crop:
        x, y, w, h = crop
        box = (
            round(x * img.width), round(y * img.height),
            round((x + w) * img.width), round((y + h) * img.height),
        )
        box = (
            max(0, box[0]), max(0, box[1]),
            min(img.width, max(box[0] + 1, box[2])), min(img.height, max(box[1] + 1, box[3])),
        )
        img = img.crop(box)

    if fit == "stretch":
        return _resize(img, (size, size))

    if fit == "fit":
        scale = min(size / img.width, size / img.height)
        inner = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
        canvas = Image.new("RGB", (size, size), (0, 0, 0))
        canvas.paste(_resize(img, inner), ((size - inner[0]) // 2, (size - inner[1]) // 2))
        return canvas

    scale = max(size / img.width, size / img.height)
    outer = (max(size, round(img.width * scale)), max(size, round(img.height * scale)))
    resized = _resize(img, outer)
    left = (outer[0] - size) // 2
    top = (outer[1] - size) // 2
    return resized.crop((left, top, left + size, top + size))


def _tone(img: Image.Image, opts: ConvertOptions) -> Image.Image:
    """Adapt colours to an LED panel."""
    if opts.brightness != 1:
        img = ImageEnhance.Brightness(img).enhance(opts.brightness)
    if opts.contrast != 1:
        img = ImageEnhance.Contrast(img).enhance(opts.contrast)
    if opts.saturation != 1:
        img = ImageEnhance.Color(img).enhance(opts.saturation)
    if opts.gamma != 1:
        lut = [round(255 * (v / 255) ** opts.gamma) for v in range(256)]
        img = img.point(lut * 3)
    if opts.black_level > 0:
        r, g, b = img.split()
        peak = ImageChops.lighter(ImageChops.lighter(r, g), b)
        lit = peak.point(lambda v: 255 if v >= opts.black_level else 0)
        img = Image.composite(img, Image.new("RGB", img.size, (0, 0, 0)), lit)
    return img


def _thin(frames: list[tuple[Image.Image, int]], step: int) -> list[tuple[Image.Image, int]]:
    """Keep one frame out of ``step``, folding the dropped time into it."""
    if step <= 1:
        return list(frames)
    return [
        (frames[i][0], sum(ms for _, ms in frames[i:i + step]))
        for i in range(0, len(frames), step)
    ]


def _pace(frames: list[list], min_ms: int = MIN_FRAME_MS) -> list[list]:
    """Fold frames that start within ``min_ms`` of the last kept one into it."""
    paced: list[list] = []
    elapsed = kept_at = 0
    for frame in frames:
        if paced and elapsed - kept_at < min_ms:
            paced[-1][1] += frame[1]
        else:
            paced.append(frame)
            kept_at = elapsed
        elapsed += frame[1]
    return paced


def _cap_rate(frames: list[list], fps: float) -> list[list]:
    """Keep the first frame of each 1/fps slot, folding the others into it.

    Slots rather than a minimum gap: a 25 fps video capped at 10 keeps 10
    frames a second, not 8. The animation lasts as long.
    """
    period = 1000 / fps
    kept: list[list] = []
    elapsed = 0
    last_slot = -1
    for frame in frames:
        slot = int(elapsed // period)
        if kept and slot == last_slot:
            kept[-1][1] += frame[1]
        else:
            kept.append(frame)
            last_slot = slot
        elapsed += frame[1]
    return kept


def _similar(a: Image.Image, b: Image.Image) -> bool:
    """Whether two screen frames would look the same on the panel."""
    if a.size != b.size:
        return False
    red, green, blue = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).split()
    change = ImageChops.add(ImageChops.add(red, green), blue).histogram()
    return sum(change[SIMILAR_LEVEL + 1:]) <= SIMILAR_SHARE * a.size[0] * a.size[1]


def _encode(frames: list[tuple[Image.Image, int]], colors: int, step: int,
            opts: ConvertOptions) -> ConvertResult:
    # Merge consecutive identical frames (common in videos and still GIFs),
    # and nearly identical ones unless asked not to. Comparing with the last
    # kept frame, not the previous one, keeps slow drifts from piling up.
    merged: list[list] = []
    for img, ms in frames:
        pixels = img.tobytes()
        if merged and (merged[-1][2] == pixels or (opts.merge_similar and _similar(merged[-1][0], img))):
            merged[-1][1] += ms
        else:
            merged.append([img, ms, pixels])
    if opts.merge_similar:
        merged = _pace(merged)
    if opts.max_fps:
        merged = _cap_rate(merged, opts.max_fps)
    images = [img for img, _, _ in merged]
    durations = [ms for _, ms, _ in merged]
    data = frames_to_gif(images, durations, colors=colors, dither=opts.dither, photo=True, fuzz=opts.fuzz)
    return ConvertResult(
        data=data,
        frames=len(images),
        duration_ms=sum(durations),
        colors=colors,
        frame_step=step,
    )


def gif_layout(data: bytes) -> dict:
    """Whether a GIF only uses its global palette, and the colour at index 0."""
    packed = data[10]
    if not packed & 0x80:
        return {"global_palette": False, "local_palettes": 0, "first_color": None}
    gct_len = (2 << (packed & 7)) * 3
    first = tuple(data[13:16])
    pos, local = 13 + gct_len, 0
    try:
        while data[pos] != 0x3B:
            if data[pos] == 0x21:  # extension: label, then sub-blocks
                pos += 2
            elif data[pos] == 0x2C:  # image descriptor
                flags = data[pos + 9]
                pos += 10
                if flags & 0x80:
                    local += 1
                    pos += (2 << (flags & 7)) * 3
                pos += 1  # LZW minimum code size
            else:
                break
            while data[pos] != 0:
                pos += 1 + data[pos]
            pos += 1
    except IndexError:
        pass  # truncated trailer: what was read is enough
    return {"global_palette": True, "local_palettes": local, "first_color": first}
