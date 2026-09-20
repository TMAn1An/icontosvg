"""Import tab: load a raster icon sheet and preview it."""

from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget


class ImportTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Drop a JPG, PNG, or WebP icon sheet, or choose a file."))
        layout.addWidget(QPushButton("Choose file..."))
        layout.addStretch()
