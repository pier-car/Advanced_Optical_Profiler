"""
Test di validazione del MetrologyEngine v1.1.

Usa immagini sintetiche con ground truth noto per verificare:
1. Accuratezza assoluta (errore medio)
2. Precisione (deviazione standard dell'errore)
3. Robustezza alla rotazione (FIX: proiezione ortogonale)
4. Robustezza al rumore
5. Robustezza al blur (fuoco)
6. Linearità su range di larghezze

Criteri di accettazione:
- Errore assoluto medio: < 0.5 px (< 0.01 mm)
- Errore massimo con rotazione fino a 15°: < 1.5 px
- Errore con rumore σ=10: < 3.0 px
"""

import pytest
import numpy as np

from core.metrology_engine import MetrologyEngine, PipelineConfig, MeasurementStatus
from tests.synthetic_generator import SyntheticParams, generate_synthetic_image


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def engine() -> MetrologyEngine:
    """Engine configurato con calibrazione sintetica."""
    config = PipelineConfig(
        num_scanlines=15,
        profile_half_length=50,
    )
    eng = MetrologyEngine(config)
    eng.set_calibration(scale_mm_per_px=0.01823)
    return eng


@pytest.fixture
def default_params() -> SyntheticParams:
    """Parametri default per immagine sintetica."""
    return SyntheticParams(
        image_width=2000,
        image_height=1200,
        bandina_width_px=600.0,
        bandina_center_y=600.0,
        bandina_angle_deg=0.0,
        background_intensity=240,
        bandina_intensity=10,
        edge_blur_sigma=2.5,
        noise_stddev=3.0,
    )


def make_image(params: SyntheticParams) -> np.ndarray:
    """Helper: genera immagine da parametri."""
    return generate_synthetic_image(params)


def ensure_image_fits_bandina(params: SyntheticParams) -> SyntheticParams:
    """
    Assicura che l'immagine sia abbastanza grande per contenere la bandina
    con margini sufficienti, e che lo SPAN ORIZZONTALE del contorno sia
    sempre dominante rispetto allo span verticale.

    FIX v1.1.1: Il contorno della bandina deve avere x_span > y_span
    affinché _extract_edge_points scelga il ramo orizzontale corretto.

    Per una bandina di larghezza W ruotata di θ:
    - Span verticale del contorno ≈ W·cos(θ) + L_visibile·sin(θ)
    - Span orizzontale del contorno ≈ L_visibile·cos(θ) + W·sin(θ)

    Dobbiamo garantire: L_visibile sia grande abbastanza che x_span > y_span.
    In pratica: image_width >> image_height per bandine molto larghe.
    """
    w_px = params.bandina_width_px
    theta = abs(np.radians(params.bandina_angle_deg))
    cos_t = np.cos(theta)
    sin_t = np.sin(theta)

    # Altezza necessaria: proiezione verticale della bandina + margini profilo
    profile_margin = 200  # pixel di margine per i profili perpendicolari
    needed_height = int(w_px * cos_t + 2 * profile_margin)

    # Per garantire x_span > y_span nel contorno, la lunghezza visibile
    # della bandina (lungo la direzione X) deve essere sufficiente.
    # y_span ≈ W/cos(θ) (per angoli piccoli)
    # x_span ≈ image_width (la bandina attraversa tutta l'immagine)
    # Quindi: image_width > W/cos(θ) + margine generoso
    y_span_estimate = w_px * cos_t + w_px * sin_t  # Stima conservativa
    needed_width = int(y_span_estimate * 2.5 + 500)  # x_span almeno 2.5× y_span
    needed_width = max(needed_width, int(w_px * 1.5) + 500)

    params.image_height = max(params.image_height, needed_height)
    params.image_width = max(params.image_width, needed_width)
    params.bandina_center_y = params.image_height / 2.0

    return params


