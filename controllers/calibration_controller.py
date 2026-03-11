# Ideato e Realizzato da Pierpaolo Careddu

"""
CalibrationController — Orchestrazione completa della calibrazione.

Responsabilità:
- Apertura e gestione del CalibrationWizard
- Applicazione del fattore mm/px al MetrologyEngine
- Propagazione della calibrazione a tutti i componenti interessati
- Verifica periodica scadenza calibrazione
- Storico calibrazioni della sessione

Flusso:
    1. start_calibration() → apre CalibrationWizard
    2. Wizard emette calibration_completed(float)
    3. Controller applica a MetrologyEngine, SessionController, UI
    4. Emette calibration_applied(float) per aggiornare tutta la UI
"""

import logging
from datetime import datetime
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot, QTimer
from PySide6.QtWidgets import QWidget, QMessageBox

from core.calibration_engine import CalibrationEngine
from core.metrology_engine import MetrologyEngine
from views.widgets.live_view_widget import LiveViewWidget, OSDSeverity

logger = logging.getLogger(__name__)


class CalibrationRecord:
    """Record storico di una calibrazione effettuata."""

    def __init__(
        self,
        scale_mm_per_px: float,
        timestamp: datetime,
        operator_id: str = "",
        sample_distance_mm: float = 0.0,
        sample_distance_px: float = 0.0,
        method: str = "wizard",
    ):
        self.scale_mm_per_px = scale_mm_per_px
        self.timestamp = timestamp
        self.operator_id = operator_id
        self.sample_distance_mm = sample_distance_mm
        self.sample_distance_px = sample_distance_px
        self.method = method

    def __repr__(self) -> str:
        return (
            f"CalibrationRecord("
            f"scale={self.scale_mm_per_px:.6f}, "
            f"time={self.timestamp.strftime('%H:%M:%S')})"
        )


