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
import cv2
import numpy as np
import yaml
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_CALIBRATION_FILE = Path("data/calibration_data.yaml")
CALIBRATION_MAX_AGE_DAYS = 30

# ═══════════════════════════════════════════════════════════════
# COSTANTI CALIBRAZIONE USAF CLICK
# ═══════════════════════════════════════════════════════════════
USAF_PROFILE_HALF_X = 150       # ±150px attorno al click → 300px totali
USAF_GAUSS_KERNEL = (5, 5)
USAF_GAUSS_SIGMA = 1.0
USAF_MIN_GRADIENT = 2.0         # soglia minima |gradiente|
USAF_GRADIENT_THRESHOLD_RATIO = 0.25
USAF_MIN_GAP_PX = 10.0
USAF_MAX_GAP_RATIO = 1.5       # gap massimo = half_x * ratio


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
        # API legacy: calcola la distanza dai due punti.
        # np.asarray garantisce la compatibilità con liste Python o tuple.
        if point_a_px is not None and point_b_px is not None:
            distance_px = float(np.linalg.norm(
                np.asarray(point_b_px, dtype=np.float64)
                - np.asarray(point_a_px, dtype=np.float64)
            ))

        # API legacy: usa known_distance_mm se distance_mm non è fornito
        if known_distance_mm is not None:
            distance_mm = float(known_distance_mm)

        # API legacy: ricava centro ottico da image_shape (height, width).
        # optical_center è (cx, cy) = (width/2, height/2) → indici [1] e [0].
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

    # ─── CLICK-TO-CALIBRATE USAF 1951 ─────────────────────────

    @staticmethod
    def _parabolic_refine(
        positions: np.ndarray,
        values: np.ndarray,
        peak_idx: int,
    ) -> float:
        """
        Raffinamento sub-pixel parabolico a 5 punti attorno a peak_idx.
        Fitta y = a·x² + b·x + c e restituisce il vertice x = -b/(2a).
        """
        if peak_idx < 2 or peak_idx >= len(values) - 2:
            return float(positions[peak_idx])

        sl = slice(peak_idx - 2, peak_idx + 3)
        xf = positions[sl].astype(np.float64)
        yf = values[sl].astype(np.float64)

        if len(xf) < 3:
            return float(positions[peak_idx])

        try:
            c = np.polyfit(xf, yf, 2)
        except (np.linalg.LinAlgError, ValueError):
            return float(positions[peak_idx])

        if abs(c[0]) < 1e-15:
            return float(positions[peak_idx])

        vertex = -c[1] / (2.0 * c[0])

        if abs(vertex - positions[peak_idx]) > 3.0:
            return float(positions[peak_idx])

        return float(vertex)

    def calibrate_from_usaf_click(
        self,
        frame: np.ndarray,
        click_x: int,
        click_y: int,
        known_gap_mm: float = 2.0,
        half_x: int = USAF_PROFILE_HALF_X,
    ) -> dict:
        """
        Calibrazione Click-to-Calibrate da target USAF 1951 Negativo.

        Algorithm:
            1. Extract horizontal profile at y=click_y, x in [cx-half_x, cx+half_x]
            2. Compute signed gradient via np.diff
            3. Find all FALLING (bright→dark) and RISING (dark→bright) edges
            4. Find closest Falling→Rising pair to click point
            5. Sub-pixel parabolic refinement on both edges
            6. gap_px = rising_x - falling_x
            7. mm_per_px = known_gap_mm / gap_px
            8. Update _scale_factor and trigger YAML save

        Args:
            frame:        Greyscale frame (H×W, uint8) or BGR (H×W×3)
            click_x:      Click X coordinate in sensor pixels
            click_y:      Click Y coordinate in sensor pixels
            known_gap_mm: Physical gap size in mm (default: 2.0)
            half_x:       Half-width of profile extraction window

        Returns:
            dict with keys: ok, mm_per_px, gap_px, profile_y, edge1_x, edge2_x,
            x_lo, x_hi, click_x, click_y, error
        """
        if frame.ndim == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        h, w = gray.shape

        result = {
            "ok": False, "mm_per_px": 0.0, "gap_px": 0.0,
            "profile_y": click_y, "edge1_x": 0.0, "edge2_x": 0.0,
            "x_lo": 0, "x_hi": 0, "click_x": click_x, "click_y": click_y,
            "error": "",
        }

        if click_y < 0 or click_y >= h or click_x < 0 or click_x >= w:
            result["error"] = (
                f"Click ({click_x},{click_y}) fuori dal frame ({w}×{h})"
            )
            logger.warning(result["error"])
            return result

        x_lo = max(0, click_x - half_x)
        x_hi = min(w - 1, click_x + half_x)
        result["x_lo"] = x_lo
        result["x_hi"] = x_hi

        if x_hi - x_lo < 20:
            result["error"] = (
                f"Profilo troppo corto: {x_hi - x_lo}px. "
                f"Click troppo vicino al bordo del frame?"
            )
            logger.warning(result["error"])
            return result

        blurred = cv2.GaussianBlur(gray, USAF_GAUSS_KERNEL, USAF_GAUSS_SIGMA)
        profile = blurred[click_y, x_lo:x_hi + 1].astype(np.float64)
        x_coords = np.arange(x_lo, x_hi + 1, dtype=np.float64)

        grad = np.diff(profile)
        grad_x = x_coords[:-1] + 0.5
        grad_abs = np.abs(grad)

        if grad_abs.max() < USAF_MIN_GRADIENT:
            result["error"] = (
                f"Nessun bordo rilevato al click ({click_x},{click_y}): "
                f"max|grad|={grad_abs.max():.1f}. "
                f"Cliccare su uno spazio tra le barre."
            )
            logger.warning(result["error"])
            return result

        thr = USAF_GRADIENT_THRESHOLD_RATIO * grad_abs.max()
        falling_peaks = []
        rising_peaks = []

        for i in range(1, len(grad) - 1):
            is_max = (
                grad_abs[i] >= grad_abs[i - 1]
                and grad_abs[i] > grad_abs[i + 1]
            )
            if is_max and grad_abs[i] > thr:
                if grad[i] < 0:
                    falling_peaks.append(i)
                else:
                    rising_peaks.append(i)

        best_pair = None
        min_dist = np.inf
        click_idx = click_x - x_lo

        for f_idx in falling_peaks:
            for r_idx in rising_peaks:
                if f_idx < r_idx:
                    gap_width = r_idx - f_idx
                    if (USAF_MIN_GAP_PX < gap_width
                            < half_x * USAF_MAX_GAP_RATIO):
                        gap_center = (f_idx + r_idx) / 2.0
                        dist = abs(gap_center - click_idx)
                        if dist < min_dist:
                            min_dist = dist
                            best_pair = (f_idx, r_idx)

        if best_pair is None:
            result["error"] = (
                "Nessuno spazio nero trovato vicino al click. "
                "Assicurarsi di cliccare al CENTRO di uno spazio tra le barre."
            )
            logger.warning(result["error"])
            return result

        neg_idx, pos_idx = best_pair

        e_neg = self._parabolic_refine(grad_x, grad_abs, neg_idx)
        e_pos = self._parabolic_refine(grad_x, grad_abs, pos_idx)

        e1 = min(e_neg, e_pos)
        e2 = max(e_neg, e_pos)
        gap_px = abs(e2 - e1)

        if gap_px < 3.0:
            result["error"] = (
                f"Gap misurato troppo stretto ({gap_px:.1f}px). "
                f"Cliccare al CENTRO di uno spazio tra le barre."
            )
            logger.warning(result["error"])
            return result

        mm_per_px = known_gap_mm / gap_px

        self._scale_factor = mm_per_px
        self._cx = float(w / 2.0)
        self._cy = float(h / 2.0)
        self._calibration_date = datetime.now()
        self._is_calibrated = True
        self._calibration_notes = (
            f"USAF Click-to-Calibrate: gap={gap_px:.2f}px, "
            f"click=({click_x},{click_y}), "
            f"known_gap={known_gap_mm:.3f}mm"
        )

        self._save()

        result["ok"] = True
        result["mm_per_px"] = mm_per_px
        result["gap_px"] = gap_px
        result["edge1_x"] = e1
        result["edge2_x"] = e2

        logger.info(
            f"USAF Click-to-Calibrate OK: "
            f"gap={gap_px:.2f}px, mm/px={mm_per_px:.6f}, "
            f"bordi a x={e1:.1f} e x={e2:.1f}"
        )

        return result

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