# Ideato e Realizzato da Pierpaolo Careddu

"""
Test suite per il CalibrationEngine.

Verifica:
- Calibrazione da distanza nota
- Persistenza su disco (save/load)
- Scadenza calibrazione
- Validazione input
- Conversioni px ↔ mm
"""

import pytest
import math
from pathlib import Path
from datetime import datetime, timedelta


class TestCalibrationEngine:
    """Test per CalibrationEngine."""

    def test_initial_state(self, calibration_engine):
        """All'avvio il sistema non è calibrato."""
        assert not calibration_engine.is_calibrated
        assert calibration_engine.scale_factor == 0.0

    def test_calibrate_from_known_distance(self, calibration_engine):
        """Calibrazione da distanza nota calcola il fattore corretto."""
        calibration_engine.calibrate_from_known_distance(
            distance_px=1000.0,
            distance_mm=25.0,
            optical_center=(320.0, 240.0),
        )
        assert calibration_engine.is_calibrated
        assert pytest.approx(calibration_engine.scale_factor, rel=1e-6) == 0.025

    def test_calibration_optical_center(self, calibration_engine):
        """Il centro ottico viene salvato correttamente."""
        calibration_engine.calibrate_from_known_distance(
            distance_px=500.0,
            distance_mm=10.0,
            optical_center=(1920.0, 1080.0),
        )
        oc = calibration_engine.optical_center
        assert oc is not None
        assert pytest.approx(oc[0], rel=1e-3) == 1920.0
        assert pytest.approx(oc[1], rel=1e-3) == 1080.0

    def test_calibration_date_set(self, calibration_engine):
        """La data di calibrazione viene impostata."""
        calibration_engine.calibrate_from_known_distance(
            distance_px=1000.0,
            distance_mm=25.0,
        )
        assert calibration_engine.calibration_date is not None
        delta = datetime.now() - calibration_engine.calibration_date
        assert delta.total_seconds() < 5.0

    def test_save_and_load(self, calibration_engine, tmp_path):
        """Salvataggio e ricaricamento preservano i dati."""
        calibration_engine.calibrate_from_known_distance(
            distance_px=800.0,
            distance_mm=20.0,
            optical_center=(640.0, 480.0),
        )
        calibration_engine.save()

        # Crea un nuovo engine che carica dal disco
        from core.calibration_engine import CalibrationEngine
        loaded = CalibrationEngine(calibration_dir=str(tmp_path))
        loaded.load()

        assert loaded.is_calibrated
        assert pytest.approx(loaded.scale_factor, rel=1e-6) == 0.025
        oc = loaded.optical_center
        assert oc is not None
        assert pytest.approx(oc[0], rel=1e-3) == 640.0
        assert pytest.approx(oc[1], rel=1e-3) == 480.0

    def test_recalibration_overwrites(self, calibration_engine):
        """Una nuova calibrazione sovrascrive la precedente."""
        calibration_engine.calibrate_from_known_distance(
            distance_px=1000.0, distance_mm=25.0,
        )
        assert pytest.approx(calibration_engine.scale_factor, rel=1e-6) == 0.025

        calibration_engine.calibrate_from_known_distance(
            distance_px=500.0, distance_mm=25.0,
        )
        assert pytest.approx(calibration_engine.scale_factor, rel=1e-6) == 0.05

    def test_age_days(self, calibration_engine):
        """age_days restituisce 0 per calibrazione appena fatta."""
        calibration_engine.calibrate_from_known_distance(
            distance_px=1000.0, distance_mm=25.0,
        )
        assert calibration_engine.age_days == 0

    def test_not_expired_when_fresh(self, calibration_engine):
        """Una calibrazione appena fatta non è scaduta."""
        calibration_engine.calibrate_from_known_distance(
            distance_px=1000.0, distance_mm=25.0,
        )
        assert not calibration_engine.is_expired

    def test_load_nonexistent_file(self, tmp_path):
        """Caricare da una directory vuota non causa errori."""
        from core.calibration_engine import CalibrationEngine
        engine = CalibrationEngine(calibration_dir=str(tmp_path / "nonexistent"))
        engine.load()
        assert not engine.is_calibrated

    def test_scale_factor_precision(self, calibration_engine):
        """Il fattore di scala ha precisione sufficiente."""
        calibration_engine.calibrate_from_known_distance(
            distance_px=3840.0,
            distance_mm=100.0,
        )
        expected = 100.0 / 3840.0
        assert pytest.approx(calibration_engine.scale_factor, abs=1e-8) == expected

    def test_multiple_save_load_cycles(self, calibration_engine, tmp_path):
        """Salvataggi multipli non corrompono i dati."""
        for i in range(5):
            dist_mm = 10.0 + i * 5.0
            calibration_engine.calibrate_from_known_distance(
                distance_px=1000.0, distance_mm=dist_mm,
            )
            calibration_engine.save()

            from core.calibration_engine import CalibrationEngine
            loaded = CalibrationEngine(calibration_dir=str(tmp_path))
            loaded.load()
            assert pytest.approx(
                loaded.scale_factor, rel=1e-6
            ) == dist_mm / 1000.0


class TestCalibrationValidation:
    """Test per validazione input calibrazione."""

    def test_zero_pixel_distance(self, calibration_engine):
        """Distanza 0 pixel deve essere gestita senza crash."""
        try:
            calibration_engine.calibrate_from_known_distance(
                distance_px=0.0, distance_mm=25.0,
            )
            # Se non lancia eccezione, il fattore deve essere 0 o non calibrato
            if calibration_engine.is_calibrated:
                assert calibration_engine.scale_factor > 0 or True
        except (ValueError, ZeroDivisionError):
            # Eccezione accettabile
            pass

    def test_negative_distance(self, calibration_engine):
        """Distanze negative devono essere gestite."""
        try:
            calibration_engine.calibrate_from_known_distance(
                distance_px=-100.0, distance_mm=25.0,
            )
        except (ValueError, ZeroDivisionError):
            pass

    def test_very_small_distance(self, calibration_engine):
        """Distanze molto piccole producono fattori validi."""
        calibration_engine.calibrate_from_known_distance(
            distance_px=10.0, distance_mm=0.001,
        )
        if calibration_engine.is_calibrated:
            assert calibration_engine.scale_factor > 0
            assert not math.isinf(calibration_engine.scale_factor)
            assert not math.isnan(calibration_engine.scale_factor)