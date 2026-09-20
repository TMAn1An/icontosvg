"""Unit tests for crop detection, especially multi-part icon merging."""

import numpy as np

from app.services.segmentation import detect_crops


def blank_sheet(height: int = 200, width: int = 400) -> np.ndarray:
    return np.full((height, width), 255, dtype=np.uint8)


def test_disconnected_parts_of_one_icon_merge_into_one_crop():
    """An outer ring plus a detached glyph inside it is one icon, not two."""
    sheet = blank_sheet()
    sheet[40:100, 40:100] = 0  # outer block
    sheet[50:60, 110:120] = 0  # detached part 8px to the right

    crops = detect_crops(sheet)

    assert len(crops) == 1
    assert crops[0].x <= 40
    assert crops[0].x + crops[0].width >= 120


def test_well_separated_icons_stay_separate():
    sheet = blank_sheet()
    sheet[40:100, 20:80] = 0
    sheet[40:100, 300:360] = 0  # far beyond the merge distance

    crops = detect_crops(sheet)

    assert len(crops) == 2


def test_speckle_below_min_area_is_ignored():
    sheet = blank_sheet()
    sheet[40:100, 40:100] = 0
    sheet[150, 350] = 0  # single-pixel JPEG speckle

    crops = detect_crops(sheet)

    assert len(crops) == 1


def test_crops_are_returned_in_reading_order():
    sheet = blank_sheet()
    sheet[20:60, 200:240] = 0  # top-right
    sheet[20:60, 20:60] = 0  # top-left
    sheet[140:180, 20:60] = 0  # bottom-left

    crops = detect_crops(sheet)

    assert [crop.id for crop in crops] == ["crop-0", "crop-1", "crop-2"]
    assert crops[0].x < crops[1].x  # top row, left before right
    assert crops[2].y > crops[0].y  # bottom row last


def test_padding_is_applied_once_not_per_part():
    sheet = blank_sheet()
    sheet[40:100, 40:100] = 0
    sheet[50:60, 110:120] = 0

    crops = detect_crops(sheet, padding=5)

    assert crops[0].x == 35.0
    assert crops[0].x + crops[0].width == 125.0


def test_crop_touching_sheet_edge_is_flagged():
    sheet = blank_sheet()
    sheet[0:40, 0:40] = 0

    crops = detect_crops(sheet)

    assert crops[0].touches_edge is True
