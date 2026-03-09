# Ideato e Realizzato da Pierpaolo Careddu

"""
FocusAssistWidget — Widget standalone per assistenza alla messa a fuoco.

Visualizza:
- Barra verticale con indicatore di sharpness
- Valore numerico percentuale
- Storico sharpness (sparkline)
- Indicatore colore (rosso→giallo→verde)
- Valore di picco (best focus raggiunto)

Può essere usato nel pannello sinistro o come overlay sul LiveView.

Light Theme compatibile con theme_industriale.qss.
"""

import logging
from typing import Optional
from collections import deque

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QSizePolicy, QProgressBar
)
from PySide6.QtCore import Qt, Signal, Slot, QSize, QRectF, QPointF
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPaintEvent,
    QLinearGradient
)

logger = logging.getLogger(__name__)


class SharpnessSparkline(QWidget):
    """Mini grafico sparkline della sharpness nel tempo."""

    def __init__(self, max_points: int = 60, parent=None):
        super().__init__(parent)
        self._values: deque[float] = deque(maxlen=max_points)
        self._max_value: float = 100.0
        self.setFixedHeight(40)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )

    def add_value(self, value: float):
        self._values.append(value)
        if value > self._max_value * 0.8:
            self._max_value = value * 1.3
        self.update()

    def clear(self):
        self._values.clear()
        self._max_value = 100.0
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        w, h = rect.width(), rect.height()

        painter.fillRect(rect, QColor("#F9FAFB"))
        painter.setPen(QPen(QColor("#E5E7EB"), 1))
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 3, 3)

        if len(self._values) < 2:
            painter.setPen(QPen(QColor("#9CA3AF")))
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "...")
            painter.end()
            return

        margin = 4
        pw = w - margin * 2
        ph = h - margin * 2
        n = len(self._values)
        max_v = max(self._max_value, 1.0)

        points = []
        for i, v in enumerate(self._values):
            px = margin + (i / max(n - 1, 1)) * pw
            py = margin + ph - (v / max_v) * ph
            points.append(QPointF(px, py))

        # Colore basato sull'ultimo valore
        last_norm = min(1.0, list(self._values)[-1] / max_v)
        if last_norm > 0.6:
            color = QColor("#059669")
        elif last_norm > 0.3:
            color = QColor("#D97706")
        else:
            color = QColor("#DC2626")

        pen = QPen(color, 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i + 1])

        painter.end()


class FocusAssistWidget(QWidget):
    """
    Widget standalone per assistenza messa a fuoco.

    Signals:
        focus_quality_changed(float): Qualità fuoco normalizzata 0.0-1.0
    """

    focus_quality_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._sharpness: float = 0.0
        self._sharpness_max: float = 500.0
        self._peak_sharpness: float = 0.0
        self._normalized: float = 0.0

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        group = QGroupBox("🔍  ASSISTENZA FUOCO")
        gl = QVBoxLayout(group)
        gl.setContentsMargins(12, 22, 12, 12)
        gl.setSpacing(6)

        # Valore percentuale grande
        self._lbl_value = QLabel("—%")
        self._lbl_value.setFont(QFont("Consolas", 22, QFont.Weight.Bold))
        self._lbl_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_value.setStyleSheet("color:#6B7280;background:transparent;")
        gl.addWidget(self._lbl_value)

        # Barra di progresso
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setTextVisible(False)
        self._progress.setFixedHeight(14)
        self._progress.setStyleSheet("""
            QProgressBar {
                background-color: #E5E7EB; border: none;
                border-radius: 7px;
            }
            QProgressBar::chunk {
                background-color: #6B7280; border-radius: 7px;
            }
        """)
        gl.addWidget(self._progress)

        # Info
        info_row = QHBoxLayout()
        info_row.setSpacing(8)

        self._lbl_current = QLabel("Corrente: —")
        self._lbl_current.setFont(QFont("Consolas", 8))
        self._lbl_current.setStyleSheet("color:#6B7280;background:transparent;")
        info_row.addWidget(self._lbl_current)

        info_row.addStretch()

        self._lbl_peak = QLabel("Picco: —")
        self._lbl_peak.setFont(QFont("Consolas", 8))
        self._lbl_peak.setStyleSheet("color:#0066B3;background:transparent;")
        info_row.addWidget(self._lbl_peak)

        gl.addLayout(info_row)

        # Sparkline
        self._sparkline = SharpnessSparkline()
        gl.addWidget(self._sparkline)

        # Suggerimento
        self._lbl_hint = QLabel("Regolare la messa a fuoco")
        self._lbl_hint.setFont(QFont("Segoe UI", 8))
        self._lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_hint.setStyleSheet("color:#9CA3AF;background:transparent;")
        gl.addWidget(self._lbl_hint)

        layout.addWidget(group)

    @Slot(float)
    def update_sharpness(self, value: float):
        """Aggiorna il valore di sharpness."""
        self._sharpness = value

        # Aggiorna il massimo dinamico
        if value > self._sharpness_max * 0.8:
            self._sharpness_max = value * 1.3

        # Aggiorna il picco
        if value > self._peak_sharpness:
            self._peak_sharpness = value

        # Normalizza
        self._normalized = min(1.0, value / max(self._sharpness_max, 1.0))

        # Colore
        pct = int(self._normalized * 100)
        if self._normalized > 0.6:
            color = "#059669"
            chunk_color = "#059669"
            hint = "✓ Fuoco ottimo"
        elif self._normalized > 0.3:
            color = "#D97706"
            chunk_color = "#D97706"
            hint = "Regolare leggermente"
        else:
            color = "#DC2626"
            chunk_color = "#DC2626"
            hint = "⚠️ Fuori fuoco"

        self._lbl_value.setText(f"{pct}%")
        self._lbl_value.setStyleSheet(
            f"color:{color};background:transparent;"
        )

        self._progress.setValue(pct)
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: #E5E7EB; border: none;
                border-radius: 7px;
            }}
            QProgressBar::chunk {{
                background-color: {chunk_color}; border-radius: 7px;
            }}
        """)

        self._lbl_current.setText(f"Corrente: {value:.0f}")
        self._lbl_peak.setText(f"Picco: {self._peak_sharpness:.0f}")
        self._lbl_hint.setText(hint)

        self._sparkline.add_value(value)
        self.focus_quality_changed.emit(self._normalized)

    def reset_peak(self):
        self._peak_sharpness = 0.0
        self._sparkline.clear()
        self._lbl_peak.setText("Picco: —")

    def sizeHint(self):
        return QSize(250, 200)