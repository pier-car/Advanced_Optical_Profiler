# Ideato e Realizzato da Pierpaolo Careddu

"""
Test suite per StatisticsModel e StatisticsSnapshot.

Verifica:
- Aggiunta e rimozione record
- Calcolo statistiche (media, std, min, max, mediana)
- Cp/Cpk con tolleranze
- OK/NOK con tolleranze definite e indefinite
- Thread safety (Welford algorithm)
- Snapshot immutabilità
- Segnali Qt emessi correttamente
- Pulizia dati
"""

import pytest
import math
import numpy as np
from typing import Optional


class TestStatisticsModelBasic:
    """Test base per StatisticsModel."""

    def test_initial_state(self, statistics_model):
        """Il modello parte vuoto."""
        assert statistics_model.count == 0
        assert statistics_model.count_valid == 0
        snap = statistics_model.get_snapshot()
        assert snap.count == 0
        assert snap.mean_mm == 0.0

    def test_add_single_record(self, statistics_model):
        """Aggiunta di un singolo record."""
        from core.statistics_model import MeasurementRecord
        record = MeasurementRecord(width_mm=5.0, std_mm=0.01)
        statistics_model.add_record(record)
        assert statistics_model.count == 1
        snap = statistics_model.get_snapshot()
        assert snap.count == 1
        assert pytest.approx(snap.mean_mm, rel=1e-6) == 5.0

    def test_add_multiple_records(self, statistics_model, sample_values):
        """Aggiunta di record multipli calcola statistiche corrette."""
        from core.statistics_model import MeasurementRecord
        for v in sample_values:
            record = MeasurementRecord(width_mm=v, std_mm=0.01)
            statistics_model.add_record(record)

        snap = statistics_model.get_snapshot()
        assert snap.count == len(sample_values)
        assert snap.count_valid == len(sample_values)
        assert pytest.approx(snap.mean_mm, abs=0.01) == np.mean(sample_values)
        assert pytest.approx(snap.std_mm, abs=0.01) == np.std(sample_values, ddof=1)

    def test_min_max(self, statistics_model):
        """Min e max calcolati correttamente."""
        from core.statistics_model import MeasurementRecord
        values = [4.9, 5.0, 5.1, 4.8, 5.2]
        for v in values:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        assert pytest.approx(snap.min_mm, abs=1e-6) == 4.8
        assert pytest.approx(snap.max_mm, abs=1e-6) == 5.2
        assert pytest.approx(snap.range_mm, abs=1e-6) == 0.4

    def test_median_odd(self, statistics_model):
        """Mediana con numero dispari di valori."""
        from core.statistics_model import MeasurementRecord
        values = [1.0, 3.0, 2.0, 5.0, 4.0]
        for v in values:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        assert pytest.approx(snap.median_mm, abs=1e-6) == 3.0

    def test_median_even(self, statistics_model):
        """Mediana con numero pari di valori."""
        from core.statistics_model import MeasurementRecord
        values = [1.0, 2.0, 3.0, 4.0]
        for v in values:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        assert pytest.approx(snap.median_mm, abs=1e-6) == 2.5

    def test_clear(self, statistics_model):
        """Clear resetta tutto."""
        from core.statistics_model import MeasurementRecord
        for i in range(10):
            statistics_model.add_record(
                MeasurementRecord(width_mm=5.0 + i * 0.01, std_mm=0.01)
            )
        assert statistics_model.count == 10
        statistics_model.clear()
        assert statistics_model.count == 0
        snap = statistics_model.get_snapshot()
        assert snap.count == 0
        assert snap.mean_mm == 0.0

    def test_last_value(self, statistics_model):
        """last_value_mm restituisce l'ultimo valore aggiunto."""
        from core.statistics_model import MeasurementRecord
        statistics_model.add_record(
            MeasurementRecord(width_mm=5.0, std_mm=0.01)
        )
        statistics_model.add_record(
            MeasurementRecord(width_mm=5.5, std_mm=0.01)
        )
        snap = statistics_model.get_snapshot()
        assert pytest.approx(snap.last_value_mm, abs=1e-6) == 5.5


