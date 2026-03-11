"""
usaf_target.py — USAF 1951 Resolution Target utilities.

Supporta il target Edmund Optics #43-05 (2×2" Negative USAF 1951):
- Gruppi da -2 a 7, Elementi da 1 a 6
- Formula: line_width_mm = 1.0 / (2^(group + (element-1)/6))

Funzionalità:
- Calcolo larghezza barra/gap per ogni gruppo/elemento
- Generazione target sintetico per la camera simulata
"""

import numpy as np

# ─── COSTANTI ──────────────────────────────────────────────────────────────

USAF_GROUPS = list(range(-2, 8))    # -2 to 7 (Edmund Optics #43-05)
USAF_ELEMENTS = list(range(1, 7))   # 1 to 6


# ─── CALCOLO LARGHEZZA ─────────────────────────────────────────────────────

def usaf_line_width_mm(group: int, element: int) -> float:
    """
    Calcola la larghezza barra/gap USAF 1951 in mm.

    Formula: width = 1.0 / (2^(group + (element-1)/6))
    Per Edmund Optics #43-05: gruppi -2 a 7, elementi 1 a 6.

    Args:
        group:   Numero di gruppo (-2 a 7)
        element: Numero di elemento (1 a 6)

    Returns:
        Larghezza della barra (= larghezza del gap) in mm.

    Raises:
        ValueError: Se group o element sono fuori range.
    """
    if group not in USAF_GROUPS:
        raise ValueError(
            f"Gruppo {group} non valido. Range: {USAF_GROUPS[0]}..{USAF_GROUPS[-1]}"
        )
    if element not in USAF_ELEMENTS:
        raise ValueError(
            f"Elemento {element} non valido. Range: {USAF_ELEMENTS[0]}..{USAF_ELEMENTS[-1]}"
        )
    lp_per_mm = 2.0 ** (group + (element - 1) / 6.0)
    return 1.0 / lp_per_mm


def usaf_label(group: int, element: int) -> str:
    """
    Etichetta leggibile per un gruppo/elemento USAF 1951.

    Returns:
        Stringa nel formato 'G-2 E1: 0.2500 mm'
    """
    w = usaf_line_width_mm(group, element)
    return f"G{group} E{element}: {w:.4f} mm"


# ─── GENERATORE TARGET SINTETICO ───────────────────────────────────────────

def generate_synthetic_usaf_target(
    width: int = 3840,
    height: int = 2748,
    scale_mm_per_px: float = 0.018,
) -> np.ndarray:
    """
    Genera un frame sintetico del target USAF 1951 (negativo — barre chiare
    su sfondo scuro) per la camera simulata.

    Il target renderizza i gruppi -2 e -1 (Elementi 1-3) che sono
    visivamente utilizzabili a ~0.018 mm/px (barre di ~14px e ~7px).

    Args:
        width:           Larghezza frame in pixel
        height:          Altezza frame in pixel
        scale_mm_per_px: Fattore di scala (mm/px) per dimensionare le barre

    Returns:
        Array numpy (height, width) uint8 con target sintetico.
        - Sfondo: ~18 DN (simulazione target negativo USAF)
        - Barre:  ~230 DN (chiare su sfondo scuro)
    """
    try:
        import cv2
        _have_cv2 = True
    except ImportError:
        _have_cv2 = False

    # Sfondo scuro (target negativo)
    frame = np.full((height, width), 18, dtype=np.uint8)

    # Gruppi e elementi da renderizzare
    render_items = [
        (-2, 1), (-2, 2), (-2, 3),
        (-1, 1), (-1, 2), (-1, 3),
        (0, 1),  (0, 2),
    ]

    BAR_ASPECT = 5.0   # altezza_barra = BAR_ASPECT * larghezza_barra
    N_BARS = 3          # 3 barre per elemento
    N_GAPS = 2          # 2 gap interni per elemento
    BAR_VALUE = 230     # DN barre
    GAP_BETWEEN_ELEMENTS = 10  # pixel di spazio tra elementi
    GAP_BETWEEN_GROUPS = 30    # pixel di spazio tra gruppi

    # Posizione di partenza (centrata verticalmente)
    # Calcolo altezza totale per centrare il layout
    total_height_needed = 0
    for g, e in render_items:
        w_mm = usaf_line_width_mm(g, e)
        bar_w_px = max(2.0, w_mm / scale_mm_per_px)
        bar_h_px = int(bar_w_px * BAR_ASPECT)
        total_height_needed += bar_h_px + GAP_BETWEEN_ELEMENTS
    total_height_needed += GAP_BETWEEN_GROUPS * 2  # margine

    start_y = max(40, (height - total_height_needed) // 2)
    start_x = max(80, width // 4)   # un quarto da sinistra

    label_margin = 60   # spazio a sinistra per etichette
    current_y = start_y
    last_group = None

    for group, element in render_items:
        # Spazio aggiuntivo tra gruppi
        if last_group is not None and group != last_group:
            current_y += GAP_BETWEEN_GROUPS
        last_group = group

        w_mm = usaf_line_width_mm(group, element)
        bar_w_px = max(2.0, w_mm / scale_mm_per_px)
        bar_h_px = max(4, int(bar_w_px * BAR_ASPECT))

        # Larghezza totale dell'elemento: 3 barre + 2 gap (ognuno = bar_w_px)
        elem_total_w = int((N_BARS + N_GAPS) * bar_w_px)

        x_start = start_x + label_margin
        y_start = current_y
        y_end = min(height - 1, y_start + bar_h_px)

        # Disegna 3 barre verticali
        for i in range(N_BARS):
            x_bar = int(x_start + i * (bar_w_px + bar_w_px))   # barra + gap
            x_bar_end = min(width - 1, int(x_bar + bar_w_px))
            if x_bar < width and y_start < height:
                frame[y_start:y_end, x_bar:x_bar_end] = BAR_VALUE

        # Etichetta a sinistra dell'elemento (usando numpy per compatibilità
        # senza cv2, oppure cv2.putText se disponibile)
        if _have_cv2 and bar_h_px >= 10:
            label_str = f"G{group}E{element}"
            font_scale = max(0.3, min(0.5, bar_h_px / 40.0))
            text_y = y_start + bar_h_px // 2 + 5
            cv2.putText(
                frame,
                label_str,
                (start_x, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                font_scale,
                200,   # colore grigio chiaro
                1,
                cv2.LINE_AA,
            )

        current_y += bar_h_px + GAP_BETWEEN_ELEMENTS

    # Applica leggera sfocatura Gaussiana (σ=0.7, kernel 3×3) per simulare PSF ottica
    if _have_cv2:
        frame = cv2.GaussianBlur(frame, (3, 3), 0.7)

    # Rumore sensore leggero (±3 DN)
    rng = np.random.default_rng(42)  # Seed fisso: target statico, no variazione
    noise = rng.integers(-3, 4, size=(height, width), dtype=np.int16)
    frame_i16 = frame.astype(np.int16)
    np.add(frame_i16, noise, out=frame_i16)
    np.clip(frame_i16, 0, 255, out=frame_i16)
    return frame_i16.astype(np.uint8)
