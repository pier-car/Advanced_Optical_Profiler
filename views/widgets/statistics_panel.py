# Ideato e Realizzato da Pierpaolo Careddu

"""
StatisticsPanel v3 — Card compatte + layout fluido per QSplitter.

Fix critici rispetto a v2:
- StatCard con altezza FISSA (62px normali, 48px compact)
- Nessun setMaximumHeight sul pannello — il QSplitter decide
- OkNokBar 18px, DistributionChart 75px
- Font ridotti per riga 2 (compact)
- Container con spacing 4px per massimizzare densità
- SizePolicy Expanding verticale per adattarsi al splitter
"""

import logging
import numpy as np
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Slot, QSize, QRectF, QPointF
from PySide6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush, QPaintEvent,
    QLinearGradient
)

from core.statistics_model import StatisticsSnapshot, ToleranceLimits

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# PALETTE
# ═══════════════════════════════════════════════════════════════

class PanelColors:
    CARD_BG = "#FFFFFF"
    CARD_BORDER = "#E5E7EB"
    CARD_BORDER_OK = "#059669"
    CARD_BORDER_NOK = "#DC2626"
    TEXT_PRIMARY = "#1C1C1E"
    TEXT_SECONDARY = "#6B7280"
    TEXT_LABEL = "#9CA3AF"
    ACCENT_BLUE = "#0066B3"
    ACCENT_GREEN = "#059669"
    ACCENT_AMBER = "#D97706"
    ACCENT_RED = "#DC2626"
    CHART_BG = "#F9FAFB"
    CHART_BAR_OK = QColor(0, 102, 179, 160)
    CHART_BAR_NOK = QColor(220, 38, 38, 160)
    CHART_MEAN_LINE = QColor(28, 28, 30, 200)
    CHART_LIMIT_LINE = QColor(220, 38, 38, 180)
    CHART_NOMINAL_LINE = QColor(5, 150, 105, 140)


# ═══════════════════════════════════════════════════════════════
# STAT CARD
# ═══════════════════════════════════════════════════════════════

class StatCard(QFrame):
    """Card numerica singola. Due varianti: normale (62px) e compact (48px)."""

    def __init__(self, label, unit="mm", font_size=18,
                 accent_color=PanelColors.TEXT_PRIMARY,
                 compact=False, parent=None):
        super().__init__(parent)
        self._unit = unit
        self._accent_color = accent_color
        self._value = 0.0
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._apply_default_style()

        layout = QVBoxLayout(self)
        if compact:
            layout.setContentsMargins(8, 4, 8, 4)
            layout.setSpacing(1)
        else:
            layout.setContentsMargins(8, 6, 8, 6)
            layout.setSpacing(2)

        lbl_size = 7 if compact else 8
        self._lbl_title = QLabel(label)
        self._lbl_title.setFont(QFont("Segoe UI", lbl_size, QFont.Weight.Bold))
        self._lbl_title.setStyleSheet(
            f"color:{PanelColors.TEXT_LABEL};background:transparent;border:none;"
        )
        self._lbl_title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._lbl_title)

        self._lbl_value = QLabel(f"— {unit}")
        self._lbl_value.setFont(QFont("Consolas", font_size, QFont.Weight.Bold))
        self._lbl_value.setStyleSheet(
            f"color:{accent_color};background:transparent;border:none;"
        )
        self._lbl_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._lbl_value)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(48 if compact else 62)

    def _apply_default_style(self):
        self.setStyleSheet(
            f"QFrame{{background:{PanelColors.CARD_BG};"
            f"border:1px solid {PanelColors.CARD_BORDER};border-radius:5px;}}"
        )

    def set_value(self, value, fmt="{:.3f}"):
        self._value = value
        self._lbl_value.setText(f"{fmt.format(value)} {self._unit}")

    def set_value_text(self, text):
        self._lbl_value.setText(text)

    def set_accent_color(self, color):
        self._accent_color = color
        self._lbl_value.setStyleSheet(
            f"color:{color};background:transparent;border:none;"
        )

    def set_border_color(self, color):
        self.setStyleSheet(
            f"QFrame{{background:{PanelColors.CARD_BG};"
            f"border:2px solid {color};border-radius:5px;}}"
        )

    def reset_border(self):
        self._apply_default_style()

    @property
    def value(self):
        return self._value


