"""Test GIFs built into send_gif.exe: a moving plasma with grain (so it
compresses poorly, like a photo clip), encoded by the integration's
device-safe encoder (one global palette, no local ones).

    python tools/make_test_gifs.py OUTPUT_FOLDER
"""
import importlib.util
import math
import random
import sys
from pathlib import Path

from PIL import Image

# weather.py only needs Pillow, but its package needs Home Assistant.
WEATHER = Path(__file__).resolve().parents[1] / "custom_components" / "idotmatrix" / "weather.py"
spec = importlib.util.spec_from_file_location("weather", WEATHER)
weather = sys.modules["weather"] = importlib.util.module_from_spec(spec)
spec.loader.exec_module(weather)

# name: (size in pixels, at least this many KB)
GIFS = {
    "test-64px-petit.gif": (64, 60),
    "test-64px-gros.gif": (64, 730),  # about the 734 KB measured on the Pi
    "test-32px.gif": (32, 200),
}

PALETTE = [0, 0, 0] + [
    int(127 + 127 * math.sin(2 * math.pi * (i / 255 + k / 3))) for i in range(1, 256) for k in range(3)
]


def make(path: Path, size: int, min_kb: int, grain: int = 40) -> None:
    rng = random.Random(size * 1000 + min_kb)
    frames, t = [], 0.0
    while True:
        pixels = bytes(
            max(1, min(255, int(128 + 40 * (math.sin(x / 6 + t) + math.sin(y / 5 - t * 0.7)
                                            + math.sin((x + y) / 9 + t * 0.4))) + rng.randint(-grain, grain)))
            for y in range(size) for x in range(size)
        )
        frame = Image.frombytes("P", (size, size), pixels)
        frame.putpalette(PALETTE)
        frames.append(frame.convert("RGB"))
        t += 0.25
        if len(frames) % 10 == 0:
            path.write_bytes(weather.frames_to_gif(frames, 80, colors=255))
            if path.stat().st_size >= min_kb * 1024:
                break
    print(f"{path.name}: {len(frames)} images, {path.stat().st_size // 1024} Ko")


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name, (size, min_kb) in GIFS.items():
        make(out / name, size, min_kb)
