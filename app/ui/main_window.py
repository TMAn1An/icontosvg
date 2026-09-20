"""Main application window: tab container and undo stack owner."""

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QMainWindow, QTabWidget

from app.ui.tabs.export_tab import ExportTab
from app.ui.tabs.import_tab import ImportTab
from app.ui.tabs.names_tab import NamesTab
from app.ui.tabs.reconstruct_tab import ReconstructTab
from app.ui.tabs.slices_tab import SlicesTab
from app.ui.theme import DARK_QSS


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Icon Sheet Studio")
        self.setStyleSheet(DARK_QSS)

        self.undo_stack = QUndoStack(self)

        tabs = QTabWidget()
        tabs.addTab(ImportTab(), "Import")
        tabs.addTab(SlicesTab(self.undo_stack), "Slices")
        tabs.addTab(NamesTab(self.undo_stack), "Names")
        tabs.addTab(ReconstructTab(), "Reconstruct")
        tabs.addTab(ExportTab(), "Export")
        self.setCentralWidget(tabs)
