# Ideato e Realizzato da Pierpaolo Careddu

"""
CameraControlPanel — Pannello hardware per controllo telecamera Basler.

Funzionalità:
- Connessione / Disconnessione camera
- Slider + SpinBox sincronizzati per Esposizione (μs)
- Slider + SpinBox sincronizzati per Guadagno (dB)
- Indicatore stato connessione (LED colorato)
- Info modello camera e FPS live
- Pulsante Start/Stop acquisizione video

Il pannello emette segnali puri: non importa CameraManager né
AcquisitionController. La MainWindow si occupa di collegare
i segnali ai controller appropriati.

Layout compatto, compatibile con sidebar sinistra 260px.
"""

import logging

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSlider, QSpinBox, QDoubleSpinBox, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QFont, QColor

logger = logging.getLogger(__name__)

# Range di default — sovrascritti dalla MainWindow se necessario
DEFAULT_EXPOSURE_MIN = 100
DEFAULT_EXPOSURE_MAX = 200000
DEFAULT_EXPOSURE_VAL = 15000

DEFAULT_GAIN_MIN = 0.0
DEFAULT_GAIN_MAX = 24.0
DEFAULT_GAIN_VAL = 0.0


class LedIndicator(QFrame):
    """LED circolare colorato per stato connessione."""

    def __init__(self, diameter: int = 12, parent=None):
        super().__init__(parent)
        self._diameter = diameter
        self.setFixedSize(diameter, diameter)
        self._set_color("#9CA3AF")  # Grigio: sconosciuto

    def _set_color(self, hex_color: str):
        self.setStyleSheet(
            f"QFrame{{"
            f"  background-color:{hex_color};"
            f"  border-radius:{self._diameter // 2}px;"
            f"  border:1px solid rgba(0,0,0,0.15);"
            f"}}"
        )

    def set_connected(self):
        self._set_color("#059669")

    def set_disconnected(self):
        self._set_color("#DC2626")

    def set_idle(self):
        self._set_color("#9CA3AF")

    def set_warning(self):
        self._set_color("#D97706")


