"""Names tab: show and edit the suggested name for each icon."""

from PySide6.QtGui import QUndoStack
from PySide6.QtWidgets import QListWidget, QVBoxLayout, QWidget


class NamesTab(QWidget):
    def __init__(self, undo_stack: QUndoStack) -> None:
        super().__init__()
        self._undo_stack = undo_stack
        self.list_widget = QListWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.list_widget)
