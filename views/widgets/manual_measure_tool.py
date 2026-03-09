# Ideato e Realizzato da Pierpaolo Careddu

"""
ManualMeasureTool — Pannello di controllo per la misura manuale.

Questo widget è il companion panel del LiveViewWidget per la modalità
di misura manuale punto-a-punto. Mentre il LiveView gestisce il click
e il rendering visivo (linea, punti, label), questo widget fornisce:

- Pulsanti Attiva/Disattiva la misura manuale
- Display della misura corrente in mm (con fattore di calibrazione)
- Storico delle misure manuali effettuate nella sessione
- Pulsante per cancellare lo storico
- Indicazione dello stato della calibrazione

Il widget si aggiorna via Signal/Slot dal LiveViewWidget e applica
il fattore di calibrazione dal CalibrationEngine.

Light Theme: colori espliciti compatibili con theme_industriale.qss.
"""

import logging
from typing import Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QListWidget, QListWidgetItem, QSizePolicy,
    QAbstractItemView, QGroupBox
)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QFont, QColor, QBrush

from core.calibration_engine import CalibrationEngine

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASS PER MISURA MANUALE
# ═══════════════════════════════════════════════════════════════

class ManualMeasureEntry:
    """Registrazione di una singola misura manuale."""

    def __init__(
        self,
        index: int,
        distance_px: float,
        distance_mm: float,
        is_calibrated: bool,
        timestamp: datetime,
    ):
        self.index = index
        self.distance_px = distance_px
        self.distance_mm = distance_mm
        self.is_calibrated = is_calibrated
        self.timestamp = timestamp


# ═══════════════════════════════════════════════════════════════
# WIDGET PRINCIPALE
# ═══════════════════════════════════════════════════════════════

