# Ideato e Realizzato da Pierpaolo Careddu

"""
MeasurementController — Orchestratore del flusso dati metrologico.

Responsabilità:
    Collega il motore di misura (MetrologyEngine) al modello statistico
    (StatisticsModel) e alle view (MeasurementTable, StatisticsPanel).

    Implementa il pattern MVC con thread safety garantita:
    - I dati arrivano dal GrabWorker (thread secondario) sotto forma
      di MeasurementResult emessi via Signal
    - Il Controller riceve i dati nel main thread (connessione Qt::AutoConnection)
    - Aggiorna il Model (StatisticsModel) che è thread-safe
    - Il Model emette statistics_updated → StatisticsPanel (GUI thread)
    - Il Controller emette record_added → MeasurementTable (GUI thread)

Flusso completo:
    GrabWorker (thread) →[measure_captured]→ AcquisitionController
          →[measure_captured]→ MeasurementController.on_measure_captured()
              ├─→ StatisticsModel.add_measurement()   ← Thread-safe
              │       └─→[statistics_updated]→ StatisticsPanel.update_statistics()
              └─→[record_display_ready]→ MeasurementTable.add_record()

Tolleranze:
    Le tolleranze vengono impostate dall'operatore all'inizio della sessione
    (o modificate in corso) e propagate sia al Model che alla Table.

Precisione:
    Tutte le grandezze in mm sono gestite con la precisione nativa del
    MetrologyEngine (sub-pixel, ~0.01 mm). La visualizzazione arrotonda
    a 3 cifre decimali (0.001 mm) per coerenza con la specifica 0.1 mm.
"""

import time
import logging
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from core.metrology_engine import MeasurementResult, MeasurementStatus
from core.statistics_model import (
    StatisticsModel, StatisticsSnapshot, MeasurementRecord, ToleranceLimits
)
from views.widgets.measurement_table import MeasurementTable
from views.widgets.statistics_panel import StatisticsPanel

logger = logging.getLogger(__name__)


