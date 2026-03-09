# Ideato e Realizzato da Pierpaolo Careddu

"""
ExportDialog — Dialog per scegliere formato e percorso di export.

L'operatore può scegliere tra PDF e CSV, selezionare il percorso
di salvataggio e configurare opzioni di base.

Light Theme compatibile con theme_industriale.qss.
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QButtonGroup, QFileDialog, QLineEdit,
    QGroupBox, QCheckBox, QMessageBox, QFrame
)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QFont

from core.report_generator import ReportGenerator
from core.statistics_model import StatisticsSnapshot, ToleranceLimits

logger = logging.getLogger(__name__)


class ExportDialog(QDialog):
    """
    Dialog per l'export dei dati in PDF o CSV.

    Signals:
        export_completed(str): Emesso con il percorso del file esportato
    """

    export_completed = Signal(str)

    def __init__(
        self,
        report_generator: ReportGenerator,
        records: list,
        snapshot: Optional[StatisticsSnapshot] = None,
        tolerance: Optional[ToleranceLimits] = None,
        default_dir: Optional[Path] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._generator = report_generator
        self._records = records
        self._snapshot = snapshot
        self._tolerance = tolerance
        self._default_dir = default_dir or Path.home() / "Documents"

        self._setup_ui()
        self._connect_signals()
        self._update_filename()

    def _setup_ui(self):
        self.setWindowTitle("Esporta Report — Advanced Optical Profiler")
        self.setMinimumSize(520, 380)
        self.setModal(True)
        self.setStyleSheet("QDialog{background-color:#F4F5F7;}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(16)

        # Header
        header = QLabel("📤  Esporta Report Misure")
        header.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        header.setStyleSheet("color:#0066B3;background:transparent;")
        layout.addWidget(header)

        # Info sessione
        n_records = len(self._records)
        n_valid = self._snapshot.count_valid if self._snapshot else 0
        info = QLabel(
            f"Misure da esportare: {n_records} "
            f"({n_valid} valide)"
        )
        info.setFont(QFont("Segoe UI", 10))
        info.setStyleSheet("color:#6B7280;background:transparent;")
        layout.addWidget(info)

        # Formato
        fmt_group = QGroupBox("Formato")
        fmt_layout = QVBoxLayout(fmt_group)
        fmt_layout.setContentsMargins(12, 20, 12, 12)
        fmt_layout.setSpacing(8)

        self._btn_group = QButtonGroup(self)

        self._radio_csv = QRadioButton(
            "📊  CSV — Foglio di calcolo (Excel, LibreOffice)"
        )
        self._radio_csv.setChecked(True)
        self._btn_group.addButton(self._radio_csv, 0)
        fmt_layout.addWidget(self._radio_csv)

        self._radio_pdf = QRadioButton(
            "📄  PDF — Report professionale con statistiche"
        )
        pdf_available = ReportGenerator.is_pdf_available()
        self._radio_pdf.setEnabled(pdf_available)
        if not pdf_available:
            self._radio_pdf.setText(
                "📄  PDF — Non disponibile (installare reportlab)"
            )
        self._btn_group.addButton(self._radio_pdf, 1)
        fmt_layout.addWidget(self._radio_pdf)

        layout.addWidget(fmt_group)

        # Opzioni
        opt_group = QGroupBox("Opzioni")
        opt_layout = QVBoxLayout(opt_group)
        opt_layout.setContentsMargins(12, 20, 12, 12)
        opt_layout.setSpacing(8)

        self._chk_stats = QCheckBox("Includi statistiche aggregate")
        self._chk_stats.setChecked(True)
        opt_layout.addWidget(self._chk_stats)

        self._chk_open = QCheckBox("Apri file dopo l'export")
        self._chk_open.setChecked(False)
        opt_layout.addWidget(self._chk_open)

        layout.addWidget(opt_group)

        # Percorso file
        path_group = QGroupBox("Percorso")
        path_layout = QHBoxLayout(path_group)
        path_layout.setContentsMargins(12, 20, 12, 12)
        path_layout.setSpacing(8)

        self._txt_path = QLineEdit()
        self._txt_path.setMinimumHeight(30)
        self._txt_path.setFont(QFont("Consolas", 9))
        self._txt_path.setReadOnly(True)
        path_layout.addWidget(self._txt_path, 1)

        self._btn_browse = QPushButton("📁  Sfoglia...")
        self._btn_browse.setMinimumHeight(30)
        path_layout.addWidget(self._btn_browse)

        layout.addWidget(path_group)

        # Pulsanti
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.addStretch()

        self._btn_cancel = QPushButton("Annulla")
        self._btn_cancel.setMinimumHeight(36)
        self._btn_cancel.setMinimumWidth(100)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_export = QPushButton("✓  Esporta")
        self._btn_export.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._btn_export.setMinimumHeight(36)
        self._btn_export.setMinimumWidth(140)
        self._btn_export.setStyleSheet(
            "QPushButton{background:#059669;color:white;"
            "border:none;border-radius:6px;padding:8px 20px;}"
            "QPushButton:hover{background:#047857;}"
        )
        btn_layout.addWidget(self._btn_export)

        layout.addLayout(btn_layout)

    def _connect_signals(self):
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_export.clicked.connect(self._on_export)
        self._btn_browse.clicked.connect(self._on_browse)
        self._btn_group.idToggled.connect(self._on_format_changed)

    def _update_filename(self):
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        ext = "csv" if self._radio_csv.isChecked() else "pdf"
        filename = f"report_misure_{ts}.{ext}"
        full_path = self._default_dir / filename
        self._txt_path.setText(str(full_path))

    @Slot(int, bool)
    def _on_format_changed(self, button_id, checked):
        if checked:
            self._update_filename()

    @Slot()
    def _on_browse(self):
        if self._radio_csv.isChecked():
            filter_str = "CSV Files (*.csv);;All Files (*)"
        else:
            filter_str = "PDF Files (*.pdf);;All Files (*)"

        filepath, _ = QFileDialog.getSaveFileName(
            self, "Salva Report",
            self._txt_path.text(), filter_str
        )
        if filepath:
            self._txt_path.setText(filepath)

    @Slot()
    def _on_export(self):
        filepath = Path(self._txt_path.text())
        if not filepath.parent.exists():
            QMessageBox.warning(
                self, "Percorso non valido",
                f"La cartella non esiste:\n{filepath.parent}"
            )
            return

        include_stats = self._chk_stats.isChecked()
        snap = self._snapshot if include_stats else None

        if self._radio_csv.isChecked():
            success = self._generator.export_csv(
                filepath=filepath,
                records=self._records,
                snapshot=snap,
            )
        else:
            # P0.6 — Usa il titolo della prova se disponibile
            report_title = getattr(self, '_report_title', 'Report Metrologico')
            success = self._generator.export_pdf(
                filepath=filepath,
                records=self._records,
                snapshot=snap,
                tolerance=self._tolerance,
                title=report_title,
            )

        if success:
            self.export_completed.emit(str(filepath))
            QMessageBox.information(
                self, "Export Completato",
                f"✓ Report esportato con successo:\n{filepath}"
            )
            if self._chk_open.isChecked():
                import os
                os.startfile(str(filepath))
            self.accept()
        else:
            QMessageBox.critical(
                self, "Errore Export",
                "❌ Errore durante l'export.\n"
                "Controllare i log per dettagli."
            )

    def sizeHint(self):
        return QSize(520, 400)