# Ideato e Realizzato da Pierpaolo Careddu

"""
ImageProcessor — Pipeline di pre-processing immagini.

Operazioni disponibili (ciascuna opzionale e configurabile):
- Conversione a grayscale
- ROI cropping
- Equalizzazione istogramma (CLAHE)
- Filtro Gaussiano (denoising)
- Regolazione luminosità/contrasto
- Sharpening (Unsharp Mask)
- Filtro mediano (rimozione salt-and-pepper)

La pipeline è configurabile: l'operatore può abilitare/disabilitare
ciascuno step e regolarne i parametri. L'ordine di esecuzione è fisso
e ottimizzato per la profilometria ottica.

Thread Safety: Ogni istanza è indipendente. Nessuno stato condiviso.
"""

import logging
import numpy as np
from typing import Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False
    logger.warning("OpenCV non disponibile — ImageProcessor disabilitato")


@dataclass
class ProcessingConfig:
    """Configurazione della pipeline di pre-processing."""

    # ROI (None = tutto il frame)
    roi_enabled: bool = False
    roi_x: int = 0
    roi_y: int = 0
    roi_width: int = 0
    roi_height: int = 0

    # Grayscale
    convert_grayscale: bool = True

    # CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe_enabled: bool = False
    clahe_clip_limit: float = 2.0
    clahe_grid_size: int = 8

    # Gaussian blur (denoising)
    gaussian_enabled: bool = False
    gaussian_kernel_size: int = 3  # Deve essere dispari

    # Brightness / Contrast
    brightness_contrast_enabled: bool = False
    brightness: float = 0.0    # -100 a +100
    contrast: float = 1.0      # 0.5 a 2.0

    # Sharpening (Unsharp Mask)
    sharpen_enabled: bool = False
    sharpen_amount: float = 1.0  # 0.0 a 3.0
    sharpen_radius: int = 3      # Kernel size, dispari

    # Filtro mediano
    median_enabled: bool = False
    median_kernel_size: int = 3  # Deve essere dispari

    def validate(self):
        """Corregge parametri non validi."""
        if self.gaussian_kernel_size % 2 == 0:
            self.gaussian_kernel_size += 1
        if self.gaussian_kernel_size < 1:
            self.gaussian_kernel_size = 3

        if self.sharpen_radius % 2 == 0:
            self.sharpen_radius += 1
        if self.sharpen_radius < 1:
            self.sharpen_radius = 3

        if self.median_kernel_size % 2 == 0:
            self.median_kernel_size += 1
        if self.median_kernel_size < 1:
            self.median_kernel_size = 3

        self.clahe_clip_limit = max(0.5, min(10.0, self.clahe_clip_limit))
        self.clahe_grid_size = max(2, min(32, self.clahe_grid_size))
        self.brightness = max(-100.0, min(100.0, self.brightness))
        self.contrast = max(0.1, min(3.0, self.contrast))
        self.sharpen_amount = max(0.0, min(5.0, self.sharpen_amount))


