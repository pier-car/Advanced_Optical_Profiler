# Ideato e Realizzato da Pierpaolo Careddu

"""
SessionController — Orchestrazione del ciclo di vita di una prova di misura.

Responsabilità:
- Creazione prova (via TestSetupDialog)
- Ricezione misure catturate → registrazione nella sessione
- Propagazione tolleranze al StatisticsModel
- Finalizzazione e salvataggio sessione
- Export tramite ReportGenerator con formato distinto (PDF/CSV)

Fix integrati:
- P0.6: report_title passato all'ExportDialog
- StatisticsModel.clear_all() (non .clear())
- add_measurement() (non add_record())
- quick_export(fmt=) con formato preselezionato
"""

import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QWidget

from core.test_session import TestSession, SessionConfig, MeasureRecord
from core.statistics_model import StatisticsModel, ToleranceLimits
from core.report_generator import ReportGenerator
from core.metrology_engine import MeasurementResult, MeasurementStatus
from views.widgets.test_setup_dialog import TestSetupDialog
from views.dialogs.export_dialog import ExportDialog

logger = logging.getLogger(__name__)


class SessionController(QObject):
    """
    Controller per il ciclo di vita delle prove di misura.

    Signals:
        session_started(str): Nome della prova avviata
        session_ended(str): Nome della prova terminata
        tolerances_changed(object): Nuove ToleranceLimits
        status_message(str): Messaggi per la status bar
    """

    session_started = Signal(str)
    session_ended = Signal(str)
    tolerances_changed = Signal(object)
    status_message = Signal(str)

    def __init__(
        self,
        statistics_model: StatisticsModel,
        operator_id: str = "",
        calibration_scale: float = 0.0,
        sessions_dir: Optional[Path] = None,
        exports_dir: Optional[Path] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._stats_model = statistics_model
        self._operator_id = operator_id
        self._cal_scale = calibration_scale
        self._sessions_dir = sessions_dir or Path("data/sessions")
        self._exports_dir = exports_dir or Path("exports")
        self._parent_widget = parent

        self._current_session: Optional[TestSession] = None
        self._session_start_time: Optional[datetime] = None

    # ═══════════════════════════════════════════════════════════
    # PROPRIETÀ
    # ═══════════════════════════════════════════���═══════════════

    @property
    def has_active_session(self) -> bool:
        return (
            self._current_session is not None
            and self._current_session.is_active
        )

    @property
    def current_session(self) -> Optional[TestSession]:
        return self._current_session

    @property
    def session_name(self) -> str:
        if self._current_session:
            return self._current_session.config.session_name
        return ""

    def set_operator(self, operator_id: str):
        self._operator_id = operator_id

    def set_calibration_scale(self, scale: float):
        self._cal_scale = scale

    # ═══════════════════════════════════════════════════════════
    # NUOVA PROVA
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def new_session(self):
        if self.has_active_session:
            reply = QMessageBox.question(
                self._parent_widget,
                "Prova Attiva",
                f"La prova '{self.session_name}' è ancora attiva.\n"
                f"Chiuderla e avviarne una nuova?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
            self.end_session()

        config, accepted = TestSetupDialog.get_session_config(
            operator_id=self._operator_id,
            calibration_scale=self._cal_scale,
            parent=self._parent_widget,
        )

        if not accepted or config is None:
            return

        # Crea la sessione
        self._current_session = TestSession()
        self._current_session.create(config)
        self._session_start_time = datetime.now()

        # Propaga tolleranze al StatisticsModel
        if config.is_tolerance_configured:
            tol = ToleranceLimits(
                nominal_mm=config.nominal_mm,
                upper_limit_mm=config.tolerance_upper_mm,
                lower_limit_mm=config.tolerance_lower_mm,
            )
            self._stats_model.set_tolerance(tol)
            self.tolerances_changed.emit(tol)

        # Pulisci dati precedenti
        self._stats_model.clear_all()

        self.session_started.emit(config.session_name)
        self.status_message.emit(
            f"📋 Prova avviata: '{config.session_name}'"
        )
        logger.info(f"Prova avviata: '{config.session_name}'")

    # ═══════════════════════════════════════════════════════════
    # REGISTRAZIONE MISURE
    # ═══════════════════════════════════════════════════════════

    @Slot(object)
    def on_measure_captured(self, result: MeasurementResult):
        if not self.has_active_session:
            return
        if not isinstance(result, MeasurementResult):
            return

        is_error = result.status in (
            MeasurementStatus.ERROR_NO_EDGES,
            MeasurementStatus.ERROR_INVALID_GEOMETRY,
        )

        record = MeasureRecord(
            width_mm=result.width_mm_mean,
            std_mm=result.width_mm_std,
            angle_deg=result.theta_avg_deg,
            n_scanlines=getattr(result, 'n_valid_scanlines', 0),
            is_valid=not is_error,
            source="auto",
        )

        idx = self._current_session.add_record(record)
        logger.debug(
            f"Prova record #{idx}: "
            f"{record.width_mm:.3f}mm ({record.status})"
        )

    # ═══════════════════════════════════════════════════════════
    # FINE PROVA
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def end_session(self):
        if not self.has_active_session:
            self.status_message.emit("ℹ️ Nessuna prova attiva")
            return

        session = self._current_session
        name = session.config.session_name

        session.finalize()

        # Salvataggio JSON
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = "".join(
            c if c.isalnum() or c in "-_ " else "_"
            for c in name
        ).strip()
        filename = f"session_{ts}_{safe_name}.json"
        filepath = self._sessions_dir / filename
        session.save(filepath)

        self.session_ended.emit(name)
        self.status_message.emit(
            f"📋 Prova '{name}' completata — "
            f"{session.count_valid} misure valide"
        )

        # Dialog riepilogo e offerta export
        stats = session.statistics
        reply = QMessageBox.question(
            self._parent_widget,
            "Prova Completata",
            f"Prova '{name}' completata.\n\n"
            f"Misure: {stats.count_valid} valide su {stats.count}\n"
            f"Media: {stats.mean_mm:.3f} mm\n"
            f"OK: {stats.ok_percentage:.1f}%\n\n"
            f"Esportare il report?",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self._offer_export(session)

        self._current_session = None
        logger.info(f"Prova '{name}' terminata e salvata: {filepath}")

    def _offer_export(self, session: TestSession, fmt: str = "pdf"):
        """
        Apre l'ExportDialog per una sessione completata.

        Args:
            session: la sessione da esportare
            fmt: formato preselezionato ("pdf" o "csv")
        """
        from core.statistics_model import StatisticsSnapshot

        snapshot = StatisticsSnapshot(
            count=session.statistics.count,
            count_valid=session.statistics.count_valid,
            count_ok=session.statistics.count_ok,
            count_nok=session.statistics.count_nok,
            mean_mm=session.statistics.mean_mm,
            std_mm=session.statistics.std_mm,
            min_mm=session.statistics.min_mm,
            max_mm=session.statistics.max_mm,
            range_mm=session.statistics.range_mm,
            median_mm=session.statistics.median_mm,
            cp=session.statistics.cp,
            cpk=session.statistics.cpk,
            ok_percentage=session.statistics.ok_percentage,
            values_mm=[
                r.width_mm for r in session.records if r.is_valid
            ],
        )

        tolerance = None
        cfg = session.config
        if cfg.is_tolerance_configured:
            tolerance = ToleranceLimits(
                nominal_mm=cfg.nominal_mm,
                upper_limit_mm=cfg.tolerance_upper_mm,
                lower_limit_mm=cfg.tolerance_lower_mm,
            )

        # P0.6 — Nome prova nel titolo del report
        report_title = f"Report Metrologico — {cfg.session_name}"

        generator = ReportGenerator(
            operator_id=cfg.operator_id,
            session_start=session.started_at,
            calibration_scale=cfg.calibration_scale_mm_per_px,
        )

        dialog = ExportDialog(
            report_generator=generator,
            records=session.record_dicts,
            snapshot=snapshot,
            tolerance=tolerance,
            default_dir=str(self._exports_dir),
            default_format=fmt,
            report_title=report_title,
            parent=self._parent_widget,
        )
        dialog.exec()

    # ═══════════════════════════════════════════════════════════
    # EXPORT RAPIDO (senza sessione attiva)
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def quick_export(self, fmt: str = "pdf"):
        """
        Export rapido dei dati correnti senza sessione formale.

        Args:
            fmt: "pdf" o "csv" — formato preselezionato nel dialog
        """
        snapshot = self._stats_model.get_snapshot()
        if snapshot.count_valid == 0:
            self.status_message.emit("ℹ️ Nessun dato da esportare")
            return

        # Costruisci records dai valori nel model
        records = []
        for i, v in enumerate(snapshot.values_mm, 1):
            records.append({
                "index": i,
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "width_mm": v,
                "std_mm": 0.0,
                "angle_deg": 0.0,
                "status": "OK",
                "n_scanlines": 0,
            })

        generator = ReportGenerator(
            operator_id=self._operator_id,
            calibration_scale=self._cal_scale,
        )

        tolerance = self._stats_model.tolerance

        # Titolo generico per export rapido
        report_title = (
            f"Report Metrologico — Export Rapido "
            f"({datetime.now().strftime('%Y-%m-%d %H:%M')})"
        )

        dialog = ExportDialog(
            report_generator=generator,
            records=records,
            snapshot=snapshot,
            tolerance=tolerance,
            default_dir=str(self._exports_dir),
            default_format=fmt,
            report_title=report_title,
            parent=self._parent_widget,
        )
        dialog.exec()

    # ═══════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════

    def cleanup(self):
        if self.has_active_session:
            logger.warning(
                "Prova attiva alla chiusura — salvataggio automatico"
            )
            self._current_session.finalize()
            ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filepath = (
                self._sessions_dir / f"session_{ts}_autosave.json"
            )
            self._current_session.save(filepath)
            self._current_session = None