"""
MetrologyEngine — Motore di misura dimensionale sub-pixel.

Pipeline completa:
    Frame RAW → Preprocessing → Segmentazione → Estrazione Bordi →
    Fitting RANSAC → Scanlines Perpendicolari → Edge Sub-Pixel →
    Larghezza Ortogonale [px] → Conversione [mm]

Precisione attesa: ±0.02 mm con setup Basler Ace2 + Edmund 16mm + EuroBrite.

Autore: R&D Metrologia
Versione: 1.1.0 — Fix compensazione rotazione e bandine larghe
"""

import numpy as np
import cv2
import threading
from scipy.ndimage import map_coordinates
from sklearn.linear_model import RANSACRegressor
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum, auto
import logging

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES — Strutture dati per risultati
# ═══════════════════════════════════════════════════════════════

class MeasurementStatus(Enum):
    """Stato di una misurazione."""
    OK = auto()
    WARNING_LOW_CONTRAST = auto()
    WARNING_HIGH_ANGLE = auto()
    ERROR_NO_EDGES = auto()
    ERROR_INVALID_GEOMETRY = auto()


@dataclass
class EdgeLine:
    """Retta fittata su un bordo della bandina."""
    slope: float
    intercept: float
    angle_rad: float
    angle_deg: float
    inlier_ratio: float
    points: np.ndarray
    inlier_mask: np.ndarray


@dataclass
class SubPixelEdge:
    """Risultato di una localizzazione bordo sub-pixel."""
    position: float
    absolute_xy: np.ndarray
    gradient_strength: float
    fit_quality: float


@dataclass
class ScanlineResult:
    """Risultato di una singola scanline perpendicolare."""
    x_position: float
    edge_top: SubPixelEdge
    edge_bottom: SubPixelEdge
    width_px: float
    width_mm: float


@dataclass
class MeasurementResult:
    """Risultato completo di una misurazione."""
    top_line: EdgeLine
    bottom_line: EdgeLine
    theta_avg_deg: float

    scanlines: list[ScanlineResult]

    width_px_mean: float
    width_px_std: float
    width_mm_mean: float
    width_mm_std: float

    status: MeasurementStatus
    contrast_ratio: float
    warnings: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# CONFIGURAZIONE PIPELINE
# ═══════════════════════════════════════════════════════════════

@dataclass
class PipelineConfig:
    """Parametri configurabili della pipeline metrologica."""
    # Preprocessing
    gaussian_sigma: float = 1.0
    gaussian_kernel_size: int = 5

    # Segmentazione
    morph_kernel_size: int = 5
    morph_close_iterations: int = 2
    morph_open_iterations: int = 1
    min_contour_area_ratio: float = 0.01

    # RANSAC
    ransac_residual_threshold: float = 3.0
    ransac_min_samples: float = 0.5
    ransac_max_trials: int = 1000

    # Scanline
    num_scanlines: int = 20
    scanline_margin_ratio: float = 0.1
    profile_half_length: int = 40
    interpolation_order: int = 3

    # Soglie qualità
    min_inlier_ratio: float = 0.7
    min_contrast_ratio: float = 3.0
    max_angle_deg: float = 30.0
    max_width_std_px: float = 5.0


# ═══════════════════════════════════════════════════════════════
# ECCEZIONE CUSTOM
# ═══════════════════════════════════════════════════════════════

class MeasurementError(Exception):
    """Eccezione specifica per errori di misurazione."""
    pass


# ═══════════════════════════════════════════════════════════════
# CLASSE PRINCIPALE — MetrologyEngine
# ═══════════════════════════════════════════════════════════════