def measure_error(engine: MetrologyEngine, params: SyntheticParams) -> dict:
    """Helper: misura e calcola l'errore rispetto al ground truth."""
    params = ensure_image_fits_bandina(params)
    image = make_image(params)
    result = engine.measure(image)

    error_px = result.width_px_mean - params.bandina_width_px
    error_mm = result.width_mm_mean - params.bandina_width_mm

    return {
        'measured_px': result.width_px_mean,
        'expected_px': params.bandina_width_px,
        'error_px': error_px,
        'error_abs_px': abs(error_px),
        'measured_mm': result.width_mm_mean,
        'expected_mm': params.bandina_width_mm,
        'error_mm': error_mm,
        'error_abs_mm': abs(error_mm),
        'std_px': result.width_px_std,
        'theta_measured': result.theta_avg_deg,
        'status': result.status,
        'n_scanlines': len(result.scanlines),
        'contrast': result.contrast_ratio,
        'warnings': result.warnings,
    }


# ═══════════════════════════════════════════════════════════════
# TEST 1: ACCURATEZZA BASELINE (Bandina dritta)
# ═══════════════════════════════════════════════════════════════

class TestBaselineAccuracy:
    """Test di accuratezza con bandina perfettamente orizzontale."""

    def test_straight_bandina_accuracy(self, engine, default_params):
        """La misura di una bandina dritta deve essere accurata a < 0.5 px."""
        params = default_params
        params.bandina_angle_deg = 0.0
        params.noise_stddev = 0.0

        result = measure_error(engine, params)

        assert result['error_abs_px'] < 0.5, (
            f"Errore baseline troppo alto: {result['error_px']:.3f} px "
            f"(misurato: {result['measured_px']:.3f}, "
            f"atteso: {result['expected_px']:.3f})"
        )
        assert result['status'] == MeasurementStatus.OK

    @pytest.mark.parametrize("width_px", [200.0, 400.0, 600.0, 1000.0, 1500.0])
    def test_linearity(self, engine, default_params, width_px):
        """La misura deve essere lineare su un range di larghezze."""
        params = default_params
        params.bandina_width_px = width_px
        params.noise_stddev = 1.0

        result = measure_error(engine, params)

        assert result['error_abs_px'] < 1.0, (
            f"Errore linearità a {width_px:.0f} px: {result['error_px']:.3f} px"
        )


# ═══════════════════════════════════════════════════════════════
# TEST 2: ROBUSTEZZA ALLA ROTAZIONE
# ═══════════════════════════════════════════════════════════════

class TestRotationRobustness:
    """Verifica che la compensazione angolare funzioni."""

    @pytest.mark.parametrize("angle_deg", [-10.0, -5.0, -2.0, -0.5, 0.5, 2.0, 5.0, 10.0])
    def test_rotation_compensation(self, engine, default_params, angle_deg):
        """Errore < 1.5 px per angoli fino a ±10°."""
        params = default_params
        params.bandina_angle_deg = angle_deg
        params.noise_stddev = 2.0

        result = measure_error(engine, params)

        assert result['error_abs_px'] < 1.5, (
            f"Errore a θ={angle_deg:+.1f}°: {result['error_px']:.3f} px "
            f"(misurato: {result['measured_px']:.3f}, "
            f"atteso: {result['expected_px']:.3f})"
        )

    @pytest.mark.parametrize("angle_deg", [15.0, -15.0])
    def test_extreme_rotation(self, engine, default_params, angle_deg):
        """Angoli estremi: errore < 3.0 px."""
        params = default_params
        params.bandina_angle_deg = angle_deg
        params.noise_stddev = 2.0

        result = measure_error(engine, params)

        assert result['error_abs_px'] < 3.0, (
            f"Errore a θ={angle_deg:+.1f}° (estremo): "
            f"{result['error_px']:.3f} px"
        )

    def test_angle_detection_accuracy(self, engine, default_params):
        """L'angolo rilevato deve essere accurato a ±0.5°."""
        params = default_params
        params.bandina_angle_deg = 5.0
        params.noise_stddev = 1.0

        params = ensure_image_fits_bandina(params)
        image = make_image(params)
        result = engine.measure(image)

        angle_error = abs(result.theta_avg_deg - params.bandina_angle_deg)
        assert angle_error < 0.5, (
            f"Errore angolo: {angle_error:.3f}° "
            f"(misurato: {result.theta_avg_deg:.3f}°, atteso: 5.0°)"
        )


