"""Unit tests for centerline extraction and primitive fitting."""

import numpy as np

from app.services.geometry.centerline import (
    binarize_for_skeleton,
    extract_skeleton,
    skeleton_to_segments,
)
from app.services.geometry.primitives import LineSegment, snap_angle


def test_snap_angle_snaps_near_horizontal_noise():
    assert snap_angle(2.0) == 0.0
    assert snap_angle(-1.5) == 0.0
    assert snap_angle(88.0) == 90.0


def test_snap_angle_leaves_non_axis_angles_alone():
    assert snap_angle(30.0) == 30.0


def test_line_segment_length_and_angle():
    segment = LineSegment(x1=0, y1=0, x2=10, y2=0)
    assert segment.length == 10.0
    assert segment.angle_degrees == 0.0


def test_skeleton_to_segments_on_synthetic_horizontal_line():
    image = np.full((20, 40), 255, dtype=np.uint8)
    image[10, 5:35] = 0

    binary = binarize_for_skeleton(image)
    skeleton = extract_skeleton(binary)
    segments = skeleton_to_segments(skeleton)

    assert len(segments) == 1
    assert segments[0].angle_degrees == 0.0
    assert segments[0].length > 20
