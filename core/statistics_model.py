# Ideato e Realizzato da Pierpaolo Careddu

"""
StatisticsModel — Motore statistico real-time per misurazioni metrologiche.

Calcola e mantiene aggiornate le statistiche su uno stream continuo di
misurazioni dimensionali. Ottimizzato per aggiornamento incrementale
(O(1) per ogni nuova misura) senza ricalcolo dell'intero dataset.

Statistiche calcolate:
- Media aritmetica (μ)
- Deviazione standard campionaria (s, con ddof=1)
- Minimo / Massimo / Range
- Mediana (aggiornata su buffer completo)
- Cp / Cpk (indici di capacità di processo)
- Conteggio totale e conteggio OK/NOK vs tolleranze

Thread Safety: Tutte le operazioni sono protette da QMutex.

Architettura:
    MeasurementResult → StatisticsModel.add_measurement()
                              ↓
                    Aggiornamento incrementale Welford
                              ↓
                    statistics_updated Signal → StatisticsPanel
"""

import math
import logging
import numpy as np
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore import QObject, Signal, QMutex, QMutexLocker

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES — Strutture dati per le statistiche
# ═══════════════════════════════════════════════════════════════

@dataclass
class ToleranceLimits:
    """Limiti di tolleranza per la valutazione conformità."""
    nominal_mm: float = 0.0
    upper_limit_mm: float = float('inf')
    lower_limit_mm: float = float('-inf')

    @property
    def is_configured(self) -> bool:
        """Verifica se le tolleranze sono state configurate."""
        return (
            self.upper_limit_mm != float('inf')
            or self.lower_limit_mm != float('-inf')
        )

    @property
    def tolerance_range_mm(self) -> float:
        """Range di tolleranza (USL - LSL)."""
        if not self.is_configured:
            return 0.0
        usl = self.upper_limit_mm if self.upper_limit_mm != float('inf') else 0.0
        lsl = self.lower_limit_mm if self.lower_limit_mm != float('-inf') else 0.0
        return usl - lsl

    def is_within_tolerance(self, value_mm: float) -> bool:
        """Verifica se un valore è entro tolleranza."""
        return self.lower_limit_mm <= value_mm <= self.upper_limit_mm


@dataclass
class MeasurementRecord:
    """Singola misura registrata con metadati."""
    index: int
    width_mm: float
    width_mm_std: float
    width_px: float
    angle_deg: float
    contrast_ratio: float
    n_scanlines: int
    timestamp_s: float
    is_within_tolerance: bool = True
    is_excluded: bool = False


@dataclass
class StatisticsSnapshot:
    """
    Fotografia immutabile delle statistiche correnti.
    Emessa via Signal per aggiornare la UI senza race condition.
    """
    count: int = 0
    count_valid: int = 0
    count_ok: int = 0
    count_nok: int = 0

    mean_mm: float = 0.0
    std_mm: float = 0.0
    min_mm: float = 0.0
    max_mm: float = 0.0
    range_mm: float = 0.0
    median_mm: float = 0.0

    last_value_mm: float = 0.0
    last_value_std_mm: float = 0.0

    cp: float = 0.0
    cpk: float = 0.0

    tolerance: Optional[ToleranceLimits] = None
    ok_percentage: float = 0.0

    values_mm: list[float] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# ALGORITMO DI WELFORD — Varianza online stabile
# ═══════════════════════════════════════════════════════════════