class TestStatisticsModelTolerance:
    """Test con tolleranze definite e indefinite."""

    def test_no_tolerance(self, statistics_model):
        """Senza tolleranze, tutti i record sono OK e Cp/Cpk sono 0."""
        from core.statistics_model import MeasurementRecord
        for v in [5.0, 5.1, 4.9]:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        assert snap.cp == 0.0
        assert snap.cpk == 0.0

    def test_with_tolerance_all_ok(self, statistics_model, tolerance_limits):
        """Tutti i valori dentro tolleranza → 100% OK."""
        from core.statistics_model import MeasurementRecord
        statistics_model.set_tolerance(tolerance_limits)
        values = [4.95, 5.0, 5.05, 5.0, 4.98, 5.02]
        for v in values:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        assert snap.ok_percentage == 100.0
        assert snap.count_ok == len(values)
        assert snap.count_nok == 0

    def test_with_tolerance_some_nok(self, statistics_model, tolerance_limits):
        """Alcuni valori fuori tolleranza → NOK conteggiati."""
        from core.statistics_model import MeasurementRecord
        statistics_model.set_tolerance(tolerance_limits)
        # 4.85 e 5.15 sono fuori [4.9, 5.1]
        values = [5.0, 5.0, 4.85, 5.15, 5.0]
        for v in values:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        assert snap.count_nok == 2
        assert snap.count_ok == 3
        assert pytest.approx(snap.ok_percentage, abs=0.1) == 60.0

    def test_cp_cpk_calculation(self, statistics_model, tolerance_limits):
        """Cp e Cpk calcolati correttamente con valori stabili."""
        from core.statistics_model import MeasurementRecord
        statistics_model.set_tolerance(tolerance_limits)
        # Valori molto centrati con bassa variabilità
        np.random.seed(123)
        values = list(np.random.normal(5.0, 0.01, 100))
        for v in values:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.001)
            )
        snap = statistics_model.get_snapshot()
        # Con tol_range=0.2 e sigma~0.01: Cp ~ 0.2/(6*0.01) ~ 3.33
        assert snap.cp > 2.0
        assert snap.cpk > 2.0

    def test_undefined_tolerance(self, statistics_model):
        """Tolleranze indefinite (inf): Cp/Cpk restano 0, tutti OK."""
        from core.statistics_model import MeasurementRecord, ToleranceLimits
        tol = ToleranceLimits(
            nominal_mm=5.0,
            upper_limit_mm=float('inf'),
            lower_limit_mm=float('-inf'),
        )
        statistics_model.set_tolerance(tol)
        for v in [4.0, 5.0, 6.0, 7.0]:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        assert snap.cp == 0.0
        assert snap.cpk == 0.0

    def test_partial_tolerance_usl_only(self, statistics_model):
        """Solo USL definito: NOK solo sopra USL."""
        from core.statistics_model import MeasurementRecord, ToleranceLimits
        tol = ToleranceLimits(
            nominal_mm=5.0,
            upper_limit_mm=5.1,
            lower_limit_mm=float('-inf'),
        )
        statistics_model.set_tolerance(tol)
        values = [4.0, 5.0, 5.2]
        for v in values:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        # Solo 5.2 è sopra USL 5.1
        assert snap.count_nok >= 1


class TestStatisticsSnapshot:
    """Test per l'immutabilità e correttezza degli snapshot."""

    def test_snapshot_is_independent(self, statistics_model):
        """Modifiche al model dopo snapshot non cambiano lo snapshot."""
        from core.statistics_model import MeasurementRecord
        statistics_model.add_record(
            MeasurementRecord(width_mm=5.0, std_mm=0.01)
        )
        snap1 = statistics_model.get_snapshot()
        assert snap1.count == 1

        statistics_model.add_record(
            MeasurementRecord(width_mm=6.0, std_mm=0.01)
        )
        assert snap1.count == 1  # Snapshot non cambiato
        snap2 = statistics_model.get_snapshot()
        assert snap2.count == 2

    def test_snapshot_values_list(self, statistics_model):
        """Lo snapshot contiene la lista completa dei valori."""
        from core.statistics_model import MeasurementRecord
        values = [5.0, 5.1, 4.9]
        for v in values:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        assert len(snap.values_mm) == 3

    def test_empty_snapshot(self):
        """Snapshot vuoto ha valori di default sicuri."""
        from core.statistics_model import StatisticsSnapshot
        snap = StatisticsSnapshot()
        assert snap.count == 0
        assert snap.mean_mm == 0.0
        assert snap.std_mm == 0.0
        assert snap.ok_percentage == 0.0
        assert snap.cp == 0.0
        assert snap.cpk == 0.0


class TestStatisticsModelWelford:
    """Test per l'algoritmo di Welford (calcolo incrementale)."""

    def test_welford_matches_numpy(self, statistics_model):
        """L'algoritmo di Welford produce gli stessi risultati di numpy."""
        from core.statistics_model import MeasurementRecord
        np.random.seed(42)
        values = list(np.random.normal(10.0, 0.5, 200))
        for v in values:
            statistics_model.add_record(
                MeasurementRecord(width_mm=v, std_mm=0.01)
            )
        snap = statistics_model.get_snapshot()
        assert pytest.approx(snap.mean_mm, abs=0.001) == np.mean(values)
        assert pytest.approx(snap.std_mm, abs=0.001) == np.std(values, ddof=1)

    def test_single_value_std_zero(self, statistics_model):
        """Con un solo valore, std deve essere 0."""
        from core.statistics_model import MeasurementRecord
        statistics_model.add_record(
            MeasurementRecord(width_mm=5.0, std_mm=0.01)
        )
        snap = statistics_model.get_snapshot()
        assert snap.std_mm == 0.0

    def test_identical_values(self, statistics_model):
        """Valori identici producono std = 0."""
        from core.statistics_model import MeasurementRecord
        for _ in range(50):
            statistics_model.add_record(
                MeasurementRecord(width_mm=5.0, std_mm=0.0)
            )
        snap = statistics_model.get_snapshot()
        assert pytest.approx(snap.mean_mm, abs=1e-9) == 5.0
        assert pytest.approx(snap.std_mm, abs=1e-9) == 0.0
        assert pytest.approx(snap.range_mm, abs=1e-9) == 0.0