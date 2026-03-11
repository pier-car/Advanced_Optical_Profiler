# Ideato e Realizzato da Pierpaolo Careddu

"""
Configurazione globale dell'applicazione Advanced Optical Profiler.

Tutte le costanti, percorsi, parametri di default e versione
sono centralizzati qui. Nessun magic number nel resto del codice.
"""

import os
from pathlib import Path


# ═══════════════════════════════════════════════════════════════
# VERSIONE E IDENTITÀ
# ═══════════════════════════════════════════════════════════════

APP_NAME = "Advanced Optical Profiler"
APP_CODENAME = "BandinaVision"
APP_VERSION = "1.0.0"
APP_AUTHOR = "Pierpaolo Careddu"
APP_ORG = "Pirelli R&D"
APP_DESCRIPTION = "Sistema metrologico ottico per il controllo dimensionale"

# ═══════════════════════════════════════════════════════════════
# PERCORSI
# ═══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent.resolve()
ASSETS_DIR = BASE_DIR / "assets"
STYLES_DIR = ASSETS_DIR / "styles"
DATA_DIR = BASE_DIR / "data"
EXPORT_DIR = BASE_DIR / "exports"
CALIBRATION_DIR = DATA_DIR / "calibration"
SESSIONS_DIR = DATA_DIR / "sessions"
LOGS_DIR = BASE_DIR / "logs"

QSS_FILE = STYLES_DIR / "theme_industriale.qss"
OPERATORS_HISTORY_FILE = DATA_DIR / "operators_history.json"
CALIBRATION_FILE = CALIBRATION_DIR / "calibration.yaml"

# Crea le directory necessarie se non esistono
for d in [DATA_DIR, EXPORT_DIR, CALIBRATION_DIR, SESSIONS_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# CAMERA
# ═══════════════════════════════════════════════════════════════

CAMERA_SIMULATE = False
CAMERA_DEFAULT_EXPOSURE_US = 8000
CAMERA_DEFAULT_GAIN_DB = 0.0
CAMERA_EXPOSURE_RANGE = (100, 100000)
CAMERA_GAIN_RANGE = (0.0, 24.0)
CAMERA_SIMULATED_FPS = 30
CAMERA_SIMULATED_WIDTH = 3840
CAMERA_SIMULATED_HEIGHT = 2160

# ═══════════════════════════════════════════════════════════════
# METROLOGIA
# ═══════════════════════════════════════════════════════════════

METROLOGY_NUM_SCANLINES = 20
METROLOGY_PROFILE_HALF_LENGTH = 50
METROLOGY_EDGE_THRESHOLD = 30
METROLOGY_RANSAC_MAX_TRIALS = 100  # iterazioni RANSAC (ridotto da 1000 per CPU)
METROLOGY_MEASURE_EVERY_N_FRAMES = 3  # misura ogni N frame (riduce carico CPU)
METROLOGY_RANSAC_THRESHOLD = 3.0
METROLOGY_MIN_INLIERS_RATIO = 0.6

# Impostazioni ROI (Region of Interest)
# ROI_ENABLED   = True
# ROI_CENTER_X  = 1920   # centro orizzontale (3840 / 2)
# ROI_CENTER_Y  = 1374   # centro verticale   (2748 / 2)
# ROI_WIDTH     = 600    # larghezza ROI in pixel
# ROI_HEIGHT    = 1000   # altezza ROI (deve contenere la bandina + margini)

# # Derivato — non modificare:
# ROI_X = ROI_CENTER_X - ROI_WIDTH  // 2   # = 1620
# ROI_Y = ROI_CENTER_Y - ROI_HEIGHT // 2   # =  874
# Impostazioni ROI (Region of Interest)
ROI_ENABLED = True
ROI_WIDTH   = 600    # larghezza ROI in pixel
ROI_HEIGHT  = 1000   # altezza ROI (deve contenere la bandina + margini)

# ROI avanzata per la pipeline metrologica
METROLOGY_ROI_ENABLED    = True
METROLOGY_ROI_Y_CENTER   = 0.5   # Centro della fascia (0.5 = metà altezza)
METROLOGY_ROI_HEIGHT_PX  = 800   # Altezza della fascia da analizzare [px]
UI_UPDATE_EVERY_N_FRAMES = 5     # Calcola istogramma/sharpness ogni N frame

# ═══════════════════════════════════════════════════════════════
# CALIBRAZIONE
# ═══════════════════════════════════════════════════════════════

CALIBRATION_EXPIRY_DAYS = 30
CALIBRATION_DEFAULT_SAMPLE_MM = 25.0

# ═══════════════════════════════════════════════════════════════
# STABILITÀ (Auto-Trigger)
# ═══════════════════════════════════════════════════════════════

STABILITY_BUFFER_SIZE = 12
STABILITY_THRESHOLD_MM = 0.05
STABILITY_REQUIRED_FRAMES = 8
STABILITY_COOLDOWN_SECONDS = 2.0

# ═══════════════════════════════════════════════════════════════
# TOLLERANZE DEFAULT
# ═══════════════════════════════════════════════════════════════

TOLERANCE_DEFAULT_NOMINAL_MM = 0.0
TOLERANCE_DEFAULT_UPPER_MM = float('inf')
TOLERANCE_DEFAULT_LOWER_MM = float('-inf')

# ═══════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════

EXPORT_PDF_AUTHOR = APP_AUTHOR
EXPORT_PDF_TITLE_PREFIX = "Report Metrologico"
EXPORT_CSV_DELIMITER = ";"
EXPORT_CSV_DECIMAL = ","
EXPORT_CSV_ENCODING = "utf-8-sig"
EXPORT_TIMESTAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"
EXPORT_DATE_FORMAT = "%Y-%m-%d"
EXPORT_TIME_FORMAT = "%H:%M:%S"

# ═══════════════════════════════════════════════════════════════
# UI
# ═══════════════════════════════════════════════════════════════

UI_MIN_WINDOW_WIDTH = 1280
UI_MIN_WINDOW_HEIGHT = 800
UI_LEFT_PANEL_MIN_WIDTH = 240
UI_LEFT_PANEL_MAX_WIDTH = 320
UI_LIVE_VIEW_MIN_HEIGHT = 200
UI_STATS_PANEL_MIN_HEIGHT = 120
UI_TABLE_MIN_HEIGHT = 80
UI_SPLITTER_RATIOS = (55, 25, 20)
UI_FONT_FAMILY = "Segoe UI"
UI_FONT_MONO = "Consolas"

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s"

LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