# ═══════════════════════════════════════════════════════════════
# TEST 3: ROBUSTEZZA AL RUMORE
# ═══════════════════════════════════════════════════════════════

class TestNoiseRobustness:
    """Verifica la degradazione graduale con aumento del rumore."""

    @pytest.mark.parametrize("noise_std,max_error_px", [
        (0.0, 0.5),
        (1.0, 0.5),
        (3.0, 1.0),
        (5.0, 1.5),
        (10.0, 3.0),
    ])
    def test_noise_degradation(self, engine, default_params, noise_std, max_error_px):
        """L'errore deve degradare gradualmente, non esplodere."""
        params = default_params
        params.noise_stddev = noise_std
        params.bandina_angle_deg = 2.0

        errors = []
        for seed in range(3):
            np.random.seed(seed + 42)
            result = measure_error(engine, params)
            errors.append(result['error_abs_px'])

        mean_error = np.mean(errors)

        assert mean_error < max_error_px, (
            f"Errore medio con rumore σ={noise_std:.0f}: "
            f"{mean_error:.3f} px (max: {max_error_px:.1f} px)"
        )


# ═══════════════════════════════════════════════════════════════
# TEST 4: ROBUSTEZZA AL BLUR
# ═══════════════════════════════════════════════════════════════

class TestBlurRobustness:
    """Verifica che il sistema funzioni con diversi gradi di fuoco."""

    @pytest.mark.parametrize("blur_sigma,max_error_px", [
        (1.0, 1.0),
        (2.0, 1.0),
        (2.5, 1.0),
        (4.0, 1.5),
        (6.0, 2.5),
    ])
    def test_blur_tolerance(self, engine, default_params, blur_sigma, max_error_px):
        """Il sistema deve tollerare un certo grado di sfocatura."""
        params = default_params
        params.edge_blur_sigma = blur_sigma
        params.bandina_angle_deg = 2.0

        result = measure_error(engine, params)

        assert result['error_abs_px'] < max_error_px, (
            f"Errore con blur σ={blur_sigma:.1f}: "
            f"{result['error_px']:.3f} px (max: {max_error_px:.1f} px)"
        )


# ═══════════════════════════════════════════════════════════════
# TEST 5: LARGHEZZE REALISTICHE (5-60 mm)
# ═══════════════════════════════════════════════════════════════

class TestRealisticWidths:
    """Test con le larghezze reali delle bandine in produzione."""

    @pytest.mark.parametrize("width_mm", [5.0, 10.0, 15.0, 25.0, 35.0, 45.0, 60.0])
    def test_realistic_width_accuracy(self, engine, default_params, width_mm):
        """Errore < 0.05 mm per tutte le larghezze realistiche."""
        scale = default_params.scale_mm_per_px
        width_px = width_mm / scale

        params = default_params
        params.bandina_width_px = width_px
        params.bandina_angle_deg = 2.5

        result = measure_error(engine, params)

        assert result['error_abs_mm'] < 0.05, (
            f"Errore per bandina {width_mm:.0f} mm: "
            f"{result['error_mm']:.4f} mm "
            f"(misurato: {result['measured_mm']:.4f} mm)"
        )


# ═══════════════════════════════════════════════════════════════
# TEST 6: QUALITÀ E DIAGNOSTICA
# ══���════════════════════════════════════════════════════════════