class MetrologyEngine:
    """
    Motore metrologico per misurazione larghezza bandine.

    Utilizzo:
        engine = MetrologyEngine()
        engine.set_calibration(scale_mm_per_px=0.01823)
        result = engine.measure(frame)
        print(f"Larghezza: {result.width_mm_mean:.3f} ± {result.width_mm_std:.3f} mm")
    """

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self._scale_mm_per_px: float = 0.0
        self._k1_radial: float = 0.0
        self._optical_center: Optional[np.ndarray] = None
        self._is_calibrated: bool = False
        # P0.7 — Lock per accesso thread-safe ai parametri di calibrazione
        self._calibration_lock = threading.Lock()

    # ─── Calibrazione ─────────────────────────────────────────

    def set_calibration(
        self,
        scale_mm_per_px: float,
        k1_radial: float = 0.0,
        optical_center: Optional[np.ndarray] = None
    ):
        """Imposta i parametri di calibrazione (thread-safe)."""
        with self._calibration_lock:
            self._scale_mm_per_px = scale_mm_per_px
            self._k1_radial = k1_radial
            self._optical_center = optical_center
            self._is_calibrated = True
        logger.info(
            f"Calibrazione impostata: {scale_mm_per_px:.6f} mm/px, "
            f"k1={k1_radial:.2e}"
        )

    @property
    def is_calibrated(self) -> bool:
        return self._is_calibrated

    # ─── PIPELINE PRINCIPALE ──────────────────────────────────

    def measure(
        self,
        frame: np.ndarray,
        roi: Optional[tuple[int, int, int, int]] = None
    ) -> MeasurementResult:
        """
        Esegue la pipeline metrologica completa su un frame.

        Args:
            frame: Immagine greyscale 8-bit (numpy array H×W)
            roi:   Regione di interesse opzionale (x, y, w, h)

        Returns:
            MeasurementResult con tutti i dati della misurazione
        """
        if frame is None or frame.size == 0:
            raise ValueError("Frame vuoto o None")
        if frame.ndim != 2:
            raise ValueError(f"Frame deve essere greyscale 2D, ricevuto shape {frame.shape}")

        # Step 1: Preprocessing
        processed = self._preprocess(frame, roi)

        # Step 2: Segmentazione
        binary = self._segment(processed)

        # Step 3: Estrazione punti bordo
        top_points, bottom_points = self._extract_edge_points(binary)

        # Step 4: Fitting RANSAC
        top_line = self._fit_ransac(top_points)
        bottom_line = self._fit_ransac(bottom_points)

        # Angolo medio
        theta_avg = (top_line.angle_rad + bottom_line.angle_rad) / 2.0

        # Step 5 & 6 & 7: Scanline perpendicolari con edge sub-pixel
        scanlines = self._measure_scanlines(processed, top_line, bottom_line, theta_avg)

        # Step 8: Aggregazione risultati
        result = self._aggregate_results(
            top_line, bottom_line, theta_avg, scanlines, processed
        )

        return result

    # ─── STEP 1: PREPROCESSING ────────────────────────────────

    def _preprocess(
        self,
        frame: np.ndarray,
        roi: Optional[tuple[int, int, int, int]] = None
    ) -> np.ndarray:
        """Applica ROI e smoothing Gaussiano."""
        if roi is not None:
            x, y, w, h = roi
            frame = frame[y:y+h, x:x+w].copy()

        cfg = self.config
        blurred = cv2.GaussianBlur(
            frame,
            (cfg.gaussian_kernel_size, cfg.gaussian_kernel_size),
            sigmaX=cfg.gaussian_sigma
        )
        return blurred

    # ─── STEP 2: SEGMENTAZIONE ────────────────────────────────

    def _segment(self, image: np.ndarray) -> np.ndarray:
        """Binarizzazione Otsu + pulizia morfologica."""
        _, binary = cv2.threshold(
            image, 0, 255,
            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
        )

        cfg = self.config
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT,
            (cfg.morph_kernel_size, cfg.morph_kernel_size)
        )
        binary = cv2.morphologyEx(
            binary, cv2.MORPH_CLOSE, kernel,
            iterations=cfg.morph_close_iterations
        )
        binary = cv2.morphologyEx(
            binary, cv2.MORPH_OPEN, kernel,
            iterations=cfg.morph_open_iterations
        )

        return binary

    # ─── STEP 3: ESTRAZIONE PUNTI BORDO ───────────────────────

    def _extract_edge_points(
        self,
        binary: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Estrae i punti appartenenti al bordo superiore e inferiore
        della bandina dalla maschera binaria.

        LOGICA ADATTIVA: determina l'orientamento principale della bandina
        (orizzontale o verticale) e sceglie la strategia di separazione
        bordi appropriata.

        Per bandina prevalentemente orizzontale (|θ| < 45°):
            Per ogni colonna x → y_min = top, y_max = bottom
        Per bandina prevalentemente verticale (|θ| ≥ 45°):
            Per ogni riga y → x_min = left, x_max = right
        """
        contours, _ = cv2.findContours(
            binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
        )

        if not contours:
            raise MeasurementError("Nessun contorno trovato nella maschera binaria")

        min_area = binary.shape[0] * binary.shape[1] * self.config.min_contour_area_ratio
        valid_contours = [c for c in contours if cv2.contourArea(c) > min_area]

        if not valid_contours:
            raise MeasurementError(
                f"Nessun contorno con area sufficiente (min: {min_area:.0f} px²)"
            )

        main_contour = max(valid_contours, key=cv2.contourArea)
        points = main_contour.reshape(-1, 2)  # (N, 2) → [x, y]

        # Determina orientamento dal bounding box del contorno
        x_span = points[:, 0].max() - points[:, 0].min()
        y_span = points[:, 1].max() - points[:, 1].min()

        if x_span >= y_span:
            # Bandina prevalentemente orizzontale → separa per colonne x
            return self._separate_edges_horizontal(points)
        else:
            # Bandina prevalentemente verticale → separa per righe y
            return self._separate_edges_vertical(points)

    def _separate_edges_horizontal(
        self, points: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Separa bordi top/bottom raggruppando per colonna x."""
        unique_x = np.unique(points[:, 0])

        top_edge = np.empty((len(unique_x), 2), dtype=np.float64)
        bottom_edge = np.empty((len(unique_x), 2), dtype=np.float64)

        for i, x_val in enumerate(unique_x):
            mask = points[:, 0] == x_val
            y_values = points[mask, 1]
            top_edge[i] = [x_val, y_values.min()]
            bottom_edge[i] = [x_val, y_values.max()]

        return top_edge, bottom_edge

    def _separate_edges_vertical(
        self, points: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Separa bordi left/right raggruppando per riga y."""
        unique_y = np.unique(points[:, 1])

        left_edge = np.empty((len(unique_y), 2), dtype=np.float64)
        right_edge = np.empty((len(unique_y), 2), dtype=np.float64)

        for i, y_val in enumerate(unique_y):
            mask = points[:, 1] == y_val
            x_values = points[mask, 0]
            left_edge[i] = [x_values.min(), y_val]
            right_edge[i] = [x_values.max(), y_val]

        return left_edge, right_edge

    # ─── STEP 4: FITTING RANSAC ───────────────────────────────

    def _fit_ransac(self, edge_points: np.ndarray) -> EdgeLine:
        """
        Fitta una retta y = m·x + q sui punti del bordo con RANSAC.
        """
        cfg = self.config

        X = edge_points[:, 0].reshape(-1, 1)
        y = edge_points[:, 1]

        ransac = RANSACRegressor(
            residual_threshold=cfg.ransac_residual_threshold,
            min_samples=cfg.ransac_min_samples,
            max_trials=cfg.ransac_max_trials,
            random_state=42
        )
        ransac.fit(X, y)

        m = float(ransac.estimator_.coef_[0])
        q = float(ransac.estimator_.intercept_)
        theta = np.arctan(m)
        inlier_mask = ransac.inlier_mask_
        inlier_ratio = inlier_mask.sum() / len(inlier_mask)

        if inlier_ratio < cfg.min_inlier_ratio:
            logger.warning(
                f"RANSAC inlier ratio basso: {inlier_ratio:.2%} "
                f"(soglia: {cfg.min_inlier_ratio:.2%})"
            )

        return EdgeLine(
            slope=m,
            intercept=q,
            angle_rad=theta,
            angle_deg=np.degrees(theta),
            inlier_ratio=inlier_ratio,
            points=edge_points,
            inlier_mask=inlier_mask,
        )

    # ─── STEP 5: ESTRAZIONE PROFILO PERPENDICOLARE ────────────

    def _extract_perpendicular_profile(
        self,
        image: np.ndarray,
        point_on_edge: np.ndarray,
        theta: float,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Estrae il profilo di intensità lungo la NORMALE al bordo.

        La direzione normale alla bandina (angolo θ) è:
            n̂ = (sin θ, -cos θ)

        Campioniamo con interpolazione cubica per valori sub-pixel.
        """
        cfg = self.config
        half = cfg.profile_half_length

        nx = np.sin(theta)
        ny = -np.cos(theta)

        positions = np.arange(-half, half + 1, dtype=np.float64)
        sample_x = point_on_edge[0] + positions * nx
        sample_y = point_on_edge[1] + positions * ny

        h, w = image.shape
        valid = (
            (sample_x >= 0) & (sample_x < w - 1) &
            (sample_y >= 0) & (sample_y < h - 1)
        )

        if valid.sum() < 10:
            raise MeasurementError(
                f"Profilo perpendicolare fuori dall'immagine "
                f"al punto ({point_on_edge[0]:.0f}, {point_on_edge[1]:.0f})"
            )

        intensities = map_coordinates(
            image.astype(np.float64),
            [sample_y[valid], sample_x[valid]],
            order=cfg.interpolation_order,
            mode='reflect'
        )

        return positions[valid], intensities

    # ─── STEP 6: LOCALIZZAZIONE SUB-PIXEL ─────────────────────

    def _subpixel_edge_position(
        self,
        positions: np.ndarray,
        intensities: np.ndarray
    ) -> SubPixelEdge:
        """
        Localizza il bordo con precisione sub-pixel via fit parabolico
        del picco del |gradiente|.

        Il profilo di intensità di un bordo defocato ha forma erf.
        La sua derivata è una Gaussiana: g(x) = A·exp(-(x-μ)²/(2σ²))
        Il vertice della parabola fittata sui punti attorno al picco dà μ.
        """
        gradient = np.gradient(intensities, positions)
        gradient_abs = np.abs(gradient)

        peak_idx = int(np.argmax(gradient_abs))

        if peak_idx < 2 or peak_idx >= len(gradient_abs) - 2:
            return SubPixelEdge(
                position=positions[peak_idx],
                absolute_xy=np.array([0.0, 0.0]),
                gradient_strength=float(gradient_abs[peak_idx]),
                fit_quality=0.0,
            )

        # Fit parabolico su 5 punti attorno al picco
        fit_slice = slice(peak_idx - 2, peak_idx + 3)
        x_fit = positions[fit_slice]
        y_fit = gradient_abs[fit_slice]

        coeffs = np.polyfit(x_fit, y_fit, 2)
        a, b, c = coeffs

        if abs(a) < 1e-12:
            subpixel_pos = positions[peak_idx]
            fit_quality = 0.0
        else:
            subpixel_pos = -b / (2.0 * a)
            y_pred = np.polyval(coeffs, x_fit)
            ss_res = np.sum((y_fit - y_pred) ** 2)
            ss_tot = np.sum((y_fit - y_fit.mean()) ** 2)
            fit_quality = 1.0 - ss_res / (ss_tot + 1e-12)
            fit_quality = max(0.0, min(1.0, fit_quality))

        return SubPixelEdge(
            position=float(subpixel_pos),
            absolute_xy=np.array([0.0, 0.0]),
            gradient_strength=float(gradient_abs[peak_idx]),
            fit_quality=fit_quality,
        )

    # ─── STEP 7: SCANLINE E CALCOLO LARGHEZZA ─────────────────

    def _measure_scanlines(
        self,
        image: np.ndarray,
        top_line: EdgeLine,
        bottom_line: EdgeLine,
        theta_avg: float,
    ) -> list[ScanlineResult]:
        """
        Misura la larghezza in N punti distribuiti lungo la bandina.
        """
        cfg = self.config
        h, w = image.shape

        # Range X dalle intersezioni dei bordi con l'immagine
        all_x = np.concatenate([top_line.points[:, 0], bottom_line.points[:, 0]])
        x_min = all_x.min()
        x_max = all_x.max()

        margin = (x_max - x_min) * cfg.scanline_margin_ratio
        x_start = x_min + margin
        x_end = x_max - margin

        if x_start >= x_end:
            raise MeasurementError("Bandina troppo stretta per le scanline con il margine attuale")

        x_positions = np.linspace(x_start, x_end, cfg.num_scanlines)

        # Versore normale alla bandina
        nx = np.sin(theta_avg)
        ny = -np.cos(theta_avg)

        scanlines = []

        for x_pos in x_positions:
            try:
                result = self._measure_single_scanline(
                    image, x_pos, top_line, bottom_line, theta_avg, nx, ny
                )
                scanlines.append(result)
            except MeasurementError as e:
                logger.debug(f"Scanline a x={x_pos:.0f} fallita: {e}")
                continue

        if len(scanlines) < 3:
            raise MeasurementError(
                f"Solo {len(scanlines)} scanline valide su {cfg.num_scanlines} tentate. "
                f"Minimo richiesto: 3."
            )

        return scanlines

    def _measure_single_scanline(
        self,
        image: np.ndarray,
        x_pos: float,
        top_line: EdgeLine,
        bottom_line: EdgeLine,
        theta: float,
        nx: float,
        ny: float,
    ) -> ScanlineResult:
        """
        Misura la larghezza a una singola posizione x.

        FIX v1.1: La larghezza ortogonale è calcolata come PROIEZIONE
        della distanza tra i bordi sulla direzione NORMALE alla bandina,
        non come distanza euclidea grezza.

        Matematicamente:
            d_vec = edge_bottom_abs - edge_top_abs
            width_ortogonale = |d_vec · n̂|

        dove n̂ = (sin θ, -cos θ) è il versore normale.

        Questo è esatto per qualsiasi angolo θ: proietta automaticamente
        la distanza sulla direzione perpendicolare alla bandina.
        """
        # Punti approssimati sui bordi
        y_top = top_line.slope * x_pos + top_line.intercept
        y_bot = bottom_line.slope * x_pos + bottom_line.intercept

        point_top = np.array([x_pos, y_top])
        point_bot = np.array([x_pos, y_bot])

        # Estrazione profili perpendicolari
        pos_t, int_t = self._extract_perpendicular_profile(image, point_top, theta)
        pos_b, int_b = self._extract_perpendicular_profile(image, point_bot, theta)

        # Localizzazione sub-pixel
        edge_top = self._subpixel_edge_position(pos_t, int_t)
        edge_bot = self._subpixel_edge_position(pos_b, int_b)

        # Posizioni assolute
        n_vec = np.array([nx, ny])
        edge_top.absolute_xy = point_top + edge_top.position * n_vec
        edge_bot.absolute_xy = point_bot + edge_bot.position * n_vec

        # ═══ FIX v1.1: LARGHEZZA ORTOGONALE VIA PROIEZIONE ═══
        # La distanza euclidea tra i due punti include una componente
        # parallela alla bandina quando θ ≠ 0.
        # La larghezza reale è solo la componente NORMALE:
        #   width = |dot(d_vec, n_hat)|
        d_vec = edge_bot.absolute_xy - edge_top.absolute_xy
        width_px = float(abs(np.dot(d_vec, n_vec)))

        # Conversione in mm
        midpoint = (edge_top.absolute_xy + edge_bot.absolute_xy) / 2.0
        width_mm = self._px_to_mm(width_px, midpoint)

        return ScanlineResult(
            x_position=x_pos,
            edge_top=edge_top,
            edge_bottom=edge_bot,
            width_px=width_px,
            width_mm=width_mm,
        )

    # ─── STEP 8: CONVERSIONE PX → MM ──────────────────────────

    def _px_to_mm(
        self,
        distance_px: float,
        position_px: Optional[np.ndarray] = None
    ) -> float:
        """Converte distanza pixel → millimetri con correzione distorsione."""
        if not self._is_calibrated:
            return 0.0

        correction = 1.0

        if position_px is not None and self._k1_radial != 0.0 and self._optical_center is not None:
            dx = position_px[0] - self._optical_center[0]
            dy = position_px[1] - self._optical_center[1]
            r2 = dx**2 + dy**2
            correction = 1.0 + self._k1_radial * r2

        return distance_px * self._scale_mm_per_px * correction

    # ─── AGGREGAZIONE RISULTATI ────────────────────────────────

    def _aggregate_results(
        self,
        top_line: EdgeLine,
        bottom_line: EdgeLine,
        theta_avg: float,
        scanlines: list[ScanlineResult],
        image: np.ndarray,
    ) -> MeasurementResult:
        """Aggrega i risultati delle scanline e valuta la qualità."""
        cfg = self.config

        widths_px = np.array([s.width_px for s in scanlines])
        widths_mm = np.array([s.width_mm for s in scanlines])

        # Filtraggio outlier con MAD (Median Absolute Deviation)
        median_px = np.median(widths_px)
        mad = np.median(np.abs(widths_px - median_px))
        sigma_robust = 1.4826 * mad

        if sigma_robust > 0:
            inlier_mask = np.abs(widths_px - median_px) < 3.0 * sigma_robust
            widths_px_clean = widths_px[inlier_mask]
            widths_mm_clean = widths_mm[inlier_mask]

            n_removed = len(widths_px) - len(widths_px_clean)
            if n_removed > 0:
                logger.info(f"Rimosse {n_removed} scanline outlier (>3σ dalla mediana)")
        else:
            widths_px_clean = widths_px
            widths_mm_clean = widths_mm

        # Fallback se tutti rimossi
        if len(widths_px_clean) == 0:
            widths_px_clean = widths_px
            widths_mm_clean = widths_mm

        # Statistiche
        width_px_mean = float(np.mean(widths_px_clean))
        width_px_std = float(np.std(widths_px_clean, ddof=1)) if len(widths_px_clean) > 1 else 0.0
        width_mm_mean = float(np.mean(widths_mm_clean))
        width_mm_std = float(np.std(widths_mm_clean, ddof=1)) if len(widths_mm_clean) > 1 else 0.0

        # ═══ FIX v1.1: CONTRASTO CALCOLATO DALLA MASCHERA ═══
        # Invece di usare percentili globali (che falliscono quando la
        # bandina occupa >50% dell'immagine), usiamo la segmentazione
        # già calcolata per separare i pixel di sfondo e oggetto.
        binary = self._segment(image)
        fg_pixels = image[binary > 0]  # Pixel della bandina
        bg_pixels = image[binary == 0]  # Pixel dello sfondo

        if len(fg_pixels) > 0 and len(bg_pixels) > 0:
            bg_mean = float(np.mean(bg_pixels))
            fg_mean = float(np.mean(fg_pixels))
            contrast_ratio = bg_mean / max(fg_mean, 1.0)
        else:
            contrast_ratio = 1.0

        # Valutazione qualità
        warnings = []
        status = MeasurementStatus.OK

        if contrast_ratio < cfg.min_contrast_ratio:
            warnings.append(
                f"Contrasto basso: {contrast_ratio:.1f}x "
                f"(minimo: {cfg.min_contrast_ratio:.1f}x)"
            )
            status = MeasurementStatus.WARNING_LOW_CONTRAST

        theta_deg = np.degrees(theta_avg)
        if abs(theta_deg) > cfg.max_angle_deg:
            warnings.append(
                f"Angolo eccessivo: {theta_deg:.1f}° "
                f"(massimo: {cfg.max_angle_deg:.1f}°)"
            )
            status = MeasurementStatus.WARNING_HIGH_ANGLE

        if width_px_std > cfg.max_width_std_px:
            warnings.append(
                f"Larghezza non uniforme: σ = {width_px_std:.2f} px "
                f"(massimo: {cfg.max_width_std_px:.1f} px)"
            )

        for label, line in [("superiore", top_line), ("inferiore", bottom_line)]:
            if line.inlier_ratio < cfg.min_inlier_ratio:
                warnings.append(
                    f"Bordo {label}: inlier ratio {line.inlier_ratio:.1%} "
                    f"(minimo: {cfg.min_inlier_ratio:.1%})"
                )

        for w in warnings:
            logger.warning(w)

        return MeasurementResult(
            top_line=top_line,
            bottom_line=bottom_line,
            theta_avg_deg=float(theta_deg),
            scanlines=scanlines,
            width_px_mean=width_px_mean,
            width_px_std=width_px_std,
            width_mm_mean=width_mm_mean,
            width_mm_std=width_mm_std,
            status=status,
            contrast_ratio=float(contrast_ratio),
            warnings=warnings,
        )

    # ─── UTILITÀ PUBBLICHE ─────────────────────────────────────

    def measure_manual(
        self,
        point_a_px: np.ndarray,
        point_b_px: np.ndarray,
    ) -> tuple[float, float]:
        """Misura manuale: distanza tra due punti cliccati dall'operatore."""
        dist_px = float(np.linalg.norm(point_b_px - point_a_px))
        midpoint = (point_a_px + point_b_px) / 2.0
        dist_mm = self._px_to_mm(dist_px, midpoint)
        return dist_px, dist_mm

    def get_sharpness(self, frame: np.ndarray, roi: Optional[tuple] = None) -> float:
        """
        Indicatore di nitidezza (varianza del Laplaciano).

        FIX v1.1: Calcola solo nella regione dei bordi (ROI attorno ai
        bordi della bandina), non su tutta l'immagine. Se nessuna ROI
        è fornita, usa la fascia centrale del frame.
        """
        if roi is not None:
            x, y, w, h = roi
            region = frame[y:y+h, x:x+w]
        else:
            # Usa fascia centrale 60% dell'immagine (dove sono i bordi)
            h, w = frame.shape
            y_start = int(h * 0.2)
            y_end = int(h * 0.8)
            region = frame[y_start:y_end, :]

        laplacian = cv2.Laplacian(region, cv2.CV_64F)
        return float(laplacian.var())

    def get_histogram(self, frame: np.ndarray) -> np.ndarray:
        """Calcola istogramma 256-bin normalizzato."""
        hist = cv2.calcHist([frame], [0], None, [256], [0, 256])
        hist = hist.flatten() / hist.sum()
        return hist