class WelfordAccumulator:
    """
    Algoritmo di Welford per il calcolo incrementale di media e varianza.

    Numericamente stabile anche per grandi dataset, evita il problema
    della cancellazione catastrofica tipico del metodo Σx² - (Σx)²/n.

    Referenza: Welford, B.P. (1962). "Note on a method for calculating
    corrected sums of squares and products". Technometrics, 4(3), 419–420.
    """

    def __init__(self):
        self._count: int = 0
        self._mean: float = 0.0
        self._m2: float = 0.0
        self._min: float = float('inf')
        self._max: float = float('-inf')

    def update(self, value: float):
        """Aggiorna le statistiche con un nuovo valore (O(1))."""
        self._count += 1
        delta = value - self._mean
        self._mean += delta / self._count
        delta2 = value - self._mean
        self._m2 += delta * delta2

        if value < self._min:
            self._min = value
        if value > self._max:
            self._max = value

    def remove(self, value: float):
        """
        Rimuove un valore dalle statistiche (operazione inversa).
        Nota: min/max non possono essere aggiornati senza ricalcolo.
        """
        if self._count <= 1:
            self.reset()
            return

        self._count -= 1
        delta = value - self._mean
        self._mean -= delta / self._count
        delta2 = value - self._mean
        self._m2 -= delta * delta2

    def reset(self):
        """Resetta completamente l'accumulatore."""
        self._count = 0
        self._mean = 0.0
        self._m2 = 0.0
        self._min = float('inf')
        self._max = float('-inf')

    @property
    def count(self) -> int:
        return self._count

    @property
    def mean(self) -> float:
        return self._mean if self._count > 0 else 0.0

    @property
    def variance(self) -> float:
        """Varianza campionaria (ddof=1)."""
        if self._count < 2:
            return 0.0
        return self._m2 / (self._count - 1)

    @property
    def std(self) -> float:
        """Deviazione standard campionaria."""
        return math.sqrt(self.variance)

    @property
    def minimum(self) -> float:
        return self._min if self._count > 0 else 0.0

    @property
    def maximum(self) -> float:
        return self._max if self._count > 0 else 0.0

    @property
    def range(self) -> float:
        if self._count < 1:
            return 0.0
        return self._max - self._min


# ═══════════════════════════════════════════════════════════════
# MODELLO STATISTICO PRINCIPALE
# ═══════════════════════════════════════════════════════════════