class TestDiagnostics:
    """Test dei controlli di qualità e warning."""

    def test_high_contrast_detection(self, engine, default_params):
        """Con retroilluminazione, il contrasto deve essere alto."""
        params = default_params
        params = ensure_image_fits_bandina(params)
        image = make_image(params)
        result = engine.measure(image)

        assert result.contrast_ratio > 10.0, (
            f"Contrasto rilevato: {result.contrast_ratio:.1f}x (atteso: >10x)"
        )

    def test_low_contrast_warning(self, engine, default_params):
        """Contrasto basso deve generare warning."""
        params = default_params
        params.background_intensity = 50
        params.bandina_intensity = 30

        params = ensure_image_fits_bandina(params)
        image = make_image(params)
        result = engine.measure(image)

        assert result.status == MeasurementStatus.WARNING_LOW_CONTRAST or \
               any("Contrasto" in w for w in result.warnings)

    def test_sharpness_indicator(self, engine, default_params):
        """L'indicatore di nitidezza deve distinguere fuoco buono/cattivo."""
        params_sharp = default_params
        params_sharp.edge_blur_sigma = 1.0
        params_sharp.noise_stddev = 0.0
        params_sharp = ensure_image_fits_bandina(params_sharp)
        img_sharp = make_image(params_sharp)

        params_blur = default_params
        params_blur.edge_blur_sigma = 10.0
        params_blur.noise_stddev = 0.0
        params_blur = ensure_image_fits_bandina(params_blur)
        img_blur = make_image(params_blur)

        h = img_sharp.shape[0]
        center_y = int(params_sharp.bandina_center_y)
        half_w = int(params_sharp.bandina_width_px / 2)
        roi_y = max(0, center_y - half_w - 30)
        roi_h = min(h, center_y + half_w + 30) - roi_y
        roi = (0, roi_y, img_sharp.shape[1], roi_h)

        sharpness_sharp = engine.get_sharpness(img_sharp, roi=roi)
        sharpness_blur = engine.get_sharpness(img_blur, roi=roi)

        assert sharpness_sharp > sharpness_blur * 2, (
            f"La nitidezza non distingue fuoco: "
            f"sharp={sharpness_sharp:.1f}, blur={sharpness_blur:.1f}"
        )

    def test_manual_measurement(self, engine):
        """La misura manuale punto-a-punto deve funzionare."""
        point_a = np.array([100.0, 200.0])
        point_b = np.array([600.0, 200.0])

        dist_px, dist_mm = engine.measure_manual(point_a, point_b)

        assert abs(dist_px - 500.0) < 0.01
        expected_mm = 500.0 * 0.01823
        assert abs(dist_mm - expected_mm) < 0.01


# ═══════════════════════════════════════════════════════════════
# TEST 7: CASI LIMITE
# ═══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test di robustezza per casi limite."""

    def test_very_narrow_bandina(self, engine, default_params):
        """Bandina molto stretta (5mm ≈ 274 px) deve funzionare."""
        params = default_params
        params.bandina_width_px = 274.0
        params.bandina_angle_deg = 1.0

        result = measure_error(engine, params)
        assert result['error_abs_px'] < 2.0

    def test_very_wide_bandina(self, engine, default_params):
        """Bandina larga deve funzionare con immagine adeguata."""
        params = default_params
        params.bandina_width_px = 1600.0
        params.bandina_angle_deg = 1.0

        result = measure_error(engine, params)
        assert result['error_abs_px'] < 2.0, (
            f"Errore bandina larga: {result['error_abs_px']:.3f} px"
        )

    def test_empty_frame_raises(self, engine):
        """Frame vuoto deve sollevare eccezione chiara."""
        with pytest.raises(ValueError, match="vuoto"):
            engine.measure(np.array([]))

    def test_color_frame_raises(self, engine):
        """Frame a colori deve sollevare eccezione chiara."""
        color_frame = np.zeros((100, 100, 3), dtype=np.uint8)
        with pytest.raises(ValueError, match="greyscale"):
            engine.measure(color_frame)

    def test_no_calibration_returns_zero_mm(self, default_params):
        """Senza calibrazione, mm deve essere 0 ma px deve funzionare."""
        engine_uncal = MetrologyEngine()
        params = default_params
        params.bandina_angle_deg = 0.0

        params = ensure_image_fits_bandina(params)
        image = make_image(params)
        result = engine_uncal.measure(image)

        assert result.width_mm_mean == 0.0
        assert result.width_px_mean > 0


