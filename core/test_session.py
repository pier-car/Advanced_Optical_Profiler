# Ideato e Realizzato da Pierpaolo Careddu

"""
TestSession — Modello dati per una sessione di prova completa.

Una sessione rappresenta un ciclo completo di misurazioni:
- Configurazione iniziale (operatore, tolleranze, nominale)
- Raccolta misure (automatiche e manuali)
- Statistiche finali
- Metadata per tracciabilità

Serializzazione JSON per persistenza su disco.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)


@dataclass
class SessionConfig:
    """Configurazione di una sessione di prova."""
    session_name: str = ""
    operator_id: str = ""
    nominal_mm: float = 0.0
    tolerance_upper_mm: float = float('inf')
    tolerance_lower_mm: float = float('-inf')
    calibration_scale_mm_per_px: float = 0.0
    notes: str = ""

    @property
    def is_tolerance_configured(self) -> bool:
        return (
            self.tolerance_upper_mm != float('inf')
            or self.tolerance_lower_mm != float('-inf')
        )

    @property
    def tolerance_range_mm(self) -> float:
        if not self.is_tolerance_configured:
            return 0.0
        upper = self.tolerance_upper_mm if self.tolerance_upper_mm != float('inf') else 0.0
        lower = self.tolerance_lower_mm if self.tolerance_lower_mm != float('-inf') else 0.0
        return upper - lower


@dataclass
class MeasureRecord:
    """Singolo record di misura nella sessione."""
    index: int = 0
    timestamp: str = ""
    width_mm: float = 0.0
    std_mm: float = 0.0
    angle_deg: float = 0.0
    n_scanlines: int = 0
    status: str = "OK"
    source: str = "auto"  # "auto", "manual", "single"
    is_valid: bool = True

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "width_mm": self.width_mm,
            "std_mm": self.std_mm,
            "angle_deg": self.angle_deg,
            "n_scanlines": self.n_scanlines,
            "status": self.status,
            "source": self.source,
            "is_valid": self.is_valid,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MeasureRecord":
        return cls(
            index=data.get("index", 0),
            timestamp=data.get("timestamp", ""),
            width_mm=data.get("width_mm", 0.0),
            std_mm=data.get("std_mm", 0.0),
            angle_deg=data.get("angle_deg", 0.0),
            n_scanlines=data.get("n_scanlines", 0),
            status=data.get("status", "OK"),
            source=data.get("source", "auto"),
            is_valid=data.get("is_valid", True),
        )


@dataclass
class SessionStatistics:
    """Statistiche aggregate calcolate a fine sessione."""
    count: int = 0
    count_valid: int = 0
    count_ok: int = 0
    count_nok: int = 0
    mean_mm: float = 0.0
    std_mm: float = 0.0
    min_mm: float = 0.0
    max_mm: float = 0.0
    range_mm: float = 0.0
    median_mm: float = 0.0
    cp: float = 0.0
    cpk: float = 0.0
    ok_percentage: float = 0.0


class TestSession:
    """
    Sessione di prova completa con ciclo di vita gestito.

    Ciclo di vita:
        1. create() → configura la sessione
        2. add_record() → aggiungi misure una alla volta
        3. finalize() → calcola statistiche finali
        4. save() → persisti su disco in JSON
        5. load() → ricarica da disco

    La sessione è immutabile dopo finalize().
    """

    def __init__(self):
        self._config = SessionConfig()
        self._records: list[MeasureRecord] = []
        self._statistics = SessionStatistics()
        self._started_at: Optional[datetime] = None
        self._ended_at: Optional[datetime] = None
        self._is_finalized: bool = False
        self._next_index: int = 1

    # ═══════════════════════════════════════════════════════════
    # CICLO DI VITA
    # ═══════════════════════════════════════════════════════════

    def create(self, config: SessionConfig):
        """Inizializza una nuova sessione con la configurazione data."""
        self._config = config
        self._records = []
        self._statistics = SessionStatistics()
        self._started_at = datetime.now()
        self._ended_at = None
        self._is_finalized = False
        self._next_index = 1
        logger.info(
            f"Sessione creata: '{config.session_name}' "
            f"operatore={config.operator_id} "
            f"nominale={config.nominal_mm:.3f}mm"
        )

    def add_record(self, record: MeasureRecord) -> int:
        """
        Aggiunge un record di misura alla sessione.

        Returns:
            L'indice assegnato al record.

        Raises:
            RuntimeError se la sessione è già finalizzata.
        """
        if self._is_finalized:
            raise RuntimeError("Sessione già finalizzata")

        record.index = self._next_index
        if not record.timestamp:
            record.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

        # Valuta OK/NOK se tolleranze configurate
        if self._config.is_tolerance_configured and record.is_valid:
            in_tol = True
            if self._config.tolerance_upper_mm != float('inf'):
                if record.width_mm > self._config.tolerance_upper_mm:
                    in_tol = False
            if self._config.tolerance_lower_mm != float('-inf'):
                if record.width_mm < self._config.tolerance_lower_mm:
                    in_tol = False
            record.status = "OK" if in_tol else "NOK"
        elif not record.is_valid:
            record.status = "ERROR"

        self._records.append(record)
        self._next_index += 1
        return record.index

    def remove_last_record(self) -> bool:
        """Rimuove l'ultimo record (undo)."""
        if self._is_finalized or not self._records:
            return False
        self._records.pop()
        self._next_index = max(1, self._next_index - 1)
        return True

    def finalize(self):
        """Finalizza la sessione e calcola le statistiche."""
        if self._is_finalized:
            return

        self._ended_at = datetime.now()
        self._is_finalized = True

        valid = [r for r in self._records if r.is_valid]
        ok = [r for r in valid if r.status == "OK"]
        nok = [r for r in valid if r.status == "NOK"]

        self._statistics.count = len(self._records)
        self._statistics.count_valid = len(valid)
        self._statistics.count_ok = len(ok)
        self._statistics.count_nok = len(nok)

        if valid:
            values = [r.width_mm for r in valid]
            n = len(values)
            self._statistics.mean_mm = sum(values) / n
            self._statistics.min_mm = min(values)
            self._statistics.max_mm = max(values)
            self._statistics.range_mm = self._statistics.max_mm - self._statistics.min_mm

            sorted_vals = sorted(values)
            mid = n // 2
            if n % 2 == 0:
                self._statistics.median_mm = (sorted_vals[mid - 1] + sorted_vals[mid]) / 2
            else:
                self._statistics.median_mm = sorted_vals[mid]

            if n >= 2:
                mean = self._statistics.mean_mm
                variance = sum((v - mean) ** 2 for v in values) / (n - 1)
                self._statistics.std_mm = variance ** 0.5
            else:
                self._statistics.std_mm = 0.0

            if self._statistics.count_valid > 0:
                self._statistics.ok_percentage = (
                    self._statistics.count_ok / self._statistics.count_valid * 100.0
                )

            # Cp/Cpk
            cfg = self._config
            if (cfg.is_tolerance_configured
                    and self._statistics.std_mm > 0
                    and cfg.tolerance_upper_mm != float('inf')
                    and cfg.tolerance_lower_mm != float('-inf')):
                tol_range = cfg.tolerance_upper_mm - cfg.tolerance_lower_mm
                sigma6 = 6 * self._statistics.std_mm
                self._statistics.cp = tol_range / sigma6 if sigma6 > 0 else 0.0
                cpu = (cfg.tolerance_upper_mm - self._statistics.mean_mm) / (3 * self._statistics.std_mm)
                cpl = (self._statistics.mean_mm - cfg.tolerance_lower_mm) / (3 * self._statistics.std_mm)
                self._statistics.cpk = min(cpu, cpl)

        logger.info(
            f"Sessione finalizzata: {self._statistics.count_valid} misure valide, "
            f"media={self._statistics.mean_mm:.3f}mm, "
            f"OK={self._statistics.ok_percentage:.1f}%"
        )

    # ═══════════════════════════════════════════════════════════
    # PERSISTENZA
    # ═══════════════════════════════════════════════════════════

    def save(self, filepath: Path) -> bool:
        """Salva la sessione su disco in formato JSON."""
        try:
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            def serialize_float(v):
                if v == float('inf'):
                    return "inf"
                if v == float('-inf'):
                    return "-inf"
                return v

            data = {
                "app_version": "1.0.0",
                "config": {
                    "session_name": self._config.session_name,
                    "operator_id": self._config.operator_id,
                    "nominal_mm": self._config.nominal_mm,
                    "tolerance_upper_mm": serialize_float(self._config.tolerance_upper_mm),
                    "tolerance_lower_mm": serialize_float(self._config.tolerance_lower_mm),
                    "calibration_scale_mm_per_px": self._config.calibration_scale_mm_per_px,
                    "notes": self._config.notes,
                },
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "ended_at": self._ended_at.isoformat() if self._ended_at else None,
                "is_finalized": self._is_finalized,
                "records": [r.to_dict() for r in self._records],
                "statistics": asdict(self._statistics),
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Sessione salvata: {filepath}")
            return True

        except Exception as e:
            logger.error(f"Errore salvataggio sessione: {e}")
            return False

    @classmethod
    def load(cls, filepath: Path) -> Optional["TestSession"]:
        """Carica una sessione da disco."""
        try:
            filepath = Path(filepath)
            if not filepath.exists():
                return None

            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)

            def deserialize_float(v):
                if v == "inf":
                    return float('inf')
                if v == "-inf":
                    return float('-inf')
                return float(v)

            session = cls()
            cfg_data = data.get("config", {})
            session._config = SessionConfig(
                session_name=cfg_data.get("session_name", ""),
                operator_id=cfg_data.get("operator_id", ""),
                nominal_mm=cfg_data.get("nominal_mm", 0.0),
                tolerance_upper_mm=deserialize_float(cfg_data.get("tolerance_upper_mm", "inf")),
                tolerance_lower_mm=deserialize_float(cfg_data.get("tolerance_lower_mm", "-inf")),
                calibration_scale_mm_per_px=cfg_data.get("calibration_scale_mm_per_px", 0.0),
                notes=cfg_data.get("notes", ""),
            )

            sa = data.get("started_at")
            session._started_at = datetime.fromisoformat(sa) if sa else None
            ea = data.get("ended_at")
            session._ended_at = datetime.fromisoformat(ea) if ea else None
            session._is_finalized = data.get("is_finalized", False)

            session._records = [
                MeasureRecord.from_dict(r) for r in data.get("records", [])
            ]
            session._next_index = len(session._records) + 1

            stats_data = data.get("statistics", {})
            session._statistics = SessionStatistics(**{
                k: stats_data.get(k, 0) for k in SessionStatistics.__dataclass_fields__
            })

            logger.info(f"Sessione caricata: {filepath}")
            return session

        except Exception as e:
            logger.error(f"Errore caricamento sessione: {e}")
            return None

    # ═══��═══════════════════════════════════════════════════════
    # PROPRIETÀ
    # ═══════════════════════════════════════════════════════════

    @property
    def config(self) -> SessionConfig:
        return self._config

    @property
    def records(self) -> list[MeasureRecord]:
        return list(self._records)

    @property
    def record_dicts(self) -> list[dict]:
        return [r.to_dict() for r in self._records]

    @property
    def statistics(self) -> SessionStatistics:
        return self._statistics

    @property
    def started_at(self) -> Optional[datetime]:
        return self._started_at

    @property
    def ended_at(self) -> Optional[datetime]:
        return self._ended_at

    @property
    def is_finalized(self) -> bool:
        return self._is_finalized

    @property
    def is_active(self) -> bool:
        return self._started_at is not None and not self._is_finalized

    @property
    def count(self) -> int:
        return len(self._records)

    @property
    def count_valid(self) -> int:
        return sum(1 for r in self._records if r.is_valid)

    @property
    def duration_seconds(self) -> float:
        if self._started_at is None:
            return 0.0
        end = self._ended_at or datetime.now()
        return (end - self._started_at).total_seconds()