class ImageProcessor:
    """
    Pipeline di pre-processing immagini configurabile.

    Ordine di esecuzione:
        1. ROI cropping
        2. Conversione grayscale
        3. CLAHE
        4. Gaussian blur
        5. Filtro mediano
        6. Brightness/Contrast
        7. Sharpening

    Uso:
        processor = ImageProcessor(ProcessingConfig(clahe_enabled=True))
        processed = processor.process(frame)
    """

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self._config = config or ProcessingConfig()
        self._config.validate()
        self._clahe = None
        self._build_clahe()

    @property
    def config(self) -> ProcessingConfig:
        return self._config

    def set_config(self, config: ProcessingConfig):
        """Aggiorna la configurazione."""
        config.validate()
        self._config = config
        self._build_clahe()

    def _build_clahe(self):
        """Crea l'oggetto CLAHE con i parametri correnti."""
        if not HAS_CV2:
            return
        cfg = self._config
        if cfg.clahe_enabled:
            self._clahe = cv2.createCLAHE(
                clipLimit=cfg.clahe_clip_limit,
                tileGridSize=(cfg.clahe_grid_size, cfg.clahe_grid_size)
            )
        else:
            self._clahe = None

    @property
    def is_identity(self) -> bool:
        """
        Restituisce True se la pipeline non applica alcuna trasformazione
        (nessuno step abilitato). Usato dal GrabWorker per ottimizzare
        il fast-path: se is_identity è True, process() viene saltato (P2).
        """
        cfg = self._config
        return not (
            cfg.roi_enabled
            or cfg.convert_grayscale
            or cfg.clahe_enabled
            or cfg.gaussian_enabled
            or cfg.median_enabled
            or cfg.brightness_contrast_enabled
            or cfg.sharpen_enabled
        )

    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        Esegue la pipeline di pre-processing.

        Ottimizzazione P2 (zero-copy fast path): il frame viene copiato
        solo prima della prima operazione distruttiva (in-place). Se
        nessuno step è abilitato, il frame originale viene restituito
        direttamente senza allocazioni.

        Args:
            frame: Frame originale (grayscale o colore)

        Returns:
            Frame processato (sempre numpy array)
        """
        if frame is None or frame.size == 0:
            return frame

        if not HAS_CV2:
            return frame

        cfg = self._config
        result = frame  # riferimento, nessuna copia ancora
        needs_copy = True  # True = prossima op deve copiare prima

        # 1. ROI — restituisce una view (slice), non una copia.
        # Conservativamente impostiamo needs_copy=True: la prossima
        # operazione distruttiva dovrà copiare il buffer prima di modificarlo.
        if cfg.roi_enabled:
            result = self._apply_roi(result)
            needs_copy = True

        # 2. Grayscale — crea un nuovo array: la copia è implicita
        if cfg.convert_grayscale and result.ndim == 3:
            result = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY)
            needs_copy = False

        # 3. CLAHE — opera su un nuovo array
        if cfg.clahe_enabled and self._clahe is not None:
            if needs_copy:
                result = result.copy()
                needs_copy = False
            result = self._apply_clahe(result)

        # 4. Gaussian blur — produce nuovo array
        if cfg.gaussian_enabled:
            ks = cfg.gaussian_kernel_size
            result = cv2.GaussianBlur(result, (ks, ks), 0)
            needs_copy = False

        # 5. Filtro mediano — produce nuovo array
        if cfg.median_enabled:
            result = cv2.medianBlur(result, cfg.median_kernel_size)
            needs_copy = False

        # 6. Brightness/Contrast — produce nuovo array via astype/clip
        if cfg.brightness_contrast_enabled:
            result = self._apply_brightness_contrast(result)
            needs_copy = False

        # 7. Sharpening — produce nuovo array
        if cfg.sharpen_enabled:
            result = self._apply_sharpen(result)
            needs_copy = False

        return result

    def _apply_roi(self, frame: np.ndarray) -> np.ndarray:
        """Applica il crop alla ROI."""
        cfg = self._config
        h, w = frame.shape[:2]
        x1 = max(0, cfg.roi_x)
        y1 = max(0, cfg.roi_y)
        x2 = min(w, cfg.roi_x + cfg.roi_width) if cfg.roi_width > 0 else w
        y2 = min(h, cfg.roi_y + cfg.roi_height) if cfg.roi_height > 0 else h

        if x2 <= x1 or y2 <= y1:
            return frame

        return frame[y1:y2, x1:x2]

    def _apply_clahe(self, frame: np.ndarray) -> np.ndarray:
        """Applica CLAHE (equalizzazione adattiva del contrasto)."""
        if self._clahe is None:
            return frame

        if frame.ndim == 2:
            return self._clahe.apply(frame)
        elif frame.ndim == 3:
            # Applica CLAHE al canale L in LAB
            lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
            lab[:, :, 0] = self._clahe.apply(lab[:, :, 0])
            return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
        return frame

    def _apply_brightness_contrast(self, frame: np.ndarray) -> np.ndarray:
        """Regola luminosità e contrasto."""
        cfg = self._config
        result = frame.astype(np.float32)
        result = result * cfg.contrast + cfg.brightness
        return np.clip(result, 0, 255).astype(np.uint8)

    def _apply_sharpen(self, frame: np.ndarray) -> np.ndarray:
        """Applica Unsharp Mask per sharpening."""
        cfg = self._config
        ks = cfg.sharpen_radius
        blurred = cv2.GaussianBlur(frame, (ks, ks), 0)

        if frame.dtype == np.uint8:
            sharpened = cv2.addWeighted(
                frame, 1.0 + cfg.sharpen_amount,
                blurred, -cfg.sharpen_amount,
                0
            )
        else:
            sharpened = frame + cfg.sharpen_amount * (
                frame.astype(np.float32) - blurred.astype(np.float32)
            )
            sharpened = np.clip(sharpened, 0, 255).astype(np.uint8)

        return sharpened

    def get_pipeline_description(self) -> str:
        """Restituisce una descrizione testuale della pipeline attiva."""
        cfg = self._config
        steps = []
        if cfg.roi_enabled:
            steps.append(f"ROI({cfg.roi_x},{cfg.roi_y},{cfg.roi_width}x{cfg.roi_height})")
        if cfg.convert_grayscale:
            steps.append("Grayscale")
        if cfg.clahe_enabled:
            steps.append(f"CLAHE(clip={cfg.clahe_clip_limit})")
        if cfg.gaussian_enabled:
            steps.append(f"Gaussian(k={cfg.gaussian_kernel_size})")
        if cfg.median_enabled:
            steps.append(f"Median(k={cfg.median_kernel_size})")
        if cfg.brightness_contrast_enabled:
            steps.append(f"B/C(b={cfg.brightness:.0f},c={cfg.contrast:.1f})")
        if cfg.sharpen_enabled:
            steps.append(f"Sharpen(a={cfg.sharpen_amount:.1f})")

        if not steps:
            return "Pipeline: nessuna elaborazione"
        return "Pipeline: " + " → ".join(steps)