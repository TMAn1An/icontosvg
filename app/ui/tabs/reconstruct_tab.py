"""Reconstruct tab: side-by-side raster crop vs. rendered SVG preview."""

from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget


class ReconstructTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.raster_view = QLabel("Original crop")
        self.svg_view = QSvgWidget()
        layout = QHBoxLayout(self)
        layout.addWidget(self.raster_view)
        layout.addWidget(self.svg_view)
