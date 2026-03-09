# Ideato e Realizzato da Pierpaolo Careddu

"""
Math Utilities — Funzioni matematiche e statistiche helper.

Fornisce:
- Calcoli statistici (media, std, mediana) con gestione edge cases
- Cp/Cpk
- Conversioni angolari
- Interpolazione lineare
- Calcoli geometrici 2D (distanza, angolo tra punti)
"""

import math
from typing import Sequence, Optional, Tuple


def safe_mean(values: Sequence[float]) -> float:
    """Media aritmetica con gestione lista vuota."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def safe_std(values: Sequence[float], ddof: int = 1) -> float:
    """
    Deviazione standard con gestione edge cases.

    Args:
        values: Sequenza di valori
        ddof: Gradi di libertà (1 = campionaria, 0 = popolazione)

    Returns:
        Deviazione standard, 0.0 se meno di ddof+1 valori
    """
    n = len(values)
    if n <= ddof:
        return 0.0
    mean = sum(values) / n
    variance = sum((v - mean) ** 2 for v in values) / (n - ddof)
    return math.sqrt(variance)


def safe_median(values: Sequence[float]) -> float:
    """Mediana con gestione lista vuota."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 0:
        return (sorted_vals[mid - 1] + sorted_vals[mid]) / 2.0
    return sorted_vals[mid]


def compute_cp(usl: float, lsl: float, std: float) -> float:
    """
    Calcola l'indice di capacità di processo Cp.

    Cp = (USL - LSL) / (6 * sigma)

    Args:
        usl: Limite superiore di specifica
        lsl: Limite inferiore di specifica
        std: Deviazione standard del processo

    Returns:
        Cp, o 0.0 se non calcolabile
    """
    if std <= 0:
        return 0.0
    if math.isinf(usl) or math.isinf(lsl):
        return 0.0
    sigma6 = 6.0 * std
    if sigma6 <= 0:
        return 0.0
    return (usl - lsl) / sigma6


def compute_cpk(
    usl: float,
    lsl: float,
    mean: float,
    std: float,
) -> float:
    """
    Calcola l'indice di capacità di processo Cpk.

    Cpk = min(CPU, CPL)
    CPU = (USL - μ) / (3σ)
    CPL = (μ - LSL) / (3σ)

    Args:
        usl: Limite superiore di specifica
        lsl: Limite inferiore di specifica
        mean: Media del processo
        std: Deviazione standard del processo

    Returns:
        Cpk, o 0.0 se non calcolabile
    """
    if std <= 0:
        return 0.0
    sigma3 = 3.0 * std
    if sigma3 <= 0:
        return 0.0

    cpu = (usl - mean) / sigma3 if not math.isinf(usl) else float('inf')
    cpl = (mean - lsl) / sigma3 if not math.isinf(lsl) else float('inf')

    result = min(cpu, cpl)
    if math.isinf(result):
        return 0.0
    return result


def distance_2d(
    x1: float, y1: float,
    x2: float, y2: float,
) -> float:
    """Distanza euclidea tra due punti 2D."""
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx * dx + dy * dy)


def angle_between_points_deg(
    x1: float, y1: float,
    x2: float, y2: float,
) -> float:
    """
    Angolo in gradi della linea tra due punti rispetto all'asse X.

    Returns:
        Angolo in gradi [-180, +180]
    """
    dx = x2 - x1
    dy = y2 - y1
    return math.degrees(math.atan2(dy, dx))


def deg_to_rad(degrees: float) -> float:
    """Converte gradi in radianti."""
    return degrees * math.pi / 180.0


def rad_to_deg(radians: float) -> float:
    """Converte radianti in gradi."""
    return radians * 180.0 / math.pi


def lerp(a: float, b: float, t: float) -> float:
    """
    Interpolazione lineare tra a e b.

    Args:
        a: Valore iniziale
        b: Valore finale
        t: Parametro [0.0, 1.0]

    Returns:
        Valore interpolato
    """
    return a + (b - a) * max(0.0, min(1.0, t))


def clamp(value: float, min_val: float, max_val: float) -> float:
    """Limita un valore nell'intervallo [min_val, max_val]."""
    return max(min_val, min(max_val, value))


def map_range(
    value: float,
    in_min: float, in_max: float,
    out_min: float, out_max: float,
) -> float:
    """
    Mappa un valore da un range a un altro.

    Args:
        value: Valore da mappare
        in_min, in_max: Range di input
        out_min, out_max: Range di output

    Returns:
        Valore mappato (non clamped)
    """
    if abs(in_max - in_min) < 1e-12:
        return out_min
    return out_min + (value - in_min) / (in_max - in_min) * (out_max - out_min)


def running_average(
    current_avg: float,
    new_value: float,
    count: int,
) -> float:
    """
    Calcolo incrementale della media (Welford step 1).

    Args:
        current_avg: Media corrente
        new_value: Nuovo valore
        count: Conteggio DOPO l'aggiunta (1-based)

    Returns:
        Nuova media
    """
    if count <= 0:
        return new_value
    return current_avg + (new_value - current_avg) / count


def percentage(part: float, total: float) -> float:
    """Calcola la percentuale, gestendo divisione per zero."""
    if total <= 0:
        return 0.0
    return (part / total) * 100.0