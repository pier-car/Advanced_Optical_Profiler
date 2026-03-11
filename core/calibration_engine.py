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
import cv2
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_CALIBRATION_FILE = Path("data/calibration_data.yaml")
CALIBRATION_MAX_AGE_DAYS = 30

# ─── Costanti per calibrazione USAF Click-to-Calibrate ─────────────────────
USAF_PROFILE_HALF_X = 150          # semi-larghezza profilo orizzontale (px)
USAF_GAUSS_KERNEL = (5, 5)         # kernel blur pre-gradiente
USAF_GAUSS_SIGMA = 1.0             # sigma blur
USAF_MIN_GRADIENT = 2.0            # gradiente minimo per considerare un edge
USAF_GRADIENT_THRESHOLD_RATIO = 0.25  # soglia relativa al picco massimo
USAF_MIN_GAP_PX = 3.0              # gap minimo accettabile (px)
USAF_MAX_GAP_RATIO = 1.5           # gap massimo = ratio × atteso (px)


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

    # ─── CALIBRAZIONE USAF CLICK-TO-CALIBRATE ──────────────────────────────

    @staticmethod
    def _parabolic_refine(values: np.ndarray, peak_idx: int) -> float:
        """
        Raffinamento sub-pixel parabolico a 5 punti attorno a un picco.

        Interpola una parabola sui 5 campioni centrati su peak_idx e
        restituisce il vertice della parabola (posizione frazionaria).

        Args:
            values:    Array 1D di valori (es. gradiente assoluto)
            peak_idx:  Indice del picco da raffinare

        Returns:
            Posizione sub-pixel del picco nella stessa scala di peak_idx.
        """
        n = len(values)
        # Richiede almeno 5 elementi per la parabola
        if n < 5:
            return float(peak_idx)
        # Garantisce che ci siano almeno 2 campioni su entrambi i lati
        i = int(np.clip(peak_idx, 2, n - 3))
        y = values[i - 2:i + 3].astype(np.float64)
        # Sistema lineare 5×3 → coefficienti a, b, c (ax²+bx+c)
        x = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
        A = np.column_stack([x ** 2, x, np.ones(5)])
        try:
            coeffs, _, _, _ = np.linalg.lstsq(A, y, rcond=None)
            a, b = coeffs[0], coeffs[1]
            if abs(a) < 1e-12:
                return float(i)
            vertex = -b / (2.0 * a)
            return float(i) + vertex
        except np.linalg.LinAlgError:
            return float(i)

    def calibrate_from_usaf_click(
        self,
        frame: np.ndarray,
        click_x: int,
        click_y: int,
        known_gap_mm: float,
        half_x: int = USAF_PROFILE_HALF_X,
    ) -> dict:
        """
        Calibra il sistema usando un click su un gap del target USAF 1951.

        Estrae un profilo orizzontale centrato sul click, trova la coppia
        di edge (caduta→salita) più vicina al click e calcola mm/px.

        Args:
            frame:         Frame corrente (grayscale uint8 o BGR uint8)
            click_x:       Coordinata X del click (pixel sensore)
            click_y:       Coordinata Y del click (pixel sensore)
            known_gap_mm:  Larghezza del gap nota in mm (da usaf_line_width_mm)
            half_x:        Semi-larghezza del profilo da estrarre (px)

        Returns:
            Dict con chiavi:
                ok          (bool)   — True se calibrazione riuscita
                mm_per_px   (float)  — Fattore di scala calcolato
                gap_px      (float)  — Larghezza gap in pixel (sub-pixel)
                profile_y   (int)    — Riga del profilo (= click_y)
                edge1_x     (float)  — Posizione sub-pixel edge caduta
                edge2_x     (float)  — Posizione sub-pixel edge salita
                x_lo        (int)    — Inizio profilo (x sensore)
                x_hi        (int)    — Fine profilo (x sensore)
                click_x     (int)    — Click originale
                click_y     (int)    — Click originale
                error       (str)    — Messaggio errore (se ok=False)
        """
        base_result = {
            "ok": False,
            "mm_per_px": 0.0,
            "gap_px": 0.0,
            "profile_y": int(click_y),
            "edge1_x": float(click_x),
            "edge2_x": float(click_x),
            "x_lo": int(click_x),
            "x_hi": int(click_x),
            "click_x": int(click_x),
            "click_y": int(click_y),
            "error": "",
        }

        try:
            # ── 1. Converti in grigio se necessario ──────────────────────
            if frame is None or frame.size == 0:
                return {**base_result, "error": "Frame non disponibile"}

            if frame.ndim == 3 and frame.shape[2] == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            elif frame.ndim == 2:
                gray = frame
            else:
                return {**base_result, "error": "Formato frame non supportato"}

            h, w = gray.shape

            # ── 2. Estrai profilo orizzontale ─────────────────────────────
            y = int(np.clip(click_y, 0, h - 1))
            x_lo = int(max(0, click_x - half_x))
            x_hi = int(min(w, click_x + half_x))

            if x_hi - x_lo < 10:
                return {
                    **base_result,
                    "x_lo": x_lo, "x_hi": x_hi,
                    "error": "Profilo troppo corto (click fuori immagine?)",
                }

            profile = gray[y, x_lo:x_hi].astype(np.float64)

            # ── 3. Blur + gradiente ───────────────────────────────────────
            blurred = cv2.GaussianBlur(
                profile.reshape(1, -1),
                USAF_GAUSS_KERNEL,
                USAF_GAUSS_SIGMA,
            ).flatten()
            grad = np.diff(blurred)  # gradiente (len = len(profile)-1)

            # ── 4. Trova i picchi del gradiente ───────────────────────────
            abs_grad = np.abs(grad)
            g_max = abs_grad.max()
            if g_max < USAF_MIN_GRADIENT:
                return {
                    **base_result,
                    "x_lo": x_lo, "x_hi": x_hi,
                    "error": (
                        f"Gradiente troppo basso ({g_max:.2f} < "
                        f"{USAF_MIN_GRADIENT}). "
                        "Cliccare su un bordo del gap USAF."
                    ),
                }

            threshold = max(USAF_MIN_GRADIENT, g_max * USAF_GRADIENT_THRESHOLD_RATIO)

            # Edge caduta (bright→dark): gradiente negativo
            falling_mask = grad < -threshold
            # Edge salita (dark→bright): gradiente positivo
            rising_mask = grad > threshold

            falling_idxs = np.where(falling_mask)[0]
            rising_idxs = np.where(rising_mask)[0]

            if len(falling_idxs) == 0 or len(rising_idxs) == 0:
                return {
                    **base_result,
                    "x_lo": x_lo, "x_hi": x_hi,
                    "error": (
                        "Edge non trovati nel profilo. "
                        "Cliccare direttamente su un gap scuro."
                    ),
                }

            # ── 5. Trova la coppia (caduta, salita) più vicina al click ──
            # Il click deve essere nel gap (zona scura) tra i due edge
            click_local = click_x - x_lo  # coordinata locale nel profilo

            best_pair = None
            best_dist = float("inf")

            for fi in falling_idxs:
                # Usa searchsorted per trovare la prima salita dopo fi in O(log n)
                insert_pos = int(np.searchsorted(rising_idxs, fi + 1))
                if insert_pos >= len(rising_idxs):
                    continue
                ri = rising_idxs[insert_pos]
                gap_center = (fi + ri) / 2.0
                dist = abs(gap_center - click_local)
                if dist < best_dist:
                    best_dist = dist
                    best_pair = (fi, ri)

            if best_pair is None:
                return {
                    **base_result,
                    "x_lo": x_lo, "x_hi": x_hi,
                    "error": (
                        "Coppia di edge non trovata. "
                        "Cliccare sul centro del gap."
                    ),
                }

            fi_raw, ri_raw = best_pair

            # ── 6. Raffinamento sub-pixel ─────────────────────────────────
            # Usa il valore assoluto del gradiente per la parabola
            edge1_local = self._parabolic_refine(abs_grad, fi_raw)
            edge2_local = self._parabolic_refine(abs_grad, ri_raw)

            # Converti in coordinate sensore
            edge1_sensor = x_lo + edge1_local
            edge2_sensor = x_lo + edge2_local

            gap_px = edge2_local - edge1_local

            if gap_px < USAF_MIN_GAP_PX:
                return {
                    **base_result,
                    "x_lo": x_lo, "x_hi": x_hi,
                    "edge1_x": edge1_sensor,
                    "edge2_x": edge2_sensor,
                    "gap_px": gap_px,
                    "error": (
                        f"Gap troppo piccolo ({gap_px:.1f} px < "
                        f"{USAF_MIN_GAP_PX} px). "
                        "Selezionare un gruppo/elemento più grande."
                    ),
                }

            # ── 7. Calcola mm/px ──────────────────────────────────────────
            mm_per_px = known_gap_mm / gap_px

            # ── 8. Aggiorna stato calibrazione ───────────────────────────
            self._scale_factor = mm_per_px
            self._cx = float(click_x)
            self._cy = float(click_y)
            self._calibration_date = datetime.now()
            self._is_calibrated = True
            self._calibration_notes = (
                f"USAF click-to-calibrate: "
                f"gap={gap_px:.2f}px, "
                f"known={known_gap_mm:.4f}mm, "
                f"scale={mm_per_px:.6f}mm/px"
            )
            self._save()

            logger.info(
                f"Calibrazione USAF: {mm_per_px:.6f} mm/px "
                f"(gap={gap_px:.1f}px, known={known_gap_mm:.4f}mm)"
            )

            return {
                "ok": True,
                "mm_per_px": mm_per_px,
                "gap_px": gap_px,
                "profile_y": y,
                "edge1_x": edge1_sensor,
                "edge2_x": edge2_sensor,
                "x_lo": x_lo,
                "x_hi": x_hi,
                "click_x": int(click_x),
                "click_y": int(click_y),
                "error": "",
            }

        except Exception as exc:
            logger.error(f"Errore calibrazione USAF: {exc}", exc_info=True)
            return {**base_result, "error": str(exc)}