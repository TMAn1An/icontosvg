"""Load and preprocess a raster icon sheet.

Uses Pillow for decoding (reliable JPG/PNG/WebP support, including palette
and ICC-profile edge cases OpenCV's imread handles inconsistently), then
hands off to numpy/OpenCV for the analysis pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image


@dataclass
class PreprocessedSheet:
    rgb: np.ndarray
    grayscale: np.ndarray
    width: int
    height: int


def load_sheet(path: str) -> PreprocessedSheet:
    """Load a JPG, PNG, or WebP file and return RGB + grayscale arrays."""
    with Image.open(path) as img:
        rgb_img = img.convert("RGB")
        rgb = np.array(rgb_img)

    grayscale = np.array(Image.fromarray(rgb).convert("L"))
    height, width = grayscale.shape
    return PreprocessedSheet(rgb=rgb, grayscale=grayscale, width=width, height=height)


def upscale(sheet: PreprocessedSheet, factor: int) -> PreprocessedSheet:
    """Upscale for analysis only. factor must be one of 1, 2, 4."""
    if factor not in (1, 2, 4):
        raise ValueError("factor must be 1, 2, or 4")
    if factor == 1:
        return sheet

    new_size = (sheet.width * factor, sheet.height * factor)
    rgb_img = Image.fromarray(sheet.rgb).resize(new_size, Image.LANCZOS)
    rgb = np.array(rgb_img)
    grayscale = np.array(rgb_img.convert("L"))
    return PreprocessedSheet(rgb=rgb, grayscale=grayscale, width=new_size[0], height=new_size[1])
