# Ideato e Realizzato da Pierpaolo Careddu

"""
Image Utilities — Funzioni helper per elaborazione immagini.

Fornisce:
- Conversione numpy → QImage / QPixmap
- Resize e crop ottimizzati
- Enhance contrasto/luminosità
- ROI extraction
- Calcolo sharpness (Laplacian, Tenengrad)
"""

import numpy as np
from typing import Optional, Tuple

from PySide6.QtGui import QImage, QPixmap


def numpy_to_qimage(frame: np.ndarray) -> Optional[QImage]:
    """
    Converte un frame numpy in QImage.

    Supporta:
    - Grayscale (H, W) → Format_Grayscale8
    - BGR (H, W, 3) → Format_BGR888
    - BGRA (H, W, 4) → Format_ARGB32

    Args:
        frame: Array numpy del frame

    Returns:
        QImage o None se il frame non è valido
    """
    if frame is None or frame.size == 0:
        return None

    frame = np.ascontiguousarray(frame)
    h, w = frame.shape[:2]

    if frame.ndim == 2:
        return QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8)
    elif frame.ndim == 3 and frame.shape[2] == 3:
        return QImage(frame.data, w, h, w * 3, QImage.Format.Format_BGR888)
    elif frame.ndim == 3 and frame.shape[2] == 4:
        return QImage(frame.data, w, h, w * 4, QImage.Format.Format_ARGB32)
    else:
        return None


def numpy_to_qpixmap(frame: np.ndarray) -> Optional[QPixmap]:
    """Converte un frame numpy in QPixmap."""
    qimage = numpy_to_qimage(frame)
    if qimage is None:
        return None
    return QPixmap.fromImage(qimage)


def extract_roi(
    frame: np.ndarray,
    x: int, y: int, width: int, height: int,
) -> Optional[np.ndarray]:
    """
    Estrae una regione di interesse (ROI) dal frame.

    Gestisce automaticamente i bordi: se la ROI eccede
    le dimensioni del frame, viene troncata.

    Args:
        frame: Frame sorgente
        x, y: Coordinate angolo superiore sinistro
        width, height: Dimensioni della ROI

    Returns:
        Array numpy della ROI o None se non valida
    """
    if frame is None or frame.size == 0:
        return None

    h, w = frame.shape[:2]
    x1 = max(0, x)
    y1 = max(0, y)
    x2 = min(w, x + width)
    y2 = min(h, y + height)

    if x2 <= x1 or y2 <= y1:
        return None

    return frame[y1:y2, x1:x2].copy()


def compute_sharpness_laplacian(frame: np.ndarray) -> float:
    """
    Calcola la nitidezza del frame usando la varianza del Laplaciano.

    Valori più alti indicano immagini più nitide.
    Metodo veloce, adatto per feedback in tempo reale.

    Args:
        frame: Frame (grayscale o colore)

    Returns:
        Valore di sharpness (varianza del Laplaciano)
    """
    try:
        import cv2
    except ImportError:
        return 0.0

    if frame is None or frame.size == 0:
        return 0.0

    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame

    laplacian = cv2.Laplacian(gray, cv2.CV_64F)
    return float(laplacian.var())


def compute_sharpness_tenengrad(frame: np.ndarray) -> float:
    """
    Calcola la nitidezza con il metodo Tenengrad (gradiente Sobel).

    Più robusto del Laplaciano per immagini con rumore.
    Leggermente più lento.

    Args:
        frame: Frame (grayscale o colore)

    Returns:
        Valore di sharpness (somma dei gradienti al quadrato)
    """
    try:
        import cv2
    except ImportError:
        return 0.0

    if frame is None or frame.size == 0:
        return 0.0

    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame

    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    return float(np.mean(gx ** 2 + gy ** 2))


def adjust_brightness_contrast(
    frame: np.ndarray,
    brightness: float = 0.0,
    contrast: float = 1.0,
) -> np.ndarray:
    """
    Regola luminosità e contrasto del frame.

    Args:
        frame: Frame sorgente
        brightness: Offset luminosità (-255 a +255)
        contrast: Fattore contrasto (0.0 a 3.0, 1.0 = nessun cambio)

    Returns:
        Frame con luminosità/contrasto regolati
    """
    if frame is None or frame.size == 0:
        return frame

    result = frame.astype(np.float32)
    result = result * contrast + brightness
    result = np.clip(result, 0, 255)
    return result.astype(np.uint8)


def compute_histogram(
    frame: np.ndarray,
    n_bins: int = 256,
) -> np.ndarray:
    """
    Calcola l'istogramma del frame.

    Args:
        frame: Frame (grayscale o colore, usa il primo canale)
        n_bins: Numero di bin

    Returns:
        Array numpy con i conteggi per ogni bin
    """
    if frame is None or frame.size == 0:
        return np.zeros(n_bins, dtype=np.float32)

    if frame.ndim == 3:
        gray = frame[:, :, 0]
    else:
        gray = frame

    counts, _ = np.histogram(gray.ravel(), bins=n_bins, range=(0, 256))
    return counts.astype(np.float32)


def resize_frame(
    frame: np.ndarray,
    max_width: int = 1920,
    max_height: int = 1080,
) -> np.ndarray:
    """
    Ridimensiona il frame mantenendo l'aspect ratio.

    Ridimensiona solo se il frame è più grande dei limiti.

    Args:
        frame: Frame sorgente
        max_width: Larghezza massima
        max_height: Altezza massima

    Returns:
        Frame ridimensionato (o originale se già entro i limiti)
    """
    try:
        import cv2
    except ImportError:
        return frame

    if frame is None or frame.size == 0:
        return frame

    h, w = frame.shape[:2]
    if w <= max_width and h <= max_height:
        return frame

    scale = min(max_width / w, max_height / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)


def frame_dimensions(frame: np.ndarray) -> Tuple[int, int]:
    """Restituisce (width, height) del frame."""
    if frame is None or frame.size == 0:
        return 0, 0
    h, w = frame.shape[:2]
    return w, h