"""
Generatore di immagini sintetiche per validazione metrologica.

Simula il setup fisico:
- Sfondo bianco (retroilluminazione EuroBrite ~240 DN)
- Bandina nera (gomma ~10 DN)
- Transizione bordo Gaussiana (simula PSF lente Edmund 16mm)
- Rumore shot noise del sensore Sony IMX546
- Rotazione arbitraria della bandina

Ogni immagine ha parametri noti → ground truth per test.
"""

import numpy as np
import cv2
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class SyntheticParams:
    """Parametri per la generazione di un'immagine sintetica."""
    # Dimensioni immagine (match sensore Basler a2A3840-45umBAS)
    image_width: int = 3840
    image_height: int = 2160  # Ridotto rispetto a 2748 per velocità test

    # Parametri bandina
    bandina_width_px: float = 800.0       # Larghezza in pixel
    bandina_center_y: float = 1080.0      # Centro verticale
    bandina_angle_deg: float = 0.0        # Angolo rotazione in gradi

    # Livelli di intensità (8-bit)
    background_intensity: int = 240       # Retroilluminazione
    bandina_intensity: int = 10           # Gomma nera

    # Simulazione ottica
    edge_blur_sigma: float = 2.5          # PSF lente → transizione bordo
                                          # 2.5 px = tipico per Edmund 16mm a f/4

    # Rumore sensore
    noise_stddev: float = 3.0             # Shot noise + read noise (~2.5 e⁻ IMX546)

    # Scala di calibrazione simulata
    scale_mm_per_px: float = 0.01823      # ~70mm FOV / 3840 px

    @property
    def bandina_width_mm(self) -> float:
        """Ground truth della larghezza in mm."""
        return self.bandina_width_px * self.scale_mm_per_px

    @property
    def bandina_angle_rad(self) -> float:
        return np.radians(self.bandina_angle_deg)


def generate_synthetic_image(params: SyntheticParams) -> np.ndarray:
    """
    Genera un'immagine sintetica di una bandina con parametri esatti.

    Algoritmo:
    1. Crea immagine float con sfondo uniforme
    2. Per ogni pixel, calcola la distanza dal centro della bandina
       lungo la direzione PERPENDICOLARE alla bandina (compensando θ)
    3. La transizione bordo è modellata come erf (error function),
       che è l'integrale della Gaussiana → simula perfettamente
       un bordo netto convoluto con PSF Gaussiana
    4. Aggiunge rumore Gaussiano
    """
    h, w = params.image_height, params.image_width
    bg = float(params.background_intensity)
    fg = float(params.bandina_intensity)

    # Griglia coordinate pixel
    y_coords, x_coords = np.mgrid[0:h, 0:w].astype(np.float64)

    # Centro immagine (punto di rotazione)
    cx = w / 2.0
    cy = params.bandina_center_y

    # Rotazione: calcoliamo la coordinata "v" perpendicolare alla bandina
    # La bandina è orientata lungo la direzione θ rispetto all'asse X.
    # La direzione perpendicolare è θ + 90°.
    # v = (y - cy)·cos(θ) - (x - cx)·sin(θ)
    # v rappresenta la distanza con segno dal centro della bandina.
    theta = params.bandina_angle_rad
    v = (y_coords - cy) * np.cos(theta) - (x_coords - cx) * np.sin(theta)

    # Transizione bordo con error function (erf)
    # erf(x / (σ√2)) va da -1 a +1, con transizione centrata su x=0
    # Bordo superiore a v = -width/2, bordo inferiore a v = +width/2
    from scipy.special import erf

    half_w = params.bandina_width_px / 2.0
    sigma = params.edge_blur_sigma
    sqrt2_sigma = sigma * np.sqrt(2.0)

    # Profilo di intensità:
    # Fuori dalla bandina → bg (bianco)
    # Dentro la bandina  → fg (nero)
    # Transizione → erf smoothing
    #
    # Formulazione: I(v) = bg - (bg - fg) * P(v)
    # dove P(v) = 0.5 * [erf((v + half_w) / sqrt2σ) - erf((v - half_w) / sqrt2σ)]
    # P(v) ≈ 1 dentro la bandina, ≈ 0 fuori

    profile = 0.5 * (erf((v + half_w) / sqrt2_sigma) - erf((v - half_w) / sqrt2_sigma))
    image_float = bg - (bg - fg) * profile

    # Aggiunta rumore Gaussiano (simula shot + read noise)
    if params.noise_stddev > 0:
        noise = np.random.normal(0, params.noise_stddev, (h, w))
        image_float += noise

    # Clip e conversione a 8-bit
    image_uint8 = np.clip(image_float, 0, 255).astype(np.uint8)

    return image_uint8


