"""Generate synthetic PNG fixtures for geometry tests.

Run as a script to (re)populate fixtures/synthetic/. Not yet wired into
the test suite as a fixture dependency — test_geometry.py currently
builds its tiny synthetic arrays inline. This script grows in slice 2 to
cover the full list from the spec (circles, rounded rects, gaps, crossings,
disconnected components, blur/JPEG variants).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

OUTPUT_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "synthetic"


def make_horizontal_line(width: int = 100, height: int = 40) -> np.ndarray:
    image = np.full((height, width), 255, dtype=np.uint8)
    image[height // 2, 10 : width - 10] = 0
    return image


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    Image.fromarray(make_horizontal_line()).save(OUTPUT_DIR / "horizontal_line.png")


if __name__ == "__main__":
    main()
