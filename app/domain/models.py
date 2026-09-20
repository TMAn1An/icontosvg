"""Core domain models for a project: sheet, crops, icons, and style settings.

These are plain dataclasses so they serialize cleanly via project_store.py
and stay independent of any UI or service-layer framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReconstructionMode(str, Enum):
    """Which reconstruction strategy an icon should use.

    All three modes are first-class from the start so the pipeline and
    UI never need to special-case "line" as the only option later.
    """

    LINE = "line"
    FILLED = "filled"
    MIXED = "mixed"


@dataclass
class Crop:
    id: str
    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0
    touches_edge: bool = False
    uncertain_grouping: bool = False


@dataclass
class IconName:
    value: str
    is_manual: bool = False
    confidence: float | None = None


@dataclass
class QualityReport:
    ssim: float | None = None
    edge_alignment: float | None = None
    stroke_width_consistency: float | None = None
    anchor_count: int | None = None
    fragment_count: int | None = None
    manual_review_status: str = "pending"
    warnings: list[str] = field(default_factory=list)


@dataclass
class Icon:
    id: str
    crop: Crop
    name: IconName
    reconstruction_mode: ReconstructionMode = ReconstructionMode.LINE
    svg_document: str | None = None
    quality: QualityReport = field(default_factory=QualityReport)


@dataclass
class SourceSheet:
    file_path: str
    file_hash: str
    width: int
    height: int


@dataclass
class Project:
    name: str
    source: SourceSheet
    icons: list[Icon] = field(default_factory=list)