class CameraControlPanel(QWidget):
    """
    Pannello hardware telecamera Basler.

    Signals:
        connect_requested()
        disconnect_requested()
        start_grabbing_requested()
        stop_grabbing_requested()
        exposure_changed(int): Esposizione in μs
        gain_changed(float): Guadagno in dB
    """

    connect_requested = Signal()
    disconnect_requested = Signal()
    start_grabbing_requested = Signal()
    stop_grabbing_requested = Signal()
    exposure_changed = Signal(int)
    gain_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._is_connected: bool = False
        self._is_grabbing: bool = False
        self._setup_ui()
        self._connect_internal_signals()

    def _setup_ui(self):
        self.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ═══════════════════════════════════════════════════
        # SEZIONE: CONNESSIONE
        # ═══════════════════════════════════════════════════
        conn_frame = QFrame()
        conn_frame.setStyleSheet(
            "QFrame{background:#FFFFFF;border:1px solid #E5E7EB;"
            "border-radius:6px;}"
        )
        conn_layout = QVBoxLayout(conn_frame)
        conn_layout.setContentsMargins(12, 10, 12, 10)
        conn_layout.setSpacing(8)

        # Titolo sezione
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        lbl_title = QLabel("📷  TELECAMERA")
        lbl_title.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        lbl_title.setStyleSheet("color:#374151;background:transparent;border:none;")
        title_row.addWidget(lbl_title)
        title_row.addStretch()
        conn_layout.addLayout(title_row)

        # Stato connessione: LED + testo + modello
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._led = LedIndicator(12)
        status_row.addWidget(self._led)
        self._lbl_status = QLabel("Disconnessa")
        self._lbl_status.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._lbl_status.setStyleSheet("color:#6B7280;background:transparent;border:none;")
        status_row.addWidget(self._lbl_status)
        status_row.addStretch()
        self._lbl_fps = QLabel("")
        self._lbl_fps.setFont(QFont("Consolas", 8))
        self._lbl_fps.setStyleSheet("color:#0066B3;background:transparent;border:none;")
        status_row.addWidget(self._lbl_fps)
        conn_layout.addLayout(status_row)

        self._lbl_model = QLabel("")
        self._lbl_model.setFont(QFont("Segoe UI", 8))
        self._lbl_model.setStyleSheet("color:#9CA3AF;background:transparent;border:none;")
        self._lbl_model.setWordWrap(True)
        self._lbl_model.setVisible(False)
        conn_layout.addWidget(self._lbl_model)

        # Pulsanti connessione
        btn_conn_row = QHBoxLayout()
        btn_conn_row.setSpacing(6)

        self._btn_connect = QPushButton("🔌 Connetti")
        self._btn_connect.setMinimumHeight(30)
        self._btn_connect.setFont(QFont("Segoe UI", 9))
        self._btn_connect.setStyleSheet(
            "QPushButton{background:#059669;color:white;border:none;"
            "border-radius:4px;padding:4px 12px;}"
            "QPushButton:hover{background:#047857;}"
            "QPushButton:disabled{background:#D1D5DB;color:#9CA3AF;}"
        )
        btn_conn_row.addWidget(self._btn_connect)

        self._btn_disconnect = QPushButton("⏏ Disconnetti")
        self._btn_disconnect.setMinimumHeight(30)
        self._btn_disconnect.setFont(QFont("Segoe UI", 9))
        self._btn_disconnect.setEnabled(False)
        self._btn_disconnect.setStyleSheet(
            "QPushButton{background:#F3F4F6;color:#374151;border:1px solid #D1D5DB;"
            "border-radius:4px;padding:4px 12px;}"
            "QPushButton:hover{background:#E5E7EB;}"
            "QPushButton:disabled{background:#F9FAFB;color:#D1D5DB;border-color:#E5E7EB;}"
        )
        btn_conn_row.addWidget(self._btn_disconnect)

        conn_layout.addLayout(btn_conn_row)

        # Pulsante Start/Stop video
        self._btn_grabbing = QPushButton("▶  Avvia Live")
        self._btn_grabbing.setMinimumHeight(32)
        self._btn_grabbing.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._btn_grabbing.setEnabled(False)
        self._btn_grabbing.setStyleSheet(
            "QPushButton{background:#0066B3;color:white;border:none;"
            "border-radius:4px;padding:6px 12px;}"
            "QPushButton:hover{background:#004A82;}"
            "QPushButton:disabled{background:#D1D5DB;color:#9CA3AF;}"
        )
        conn_layout.addWidget(self._btn_grabbing)

        root.addWidget(conn_frame)
        root.addSpacing(6)

        # ═══════════════════════════════════════════════════
        # SEZIONE: ESPOSIZIONE E GUADAGNO
        # ═══════════════════════════════════════════════════
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet(
            "QFrame{background:#FFFFFF;border:1px solid #E5E7EB;"
            "border-radius:6px;}"
        )
        ctrl_layout = QVBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(12, 10, 12, 10)
        ctrl_layout.setSpacing(6)

        lbl_ctrl = QLabel("🔆  PARAMETRI ACQUISIZIONE")
        lbl_ctrl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        lbl_ctrl.setStyleSheet("color:#374151;background:transparent;border:none;")
        ctrl_layout.addWidget(lbl_ctrl)

        # --- Esposizione ---
        exp_label_row = QHBoxLayout()
        exp_label_row.setSpacing(4)
        lbl_exp = QLabel("Esposizione")
        lbl_exp.setFont(QFont("Segoe UI", 8))
        lbl_exp.setStyleSheet("color:#6B7280;background:transparent;border:none;")
        exp_label_row.addWidget(lbl_exp)
        exp_label_row.addStretch()
        self._spin_exposure = QSpinBox()
        self._spin_exposure.setRange(DEFAULT_EXPOSURE_MIN, DEFAULT_EXPOSURE_MAX)
        self._spin_exposure.setValue(DEFAULT_EXPOSURE_VAL)
        self._spin_exposure.setSuffix(" μs")
        self._spin_exposure.setFont(QFont("Consolas", 8))
        self._spin_exposure.setFixedWidth(100)
        self._spin_exposure.setFixedHeight(24)
        self._spin_exposure.setStyleSheet("border:1px solid #D1D5DB;border-radius:3px;")
        exp_label_row.addWidget(self._spin_exposure)
        ctrl_layout.addLayout(exp_label_row)

        self._slider_exposure = QSlider(Qt.Orientation.Horizontal)
        self._slider_exposure.setRange(DEFAULT_EXPOSURE_MIN, DEFAULT_EXPOSURE_MAX)
        self._slider_exposure.setValue(DEFAULT_EXPOSURE_VAL)
        self._slider_exposure.setFixedHeight(20)
        ctrl_layout.addWidget(self._slider_exposure)

        ctrl_layout.addSpacing(4)

        # --- Guadagno ---
        gain_label_row = QHBoxLayout()
        gain_label_row.setSpacing(4)
        lbl_gain = QLabel("Guadagno")
        lbl_gain.setFont(QFont("Segoe UI", 8))
        lbl_gain.setStyleSheet("color:#6B7280;background:transparent;border:none;")
        gain_label_row.addWidget(lbl_gain)
        gain_label_row.addStretch()
        self._spin_gain = QDoubleSpinBox()
        self._spin_gain.setRange(DEFAULT_GAIN_MIN, DEFAULT_GAIN_MAX)
        self._spin_gain.setValue(DEFAULT_GAIN_VAL)
        self._spin_gain.setSingleStep(0.5)
        self._spin_gain.setDecimals(1)
        self._spin_gain.setSuffix(" dB")
        self._spin_gain.setFont(QFont("Consolas", 8))
        self._spin_gain.setFixedWidth(100)
        self._spin_gain.setFixedHeight(24)
        self._spin_gain.setStyleSheet("border:1px solid #D1D5DB;border-radius:3px;")
        gain_label_row.addWidget(self._spin_gain)
        ctrl_layout.addLayout(gain_label_row)

        self._slider_gain = QSlider(Qt.Orientation.Horizontal)
        self._slider_gain.setRange(
            int(DEFAULT_GAIN_MIN * 10),
            int(DEFAULT_GAIN_MAX * 10),
        )
        self._slider_gain.setValue(int(DEFAULT_GAIN_VAL * 10))
        self._slider_gain.setFixedHeight(20)
        ctrl_layout.addWidget(self._slider_gain)

        root.addWidget(ctrl_frame)

    def _connect_internal_signals(self):
        self._btn_connect.clicked.connect(self._on_connect_clicked)
        self._btn_disconnect.clicked.connect(self._on_disconnect_clicked)
        self._btn_grabbing.clicked.connect(self._on_grabbing_clicked)

        self._slider_exposure.valueChanged.connect(self._on_exposure_slider_moved)
        self._spin_exposure.valueChanged.connect(self._on_exposure_spin_changed)
        self._slider_gain.valueChanged.connect(self._on_gain_slider_moved)
        self._spin_gain.valueChanged.connect(self._on_gain_spin_changed)

    # ═══════════════════════════════════════════════════════════
    # HANDLER INTERNI — PULSANTI
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def _on_connect_clicked(self):
        self._btn_connect.setEnabled(False)
        self._btn_connect.setText("⏳ Connessione...")
        self.connect_requested.emit()

    @Slot()
    def _on_disconnect_clicked(self):
        self.disconnect_requested.emit()

    @Slot()
    def _on_grabbing_clicked(self):
        if self._is_grabbing:
            self.stop_grabbing_requested.emit()
        else:
            self.start_grabbing_requested.emit()

    # ═══════════════════════════════════════════════════════════
    # HANDLER INTERNI — SLIDER/SPIN SINCRONIZZAZIONE
    # ═══════════════════════════════════════════════════════════

    @Slot(int)
    def _on_exposure_slider_moved(self, value: int):
        self._spin_exposure.blockSignals(True)
        self._spin_exposure.setValue(value)
        self._spin_exposure.blockSignals(False)
        self.exposure_changed.emit(value)

    @Slot(int)
    def _on_exposure_spin_changed(self, value: int):
        self._slider_exposure.blockSignals(True)
        self._slider_exposure.setValue(value)
        self._slider_exposure.blockSignals(False)
        self.exposure_changed.emit(value)

    @Slot(int)
    def _on_gain_slider_moved(self, value_x10: int):
        db = value_x10 / 10.0
        self._spin_gain.blockSignals(True)
        self._spin_gain.setValue(db)
        self._spin_gain.blockSignals(False)
        self.gain_changed.emit(db)

    @Slot(float)
    def _on_gain_spin_changed(self, value_db: float):
        self._slider_gain.blockSignals(True)
        self._slider_gain.setValue(int(value_db * 10))
        self._slider_gain.blockSignals(False)
        self.gain_changed.emit(value_db)

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA — Chiamata dalla MainWindow
    # ═══════════════════════════════════════════════════════════

    @Slot(bool)
    def update_connection_state(self, connected: bool):
        """Aggiorna lo stato di connessione nel pannello."""
        self._is_connected = connected

        if connected:
            self._led.set_connected()
            self._lbl_status.setText("Connessa")
            self._lbl_status.setStyleSheet(
                "color:#059669;background:transparent;border:none;"
            )
            self._btn_connect.setText("🔌 Connetti")
            self._btn_connect.setEnabled(False)
            self._btn_disconnect.setEnabled(True)
            self._btn_grabbing.setEnabled(True)
        else:
            self._led.set_disconnected()
            self._lbl_status.setText("Disconnessa")
            self._lbl_status.setStyleSheet(
                "color:#DC2626;background:transparent;border:none;"
            )
            self._lbl_model.setVisible(False)
            self._lbl_fps.setText("")
            self._btn_connect.setText("🔌 Connetti")
            self._btn_connect.setEnabled(True)
            self._btn_disconnect.setEnabled(False)
            self._btn_grabbing.setEnabled(False)
            self._is_grabbing = False
            self._btn_grabbing.setText("▶  Avvia Live")
            self._btn_grabbing.setStyleSheet(
                "QPushButton{background:#0066B3;color:white;border:none;"
                "border-radius:4px;padding:6px 12px;}"
                "QPushButton:hover{background:#004A82;}"
                "QPushButton:disabled{background:#D1D5DB;color:#9CA3AF;}"
            )

    @Slot(bool)
    def update_grabbing_state(self, grabbing: bool):
        """Aggiorna lo stato di acquisizione video."""
        self._is_grabbing = grabbing
        if grabbing:
            self._btn_grabbing.setText("⏹  Ferma Live")
            self._btn_grabbing.setStyleSheet(
                "QPushButton{background:#DC2626;color:white;border:none;"
                "border-radius:4px;padding:6px 12px;}"
                "QPushButton:hover{background:#B91C1C;}"
            )
            self._btn_connect.setEnabled(False)
            self._btn_disconnect.setEnabled(False)
        else:
            self._btn_grabbing.setText("▶  Avvia Live")
            self._btn_grabbing.setStyleSheet(
                "QPushButton{background:#0066B3;color:white;border:none;"
                "border-radius:4px;padding:6px 12px;}"
                "QPushButton:hover{background:#004A82;}"
                "QPushButton:disabled{background:#D1D5DB;color:#9CA3AF;}"
            )
            if self._is_connected:
                self._btn_disconnect.setEnabled(True)
            self._lbl_fps.setText("")

    @Slot(str)
    def update_model_info(self, model: str):
        """Mostra il modello della camera."""
        self._lbl_model.setText(model)
        self._lbl_model.setVisible(True)

    @Slot(float)
    def update_fps(self, fps: float):
        """Aggiorna il contatore FPS."""
        if fps > 0:
            self._lbl_fps.setText(f"{fps:.1f} FPS")
        else:
            self._lbl_fps.setText("")

    def set_exposure_range(self, min_us: int, max_us: int, default_us: int):
        """Imposta il range dell'esposizione dal config."""
        self._slider_exposure.blockSignals(True)
        self._spin_exposure.blockSignals(True)
        self._slider_exposure.setRange(min_us, max_us)
        self._spin_exposure.setRange(min_us, max_us)
        self._slider_exposure.setValue(default_us)
        self._spin_exposure.setValue(default_us)
        self._slider_exposure.blockSignals(False)
        self._spin_exposure.blockSignals(False)

    def set_gain_range(self, min_db: float, max_db: float, default_db: float):
        """Imposta il range del guadagno dal config."""
        self._slider_gain.blockSignals(True)
        self._spin_gain.blockSignals(True)
        self._slider_gain.setRange(int(min_db * 10), int(max_db * 10))
        self._spin_gain.setRange(min_db, max_db)
        self._slider_gain.setValue(int(default_db * 10))
        self._spin_gain.setValue(default_db)
        self._slider_gain.blockSignals(False)
        self._spin_gain.blockSignals(False)

    def get_exposure(self) -> int:
        """Restituisce il valore corrente di esposizione in μs."""
        return self._spin_exposure.value()

    def get_gain(self) -> float:
        """Restituisce il valore corrente di guadagno in dB."""
        return self._spin_gain.value()

    def sizeHint(self) -> QSize:
        return QSize(260, 310)