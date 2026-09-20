"""Quality evaluation: multiple independent signals, no single auto-verdict.

manual_review_status always starts and stays "pending" here — only the
user, after actually looking at the rendered SVG, may change it. Automated
signals inform the Quality tab; they never substitute for that review.
"""

from __future__ import annotations

import numpy as np
from skimage.metrics import structural_similarity

from app.domain.models import QualityReport


def compute_ssim(rendered_rgb: np.ndarray, original_rgb: np.ndarray) -> float:
    if rendered_rgb.shape != original_rgb.shape:
        raise ValueError("rendered and original images must be the same shape for SSIM")
    return float(
        structural_similarity(rendered_rgb, original_rgb, channel_axis=2, data_range=255)
    )


def compute_edge_alignment(rendered_edges: np.ndarray, original_edges: np.ndarray) -> float:
    """Fraction of original edge pixels that have a rendered edge pixel nearby."""
    if rendered_edges.shape != original_edges.shape:
        raise ValueError("edge maps must be the same shape")
    original_count = int(original_edges.sum())
    if original_count == 0:
        return 1.0
    overlap = int(np.logical_and(rendered_edges, original_edges).sum())
    return overlap / original_count


def compute_stroke_width_consistency(stroke_widths: list[float]) -> float:
    """1.0 = perfectly consistent, lower = more variance relative to the mean."""
    if not stroke_widths:
        return 1.0
    widths = np.array(stroke_widths, dtype=float)
    mean_width = widths.mean()
    if mean_width == 0:
        return 1.0
    coefficient_of_variation = widths.std() / mean_width
    return float(max(0.0, 1.0 - coefficient_of_variation))


def count_fragments(component_labels: np.ndarray, expected_components: int) -> int:
    """Extra connected components beyond what was expected (accidental fragments)."""
    found = int(component_labels.max())
    return max(0, found - expected_components)


def build_quality_report(
    ssim: float | None = None,
    edge_alignment: float | None = None,
    stroke_width_consistency: float | None = None,
    anchor_count: int | None = None,
    fragment_count: int | None = None,
    warnings: list[str] | None = None,
) -> QualityReport:
    return QualityReport(
        ssim=ssim,
        edge_alignment=edge_alignment,
        stroke_width_consistency=stroke_width_consistency,
        anchor_count=anchor_count,
        fragment_count=fragment_count,
        manual_review_status="pending",
        warnings=warnings or [],
    )
