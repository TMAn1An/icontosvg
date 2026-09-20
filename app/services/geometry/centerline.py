"""Centerline extraction for line icons.

Pipeline: binarize -> skeletonize -> trace the skeleton as a graph of
branches -> prune spurs -> simplify each branch.

Works only on the skeleton, never on the raw contour, so it cannot
degrade into tracing both sides of a blurry stroke (see
docs/reference/rough-conversion-reference.png for the failure mode this
avoids).
"""

from __future__ import annotations

import cv2
import numpy as np
from skimage.morphology import skeletonize

Pixel = tuple[int, int]  # (row, col)

_NEIGHBOR_OFFSETS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)


def binarize_for_skeleton(grayscale: np.ndarray, threshold: int = 200) -> np.ndarray:
    return grayscale < threshold


def extract_skeleton(binary: np.ndarray) -> np.ndarray:
    return skeletonize(binary)


def estimate_stroke_width(binary: np.ndarray, skeleton: np.ndarray) -> tuple[float, np.ndarray]:
    """Estimate stroke width from the distance transform at skeleton pixels.

    Returns (median width, per-skeleton-pixel widths). The distance
    transform gives the distance to the nearest background pixel, so twice
    that at the centerline is the local stroke width.
    """
    distance = cv2.distanceTransform(binary.astype(np.uint8), cv2.DIST_L2, 5)
    widths = 2.0 * distance[skeleton]
    if widths.size == 0:
        return 0.0, widths
    return float(np.median(widths)), widths


def _neighbors(skeleton: np.ndarray, pixel: Pixel) -> list[Pixel]:
    row, col = pixel
    height, width = skeleton.shape
    found = []
    for d_row, d_col in _NEIGHBOR_OFFSETS:
        n_row, n_col = row + d_row, col + d_col
        if 0 <= n_row < height and 0 <= n_col < width and skeleton[n_row, n_col]:
            found.append((n_row, n_col))
    return found


def _neighbor_group_count(skeleton: np.ndarray, pixel: Pixel) -> int:
    """Number of distinct neighbor clusters around a skeleton pixel.

    Counting raw 8-neighbors misclassifies diagonal staircases (a plain
    path pixel can have 3 mutually-adjacent neighbors). Grouping adjacent
    neighbors together gives the topological degree: 1 = endpoint,
    2 = path, 3+ = junction.
    """
    neighbors = _neighbors(skeleton, pixel)
    if not neighbors:
        return 0

    unassigned = list(neighbors)
    groups = 0
    while unassigned:
        stack = [unassigned.pop()]
        groups += 1
        while stack:
            current = stack.pop()
            for candidate in list(unassigned):
                if (
                    abs(candidate[0] - current[0]) <= 1
                    and abs(candidate[1] - current[1]) <= 1
                ):
                    unassigned.remove(candidate)
                    stack.append(candidate)
    return groups


def trace_branches(skeleton: np.ndarray) -> list[np.ndarray]:
    """Trace the skeleton into branches of connected pixels.

    A branch runs between two nodes (endpoints or junctions), or all the
    way around a closed loop that contains neither. Returned arrays are
    (N, 2) in x/y order, ready for simplification.
    """
    skeleton = skeleton.astype(bool)
    pixels = [(int(row), int(col)) for row, col in zip(*np.where(skeleton))]
    if not pixels:
        return []

    degrees = {pixel: _neighbor_group_count(skeleton, pixel) for pixel in pixels}
    nodes = {pixel for pixel, degree in degrees.items() if degree != 2}

    visited_edges: set[frozenset[Pixel]] = set()
    branches: list[list[Pixel]] = []

    def walk(start: Pixel, first: Pixel) -> list[Pixel]:
        path = [start, first]
        visited_edges.add(frozenset((start, first)))
        previous, current = start, first
        while current not in nodes:
            candidates = [
                candidate
                for candidate in _neighbors(skeleton, current)
                if candidate != previous
                and frozenset((current, candidate)) not in visited_edges
            ]
            if not candidates:
                break
            # Prefer a step that leaves the previous pixel's neighborhood,
            # so diagonal staircases advance instead of doubling back.
            candidates.sort(
                key=lambda candidate: (
                    abs(candidate[0] - previous[0]) <= 1
                    and abs(candidate[1] - previous[1]) <= 1
                )
            )
            next_pixel = candidates[0]
            visited_edges.add(frozenset((current, next_pixel)))
            path.append(next_pixel)
            previous, current = current, next_pixel
        return path

    for node in sorted(nodes):
        for neighbor in _neighbors(skeleton, node):
            if frozenset((node, neighbor)) in visited_edges:
                continue
            branches.append(walk(node, neighbor))

    # Closed loops with no endpoint or junction are untouched by the walk
    # above; trace each remaining component as a cycle.
    covered = {pixel for branch in branches for pixel in branch}
    remaining = [pixel for pixel in pixels if pixel not in covered]
    while remaining:
        start = remaining[0]
        neighbors = _neighbors(skeleton, start)
        if not neighbors:
            remaining.pop(0)
            continue
        loop = walk(start, neighbors[0])
        if loop[-1] != start:
            loop.append(start)  # close the cycle
        branches.append(loop)
        covered.update(loop)
        remaining = [pixel for pixel in remaining if pixel not in covered]

    # Convert (row, col) to (x, y).
    return [np.array([(col, row) for row, col in branch], dtype=np.float64) for branch in branches]


def prune_spurs(
    branches: list[np.ndarray], skeleton: np.ndarray, stroke_width: float
) -> list[np.ndarray]:
    """Drop short dead-end branches created by stroke caps and corners.

    A spur is a branch with a free end whose length is under roughly one
    stroke width — too short to be intended geometry.
    """
    if stroke_width <= 0:
        return branches

    skeleton = skeleton.astype(bool)
    min_length = stroke_width * 1.2

    kept = []
    for branch in branches:
        length = float(np.sum(np.hypot(*np.diff(branch, axis=0).T))) if len(branch) > 1 else 0.0
        if length >= min_length:
            kept.append(branch)
            continue

        start_pixel = (int(branch[0][1]), int(branch[0][0]))
        end_pixel = (int(branch[-1][1]), int(branch[-1][0]))
        has_free_end = (
            _neighbor_group_count(skeleton, start_pixel) == 1
            or _neighbor_group_count(skeleton, end_pixel) == 1
        )
        if not has_free_end:
            kept.append(branch)
    return kept


def is_closed(branch: np.ndarray, tolerance: float = 2.0) -> bool:
    return bool(len(branch) > 3 and np.hypot(*(branch[0] - branch[-1])) <= tolerance)


def simplify_branch(branch: np.ndarray, epsilon: float, closed: bool) -> np.ndarray:
    """Ramer-Douglas-Peucker simplification, via OpenCV's implementation."""
    if len(branch) <= 2:
        return branch
    contour = branch.astype(np.float32).reshape(-1, 1, 2)
    simplified = cv2.approxPolyDP(contour, epsilon, closed)
    return simplified.reshape(-1, 2).astype(np.float64)