# ═══════════════════════════════════════════════════════════════
# DISTRIBUTION CHART
# ═══════════════════════════════════════════════════════════════

class DistributionChart(QWidget):
    """Mini istogramma distribuzione misure."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._values = []
        self._nominal = 0.0
        self._lsl = float('-inf')
        self._usl = float('inf')
        self._mean = 0.0
        self._n_bins = 30
        self.setMinimumHeight(60)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

    def update_data(self, values, mean, nominal, lsl, usl):
        self._values = values
        self._mean = mean
        self._nominal = nominal
        self._lsl = lsl
        self._usl = usl
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        w, h = rect.width(), rect.height()

        painter.fillRect(rect, QColor(PanelColors.CHART_BG))
        painter.setPen(QPen(QColor(PanelColors.CARD_BORDER), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 4, 4)

        if len(self._values) < 2:
            painter.setPen(QPen(QColor(PanelColors.TEXT_LABEL)))
            painter.setFont(QFont("Segoe UI", 8))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "In attesa di dati...")
            painter.end()
            return

        values = np.array(self._values)
        ml, mr, mt, mb = 6, 6, 8, 14
        pw = w - ml - mr
        ph = h - mt - mb

        v_min, v_max = values.min(), values.max()
        dr = v_max - v_min
        if dr < 1e-9:
            bw = pw * 0.2
            bx = ml + (pw - bw) / 2
            bh = ph * 0.7
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(PanelColors.CHART_BAR_OK))
            painter.drawRoundedRect(QRectF(bx, mt + ph - bh, bw, bh), 2, 2)
            painter.end()
            return

        d_min = v_min - dr * 0.1
        d_max = v_max + dr * 0.1
        if self._lsl != float('-inf'):
            d_min = min(d_min, self._lsl - dr * 0.05)
        if self._usl != float('inf'):
            d_max = max(d_max, self._usl + dr * 0.05)
        d_range = max(d_max - d_min, 1e-9)

        nb = min(self._n_bins, max(5, len(values) // 2))
        counts, edges = np.histogram(values, bins=nb, range=(v_min, v_max))
        mc = max(counts.max(), 1)

        def vtx(val):
            return ml + (val - d_min) / d_range * pw

        for i in range(len(counts)):
            if counts[i] == 0:
                continue
            x1, x2 = vtx(edges[i]), vtx(edges[i + 1])
            bh = (counts[i] / mc) * ph * 0.85
            by = mt + ph - bh
            bc = (edges[i] + edges[i + 1]) / 2.0
            oos = ((self._lsl != float('-inf') and bc < self._lsl) or
                   (self._usl != float('inf') and bc > self._usl))
            color = PanelColors.CHART_BAR_NOK if oos else PanelColors.CHART_BAR_OK
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(color))
            painter.drawRoundedRect(QRectF(x1, by, max(1.0, x2 - x1 - 1), bh), 1, 1)

        mx = vtx(self._mean)
        painter.setPen(QPen(PanelColors.CHART_MEAN_LINE, 2))
        painter.drawLine(QPointF(mx, mt), QPointF(mx, mt + ph))
        painter.setFont(QFont("Consolas", 6))
        painter.drawText(QPointF(mx + 2, mt + 8), f"μ={self._mean:.3f}")

        if self._lsl != float('-inf'):
            lx = vtx(self._lsl)
            painter.setPen(QPen(PanelColors.CHART_LIMIT_LINE, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(lx, mt), QPointF(lx, mt + ph))

        if self._usl != float('inf'):
            ux = vtx(self._usl)
            painter.setPen(QPen(PanelColors.CHART_LIMIT_LINE, 1, Qt.PenStyle.DashLine))
            painter.drawLine(QPointF(ux, mt), QPointF(ux, mt + ph))

        painter.end()


# ═══════════════════════════════════════════════════════════════
# OK/NOK BAR
# ═══════════════════════════════════════════════════════════════

class OkNokBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._ok_pct = 0.0
        self._count_ok = 0
        self._count_nok = 0
        self.setFixedHeight(18)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def update_data(self, ok_pct, count_ok, count_nok):
        self._ok_pct = ok_pct
        self._count_ok = count_ok
        self._count_nok = count_nok
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect()
        w, h = rect.width(), rect.height()
        total = self._count_ok + self._count_nok
        painter.fillRect(rect, QColor("#F0F1F3"))
        if total == 0:
            painter.setPen(QPen(QColor(PanelColors.TEXT_LABEL)))
            painter.setFont(QFont("Segoe UI", 7))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "Nessuna misura")
            painter.end()
            return
        ok_w = (self._ok_pct / 100.0) * w
        if ok_w > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(5, 150, 105, 180)))
            painter.drawRoundedRect(QRectF(0, 0, ok_w, h), 3, 3)
        if self._count_nok > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(220, 38, 38, 180)))
            painter.drawRoundedRect(QRectF(ok_w, 0, w - ok_w, h), 3, 3)
        painter.setPen(QPen(QColor("#FFFFFF")))
        painter.setFont(QFont("Segoe UI", 7, QFont.Weight.Bold))
        painter.drawText(
            rect, Qt.AlignmentFlag.AlignCenter,
            f"OK: {self._count_ok} ({self._ok_pct:.0f}%)  │  NOK: {self._count_nok}"
        )
        painter.end()


# ═══════════════════════════════════════════════════════════════
# STATISTICS PANEL
# ═══════════════════════════════════════════════════════════════

class StatisticsPanel(QWidget):
    """
    Pannello statistiche completo. Si adatta al QSplitter:
    - minimumHeight 120px (compresso mostra solo riga 1 + barra)
    - Expanding verticale: il grafico si espande con lo spazio
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_snapshot = None
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        container = QFrame()
        container.setStyleSheet(
            f"QFrame{{background:{PanelColors.CARD_BG};"
            f"border:1px solid {PanelColors.CARD_BORDER};border-radius:6px;}}"
        )
        cl = QVBoxLayout(container)
        cl.setContentsMargins(8, 6, 8, 6)
        cl.setSpacing(4)

        # Header
        hl = QHBoxLayout()
        title = QLabel("📈  STATISTICHE")
        title.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        title.setStyleSheet(
            f"color:{PanelColors.ACCENT_BLUE};background:transparent;border:none;"
        )
        hl.addWidget(title)
        hl.addStretch()
        cl.addLayout(hl)

        # Riga 1: card normali (62px)
        r1 = QHBoxLayout()
        r1.setSpacing(4)
        self._card_last = StatCard("ULTIMA", "mm", 20, PanelColors.ACCENT_BLUE)
        self._card_last.setMinimumWidth(130)
        r1.addWidget(self._card_last, 2)
        self._card_mean = StatCard("MEDIA (μ)", "mm", 16, PanelColors.TEXT_PRIMARY)
        r1.addWidget(self._card_mean, 1)
        self._card_std = StatCard("σ", "mm", 16, PanelColors.ACCENT_AMBER)
        r1.addWidget(self._card_std, 1)
        self._card_min = StatCard("MIN", "mm", 16, PanelColors.TEXT_SECONDARY)
        r1.addWidget(self._card_min, 1)
        self._card_max = StatCard("MAX", "mm", 16, PanelColors.TEXT_SECONDARY)
        r1.addWidget(self._card_max, 1)
        cl.addLayout(r1)

        # Riga 2: card compact (48px)
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        self._card_range = StatCard("RANGE", "mm", 12, PanelColors.TEXT_SECONDARY, compact=True)
        r2.addWidget(self._card_range, 1)
        self._card_median = StatCard("MEDIANA", "mm", 12, PanelColors.TEXT_PRIMARY, compact=True)
        r2.addWidget(self._card_median, 1)
        self._card_count = StatCard("N", "", 12, PanelColors.ACCENT_BLUE, compact=True)
        r2.addWidget(self._card_count, 1)
        self._card_ok_pct = StatCard("OK%", "%", 12, PanelColors.ACCENT_GREEN, compact=True)
        r2.addWidget(self._card_ok_pct, 1)
        self._card_cp = StatCard("Cp", "", 12, PanelColors.TEXT_SECONDARY, compact=True)
        r2.addWidget(self._card_cp, 1)
        self._card_cpk = StatCard("Cpk", "", 12, PanelColors.TEXT_SECONDARY, compact=True)
        r2.addWidget(self._card_cpk, 1)
        cl.addLayout(r2)

        # Barra OK/NOK
        self._ok_nok_bar = OkNokBar()
        cl.addWidget(self._ok_nok_bar)

        # Grafico — si ESPANDE con lo spazio disponibile
        self._distribution_chart = DistributionChart()
        cl.addWidget(self._distribution_chart, 1)

        main_layout.addWidget(container)

    @Slot(object)
    def update_statistics(self, snapshot):
        if not isinstance(snapshot, StatisticsSnapshot):
            return
        self._last_snapshot = snapshot
        s = snapshot

        if s.count_valid > 0:
            self._card_last.set_value(s.last_value_mm)
            self._card_mean.set_value(s.mean_mm)
            self._card_std.set_value(s.std_mm, fmt="{:.4f}")
            self._card_min.set_value(s.min_mm)
            self._card_max.set_value(s.max_mm)
            self._card_range.set_value(s.range_mm)
            self._card_median.set_value(s.median_mm)
            self._card_count.set_value_text(f"{s.count_valid}/{s.count}")
            self._card_ok_pct.set_value(s.ok_percentage, fmt="{:.1f}")
        else:
            for c in [self._card_last, self._card_mean, self._card_std,
                       self._card_min, self._card_max, self._card_range,
                       self._card_median]:
                c.set_value_text("— mm")
            self._card_count.set_value_text("0/0")
            self._card_ok_pct.set_value_text("— %")

        if s.cp > 0:
            self._card_cp.set_value(s.cp, fmt="{:.2f}")
            self._card_cpk.set_value(s.cpk, fmt="{:.2f}")
            if s.cpk >= 1.33:
                self._card_cpk.set_accent_color(PanelColors.ACCENT_GREEN)
                self._card_cpk.set_border_color(PanelColors.CARD_BORDER_OK)
            elif s.cpk >= 1.0:
                self._card_cpk.set_accent_color(PanelColors.ACCENT_AMBER)
                self._card_cpk.set_border_color(PanelColors.ACCENT_AMBER)
            else:
                self._card_cpk.set_accent_color(PanelColors.ACCENT_RED)
                self._card_cpk.set_border_color(PanelColors.CARD_BORDER_NOK)
            if s.cp >= 1.33:
                self._card_cp.set_accent_color(PanelColors.ACCENT_GREEN)
            elif s.cp >= 1.0:
                self._card_cp.set_accent_color(PanelColors.ACCENT_AMBER)
            else:
                self._card_cp.set_accent_color(PanelColors.ACCENT_RED)
        else:
            self._card_cp.set_value_text("—")
            self._card_cpk.set_value_text("—")
            self._card_cp.set_accent_color(PanelColors.TEXT_LABEL)
            self._card_cpk.set_accent_color(PanelColors.TEXT_LABEL)
            self._card_cpk.reset_border()

        if s.count_valid > 0:
            if s.ok_percentage >= 100.0:
                self._card_ok_pct.set_accent_color(PanelColors.ACCENT_GREEN)
            elif s.ok_percentage >= 90.0:
                self._card_ok_pct.set_accent_color(PanelColors.ACCENT_AMBER)
            else:
                self._card_ok_pct.set_accent_color(PanelColors.ACCENT_RED)

        if (s.tolerance is not None and s.tolerance.is_configured
                and s.count_valid > 0):
            if s.tolerance.is_within_tolerance(s.last_value_mm):
                self._card_last.set_accent_color(PanelColors.ACCENT_GREEN)
                self._card_last.set_border_color(PanelColors.CARD_BORDER_OK)
            else:
                self._card_last.set_accent_color(PanelColors.ACCENT_RED)
                self._card_last.set_border_color(PanelColors.CARD_BORDER_NOK)
        else:
            self._card_last.set_accent_color(PanelColors.ACCENT_BLUE)
            self._card_last.reset_border()

        self._ok_nok_bar.update_data(s.ok_percentage, s.count_ok, s.count_nok)

        tol = s.tolerance or ToleranceLimits()
        self._distribution_chart.update_data(
            values=s.values_mm, mean=s.mean_mm,
            nominal=tol.nominal_mm, lsl=tol.lower_limit_mm, usl=tol.upper_limit_mm,
        )

    @Slot()
    def reset_display(self):
        self.update_statistics(StatisticsSnapshot())

    @property
    def last_snapshot(self):
        return self._last_snapshot

    def sizeHint(self):
        return QSize(800, 260)

    def minimumSizeHint(self):
        return QSize(500, 120)