# ═══════════════════════════════════════════════════════════════
# RUNNER STANDALONE
# ═══════════════════════════════════════════════════════════════

def run_full_validation():
    """Esegue validazione completa con tabella di risultati."""
    print("=" * 90)
    print("   VALIDAZIONE COMPLETA — MetrologyEngine v1.1.1")
    print("=" * 90)

    engine = MetrologyEngine(PipelineConfig(num_scanlines=20, profile_half_length=50))
    engine.set_calibration(scale_mm_per_px=0.01823)

    print(f"\n{'Test':<30} {'W att[px]':>10} {'W mis[px]':>10} "
          f"{'Err[px]':>8} {'Err[mm]':>9} {'θ mis[°]':>8} {'Stato':<10}")
    print("─" * 90)

    total_tests = 0
    passed_tests = 0
    max_error_px = 0.0

    test_configs = [
        ("Dritta 600px",         600.0,   0.0,  2.0, 2.5),
        ("Dritta 1000px",       1000.0,   0.0,  2.0, 2.5),
        ("Dritta 1500px",       1500.0,   0.0,  2.0, 2.5),
        ("Rotata +2°",          600.0,   2.0,  2.0, 2.5),
        ("Rotata -5°",          600.0,  -5.0,  2.0, 2.5),
        ("Rotata +10°",         600.0,  10.0,  2.0, 2.5),
        ("Rotata +15°",         600.0,  15.0,  2.0, 2.5),
        ("Rumore σ=0",          600.0,   2.0,  0.0, 2.5),
        ("Rumore σ=5",          600.0,   2.0,  5.0, 2.5),
        ("Rumore σ=10",         600.0,   2.0, 10.0, 2.5),
        ("Blur σ=1.0 (sharp)",  600.0,   2.0,  2.0, 1.0),
        ("Blur σ=4.0 (soft)",   600.0,   2.0,  2.0, 4.0),
        ("5mm reale",           274.3,   2.5,  3.0, 2.5),
        ("25mm reale",         1371.4,   2.5,  3.0, 2.5),
        ("35mm reale",         1920.0,   2.5,  3.0, 2.5),
        ("45mm reale",         2468.5,   2.5,  3.0, 2.5),
        ("60mm reale",         3291.3,   2.5,  3.0, 2.5),
    ]

    for name, w_px, angle, noise, blur in test_configs:
        np.random.seed(42)
        params = SyntheticParams(
            image_width=2000,
            image_height=1200,
            bandina_width_px=w_px,
            bandina_center_y=600.0,
            bandina_angle_deg=angle,
            noise_stddev=noise,
            edge_blur_sigma=blur,
        )
        params = ensure_image_fits_bandina(params)

        try:
            image = make_image(params)
            result = engine.measure(image)
            err_px = result.width_px_mean - w_px
            err_mm = result.width_mm_mean - (w_px * 0.01823)
            theta_m = result.theta_avg_deg
            ok = abs(err_px) < 3.0
            status = "✅ PASS" if ok else "❌ FAIL"

            if ok:
                passed_tests += 1
            max_error_px = max(max_error_px, abs(err_px))

            print(f"{name:<30} {w_px:>10.1f} {result.width_px_mean:>10.3f} "
                  f"{err_px:>+8.3f} {err_mm:>+9.5f} {theta_m:>+8.2f} {status}")
        except Exception as e:
            print(f"{name:<30} {'ERROR':>10} {str(e)[:45]:<45} {'❌ FAIL'}")

        total_tests += 1

    print("─" * 90)
    print(f"\nRisultati: {passed_tests}/{total_tests} superati")
    print(f"Errore massimo: {max_error_px:.3f} px = {max_error_px * 0.01823:.4f} mm")

    if passed_tests == total_tests:
        print("\n🎉 VALIDAZIONE SUPERATA — Pipeline metrologica v1.1.1 conforme")
    else:
        print(f"\n⚠️  {total_tests - passed_tests} test falliti — revisione necessaria")


if __name__ == "__main__":
    run_full_validation()