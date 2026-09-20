"""Export tab: export the current icon as a single validated SVG file."""

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class ExportTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Export the reconstructed icon as SVG."))
        layout.addWidget(QPushButton("Export SVG..."))
        layout.addStretch()
