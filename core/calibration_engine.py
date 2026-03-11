"""
CalibrationEngine — Gestione calibrazione pixel → millimetri.

Supporta:
- Calibrazione lineare da distanza nota (target USAF 1951)
- Correzione distorsione radiale (coefficiente k1)
- Persistenza su file YAML
- Validazione temporale della calibrazione

Autore: R&D Metrologia
Versione: 1.1
"""

import logging
import numpy as np
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_CALIBRATION_FILE = Path("data/calibration_data.yaml")
CALIBRATION_MAX_AGE_DAYS = 30


class CalibrationEngine:
    """
    Motore di calibrazione per conversione pixel ↔ millimetri.

    Utilizzo:
        cal = CalibrationEngine()
        cal.load()  # Carica calibrazione precedente se esiste

        # Oppure calibra da zero (API semplificata):
        cal.calibrate_from_known_distance(
            distance_px=800.0,
            distance_mm=20.0,
            optical_center=(1920.0, 1080.0),
        )

        # Oppure con i due punti (API legacy — CalibrationWizard):
        cal.calibrate_from_known_distance(
            point_a_px=np.array([100, 500]),
            point_b_px=np.array([900, 500]),
            known_distance_mm=14.6,
            image_shape=(2748, 3840),
        )

        # Converti
        mm = cal.px_to_mm(distance_px=523.7)
    """

    def __init__(self, calibration_dir: Optional[str] = None):
        """
        Args:
            calibration_dir: Directory dove salvare/caricare il file YAML di
                             calibrazione. Se None, usa il percorso di default
                             ``data/calibration_data.yaml``.
        """
        if calibration_dir is not None:
            cal_dir = Path(calibration_dir)
            cal_dir.mkdir(parents=True, exist_ok=True)
            self._calibration_file = cal_dir / "calibration_data.yaml"
        else:
            self._calibration_file = _DEFAULT_CALIBRATION_FILE

        self._scale_factor: float = 0.0         # mm/pixel
        self._k1_radial: float = 0.0            # Coefficiente distorsione radiale
        self._cx: float = 0.0                    # Centro ottico x
        self._cy: float = 0.0                    # Centro ottico y
        self._is_calibrated: bool = False
        self._calibration_date: Optional[datetime] = None
        self._calibration_notes: str = ""

    # ─── PROPRIETÀ ─────────────────────────────────────────────

    @property
    def is_calibrated(self) -> bool:
        return self._is_calibrated

    @property
    def scale_factor(self) -> float:
        """Fattore di scala mm/pixel."""
        return self._scale_factor

    @property
    def k1_radial(self) -> float:
        return self._k1_radial

    @property
    def optical_center(self) -> Optional[np.ndarray]:
        if self._cx > 0 and self._cy > 0:
            return np.array([self._cx, self._cy])
        return None

    @property
    def calibration_date(self) -> Optional[datetime]:
        return self._calibration_date

    @property
    def is_expired(self) -> bool:
        """Verifica se la calibrazione è scaduta."""
        if self._calibration_date is None:
            return True
        age = datetime.now() - self._calibration_date
        return age > timedelta(days=CALIBRATION_MAX_AGE_DAYS)

    @property
    def age_days(self) -> int:
        """Età della calibrazione in giorni."""
        if self._calibration_date is None:
            return -1
        return (datetime.now() - self._calibration_date).days

    # ─── CALIBRAZIONE ──────────────────────────────────────────

    def calibrate_from_known_distance(
        self,
        distance_px: float = 0.0,
        distance_mm: float = 0.0,
        optical_center: Optional[tuple] = None,
        # Backward-compatible keyword args used by CalibrationWizard
        point_a_px: Optional[np.ndarray] = None,
        point_b_px: Optional[np.ndarray] = None,
        known_distance_mm: Optional[float] = None,
        image_shape: Optional[tuple] = None,
    ):
        """
        Calibrazione lineare da distanza nota.

        Supporta due API:

        **API semplificata** (nuova):
            cal.calibrate_from_known_distance(
                distance_px=800.0,
                distance_mm=20.0,
                optical_center=(cx, cy),   # opzionale
            )

        **API con due punti** (legacy — CalibrationWizard):
            cal.calibrate_from_known_distance(
                point_a_px=np.array([x1, y1]),
                point_b_px=np.array([x2, y2]),
                known_distance_mm=14.6,
                image_shape=(height, width),  # opzionale
            )

        Args:
            distance_px:       Distanza in pixel già calcolata (API nuova)
            distance_mm:       Distanza nota in mm (API nuova)
            optical_center:    Centro ottico (cx, cy) in pixel (API nuova)
            point_a_px:        Primo punto [x, y] in pixel (API legacy)
            point_b_px:        Secondo punto [x, y] in pixel (API legacy)
            known_distance_mm: Distanza nota in mm (API legacy)
            image_shape:       (height, width) per calcolo centro (API legacy)
        """
        # ── Risolvi i parametri ──────────────────────────────────────────
        # API legacy: calcola la distanza dai due punti
        if point_a_px is not None and point_b_px is not None:
            distance_px = float(np.linalg.norm(
                np.asarray(point_b_px, dtype=np.float64)
                - np.asarray(point_a_px, dtype=np.float64)
            ))

        # API legacy: usa known_distance_mm se distance_mm non è fornito
        if known_distance_mm is not None:
            distance_mm = float(known_distance_mm)

        # API legacy: ricava centro ottico da image_shape
        if image_shape is not None and optical_center is None:
            optical_center = (image_shape[1] / 2.0, image_shape[0] / 2.0)

        # ── Validazione ──────────────────────────────────────────────────
        if distance_px < 10:
            raise ValueError(
                "Distanza in pixel troppo piccola per calibrazione affidabile "
                f"({distance_px:.1f} px; minimo 10 px)"
            )

        if distance_mm <= 0:
            raise ValueError(
                "La distanza nota deve essere positiva "
                f"(ricevuto {distance_mm:.3f} mm)"
            )

        # ── Calcolo fattore di scala ─────────────────────────────────────
        self._scale_factor = distance_mm / distance_px

        if optical_center is not None:
            self._cx = float(optical_center[0])
            self._cy = float(optical_center[1])
        else:
            self._cx = 0.0
            self._cy = 0.0

        self._calibration_date = datetime.now()
        self._is_calibrated = True

        logger.info(
            f"Calibrazione completata: {self._scale_factor:.6f} mm/px "
            f"({distance_px:.1f} px = {distance_mm:.3f} mm)"
        )

        self._save()

    def calibrate_distortion(
        self,
        grid_points_px: np.ndarray,
        grid_points_mm: np.ndarray
    ):
        """
        Calibrazione distorsione radiale da griglia di punti.

        Modello: r_corrected = r_measured · (1 + k1·r²)

        Args:
            grid_points_px: Punti della griglia in pixel (N, 2)
            grid_points_mm: Punti della griglia in mm (N, 2)
        """
        if not self._is_calibrated:
            raise RuntimeError("Eseguire prima la calibrazione lineare")

        dx = grid_points_px[:, 0] - self._cx
        dy = grid_points_px[:, 1] - self._cy
        r_px = np.sqrt(dx**2 + dy**2)

        dx_mm = grid_points_mm[:, 0]
        dy_mm = grid_points_mm[:, 1]
        r_mm = np.sqrt(dx_mm**2 + dy_mm**2)

        r_expected = r_px * self._scale_factor
        ratio = r_mm / (r_expected + 1e-12) - 1.0
        self._k1_radial = float(np.dot(ratio, r_px**2) / np.dot(r_px**2, r_px**2))

        logger.info(f"Distorsione radiale calibrata: k1 = {self._k1_radial:.2e}")
        self._save()

    # ─── CONVERSIONE ───────────────────────────────────────────

    def px_to_mm(
        self,
        distance_px: float,
        position_px: Optional[np.ndarray] = None
    ) -> float:
        """Converte una distanza in pixel a millimetri."""
        if not self._is_calibrated:
            raise RuntimeError("Sistema non calibrato!")

        correction = 1.0
        if position_px is not None and self._k1_radial != 0.0:
            dx = position_px[0] - self._cx
            dy = position_px[1] - self._cy
            r2 = dx**2 + dy**2
            correction = 1.0 + self._k1_radial * r2

        return distance_px * self._scale_factor * correction

    def mm_to_px(self, distance_mm: float) -> float:
        """Converte una distanza in millimetri a pixel (approssimata, senza distorsione)."""
        if not self._is_calibrated:
            raise RuntimeError("Sistema non calibrato!")
        return distance_mm / self._scale_factor

    # ─── PERSISTENZA ──────────────────────────────────────────────

    def save(self):
        """Salva la calibrazione su file YAML (metodo pubblico)."""
        self._save()

    def _save(self):
        """Salva la calibrazione su file YAML."""
        data = {
            'scale_factor_mm_per_px': float(self._scale_factor),
            'k1_radial': float(self._k1_radial),
            'cx': float(self._cx),
            'cy': float(self._cy),
            'calibration_date': self._calibration_date.isoformat() if self._calibration_date else None,
            'notes': self._calibration_notes,
        }
        try:
            self._calibration_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._calibration_file, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=False)
            logger.info(f"Calibrazione salvata in {self._calibration_file}")
        except IOError as e:
            logger.error(f"Errore salvataggio calibrazione: {e}")

    def load(self) -> bool:
        """
        Carica la calibrazione da file YAML.

        Returns:
            True se caricata con successo, False altrimenti.
        """
        try:
            if not self._calibration_file.exists():
                logger.info("Nessun file di calibrazione trovato")
                return False

            with open(self._calibration_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            self._scale_factor = float(data['scale_factor_mm_per_px'])
            self._k1_radial = float(data.get('k1_radial', 0.0))
            self._cx = float(data.get('cx', 0.0))
            self._cy = float(data.get('cy', 0.0))
            self._calibration_notes = data.get('notes', '')

            date_str = data.get('calibration_date')
            if date_str:
                self._calibration_date = datetime.fromisoformat(date_str)
            else:
                self._calibration_date = None

            self._is_calibrated = True

            age_str = f"{self.age_days} giorni" if self.age_days >= 0 else "sconosciuta"
            logger.info(
                f"Calibrazione caricata: {self._scale_factor:.6f} mm/px, "
                f"età: {age_str}"
            )

            if self.is_expired:
                logger.warning(
                    f"⚠️ Calibrazione scaduta (età: {self.age_days} giorni, "
                    f"max: {CALIBRATION_MAX_AGE_DAYS} giorni)"
                )

            return True

        except Exception as e:
            logger.error(f"Errore caricamento calibrazione: {e}")
            return False

    def reset(self):
        """Resetta la calibrazione."""
        self._scale_factor = 0.0
        self._k1_radial = 0.0
        self._cx = 0.0
        self._cy = 0.0
        self._is_calibrated = False
        self._calibration_date = None
        self._calibration_notes = ""
        logger.info("Calibrazione resettata")