class MeasurementController(QObject):
    """
    Controller MVC che orchestra il flusso dati tra Engine, Model e View.

    Signals:
        record_display_ready(MeasurementRecord):
            Emesso quando un nuovo record è pronto per la visualizzazione
            nella tabella. Connesso a MeasurementTable.add_record().

        statistics_snapshot_ready(StatisticsSnapshot):
            Re-emissione dello snapshot dal Model verso la View.
            Connesso a StatisticsPanel.update_statistics().

        tolerance_changed(ToleranceLimits):
            Emesso quando le tolleranze vengono modificate.

        session_data_cleared():
            Emesso quando i dati della sessione vengono cancellati.

        status_message(str):
            Messaggi di stato per la status bar della MainWindow.
    """

    record_display_ready = Signal(object)
    statistics_snapshot_ready = Signal(object)
    tolerance_changed = Signal(object)
    session_data_cleared = Signal()
    status_message = Signal(str)

    def __init__(
        self,
        statistics_model: StatisticsModel,
        measurement_table: MeasurementTable,
        statistics_panel: StatisticsPanel,
        parent=None
    ):
        super().__init__(parent)

        # ─── Riferimenti Model e View ───
        self._model = statistics_model
        self._table = measurement_table
        self._panel = statistics_panel

        # ─── Stato interno ───
        self._is_active: bool = False
        self._measures_since_last_log: int = 0
        self._log_interval: int = 10  # Log ogni N misure

        # ─── Connessioni Signal/Slot ───
        self._connect_model_to_views()
        self._connect_table_actions()

    # ═══════════════════════════════════════════════════════════
    # CONNESSIONI INTERNE
    # ═══════════════════════════════════════════════════════════

    def _connect_model_to_views(self):
        """
        Stabilisce il data flow Model ��� View.

        Architettura delle connessioni:
            StatisticsModel.statistics_updated → StatisticsPanel.update_statistics
            StatisticsModel.record_added       → MeasurementTable.add_record
            StatisticsModel.record_removed     → MeasurementTable.mark_excluded
            StatisticsModel.data_cleared       → MeasurementTable.clear_all
            StatisticsModel.data_cleared       → StatisticsPanel.reset_display
        """
        # Model → Panel (statistiche aggregate)
        self._model.statistics_updated.connect(self._panel.update_statistics)

        # Model → Table (singoli record)
        self._model.record_added.connect(self._table.add_record)
        self._model.record_removed.connect(self._table.mark_excluded)
        self._model.data_cleared.connect(self._table.clear_all)
        self._model.data_cleared.connect(self._panel.reset_display)

    def _connect_table_actions(self):
        """
        Connette le azioni dell'utente sulla tabella al Model.

        Flusso bidirezionale:
            Utente click destro → Table.measurement_excluded → Controller → Model
            Utente click destro → Table.measurement_restored → Controller → Model
        """
        self._table.measurement_excluded.connect(self._on_exclude_requested)
        self._table.measurement_restored.connect(self._on_restore_requested)

    # ═══════════════════════════════════════════════════════════
    # RICEZIONE MISURE (dall'AcquisitionController)
    # ═══════════════════════════════════════════════════════════

    @Slot(object)
    def on_measure_captured(self, result: MeasurementResult):
        """
        Slot principale: riceve una misura catturata (stabile o manuale)
        dall'AcquisitionController e la inserisce nel flusso dati.

        Questo metodo è il PUNTO DI INGRESSO UNICO per i dati nel
        sottosistema statistico. Viene eseguito nel main thread grazie
        al meccanismo Qt::AutoConnection dei Signal/Slot.

        Args:
            result: MeasurementResult dal MetrologyEngine, già validato
                    dall'AcquisitionController (status == OK o warning).
        """
        if not isinstance(result, MeasurementResult):
            logger.warning(
                f"MeasurementController: ricevuto tipo inatteso: "
                f"{type(result).__name__}"
            )
            return

        if not self._is_active:
            logger.debug("MeasurementController: misura ignorata (controller non attivo)")
            return

        # Filtra solo misure con stato valido (OK o warning accettabile)
        if result.status in (
            MeasurementStatus.ERROR_NO_EDGES,
            MeasurementStatus.ERROR_INVALID_GEOMETRY,
        ):
            logger.debug(
                f"MeasurementController: misura scartata "
                f"(status={result.status.name})"
            )
            self.status_message.emit(
                f"⚠️ Misura scartata: {result.status.name}"
            )
            return

        # Registra nel model (thread-safe)
        # Il model emetterà automaticamente i segnali verso le view
        record = self._model.add_measurement(
            width_mm=result.width_mm_mean,
            width_mm_std=result.width_mm_std,
            width_px=result.width_px_mean,
            angle_deg=result.theta_avg_deg,
            contrast_ratio=result.contrast_ratio,
            n_scanlines=len(result.scanlines),
            timestamp_s=time.perf_counter(),
        )

        # Logging periodico per non inondare il log
        self._measures_since_last_log += 1
        if self._measures_since_last_log >= self._log_interval:
            snapshot = self._model.get_snapshot()
            logger.info(
                f"Statistiche ({snapshot.count_valid} misure): "
                f"μ={snapshot.mean_mm:.3f} mm, "
                f"σ={snapshot.std_mm:.4f} mm, "
                f"range={snapshot.range_mm:.3f} mm, "
                f"OK={snapshot.ok_percentage:.0f}%"
            )
            self._measures_since_last_log = 0

        # Messaggio status bar con formattazione leggibile
        status_icon = "✅" if record.is_within_tolerance else "❌"
        self.status_message.emit(
            f"{status_icon} Misura #{record.index}: "
            f"{record.width_mm:.3f} ± {record.width_mm_std:.3f} mm"
        )

    # ═══════════════════════════════════════════════════════════
    # GESTIONE TOLLERANZE
    # ═══════════════════════════════════════════════════════════

    @Slot(float, float, float)
    def set_tolerance(
        self,
        nominal_mm: float,
        upper_limit_mm: float,
        lower_limit_mm: float
    ):
        """
        Imposta le tolleranze e propaga la modifica a Model e View.

        Validazione:
        - nominal deve essere > 0
        - upper_limit deve essere > lower_limit
        - I valori vengono arrotondati a 3 cifre decimali per coerenza

        Args:
            nominal_mm:     Valore nominale della larghezza
            upper_limit_mm: Limite superiore (USL)
            lower_limit_mm: Limite inferiore (LSL)
        """
        # Validazione
        if nominal_mm <= 0:
            logger.warning(
                f"Tolleranza rifiutata: nominale non valido ({nominal_mm:.3f} mm)"
            )
            self.status_message.emit("⚠️ Valore nominale non valido")
            return

        if upper_limit_mm <= lower_limit_mm:
            logger.warning(
                f"Tolleranza rifiutata: USL ({upper_limit_mm:.3f}) "
                f"<= LSL ({lower_limit_mm:.3f})"
            )
            self.status_message.emit("⚠️ USL deve essere maggiore di LSL")
            return

        # Arrotondamento di precisione
        nominal_mm = round(nominal_mm, 3)
        upper_limit_mm = round(upper_limit_mm, 3)
        lower_limit_mm = round(lower_limit_mm, 3)

        # Propaga al Model (ricalcola conformità su tutte le misure)
        self._model.set_tolerance(nominal_mm, upper_limit_mm, lower_limit_mm)

        # Propaga alla Table (riformatta le righe)
        tolerance = ToleranceLimits(
            nominal_mm=nominal_mm,
            upper_limit_mm=upper_limit_mm,
            lower_limit_mm=lower_limit_mm,
        )
        self._table.set_tolerance(tolerance)

        # Emetti segnale per altri listener
        self.tolerance_changed.emit(tolerance)

        logger.info(
            f"Tolleranze impostate: "
            f"NOM={nominal_mm:.3f} mm, "
            f"LSL={lower_limit_mm:.3f} mm, "
            f"USL={upper_limit_mm:.3f} mm"
        )
        self.status_message.emit(
            f"⚙️ Tolleranze: {nominal_mm:.3f} mm "
            f"[{lower_limit_mm:.3f} — {upper_limit_mm:.3f}]"
        )

    def get_current_tolerance(self) -> ToleranceLimits:
        """Restituisce le tolleranze correnti."""
        return self._model.tolerance

    # ═══════════════════════════════════════════════════════════
    # AZIONI UTENTE SULLA TABELLA
    # ═══════════════════════════════════════════════════════════

    @Slot(int)
    def _on_exclude_requested(self, index: int):
        """
        L'utente ha richiesto l'esclusione di una misura dalla tabella.
        Propaga al Model che ricalcola le statistiche.
        """
        success = self._model.remove_measurement(index)
        if success:
            logger.info(f"Misura #{index} esclusa dall'operatore")
            self.status_message.emit(f"🚫 Misura #{index} esclusa dalle statistiche")
        else:
            logger.warning(f"Impossibile escludere misura #{index}")
            self.status_message.emit(f"⚠️ Impossibile escludere misura #{index}")

    @Slot(int)
    def _on_restore_requested(self, index: int):
        """
        L'utente ha richiesto il ripristino di una misura esclusa.
        Propaga al Model che ricalcola le statistiche.
        """
        success = self._model.restore_measurement(index)
        if success:
            logger.info(f"Misura #{index} ripristinata dall'operatore")
            self.status_message.emit(f"♻️ Misura #{index} ripristinata nelle statistiche")
        else:
            logger.warning(f"Impossibile ripristinare misura #{index}")
            self.status_message.emit(f"⚠️ Impossibile ripristinare misura #{index}")

    # ═══════════════════════════════════════════════════════════
    # CONTROLLO SESSIONE
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def activate(self):
        """
        Attiva il controller per la ricezione delle misure.
        Deve essere chiamato all'inizio di una sessione di prova.
        """
        self._is_active = True
        self._model.set_start_time(time.perf_counter())
        self._measures_since_last_log = 0
        logger.info("MeasurementController: attivato")

    @Slot()
    def deactivate(self):
        """
        Disattiva il controller. Le misure ricevute verranno ignorate.
        NON cancella i dati esistenti.
        """
        self._is_active = False
        logger.info("MeasurementController: disattivato")

    @Slot()
    def clear_session_data(self):
        """
        Cancella tutti i dati della sessione corrente.
        Resetta Model, Table e Panel.
        """
        self._model.clear_all()
        self._measures_since_last_log = 0
        self.session_data_cleared.emit()
        logger.info("MeasurementController: dati sessione cancellati")
        self.status_message.emit("🗑️ Dati sessione cancellati")

    @property
    def is_active(self) -> bool:
        """Indica se il controller sta accettando misure."""
        return self._is_active

    # ═══════════════════════════════════════════════════════════
    # ACCESSO DATI (per export e report)
    # ═══════════════════════════════════════════════════════════

    def get_statistics_snapshot(self) -> StatisticsSnapshot:
        """
        Restituisce lo snapshot corrente delle statistiche.
        Thread-safe. Usato dal ReportGenerator e dall'ExportDialog.
        """
        return self._model.get_snapshot()

    def get_all_records(self) -> list[MeasurementRecord]:
        """
        Restituisce tutti i record (inclusi esclusi).
        Thread-safe. Usato per l'export CSV/PDF completo.
        """
        return self._model.get_all_records()

    def get_valid_records(self) -> list[MeasurementRecord]:
        """
        Restituisce solo i record non esclusi.
        Thread-safe. Usato per l'export dei soli dati validi.
        """
        return self._model.get_valid_records()

    def get_values_mm(self) -> list[float]:
        """
        Restituisce la lista dei valori validi in mm.
        Thread-safe. Usato per grafici e analisi.
        """
        return self._model.get_values_mm()

    @property
    def record_count(self) -> int:
        """Numero totale di record (inclusi esclusi)."""
        return self._model.count

    @property
    def valid_record_count(self) -> int:
        """Numero di record validi (non esclusi)."""
        return self._model.count_valid

    # ═══════════════════════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════════════════════

    def cleanup(self):
        """Pulizia risorse prima della chiusura."""
        self._is_active = False
        logger.info("MeasurementController: cleanup completato")