class CalibrationController(QObject):
    """
    Controller per la gestione completa della calibrazione.

    Signals:
        calibration_applied(float): Nuovo fattore mm/px applicato
        calibration_expired(): La calibrazione è scaduta
        calibration_status_changed(bool): Stato calibrazione cambiato
        status_message(str): Messaggi per la status bar
    """

    calibration_applied = Signal(float)
    calibration_expired = Signal()
    calibration_status_changed = Signal(bool)
    status_message = Signal(str)
    usaf_calibration_result = Signal(dict)

    # Intervallo controllo scadenza: ogni 5 minuti
    EXPIRY_CHECK_INTERVAL_MS = 5 * 60 * 1000

    def __init__(
        self,
        calibration_engine: CalibrationEngine,
        metrology_engine: MetrologyEngine,
        live_view: LiveViewWidget,
        operator_id: str = "",
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)

        self._cal_engine = calibration_engine
        self._met_engine = metrology_engine
        self._live_view = live_view
        self._operator_id = operator_id
        self._parent_widget = parent

        self._history: list[CalibrationRecord] = []
        self._grab_worker = None  # Impostato da AcquisitionController

        # Stato USAF Click-to-Calibrate
        self._usaf_click_mode_active: bool = False
        self._usaf_group: int = -2      # Default: Gruppo -2
        self._usaf_element: int = 1     # Default: Elemento 1

        # Timer per controllo scadenza periodico
        self._expiry_timer = QTimer(self)
        self._expiry_timer.setInterval(self.EXPIRY_CHECK_INTERVAL_MS)
        self._expiry_timer.timeout.connect(self._check_expiry)
        self._expiry_timer.start()

        # Connessioni segnali USAF
        self._live_view.calibration_point_clicked.connect(
            self._on_usaf_click_received
        )
        self.usaf_calibration_result.connect(
            self._live_view.set_usaf_calibration_result
        )

        # Se già calibrato all'avvio, registra nello storico
        if self._cal_engine.is_calibrated:
            self._history.append(CalibrationRecord(
                scale_mm_per_px=self._cal_engine.scale_factor,
                timestamp=self._cal_engine.calibration_date or datetime.now(),
                operator_id="(pre-esistente)",
            ))

    # ═══════════════════════════════════════════════════════════
    # PROPRIETÀ
    # ═══════════════════════════════════════════════════════════

    @property
    def is_calibrated(self) -> bool:
        return self._cal_engine.is_calibrated

    @property
    def is_expired(self) -> bool:
        return self._cal_engine.is_expired if self._cal_engine.is_calibrated else False

    @property
    def scale_factor(self) -> float:
        if self._cal_engine.is_calibrated:
            return self._cal_engine.scale_factor
        return 0.0

    @property
    def history(self) -> list[CalibrationRecord]:
        return list(self._history)

    @property
    def calibration_count(self) -> int:
        return len(self._history)

    def set_operator(self, operator_id: str):
        self._operator_id = operator_id

    def set_grab_worker(self, worker):
        """Imposta il GrabWorker per il feed frame al wizard."""
        self._grab_worker = worker

    # ═══════════════════════════════════════════════════════════
    # AVVIO CALIBRAZIONE
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def start_calibration(self):
        """
        Apre il CalibrationWizard e gestisce il risultato.

        Il wizard riceve il frame corrente dal LiveView e,
        se il grabbing è attivo, riceve frame aggiornati
        dal GrabWorker.
        """
        # Disattiva USAF mode se attivo
        if self._usaf_click_mode_active:
            self.stop_usaf_click_calibration()

        from views.widgets.calibration_wizard import CalibrationWizard

        frame = self._live_view.get_current_frame()

        wizard = CalibrationWizard(
            calibration_engine=self._cal_engine,
            current_frame=frame,
            parent=self._parent_widget,
        )

        # Feed frame live al wizard se grabbing attivo
        if self._grab_worker is not None:
            self._grab_worker.frame_ready.connect(wizard.set_current_frame)

        wizard.calibration_completed.connect(self._on_wizard_completed)
        wizard.exec()

        # Disconnetti il feed frame
        if self._grab_worker is not None:
            try:
                self._grab_worker.frame_ready.disconnect(wizard.set_current_frame)
            except RuntimeError:
                pass

    # ═══════════════════════════════════════════════════════════
    # APPLICAZIONE CALIBRAZIONE
    # ═══════════════════════════════════════════════════════════

    @Slot(float)
    def _on_wizard_completed(self, scale_mm_per_px: float):
        """Callback dal wizard — applica la nuova calibrazione."""
        if scale_mm_per_px <= 0:
            logger.warning("Calibrazione con scala non valida, ignorata")
            return

        # Applica al MetrologyEngine
        self._met_engine.set_calibration(
            scale_mm_per_px=scale_mm_per_px,
            k1_radial=self._cal_engine.k1_radial,
            optical_center=self._cal_engine.optical_center,
        )

        # Registra nello storico
        record = CalibrationRecord(
            scale_mm_per_px=scale_mm_per_px,
            timestamp=datetime.now(),
            operator_id=self._operator_id,
        )
        self._history.append(record)

        # Emetti segnali
        self.calibration_applied.emit(scale_mm_per_px)
        self.calibration_status_changed.emit(True)
        self.status_message.emit(
            f"⚙️ Calibrazione applicata: {scale_mm_per_px:.6f} mm/px"
        )

        logger.info(
            f"Calibrazione #{len(self._history)} applicata: "
            f"{scale_mm_per_px:.6f} mm/px "
            f"(operatore: {self._operator_id})"
        )

    def apply_existing_calibration(self):
        """
        Applica la calibrazione già presente nel CalibrationEngine.
        Chiamato all'avvio se il file di calibrazione esiste.
        """
        if not self._cal_engine.is_calibrated:
            return

        scale = self._cal_engine.scale_factor
        self._met_engine.set_calibration(
            scale_mm_per_px=scale,
            k1_radial=self._cal_engine.k1_radial,
            optical_center=self._cal_engine.optical_center,
        )

        self.calibration_status_changed.emit(True)

        if self._cal_engine.is_expired:
            self.calibration_expired.emit()
            self.status_message.emit(
                f"⚠️ Calibrazione scaduta ({self._cal_engine.age_days} giorni)"
            )
        else:
            self.status_message.emit(
                f"⚙️ Calibrazione caricata: {scale:.6f} mm/px"
            )

    # ═══════════════════════════════════════════════════════════
    # USAF CLICK-TO-CALIBRATE
    # ═══════════════════════════════════════════════════════════

    def set_usaf_group_element(self, group: int, element: int):
        """Imposta il gruppo/elemento USAF per la prossima calibrazione click."""
        self._usaf_group = group
        self._usaf_element = element
        logger.debug(f"USAF selezione: G{group} E{element}")

    def start_usaf_click_calibration(self):
        """Attiva la modalità Click-to-Calibrate sul LiveView."""
        self._usaf_click_mode_active = True
        self._live_view.set_usaf_calibration_mode(True)
        self.status_message.emit(
            f"📐 Calibrazione USAF attiva — G{self._usaf_group} E{self._usaf_element} "
            f"— Clicca su un gap del target"
        )
        logger.info(
            f"USAF calibrazione avviata: G{self._usaf_group} E{self._usaf_element}"
        )

    def stop_usaf_click_calibration(self):
        """Disattiva la modalità Click-to-Calibrate."""
        self._usaf_click_mode_active = False
        self._live_view.set_usaf_calibration_mode(False)
        logger.info("USAF calibrazione annullata")

    @Slot(int, int)
    def _on_usaf_click_received(self, sensor_x: int, sensor_y: int):
        """Gestisce il click dal LiveView durante la calibrazione USAF."""
        if not self._usaf_click_mode_active:
            return

        frame = self._live_view.get_current_frame()
        if frame is None:
            self._live_view.show_osd_message(
                "⚠️ Nessun frame disponibile — Avviare il live",
                OSDSeverity.WARNING, 4000,
            )
            return

        # Calcola la larghezza del gap nota da gruppo/elemento
        from core.usaf_target import usaf_line_width_mm
        known_gap_mm = usaf_line_width_mm(self._usaf_group, self._usaf_element)

        result = self._cal_engine.calibrate_from_usaf_click(
            frame=frame,
            click_x=sensor_x,
            click_y=sensor_y,
            known_gap_mm=known_gap_mm,
        )

        # Emetti risultato per l'overlay
        self.usaf_calibration_result.emit(result)

        if result["ok"]:
            mm_per_px = result["mm_per_px"]

            # Propaga al MetrologyEngine
            self._met_engine.set_calibration(
                scale_mm_per_px=mm_per_px,
                k1_radial=self._cal_engine.k1_radial,
                optical_center=self._cal_engine.optical_center,
            )

            # Registra nello storico
            record = CalibrationRecord(
                scale_mm_per_px=mm_per_px,
                timestamp=datetime.now(),
                operator_id=self._operator_id,
                sample_distance_mm=known_gap_mm,
                sample_distance_px=result["gap_px"],
                method="usaf_click",
            )
            self._history.append(record)

            # Emetti segnali
            self.calibration_applied.emit(mm_per_px)
            self.calibration_status_changed.emit(True)
            self.status_message.emit(
                f"⚙️ Calibrazione USAF: {mm_per_px:.6f} mm/px  |  "
                f"gap = {result['gap_px']:.1f} px"
            )

            # OSD successo (italiano)
            self._live_view.show_osd_message(
                f"✅ CALIBRAZIONE RIUSCITA — 1 px = {mm_per_px:.6f} mm  |  "
                f"gap = {result['gap_px']:.1f} px",
                OSDSeverity.INFO, 6000,
            )

            # Disattiva modalità calibrazione
            self._usaf_click_mode_active = False
            self._live_view.set_usaf_calibration_mode(False)

            logger.info(
                f"Calibrazione USAF riuscita: {mm_per_px:.6f} mm/px "
                f"(G{self._usaf_group} E{self._usaf_element}, "
                f"gap={result['gap_px']:.1f}px)"
            )
        else:
            # OSD errore (italiano)
            error_msg = result.get("error", "Errore sconosciuto")
            self._live_view.show_osd_message(
                f"⚠️ CALIBRAZIONE FALLITA — {error_msg}",
                OSDSeverity.WARNING, 5000,
            )
            logger.warning(f"Calibrazione USAF fallita: {error_msg}")

    # ═══════════════════════════════════════════════════════════
    # CONTROLLO SCADENZA
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def _check_expiry(self):
        """Verifica periodica della scadenza calibrazione."""
        if not self._cal_engine.is_calibrated:
            return

        if self._cal_engine.is_expired:
            self.calibration_expired.emit()
            from views.widgets.live_view_widget import OSDSeverity
            self._live_view.show_osd_message(
                "⚠️ CALIBRAZIONE SCADUTA — Ricalibrare il sistema",
                OSDSeverity.WARNING, 5000
            )
            logger.warning(
                f"Calibrazione scaduta: "
                f"{self._cal_engine.age_days} giorni"
            )

    # ═══════════════════════════════════════════════════════════
    # UTILITY
    # ═══════════════════════════════════════════════════════════

    def get_calibration_summary(self) -> str:
        """Restituisce un riepilogo testuale della calibrazione."""
        if not self._cal_engine.is_calibrated:
            return "Sistema non calibrato"

        cal = self._cal_engine
        lines = [
            f"Scala: {cal.scale_factor:.6f} mm/px",
            f"Età: {cal.age_days} giorni",
        ]
        if cal.calibration_date:
            lines.append(
                f"Data: {cal.calibration_date.strftime('%Y-%m-%d %H:%M')}"
            )
        if cal.is_expired:
            lines.append("⚠️ SCADUTA")
        else:
            lines.append("✓ Valida")

        if self._history:
            last = self._history[-1]
            lines.append(f"Calibrazioni in sessione: {len(self._history)}")
            lines.append(f"Metodo: {last.method}")

        return "\n".join(lines)

    def cleanup(self):
        """Pulizia risorse."""
        if self._usaf_click_mode_active:
            self.stop_usaf_click_calibration()
        self._expiry_timer.stop()
        logger.info(
            f"CalibrationController: cleanup "
            f"({len(self._history)} calibrazioni in sessione)"
        )