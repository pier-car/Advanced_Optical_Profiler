# Ideato e Realizzato da Pierpaolo Careddu

"""
TestSetupDialog — Dialog per configurare una nuova prova di misura.

Layout pulito: nessun GroupBox (evita il problema del top margin),
usa QFrame con titolo manuale per separazione visiva.
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QLineEdit, QFormLayout, QMessageBox,
    QFrame, QCheckBox, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QFont

from core.test_session import SessionConfig

logger = logging.getLogger(__name__)


def _section_title(text: str) -> QLabel:
    """Crea un titolo di sezione stilizzato."""
    lbl = QLabel(text)
    lbl.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
    lbl.setStyleSheet(
        "color:#374151;background:transparent;"
        "padding:0;margin:0;"
    )
    return lbl


def _separator() -> QFrame:
    """Crea una linea separatrice orizzontale sottile."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet("background:#E5E7EB;")
    return line


class TestSetupDialog(QDialog):
    """Dialog per configurare una nuova prova di misura."""

    session_configured = Signal(object)

    def __init__(self, operator_id="", calibration_scale=0.0, parent=None):
        super().__init__(parent)
        self._operator_id = operator_id
        self._cal_scale = calibration_scale
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        self.setWindowTitle("Nuova Prova — Advanced Optical Profiler")
        self.setFixedSize(500, 480)
        self.setModal(True)
        self.setStyleSheet(
            "QDialog{background-color:#F4F5F7;}"
            "QDoubleSpinBox{padding:4px 6px;}"
            "QLineEdit{padding:4px 8px;}"
            "QCheckBox{spacing:6px;}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(0)

        # ════════════════════════════════════════════
        # HEADER
        # ════════════════════════════════════════════
        header = QLabel("📋  Nuova Prova di Misura")
        header.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        header.setStyleSheet("color:#0066B3;background:transparent;")
        root.addWidget(header)
        root.addSpacing(6)

        # Info operatore — badge compatto
        badge = QLabel(
            f"  👤 {self._operator_id}   │   "
            f"⚙️ {self._cal_scale:.6f} mm/px  "
        )
        badge.setFont(QFont("Segoe UI", 8))
        badge.setFixedHeight(24)
        badge.setStyleSheet(
            "color:#1E40AF;background:#DBEAFE;"
            "border:1px solid #93C5FD;border-radius:4px;"
        )
        root.addWidget(badge)
        root.addSpacing(14)

        # ════════════════════════════════════════════
        # SEZIONE: NOME PROVA
        # ════════════════════════════════════════════
        root.addWidget(_section_title("IDENTIFICATIVO PROVA"))
        root.addSpacing(4)

        self._txt_name = QLineEdit()
        self._txt_name.setPlaceholderText(
            "es. Lotto 2026-03-01 — Mescola XR42 — Bandina 5mm"
        )
        self._txt_name.setFixedHeight(32)
        self._txt_name.setFont(QFont("Segoe UI", 10))
        root.addWidget(self._txt_name)
        root.addSpacing(14)

        # ══════════════════════════════���═════════════
        # SEZIONE: TOLLERANZE
        # ════════════════════════════════════════════
        root.addWidget(_separator())
        root.addSpacing(10)
        root.addWidget(_section_title("TOLLERANZE DIMENSIONALI"))
        root.addSpacing(6)

        self._chk_tolerance = QCheckBox(
            "Abilita controllo tolleranze (OK/NOK, Cp, Cpk)"
        )
        self._chk_tolerance.setChecked(False)
        self._chk_tolerance.setFont(QFont("Segoe UI", 9))
        root.addWidget(self._chk_tolerance)
        root.addSpacing(8)

        # Form: Nominale / USL / LSL
        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow
        )

        self._spin_nominal = self._make_spin(5.000, 0.1)
        lbl_n = QLabel("Nominale:")
        lbl_n.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        form.addRow(lbl_n, self._spin_nominal)

        self._spin_usl = self._make_spin(5.100, 0.01)
        form.addRow(QLabel("USL (+):"), self._spin_usl)

        self._spin_lsl = self._make_spin(4.900, 0.01)
        form.addRow(QLabel("LSL (−):"), self._spin_lsl)

        root.addLayout(form)
        root.addSpacing(4)

        hint = QLabel(
            "💡 Se non conosci ancora le tolleranze, lascia disabilitato."
        )
        hint.setFont(QFont("Segoe UI", 8))
        hint.setStyleSheet("color:#9CA3AF;background:transparent;")
        root.addWidget(hint)
        root.addSpacing(12)

        # ════════════════════════════════════════════
        # SEZIONE: NOTE
        # ════════════════════════════════════════════
        root.addWidget(_separator())
        root.addSpacing(8)

        note_row = QHBoxLayout()
        note_row.setSpacing(10)
        lbl_note = QLabel("Note:")
        lbl_note.setFont(QFont("Segoe UI", 9))
        lbl_note.setStyleSheet("background:transparent;")
        note_row.addWidget(lbl_note)
        self._txt_notes = QLineEdit()
        self._txt_notes.setPlaceholderText("Annotazioni libere (opzionale)")
        self._txt_notes.setFixedHeight(28)
        self._txt_notes.setFont(QFont("Segoe UI", 9))
        note_row.addWidget(self._txt_notes, 1)
        root.addLayout(note_row)

        # ════════════════════════════════════════════
        # STRETCH + PULSANTI
        # ════════════════════════════════════════════
        root.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        btn_row.addStretch()

        self._btn_cancel = QPushButton("Annulla")
        self._btn_cancel.setFixedHeight(34)
        self._btn_cancel.setMinimumWidth(90)
        btn_row.addWidget(self._btn_cancel)

        self._btn_start = QPushButton("▶  Avvia Prova")
        self._btn_start.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_start.setFixedHeight(34)
        self._btn_start.setMinimumWidth(140)
        self._btn_start.setStyleSheet(
            "QPushButton{background:#059669;color:white;border:none;"
            "border-radius:6px;padding:6px 20px;}"
            "QPushButton:hover{background:#047857;}"
        )
        btn_row.addWidget(self._btn_start)
        root.addLayout(btn_row)

    def _make_spin(self, default: float, step: float) -> QDoubleSpinBox:
        """Factory per spinbox tolleranza, tutti uguali."""
        spin = QDoubleSpinBox()
        spin.setRange(0.001, 999.999)
        spin.setValue(default)
        spin.setDecimals(3)
        spin.setSingleStep(step)
        spin.setSuffix(" mm")
        spin.setFont(QFont("Consolas", 11))
        spin.setFixedHeight(32)
        spin.setEnabled(False)
        return spin

    # ═══════════════════════════════════════════════════════════
    # SEGNALI
    # ════════��══════════════════════════════════════════════════

    def _connect_signals(self):
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_start.clicked.connect(self._on_start)
        self._chk_tolerance.toggled.connect(self._on_tolerance_toggled)
        self._spin_nominal.valueChanged.connect(self._on_nominal_changed)

    @Slot(bool)
    def _on_tolerance_toggled(self, checked):
        self._spin_nominal.setEnabled(checked)
        self._spin_usl.setEnabled(checked)
        self._spin_lsl.setEnabled(checked)

    @Slot(float)
    def _on_nominal_changed(self, value):
        delta_up = self._spin_usl.value() - self._spin_nominal.value()
        delta_lo = self._spin_nominal.value() - self._spin_lsl.value()
        if delta_up < 0.001:
            delta_up = 0.1
        if delta_lo < 0.001:
            delta_lo = 0.1
        self._spin_usl.blockSignals(True)
        self._spin_lsl.blockSignals(True)
        self._spin_usl.setValue(value + delta_up)
        self._spin_lsl.setValue(value - delta_lo)
        self._spin_usl.blockSignals(False)
        self._spin_lsl.blockSignals(False)

    @Slot()
    def _on_start(self):
        name = self._txt_name.text().strip()
        if not name:
            QMessageBox.warning(
                self, "Nome Mancante",
                "Inserire un nome per identificare la prova.\n\n"
                "Esempio: Lotto 2026-03-01 — Mescola XR42"
            )
            self._txt_name.setFocus()
            return

        if self._chk_tolerance.isChecked():
            usl = self._spin_usl.value()
            lsl = self._spin_lsl.value()
            nom = self._spin_nominal.value()
            if usl <= lsl:
                QMessageBox.warning(
                    self, "Tolleranze Errate",
                    "USL deve essere maggiore di LSL."
                )
                return
            if nom < lsl or nom > usl:
                QMessageBox.warning(
                    self, "Nominale Fuori Range",
                    "Il nominale deve essere tra LSL e USL."
                )
                return
            tol_upper = usl
            tol_lower = lsl
        else:
            nom = 0.0
            tol_upper = float('inf')
            tol_lower = float('-inf')

        config = SessionConfig(
            session_name=name,
            operator_id=self._operator_id,
            nominal_mm=nom,
            tolerance_upper_mm=tol_upper,
            tolerance_lower_mm=tol_lower,
            calibration_scale_mm_per_px=self._cal_scale,
            notes=self._txt_notes.text().strip(),
        )
        self.session_configured.emit(config)
        self.accept()

    @staticmethod
    def get_session_config(operator_id, calibration_scale, parent=None):
        dialog = TestSetupDialog(operator_id, calibration_scale, parent)
        result_config = None

        def on_configured(config):
            nonlocal result_config
            result_config = config

        dialog.session_configured.connect(on_configured)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        return result_config, accepted

    def sizeHint(self):
        return QSize(500, 480)