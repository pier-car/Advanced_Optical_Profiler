# Ideato e Realizzato da Pierpaolo Careddu

"""
StatusBarWidget — Barra di stato inferiore per la MainWindow.

Mostra in modo strutturato e sempre visibile:
- LED + stato camera (connessa/disconnessa)
- LED + stato calibrazione (calibrato/non calibrato/scaduto + scala)
- Stato sessione (nome prova attiva + contatore misure)
- Operatore corrente
- Messaggio temporaneo (ultimo evento)
- Orologio in tempo reale

Layout orizzontale con separatori, altezza fissa 28px.
Compatibile con theme_industriale.qss.
"""

import logging
from datetime import datetime

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Slot, QTimer, QSize
from PySide6.QtGui import QFont

logger = logging.getLogger(__name__)


class StatusSeparator(QFrame):
    """Separatore verticale sottile tra sezioni."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.VLine)
        self.setFixedWidth(1)
        self.setFixedHeight(18)
        self.setStyleSheet("background:#D1D5DB;")


class StatusLed(QFrame):
    """LED circolare piccolo per indicatori di stato."""

    COLOR_GREEN = "#059669"
    COLOR_RED = "#DC2626"
    COLOR_YELLOW = "#D97706"
    COLOR_GRAY = "#9CA3AF"

    def __init__(self, diameter: int = 8, parent=None):
        super().__init__(parent)
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)
        self.set_color(self.COLOR_GRAY)

    def set_color(self, hex_color: str):
        self.setStyleSheet(
            f"QFrame{{"
            f"  background-color:{hex_color};"
            f"  border-radius:{self._diameter // 2}px;"
            f"  border:none;"
            f"}}"
        )

    def set_green(self):
        self.set_color(self.COLOR_GREEN)

    def set_red(self):
        self.set_color(self.COLOR_RED)

    def set_yellow(self):
        self.set_color(self.COLOR_YELLOW)

    def set_gray(self):
        self.set_color(self.COLOR_GRAY)


class StatusBarWidget(QWidget):
    """
    Barra di stato inferiore con sezioni strutturate.

    Sezioni (da sinistra a destra):
    [LED Camera][LED Cal][Sessione][--- Messaggio ---][Operatore][Orologio]
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self.setStyleSheet(
            "QWidget{background:#F9FAFB;border-top:1px solid #D1D5DB;}"
        )

        self._temp_message_timer = QTimer(self)
        self._temp_message_timer.setSingleShot(True)
        self._temp_message_timer.timeout.connect(self._clear_temp_message)

        self._setup_ui()
        self._start_clock()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(0)

        base_font = QFont("Segoe UI", 8)
        mono_font = QFont("Consolas", 8)

        # ── Sezione Camera ──
        cam_container = QHBoxLayout()
        cam_container.setSpacing(4)
        cam_container.setContentsMargins(0, 0, 8, 0)

        self._led_camera = StatusLed(8)
        cam_container.addWidget(self._led_camera)

        self._lbl_camera = QLabel("Camera: —")
        self._lbl_camera.setFont(base_font)
        self._lbl_camera.setStyleSheet(
            "color:#6B7280;background:transparent;border:none;"
        )
        cam_container.addWidget(self._lbl_camera)
        layout.addLayout(cam_container)

        layout.addWidget(StatusSeparator())
        layout.addSpacing(8)

        # ── Sezione Calibrazione ──
        cal_container = QHBoxLayout()
        cal_container.setSpacing(4)
        cal_container.setContentsMargins(0, 0, 8, 0)

        self._led_cal = StatusLed(8)
        cal_container.addWidget(self._led_cal)

        self._lbl_cal = QLabel("Cal: —")
        self._lbl_cal.setFont(base_font)
        self._lbl_cal.setStyleSheet(
            "color:#6B7280;background:transparent;border:none;"
        )
        cal_container.addWidget(self._lbl_cal)
        layout.addLayout(cal_container)

        layout.addWidget(StatusSeparator())
        layout.addSpacing(8)

        # ── Sezione Sessione ──
        session_container = QHBoxLayout()
        session_container.setSpacing(4)
        session_container.setContentsMargins(0, 0, 8, 0)

        self._lbl_session = QLabel("Prova: —")
        self._lbl_session.setFont(base_font)
        self._lbl_session.setStyleSheet(
            "color:#6B7280;background:transparent;border:none;"
        )
        session_container.addWidget(self._lbl_session)

        self._lbl_count = QLabel("")
        self._lbl_count.setFont(mono_font)
        self._lbl_count.setStyleSheet(
            "color:#0066B3;background:transparent;border:none;"
        )
        session_container.addWidget(self._lbl_count)
        layout.addLayout(session_container)

        layout.addWidget(StatusSeparator())
        layout.addSpacing(8)

        # ── Messaggio temporaneo (si espande) ──
        self._lbl_message = QLabel("")
        self._lbl_message.setFont(base_font)
        self._lbl_message.setStyleSheet(
            "color:#374151;background:transparent;border:none;"
        )
        self._lbl_message.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._lbl_message.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._lbl_message)

        # ── Sezione Operatore ──
        layout.addWidget(StatusSeparator())
        layout.addSpacing(8)

        op_container = QHBoxLayout()
        op_container.setSpacing(4)
        op_container.setContentsMargins(0, 0, 8, 0)

        lbl_op_icon = QLabel("👤")
        lbl_op_icon.setFont(base_font)
        lbl_op_icon.setStyleSheet("background:transparent;border:none;")
        op_container.addWidget(lbl_op_icon)

        self._lbl_operator = QLabel("—")
        self._lbl_operator.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        self._lbl_operator.setStyleSheet(
            "color:#0066B3;background:transparent;border:none;"
        )
        op_container.addWidget(self._lbl_operator)
        layout.addLayout(op_container)

        # ── Orologio ──
        layout.addWidget(StatusSeparator())
        layout.addSpacing(8)

        self._lbl_clock = QLabel("--:--:--")
        self._lbl_clock.setFont(mono_font)
        self._lbl_clock.setFixedWidth(55)
        self._lbl_clock.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._lbl_clock.setStyleSheet(
            "color:#6B7280;background:transparent;border:none;"
        )
        layout.addWidget(self._lbl_clock)

    def _start_clock(self):
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

    @Slot()
    def _update_clock(self):
        self._lbl_clock.setText(datetime.now().strftime("%H:%M:%S"))

    @Slot()
    def _clear_temp_message(self):
        self._lbl_message.setText("")

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA — Camera
    # ═══════════════════════════════════════════════════════════

    @Slot(bool)
    def update_camera_status(self, connected: bool):
        """Aggiorna LED e testo camera."""
        if connected:
            self._led_camera.set_green()
            self._lbl_camera.setText("Camera: ON")
            self._lbl_camera.setStyleSheet(
                "color:#059669;background:transparent;border:none;"
            )
        else:
            self._led_camera.set_red()
            self._lbl_camera.setText("Camera: OFF")
            self._lbl_camera.setStyleSheet(
                "color:#DC2626;background:transparent;border:none;"
            )

    @Slot(str)
    def update_camera_model(self, model: str):
        """Aggiorna il testo con il modello camera."""
        short = model[:25] + "…" if len(model) > 25 else model
        self._lbl_camera.setText(f"Camera: {short}")

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA — Calibrazione
    # ═══════════════════════════════════════════════════════════

    @Slot(bool, str)
    def update_calibration_status(self, calibrated: bool, detail: str = ""):
        """
        Aggiorna LED e testo calibrazione.

        Args:
            calibrated: True se calibrato
            detail: Testo aggiuntivo (es. "0.025000 mm/px")
        """
        if calibrated:
            if detail:
                self._lbl_cal.setText(f"Cal: {detail}")
            else:
                self._lbl_cal.setText("Cal: ✓")
            self._lbl_cal.setStyleSheet(
                "color:#059669;background:transparent;border:none;"
            )
            self._led_cal.set_green()
        else:
            self._lbl_cal.setText("Cal: ✗ Non calibrato")
            self._lbl_cal.setStyleSheet(
                "color:#DC2626;background:transparent;border:none;"
            )
            self._led_cal.set_red()

    @Slot()
    def set_calibration_expired(self):
        """Mostra calibrazione scaduta con LED giallo."""
        self._led_cal.set_yellow()
        self._lbl_cal.setText("Cal: ⚠ Scaduta")
        self._lbl_cal.setStyleSheet(
            "color:#D97706;background:transparent;border:none;"
        )

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA — Sessione
    # ═══════════════════════════════════════════════════════════

    @Slot(str)
    def update_session_name(self, name: str):
        """Mostra il nome della prova attiva."""
        if name:
            short = name[:20] + "…" if len(name) > 20 else name
            self._lbl_session.setText(f"Prova: {short}")
            self._lbl_session.setStyleSheet(
                "color:#059669;background:transparent;border:none;"
            )
        else:
            self._lbl_session.setText("Prova: —")
            self._lbl_session.setStyleSheet(
                "color:#6B7280;background:transparent;border:none;"
            )
            self._lbl_count.setText("")

    @Slot(int)
    def update_measure_count(self, count: int):
        """Aggiorna il contatore misure della sessione."""
        if count > 0:
            self._lbl_count.setText(f"[{count}]")
        else:
            self._lbl_count.setText("")

    @Slot()
    def clear_session(self):
        """Pulisce le info sessione (prova terminata)."""
        self._lbl_session.setText("Prova: —")
        self._lbl_session.setStyleSheet(
            "color:#6B7280;background:transparent;border:none;"
        )
        self._lbl_count.setText("")

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA — Operatore
    # ═══════════════════════════════════════════════════════════

    @Slot(str)
    def update_operator(self, operator_id: str):
        """Mostra l'operatore corrente."""
        if operator_id:
            self._lbl_operator.setText(operator_id)
        else:
            self._lbl_operator.setText("—")

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA — Messaggi temporanei
    # ═══════════════════════════════════════════════════════════

    @Slot(str)
    def show_message(self, text: str, duration_ms: int = 5000):
        """
        Mostra un messaggio temporaneo nella barra.
        Scompare dopo duration_ms millisecondi.
        """
        self._lbl_message.setText(text)
        self._temp_message_timer.stop()
        if duration_ms > 0:
            self._temp_message_timer.start(duration_ms)

    @Slot(str)
    def show_persistent_message(self, text: str):
        """Mostra un messaggio che resta finché non viene sostituito."""
        self._temp_message_timer.stop()
        self._lbl_message.setText(text)

    @Slot()
    def clear_message(self):
        """Pulisce il messaggio corrente."""
        self._temp_message_timer.stop()
        self._lbl_message.setText("")

    def sizeHint(self) -> QSize:
        return QSize(800, 28)