def generate_test_suite(output_dir: Path) -> list[dict]:
    """
    Genera una suite completa di immagini di test con parametri variabili.
    Restituisce la lista dei ground truth per la validazione.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    test_cases = []

    # ─── Caso 1: Bandina dritta (baseline) ───
    for width_px in [300.0, 500.0, 800.0, 1200.0, 2000.0, 3000.0]:
        params = SyntheticParams(
            bandina_width_px=width_px,
            bandina_angle_deg=0.0,
        )
        name = f"straight_w{int(width_px)}"
        img = generate_synthetic_image(params)
        cv2.imwrite(str(output_dir / f"{name}.png"), img)
        test_cases.append({
            'name': name,
            'width_px': width_px,
            'width_mm': params.bandina_width_mm,
            'angle_deg': 0.0,
            'params': params,
        })

    # ─── Caso 2: Bandina ruotata (il caso reale) ───
    for angle in [-5.0, -3.0, -1.5, -0.5, 0.5, 1.5, 3.0, 5.0, 10.0, 15.0]:
        params = SyntheticParams(
            bandina_width_px=800.0,
            bandina_angle_deg=angle,
        )
        name = f"rotated_a{angle:+.1f}"
        img = generate_synthetic_image(params)
        cv2.imwrite(str(output_dir / f"{name}.png"), img)
        test_cases.append({
            'name': name,
            'width_px': 800.0,
            'width_mm': params.bandina_width_mm,
            'angle_deg': angle,
            'params': params,
        })

    # ─── Caso 3: Variazione rumore ���──
    for noise in [0.0, 1.0, 3.0, 5.0, 10.0]:
        params = SyntheticParams(
            bandina_width_px=800.0,
            bandina_angle_deg=2.0,
            noise_stddev=noise,
        )
        name = f"noise_n{noise:.0f}"
        img = generate_synthetic_image(params)
        cv2.imwrite(str(output_dir / f"{name}.png"), img)
        test_cases.append({
            'name': name,
            'width_px': 800.0,
            'width_mm': params.bandina_width_mm,
            'angle_deg': 2.0,
            'noise': noise,
            'params': params,
        })

    # ─── Caso 4: Variazione blur (simulazione fuoco) ───
    for blur in [1.0, 2.0, 2.5, 4.0, 6.0]:
        params = SyntheticParams(
            bandina_width_px=800.0,
            bandina_angle_deg=2.0,
            edge_blur_sigma=blur,
        )
        name = f"blur_s{blur:.1f}"
        img = generate_synthetic_image(params)
        cv2.imwrite(str(output_dir / f"{name}.png"), img)
        test_cases.append({
            'name': name,
            'width_px': 800.0,
            'width_mm': params.bandina_width_mm,
            'angle_deg': 2.0,
            'blur_sigma': blur,
            'params': params,
        })

    # ─── Caso 5: Larghezze realistiche (5-60mm in pixel) ───
    scale = 0.01823  # mm/px
    for width_mm in [5.0, 10.0, 15.0, 25.0, 35.0, 45.0, 60.0]:
        width_px = width_mm / scale
        params = SyntheticParams(
            bandina_width_px=width_px,
            bandina_angle_deg=2.5,  # Angolo tipico reale
        )
        name = f"real_w{width_mm:.0f}mm"
        img = generate_synthetic_image(params)
        cv2.imwrite(str(output_dir / f"{name}.png"), img)
        test_cases.append({
            'name': name,
            'width_px': width_px,
            'width_mm': width_mm,
            'angle_deg': 2.5,
            'params': params,
        })

    print(f"✅ Generati {len(test_cases)} casi di test in {output_dir}")
    return test_cases


# ─── Entry point per generazione standalone ───
if __name__ == "__main__":
    cases = generate_test_suite(Path("tests/fixtures"))
    print("\nGround Truth generati:")
    print(f"{'Nome':<25} {'W [px]':>10} {'W [mm]':>10} {'θ [°]':>8}")
    print("─" * 55)
    for c in cases:
        print(f"{c['name']:<25} {c['width_px']:>10.1f} {c['width_mm']:>10.3f} {c['angle_deg']:>8.1f}")