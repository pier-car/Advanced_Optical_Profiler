# Ideato e Realizzato da Pierpaolo Careddu

"""
VisualToolsPanel — Pannello strumenti di visualizzazione.

Controlla le opzioni di overlay del LiveView:
- Mostra/nascondi bordi rilevati
- Mostra/nascondi barra fuoco
- Mostra/nascondi istogramma
- Mostra/nascondi crosshair
- Mostra/nascondi griglia
- Zoom preset (1x, 2x, 4x, Fit)

Light Theme compatibile con theme_industriale.qss.
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QCheckBox, QGroupBox, QSizePolicy, QButtonGroup
)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)


class VisualToolsPanel(QWidget):
    """
    Pannello strumenti di visualizzazione standalone.

    Signals:
        show_edges_changed(bool)
        show_focus_bar_changed(bool)
        show_histogram_changed(bool)
        show_crosshair_changed(bool)
        show_grid_changed(bool)
        zoom_preset_requested(float): Fattore zoom richiesto (0.0 = fit)
        reset_zoom_requested()
    """

    show_edges_changed = Signal(bool)
    show_focus_bar_changed = Signal(bool)
    show_histogram_changed = Signal(bool)
    show_crosshair_changed = Signal(bool)
    show_grid_changed = Signal(bool)
    zoom_preset_requested = Signal(float)
    reset_zoom_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Overlay ──
        overlay_group = QGroupBox("🎨  OVERLAY")
        ol = QVBoxLayout(overlay_group)
        ol.setContentsMargins(12, 22, 12, 12)
        ol.setSpacing(6)

        self._chk_edges = QCheckBox("Mostra bordi rilevati")
        self._chk_edges.setChecked(True)
        ol.addWidget(self._chk_edges)

        self._chk_focus = QCheckBox("Barra assistenza fuoco")
        self._chk_focus.setChecked(True)
        ol.addWidget(self._chk_focus)

        self._chk_histogram = QCheckBox("Istogramma luminosità")
        self._chk_histogram.setChecked(True)
        ol.addWidget(self._chk_histogram)

        self._chk_crosshair = QCheckBox("Crosshair centrale")
        self._chk_crosshair.setChecked(False)
        ol.addWidget(self._chk_crosshair)

        self._chk_grid = QCheckBox("Griglia di riferimento")
        self._chk_grid.setChecked(False)
        ol.addWidget(self._chk_grid)

        layout.addWidget(overlay_group)

        # ── Zoom ──
        zoom_group = QGroupBox("🔍  ZOOM")
        zl = QVBoxLayout(zoom_group)
        zl.setContentsMargins(12, 22, 12, 12)
        zl.setSpacing(6)

        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(4)

        self._btn_fit = QPushButton("Fit")
        self._btn_fit.setMinimumHeight(28)
        self._btn_fit.setToolTip("Adatta al widget")
        zoom_row.addWidget(self._btn_fit)

        self._btn_1x = QPushButton("1x")
        self._btn_1x.setMinimumHeight(28)
        zoom_row.addWidget(self._btn_1x)

        self._btn_2x = QPushButton("2x")
        self._btn_2x.setMinimumHeight(28)
        zoom_row.addWidget(self._btn_2x)

        self._btn_4x = QPushButton("4x")
        self._btn_4x.setMinimumHeight(28)
        zoom_row.addWidget(self._btn_4x)

        zl.addLayout(zoom_row)

        hint = QLabel(
            "Rotella mouse: zoom libero\n"
            "Pulsante centrale: pan\n"
            "Doppio click: reset"
        )
        hint.setFont(QFont("Segoe UI", 7))
        hint.setStyleSheet("color:#9CA3AF;background:transparent;")
        zl.addWidget(hint)

        layout.addWidget(zoom_group)

    def _connect_signals(self):
        self._chk_edges.toggled.connect(self.show_edges_changed.emit)
        self._chk_focus.toggled.connect(self.show_focus_bar_changed.emit)
        self._chk_histogram.toggled.connect(self.show_histogram_changed.emit)
        self._chk_crosshair.toggled.connect(self.show_crosshair_changed.emit)
        self._chk_grid.toggled.connect(self.show_grid_changed.emit)

        self._btn_fit.clicked.connect(lambda: self.zoom_preset_requested.emit(0.0))
        self._btn_1x.clicked.connect(lambda: self.zoom_preset_requested.emit(1.0))
        self._btn_2x.clicked.connect(lambda: self.zoom_preset_requested.emit(2.0))
        self._btn_4x.clicked.connect(lambda: self.zoom_preset_requested.emit(4.0))

    def sizeHint(self):
        return QSize(250, 280)