class StatisticsModel(QObject):
    """
    Modello statistico real-time per il flusso di misurazioni.

    Thread-safe: tutte le operazioni di lettura/scrittura sono
    protette da QMutex per l'uso sicuro da thread di acquisizione.

    Signals:
        statistics_updated(StatisticsSnapshot):
            Emesso ogni volta che le statistiche cambiano.
            Il payload è una copia immutabile → sicuro per la GUI.

        record_added(MeasurementRecord):
            Emesso quando una nuova misura viene registrata.

        record_removed(int):
            Emesso quando una misura viene rimossa (indice).

        data_cleared():
            Emesso quando tutti i dati vengono cancellati.
    """

    statistics_updated = Signal(object)
    record_added = Signal(object)
    record_removed = Signal(int)
    data_cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._mutex = QMutex()

        # Storage completo delle misure
        self._records: list[MeasurementRecord] = []
        self._next_index: int = 1

        # Accumulatore Welford per statistiche incrementali
        self._welford = WelfordAccumulator()

        # Contatori conformità
        self._count_ok: int = 0
        self._count_nok: int = 0

        # Tolleranze
        self._tolerance = ToleranceLimits()

        # Timestamp di riferimento per tempi relativi
        self._start_time: float = 0.0

    # ═══════════════════════════════════════════════════════════
    # CONFIGURAZIONE
    # ═══════════════════════════════════════════════════════════

    def set_tolerance(
        self,
        nominal_mm: float,
        upper_limit_mm: float,
        lower_limit_mm: float
    ):
        """
        Imposta i limiti di tolleranza e ricalcola la conformità
        di tutte le misure esistenti.
        """
        with QMutexLocker(self._mutex):
            self._tolerance = ToleranceLimits(
                nominal_mm=nominal_mm,
                upper_limit_mm=upper_limit_mm,
                lower_limit_mm=lower_limit_mm,
            )

            # Ricalcola conformità su tutte le misure esistenti
            self._count_ok = 0
            self._count_nok = 0

            for record in self._records:
                if record.is_excluded:
                    continue
                record.is_within_tolerance = self._tolerance.is_within_tolerance(
                    record.width_mm
                )
                if record.is_within_tolerance:
                    self._count_ok += 1
                else:
                    self._count_nok += 1

        logger.info(
            f"Tolleranze impostate: nominale={nominal_mm:.3f} mm, "
            f"LSL={lower_limit_mm:.3f} mm, USL={upper_limit_mm:.3f} mm"
        )

        self._emit_statistics()

    def set_start_time(self, timestamp: float):
        """Imposta il timestamp di inizio sessione."""
        with QMutexLocker(self._mutex):
            self._start_time = timestamp

    @property
    def tolerance(self) -> ToleranceLimits:
        """Restituisce le tolleranze correnti (thread-safe read)."""
        with QMutexLocker(self._mutex):
            return ToleranceLimits(
                nominal_mm=self._tolerance.nominal_mm,
                upper_limit_mm=self._tolerance.upper_limit_mm,
                lower_limit_mm=self._tolerance.lower_limit_mm,
            )

    # ═══════════════════════════════════════════════════════════
    # AGGIUNTA / RIMOZIONE MISURE
    # ═══════════════════════════════════════════════════════════

    def add_measurement(
        self,
        width_mm: float,
        width_mm_std: float,
        width_px: float,
        angle_deg: float,
        contrast_ratio: float,
        n_scanlines: int,
        timestamp_s: float,
    ) -> MeasurementRecord:
        """
        Registra una nuova misura e aggiorna le statistiche.

        Thread-safe: può essere chiamato dal thread di acquisizione.

        Args:
            width_mm:       Larghezza media in mm
            width_mm_std:   Deviazione standard in mm
            width_px:       Larghezza media in pixel
            angle_deg:      Angolo medio della bandina
            contrast_ratio: Rapporto di contrasto
            n_scanlines:    Numero di scanline valide
            timestamp_s:    Timestamp della misura (time.perf_counter)

        Returns:
            MeasurementRecord creato.
        """
        with QMutexLocker(self._mutex):
            is_ok = self._tolerance.is_within_tolerance(width_mm)

            record = MeasurementRecord(
                index=self._next_index,
                width_mm=width_mm,
                width_mm_std=width_mm_std,
                width_px=width_px,
                angle_deg=angle_deg,
                contrast_ratio=contrast_ratio,
                n_scanlines=n_scanlines,
                timestamp_s=timestamp_s - self._start_time,
                is_within_tolerance=is_ok,
                is_excluded=False,
            )

            self._records.append(record)
            self._next_index += 1

            # Aggiornamento incrementale Welford
            self._welford.update(width_mm)

            if is_ok:
                self._count_ok += 1
            else:
                self._count_nok += 1

        logger.debug(
            f"Misura #{record.index}: {width_mm:.3f} ± {width_mm_std:.3f} mm "
            f"({'OK' if is_ok else 'NOK'})"
        )

        self.record_added.emit(record)
        self._emit_statistics()

        return record

    def remove_measurement(self, index: int) -> bool:
        """
        Rimuove (esclude) una misura dal calcolo statistico.

        Non elimina fisicamente il record ma lo marca come escluso.
        Le statistiche vengono ricalcolate completamente per garantire
        correttezza di min/max.

        Args:
            index: Indice della misura da escludere.

        Returns:
            True se la misura è stata trovata e rimossa.
        """
        with QMutexLocker(self._mutex):
            record = self._find_record_by_index(index)
            if record is None:
                logger.warning(f"Misura #{index} non trovata per la rimozione")
                return False

            if record.is_excluded:
                logger.warning(f"Misura #{index} già esclusa")
                return False

            record.is_excluded = True

            # Ricalcolo completo necessario per min/max corretti
            self._recalculate_all()

        logger.info(f"Misura #{index} esclusa dalle statistiche")

        self.record_removed.emit(index)
        self._emit_statistics()

        return True

    def restore_measurement(self, index: int) -> bool:
        """Ripristina una misura precedentemente esclusa."""
        with QMutexLocker(self._mutex):
            record = self._find_record_by_index(index)
            if record is None:
                return False

            if not record.is_excluded:
                return False

            record.is_excluded = False
            self._recalculate_all()

        logger.info(f"Misura #{index} ripristinata nelle statistiche")

        self.record_added.emit(record)
        self._emit_statistics()

        return True

    def clear_all(self):
        """Cancella tutte le misure e resetta le statistiche."""
        with QMutexLocker(self._mutex):
            self._records.clear()
            self._next_index = 1
            self._welford.reset()
            self._count_ok = 0
            self._count_nok = 0

        logger.info("Tutte le misure cancellate")

        self.data_cleared.emit()
        self._emit_statistics()

    # ═══════════════════════════════════════════════════════════
    # ACCESSO DATI (Thread-safe)
    # ═══════════════════════════════════════════════════════════

    def get_snapshot(self) -> StatisticsSnapshot:
        """
        Restituisce una fotografia immutabile delle statistiche.
        Thread-safe.
        """
        with QMutexLocker(self._mutex):
            return self._build_snapshot()

    def get_all_records(self) -> list[MeasurementRecord]:
        """Restituisce una copia di tutti i record (inclusi esclusi)."""
        with QMutexLocker(self._mutex):
            return list(self._records)

    def get_valid_records(self) -> list[MeasurementRecord]:
        """Restituisce solo i record non esclusi."""
        with QMutexLocker(self._mutex):
            return [r for r in self._records if not r.is_excluded]

    def get_values_mm(self) -> list[float]:
        """Restituisce la lista dei valori validi in mm."""
        with QMutexLocker(self._mutex):
            return [r.width_mm for r in self._records if not r.is_excluded]

    @property
    def count(self) -> int:
        """Numero totale di misure (incluse escluse)."""
        with QMutexLocker(self._mutex):
            return len(self._records)

    @property
    def count_valid(self) -> int:
        """Numero di misure valide (non escluse)."""
        with QMutexLocker(self._mutex):
            return sum(1 for r in self._records if not r.is_excluded)

    # ═══════════════════════════════════════════════════════════
    # CALCOLI INTERNI
    # ═══════════════════════════════════════════════════════════

    def _recalculate_all(self):
        """
        Ricalcola tutte le statistiche da zero sui record non esclusi.
        Chiamato dopo rimozione/ripristino per garantire min/max corretti.
        DEVE essere chiamato con mutex già acquisito.
        """
        self._welford.reset()
        self._count_ok = 0
        self._count_nok = 0

        for record in self._records:
            if record.is_excluded:
                continue

            self._welford.update(record.width_mm)

            if record.is_within_tolerance:
                self._count_ok += 1
            else:
                self._count_nok += 1

    def _build_snapshot(self) -> StatisticsSnapshot:
        """
        Costruisce lo snapshot delle statistiche correnti.
        DEVE essere chiamato con mutex già acquisito.
        """
        valid_values = [r.width_mm for r in self._records if not r.is_excluded]
        count_valid = len(valid_values)

        # Mediana calcolata dal buffer completo
        if count_valid > 0:
            sorted_values = sorted(valid_values)
            mid = count_valid // 2
            if count_valid % 2 == 0:
                median = (sorted_values[mid - 1] + sorted_values[mid]) / 2.0
            else:
                median = sorted_values[mid]
        else:
            median = 0.0

        # Cp e Cpk
        cp = 0.0
        cpk = 0.0

        if (
            self._tolerance.is_configured
            and count_valid >= 2
            and self._welford.std > 0
        ):
            usl = self._tolerance.upper_limit_mm
            lsl = self._tolerance.lower_limit_mm
            sigma = self._welford.std
            mu = self._welford.mean

            if usl != float('inf') and lsl != float('-inf'):
                cp = (usl - lsl) / (6.0 * sigma)
                cpu = (usl - mu) / (3.0 * sigma)
                cpl = (mu - lsl) / (3.0 * sigma)
                cpk = min(cpu, cpl)
            elif usl != float('inf'):
                cpk = (usl - mu) / (3.0 * sigma)
            elif lsl != float('-inf'):
                cpk = (mu - lsl) / (3.0 * sigma)

        # Ultimo valore
        last_value = 0.0
        last_std = 0.0
        if self._records:
            for record in reversed(self._records):
                if not record.is_excluded:
                    last_value = record.width_mm
                    last_std = record.width_mm_std
                    break

        # Percentuale OK
        total_evaluated = self._count_ok + self._count_nok
        ok_pct = (self._count_ok / total_evaluated * 100.0) if total_evaluated > 0 else 0.0

        return StatisticsSnapshot(
            count=len(self._records),
            count_valid=count_valid,
            count_ok=self._count_ok,
            count_nok=self._count_nok,
            mean_mm=self._welford.mean,
            std_mm=self._welford.std,
            min_mm=self._welford.minimum,
            max_mm=self._welford.maximum,
            range_mm=self._welford.range,
            median_mm=median,
            last_value_mm=last_value,
            last_value_std_mm=last_std,
            cp=cp,
            cpk=cpk,
            tolerance=ToleranceLimits(
                nominal_mm=self._tolerance.nominal_mm,
                upper_limit_mm=self._tolerance.upper_limit_mm,
                lower_limit_mm=self._tolerance.lower_limit_mm,
            ),
            ok_percentage=ok_pct,
            values_mm=list(valid_values),
        )

    def _find_record_by_index(self, index: int) -> Optional[MeasurementRecord]:
        """
        Trova un record per indice.
        DEVE essere chiamato con mutex già acquisito.
        """
        for record in self._records:
            if record.index == index:
                return record
        return None

    def _emit_statistics(self):
        """Emette il segnale con lo snapshot corrente."""
        snapshot = self.get_snapshot()
        self.statistics_updated.emit(snapshot)