class ManualMeasureTool(QWidget):
    """
    Pannello di controllo per la misura manuale.

    Signals:
        manual_mode_requested(bool): Richiesta attivazione/disattivazione
        clear_requested(): Richiesta cancellazione misure manuali
    """

    manual_mode_requested = Signal(bool)
    clear_requested = Signal()

    def __init__(
        self,
        calibration_engine: CalibrationEngine,
        parent=None,
    ):
        super().__init__(parent)

        self._cal_engine = calibration_engine
        self._is_active: bool = False
        self._entries: list[ManualMeasureEntry] = []
        self._next_index: int = 1

        self._setup_ui()
        self._connect_signals()
        self._update_calibration_status()

    def _setup_ui(self):
        """Costruisce l'interfaccia — Light Theme."""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ─── Container ───
        container = QGroupBox("📐  MISURA MANUALE")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(12, 22, 12, 12)
        container_layout.setSpacing(10)

        # ─── Stato calibrazione ───
        self._lbl_cal_status = QLabel("")
        self._lbl_cal_status.setFont(QFont("Segoe UI", 8))
        self._lbl_cal_status.setWordWrap(True)
        container_layout.addWidget(self._lbl_cal_status)

        # ─── Pulsante attiva/disattiva ───
        self._btn_toggle = QPushButton("📐  Attiva Misura Manuale")
        self._btn_toggle.setCheckable(True)
        self._btn_toggle.setMinimumHeight(36)
        self._btn_toggle.setFont(
            QFont("Segoe UI", 10, QFont.Weight.Bold)
        )
        self._btn_toggle.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF; color: #374151;
                border: 2px solid #D1D5DB; border-radius: 6px;
                padding: 8px 16px;
            }
            QPushButton:hover {
                background-color: #F0F7FF; border-color: #0066B3;
                color: #0066B3;
            }
            QPushButton:checked {
                background-color: #DBEAFE; color: #0066B3;
                border-color: #0066B3;
            }
        """)
        container_layout.addWidget(self._btn_toggle)

        # ─── Display misura corrente ───
        self._lbl_current_title = QLabel("Ultima misura:")
        self._lbl_current_title.setFont(QFont("Segoe UI", 9))
        self._lbl_current_title.setStyleSheet(
            "color: #6B7280; background: transparent;"
        )
        container_layout.addWidget(self._lbl_current_title)

        self._lbl_current_value = QLabel("— mm")
        self._lbl_current_value.setFont(
            QFont("Consolas", 20, QFont.Weight.Bold)
        )
        self._lbl_current_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_current_value.setStyleSheet(
            "color: #0066B3; background: transparent; padding: 4px;"
        )
        self._lbl_current_value.setMinimumHeight(40)
        container_layout.addWidget(self._lbl_current_value)

        self._lbl_current_px = QLabel("")
        self._lbl_current_px.setFont(QFont("Consolas", 9))
        self._lbl_current_px.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_current_px.setStyleSheet(
            "color: #9CA3AF; background: transparent;"
        )
        container_layout.addWidget(self._lbl_current_px)

        # ─── Storico misure ───
        history_header = QHBoxLayout()
        lbl_history = QLabel("Storico misure:")
        lbl_history.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_history.setStyleSheet(
            "color: #374151; background: transparent;"
        )
        history_header.addWidget(lbl_history)

        history_header.addStretch()

        self._lbl_count = QLabel("0")
        self._lbl_count.setFont(QFont("Consolas", 9))
        self._lbl_count.setStyleSheet(
            "color: #6B7280; background: transparent;"
        )
        history_header.addWidget(self._lbl_count)

        container_layout.addLayout(history_header)

        self._list_history = QListWidget()
        self._list_history.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._list_history.setMinimumHeight(100)
        self._list_history.setMaximumHeight(200)
        self._list_history.setFont(QFont("Consolas", 9))
        self._list_history.setStyleSheet("""
            QListWidget {
                background-color: #FFFFFF;
                color: #1C1C1E;
                border: 1px solid #E5E7EB;
                border-radius: 4px;
                outline: none;
            }
            QListWidget::item {
                padding: 4px 8px;
                border-bottom: 1px solid #F0F1F3;
            }
            QListWidget::item:selected {
                background-color: #DBEAFE;
                color: #1C1C1E;
            }
            QListWidget::item:hover {
                background-color: #F0F7FF;
            }
        """)
        container_layout.addWidget(self._list_history, 1)

        # ─── Statistiche rapide ───
        self._lbl_stats = QLabel("")
        self._lbl_stats.setFont(QFont("Consolas", 8))
        self._lbl_stats.setStyleSheet(
            "color: #6B7280; background: transparent;"
        )
        self._lbl_stats.setWordWrap(True)
        container_layout.addWidget(self._lbl_stats)

        # ─── Pulsante cancella ───
        self._btn_clear = QPushButton("🗑  Cancella Tutto")
        self._btn_clear.setMinimumHeight(30)
        self._btn_clear.setEnabled(False)
        container_layout.addWidget(self._btn_clear)

        main_layout.addWidget(container)

    def _connect_signals(self):
        """Collega i segnali interni."""
        self._btn_toggle.toggled.connect(self._on_toggle_clicked)
        self._btn_clear.clicked.connect(self._on_clear_clicked)

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA
    # ═══════════════════════════════════════════════════════════

    @Slot(float, float)
    def on_manual_measure_completed(
        self, distance_px: float, distance_mm: float
    ):
        """
        Riceve una misura manuale completata dal LiveViewWidget.

        Se la calibrazione è disponibile, calcola la distanza in mm.
        Altrimenti mostra solo la distanza in pixel.
        """
        # Calcola mm se calibrato
        is_calibrated = self._cal_engine.is_calibrated
        if is_calibrated and distance_mm <= 0:
            distance_mm = distance_px * self._cal_engine.scale_factor

        # Crea entry
        entry = ManualMeasureEntry(
            index=self._next_index,
            distance_px=distance_px,
            distance_mm=distance_mm,
            is_calibrated=is_calibrated,
            timestamp=datetime.now(),
        )
        self._entries.append(entry)
        self._next_index += 1

        # Aggiorna display corrente
        if is_calibrated:
            self._lbl_current_value.setText(f"{distance_mm:.3f} mm")
            self._lbl_current_value.setStyleSheet(
                "color: #059669; background: transparent; "
                "padding: 4px; font-weight: bold;"
            )
        else:
            self._lbl_current_value.setText(f"{distance_px:.1f} px")
            self._lbl_current_value.setStyleSheet(
                "color: #D97706; background: transparent; "
                "padding: 4px; font-weight: bold;"
            )
        self._lbl_current_px.setText(f"({distance_px:.1f} px)")

        # Aggiorna storico
        self._add_history_item(entry)

        # Aggiorna statistiche
        self._update_statistics()

        # Abilita cancella
        self._btn_clear.setEnabled(True)

        # Aggiorna misura mm nel LiveView
        from views.widgets.live_view_widget import LiveViewWidget
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, '_live_view'):
                parent._live_view.update_last_manual_measurement_mm(
                    distance_mm
                )
                break
            parent = parent.parent()

        logger.debug(
            f"Misura manuale #{entry.index}: "
            f"{distance_px:.1f} px = {distance_mm:.3f} mm"
        )

    @Slot()
    def on_calibration_changed(self):
        """Chiamato quando la calibrazione cambia."""
        self._update_calibration_status()

        # Ricalcola tutte le misure con il nuovo fattore
        if self._cal_engine.is_calibrated:
            scale = self._cal_engine.scale_factor
            for entry in self._entries:
                entry.distance_mm = entry.distance_px * scale
                entry.is_calibrated = True

            # Ricostruisci la lista
            self._list_history.clear()
            for entry in self._entries:
                self._add_history_item(entry)

            self._update_statistics()

    # ═══════════════════════════════════════════════════════════
    # SLOT INTERNI
    # ═══════════════════════════════════════════════════════════

    @Slot(bool)
    def _on_toggle_clicked(self, checked: bool):
        """Toggle attivazione misura manuale."""
        self._is_active = checked
        if checked:
            self._btn_toggle.setText("📐  Disattiva Misura Manuale")
        else:
            self._btn_toggle.setText("📐  Attiva Misura Manuale")
        self.manual_mode_requested.emit(checked)

    @Slot()
    def _on_clear_clicked(self):
        """Cancella tutte le misure manuali."""
        self._entries.clear()
        self._next_index = 1
        self._list_history.clear()
        self._lbl_current_value.setText("— mm")
        self._lbl_current_value.setStyleSheet(
            "color: #0066B3; background: transparent; padding: 4px;"
        )
        self._lbl_current_px.setText("")
        self._lbl_stats.setText("")
        self._lbl_count.setText("0")
        self._btn_clear.setEnabled(False)
        self.clear_requested.emit()

    # ═══════════════════════════════════════════════════════════
    # DISPLAY
    # ═══════════════════════════════════════════════════════════

    def _add_history_item(self, entry: ManualMeasureEntry):
        """Aggiunge un elemento alla lista storico."""
        if entry.is_calibrated:
            text = (
                f"#{entry.index:3d}  │  {entry.distance_mm:8.3f} mm  │  "
                f"{entry.distance_px:7.1f} px  │  "
                f"{entry.timestamp.strftime('%H:%M:%S')}"
            )
            color = QColor("#1C1C1E")
        else:
            text = (
                f"#{entry.index:3d}  │  {entry.distance_px:7.1f} px  │  "
                f"(non calibrato)  │  "
                f"{entry.timestamp.strftime('%H:%M:%S')}"
            )
            color = QColor("#D97706")

        item = QListWidgetItem(text)
        item.setForeground(QBrush(color))
        self._list_history.addItem(item)
        self._list_history.scrollToBottom()
        self._lbl_count.setText(str(len(self._entries)))

    def _update_statistics(self):
        """Aggiorna le statistiche rapide."""
        if not self._entries:
            self._lbl_stats.setText("")
            return

        calibrated = [e for e in self._entries if e.is_calibrated]
        if not calibrated:
            self._lbl_stats.setText(
                f"Totale: {len(self._entries)} misure (non calibrate)"
            )
            return

        values = [e.distance_mm for e in calibrated]
        n = len(values)
        mean_val = sum(values) / n
        min_val = min(values)
        max_val = max(values)

        if n >= 2:
            variance = sum((v - mean_val) ** 2 for v in values) / (n - 1)
            std_val = variance ** 0.5
            self._lbl_stats.setText(
                f"N={n}  │  μ={mean_val:.3f}  │  σ={std_val:.4f}  │  "
                f"min={min_val:.3f}  │  max={max_val:.3f} mm"
            )
        else:
            self._lbl_stats.setText(
                f"N={n}  │  Valore: {mean_val:.3f} mm"
            )

    def _update_calibration_status(self):
        """Aggiorna il label di stato calibrazione."""
        if self._cal_engine.is_calibrated:
            scale = self._cal_engine.scale_factor
            if self._cal_engine.is_expired:
                self._lbl_cal_status.setText(
                    f"⚠️ Calibrazione scaduta "
                    f"(scala: {scale:.6f} mm/px)"
                )
                self._lbl_cal_status.setStyleSheet(
                    "color: #D97706; background: transparent;"
                )
            else:
                self._lbl_cal_status.setText(
                    f"✓ Calibrato: {scale:.6f} mm/px"
                )
                self._lbl_cal_status.setStyleSheet(
                    "color: #059669; background: transparent;"
                )
        else:
            self._lbl_cal_status.setText(
                "⚠️ Non calibrato — le misure saranno solo in pixel"
            )
            self._lbl_cal_status.setStyleSheet(
                "color: #DC2626; background: transparent;"
            )

    # ═══════════════════════════════════════════════════════════
    # PROPRIETÀ
    # ═══════════════════════════════════════════════════════════

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def entries(self) -> list[ManualMeasureEntry]:
        return list(self._entries)

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def sizeHint(self) -> QSize:
        return QSize(260, 450)

    def minimumSizeHint(self) -> QSize:
        return QSize(220, 300)