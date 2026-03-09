# Ideato e Realizzato da Pierpaolo Careddu

"""
conftest.py — Configurazione e fixture condivise per pytest.

Fornisce:
- Fixture per frame sintetici (grayscale, colore, con bandina)
- Fixture per componenti core (CalibrationEngine, StatisticsModel)
- Fixture per configurazioni di test
- Helper per test di integrazione Qt (se qtbot disponibile)
"""

import sys
import numpy as np
import pytest
from pathlib import Path
from datetime import datetime

# Aggiungi la root del progetto al path
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════
# FIXTURE: FRAME SINTETICI
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def grayscale_frame():
    """Frame grayscale 640x480 con gradiente."""
    frame = np.zeros((480, 640), dtype=np.uint8)
    for y in range(480):
        frame[y, :] = int(255 * y / 479)
    return frame


@pytest.fixture
def color_frame():
    """Frame BGR 640x480."""
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[:, :, 0] = 100  # B
    frame[:, :, 1] = 150  # G
    frame[:, :, 2] = 200  # R
    return frame


@pytest.fixture
def bandina_frame():
    """
    Frame sintetico con una bandina (striscia orizzontale bianca su sfondo nero).

    La bandina è centrata verticalmente, larga ~50px, con bordi netti.
    Utile per testare il MetrologyEngine.
    """
    frame = np.zeros((480, 640), dtype=np.uint8)
    # Bandina: riga 200-250 (50px di larghezza)
    frame[200:250, 50:590] = 220
    # Aggiungi un po' di rumore
    noise = np.random.normal(0, 5, frame.shape).astype(np.int16)
    frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return frame


@pytest.fixture
def bandina_frame_angled():
    """Frame sintetico con bandina leggermente inclinata (~2°)."""
    frame = np.zeros((480, 640), dtype=np.uint8)
    for x in range(50, 590):
        offset = int(x * 0.035)  # ~2 gradi
        y_top = 200 + offset
        y_bot = 250 + offset
        if 0 <= y_top < 480 and 0 <= y_bot < 480:
            frame[y_top:y_bot, x] = 220
    noise = np.random.normal(0, 3, frame.shape).astype(np.int16)
    frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return frame


@pytest.fixture
def empty_frame():
    """Frame completamente nero (nessun bordo)."""
    return np.zeros((480, 640), dtype=np.uint8)


@pytest.fixture
def white_frame():
    """Frame completamente bianco."""
    return np.full((480, 640), 255, dtype=np.uint8)


# ═══════════════════════════════════════════════════════════════
# FIXTURE: COMPONENTI CORE
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def calibration_engine(tmp_path):
    """CalibrationEngine con directory temporanea."""
    from core.calibration_engine import CalibrationEngine
    engine = CalibrationEngine(calibration_dir=str(tmp_path))
    return engine


@pytest.fixture
def calibrated_engine(tmp_path):
    """CalibrationEngine già calibrato."""
    from core.calibration_engine import CalibrationEngine
    engine = CalibrationEngine(calibration_dir=str(tmp_path))
    engine.calibrate_from_known_distance(
        distance_px=1000.0,
        distance_mm=25.0,
        optical_center=(320.0, 240.0),
    )
    engine.save()
    return engine


@pytest.fixture
def statistics_model():
    """StatisticsModel fresco."""
    from core.statistics_model import StatisticsModel
    model = StatisticsModel()
    return model


@pytest.fixture
def tolerance_limits():
    """ToleranceLimits standard per test."""
    from core.statistics_model import ToleranceLimits
    return ToleranceLimits(
        nominal_mm=5.0,
        upper_limit_mm=5.1,
        lower_limit_mm=4.9,
    )


@pytest.fixture
def sample_values():
    """Lista di valori simulati attorno a 5.0mm."""
    np.random.seed(42)
    return list(np.random.normal(5.0, 0.02, 50))


@pytest.fixture
def session_config():
    """SessionConfig standard per test."""
    from core.test_session import SessionConfig
    return SessionConfig(
        session_name="Test Session",
        operator_id="TEST_OP",
        nominal_mm=5.0,
        tolerance_upper_mm=5.1,
        tolerance_lower_mm=4.9,
        calibration_scale_mm_per_px=0.025,
    )


# ═══════════════════════════════════════════════════════════════
# FIXTURE: PERCORSI TEMPORANEI
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def export_dir(tmp_path):
    """Directory temporanea per export."""
    d = tmp_path / "exports"
    d.mkdir()
    return d


@pytest.fixture
def sessions_dir(tmp_path):
    """Directory temporanea per sessioni."""
    d = tmp_path / "sessions"
    d.mkdir()
    return d