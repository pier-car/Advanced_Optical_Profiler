# Ideato e Realizzato da Pierpaolo Careddu

"""
ReportGenerator — Generazione report PDF e CSV.

PDF: Report professionale con intestazione, tabella misure,
     statistiche riassuntive. Usa reportlab se disponibile.

CSV: Export tabellare con delimitatore configurabile,
     intestazioni, footer con statistiche.
"""

import csv
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from core.statistics_model import StatisticsSnapshot, ToleranceLimits

logger = logging.getLogger(__name__)

try:
    from reportlab.lib import colors as rl_colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm as rl_mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph,
        Spacer, HRFlowable
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    logger.warning(
        "reportlab non disponibile — export PDF disabilitato. "
        "Installare con: pip install reportlab"
    )


class ReportGenerator:
    """Genera report PDF e CSV dalle misure e statistiche."""

    def __init__(
        self,
        operator_id: str = "",
        session_start: Optional[datetime] = None,
        calibration_scale: float = 0.0,
    ):
        self._operator = operator_id
        self._session_start = session_start or datetime.now()
        self._cal_scale = calibration_scale

    @staticmethod
    def is_pdf_available() -> bool:
        return HAS_REPORTLAB

    # ═══════════════════════════════════════════════════════════
    # EXPORT CSV
    # ═══════════════════════════════════════════════════════════

    def export_csv(
        self,
        filepath: Path,
        records: list,
        snapshot: Optional[StatisticsSnapshot] = None,
        delimiter: str = ";",
        decimal: str = ",",
        encoding: str = "utf-8-sig",
    ) -> bool:
        try:
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            def fmt(value, decimals=3):
                if value is None:
                    return ""
                s = f"{value:.{decimals}f}"
                if decimal != ".":
                    s = s.replace(".", decimal)
                return s

            with open(filepath, "w", newline="", encoding=encoding) as f:
                w = csv.writer(f, delimiter=delimiter)

                w.writerow(["Advanced Optical Profiler — Report Misure"])
                w.writerow([
                    f"Operatore: {self._operator}",
                    f"Data: {self._session_start.strftime('%Y-%m-%d')}",
                    f"Ora inizio: {self._session_start.strftime('%H:%M:%S')}",
                    f"Ora export: {datetime.now().strftime('%H:%M:%S')}",
                ])
                if self._cal_scale > 0:
                    w.writerow([f"Calibrazione: {self._cal_scale:.6f} mm/px"])
                w.writerow([])

                w.writerow([
                    "#", "Timestamp", "Larghezza [mm]", "sigma [mm]",
                    "Angolo [deg]", "Stato", "N scanlines"
                ])

                for i, rec in enumerate(records, 1):
                    w.writerow([
                        i,
                        rec.get("timestamp", ""),
                        fmt(rec.get("width_mm", 0.0)),
                        fmt(rec.get("std_mm", 0.0), 4),
                        fmt(rec.get("angle_deg", 0.0), 1),
                        rec.get("status", ""),
                        rec.get("n_scanlines", ""),
                    ])

                if snapshot is not None and snapshot.count_valid > 0:
                    w.writerow([])
                    w.writerow(["STATISTICHE AGGREGATE"])
                    w.writerow(["N valide", fmt(snapshot.count_valid, 0)])
                    w.writerow(["Media [mm]", fmt(snapshot.mean_mm)])
                    w.writerow(["Dev.Std [mm]", fmt(snapshot.std_mm, 4)])
                    w.writerow(["Min [mm]", fmt(snapshot.min_mm)])
                    w.writerow(["Max [mm]", fmt(snapshot.max_mm)])
                    w.writerow(["Range [mm]", fmt(snapshot.range_mm)])
                    w.writerow(["Mediana [mm]", fmt(snapshot.median_mm)])
                    if snapshot.cp > 0:
                        w.writerow(["Cp", fmt(snapshot.cp, 2)])
                        w.writerow(["Cpk", fmt(snapshot.cpk, 2)])
                    w.writerow(["OK%", fmt(snapshot.ok_percentage, 1)])

            logger.info(f"CSV esportato: {filepath}")
            return True

        except Exception as e:
            logger.error(f"Errore export CSV: {e}")
            return False

    # ═══════════════════════════════════════════════════════════
    # EXPORT PDF
    # ═══════════════════════════════════════════════════════════

    def export_pdf(
        self,
        filepath: Path,
        records: list,
        snapshot: Optional[StatisticsSnapshot] = None,
        tolerance: Optional[ToleranceLimits] = None,
        title: str = "Report Metrologico",
    ) -> bool:
        if not HAS_REPORTLAB:
            logger.error("reportlab non disponibile per export PDF")
            return False

        try:
            filepath = Path(filepath)
            filepath.parent.mkdir(parents=True, exist_ok=True)

            doc = SimpleDocTemplate(
                str(filepath), pagesize=A4,
                rightMargin=15 * rl_mm, leftMargin=15 * rl_mm,
                topMargin=15 * rl_mm, bottomMargin=15 * rl_mm,
            )

            styles = getSampleStyleSheet()
            styles.add(ParagraphStyle(
                name='RTitle', parent=styles['Heading1'],
                fontSize=16, spaceAfter=6,
                textColor=rl_colors.HexColor("#0066B3"),
                alignment=TA_CENTER,
            ))
            styles.add(ParagraphStyle(
                name='RSub', parent=styles['Normal'],
                fontSize=9, textColor=rl_colors.HexColor("#6B7280"),
                alignment=TA_CENTER, spaceAfter=12,
            ))
            styles.add(ParagraphStyle(
                name='RSec', parent=styles['Heading2'],
                fontSize=12, spaceBefore=16, spaceAfter=6,
                textColor=rl_colors.HexColor("#1C1C1E"),
            ))

            elements = []

            # ── Titolo ──
            elements.append(Paragraph(title, styles['RTitle']))
            elements.append(Paragraph(
                f"Operatore: {self._operator} &nbsp;|&nbsp; "
                f"Data: {self._session_start.strftime('%Y-%m-%d %H:%M')} &nbsp;|&nbsp; "
                f"Calibrazione: {self._cal_scale:.6f} mm/px",
                styles['RSub']
            ))
            elements.append(HRFlowable(
                width="100%", thickness=1,
                color=rl_colors.HexColor("#E5E7EB")
            ))
            elements.append(Spacer(1, 8))

            # ── Statistiche aggregate ──
            if snapshot is not None and snapshot.count_valid > 0:
                elements.append(Paragraph("Statistiche Aggregate", styles['RSec']))

                stats_data = [
                    ["Parametro", "Valore"],
                    ["N misure valide", str(snapshot.count_valid)],
                    ["Media", f"{snapshot.mean_mm:.3f} mm"],
                    ["Deviazione Standard", f"{snapshot.std_mm:.4f} mm"],
                    ["Minimo", f"{snapshot.min_mm:.3f} mm"],
                    ["Massimo", f"{snapshot.max_mm:.3f} mm"],
                    ["Range", f"{snapshot.range_mm:.3f} mm"],
                    ["Mediana", f"{snapshot.median_mm:.3f} mm"],
                    ["OK%", f"{snapshot.ok_percentage:.1f}%"],
                ]
                if snapshot.cp > 0:
                    stats_data.append(["Cp", f"{snapshot.cp:.2f}"])
                    stats_data.append(["Cpk", f"{snapshot.cpk:.2f}"])

                if tolerance is not None and tolerance.is_configured:
                    stats_data.append([
                        "Tolleranze",
                        f"Nom={tolerance.nominal_mm:.3f}  "
                        f"LSL={tolerance.lower_limit_mm:.3f}  "
                        f"USL={tolerance.upper_limit_mm:.3f}"
                    ])

                stats_table = Table(stats_data, colWidths=[55 * rl_mm, 80 * rl_mm])
                stats_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor("#0066B3")),
                    ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.white),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 9),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('BACKGROUND', (0, 1), (-1, -1), rl_colors.HexColor("#F9FAFB")),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                     [rl_colors.HexColor("#FFFFFF"), rl_colors.HexColor("#F9FAFB")]),
                    ('GRID', (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
                    ('TOPPADDING', (0, 0), (-1, -1), 4),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ]))
                elements.append(stats_table)
                elements.append(Spacer(1, 12))

            # ── Tabella misure ──
            elements.append(Paragraph("Registro Misure", styles['RSec']))

            table_header = [
                "#", "Timestamp", "Larghezza [mm]",
                "σ [mm]", "Angolo [°]", "Stato"
            ]
            table_data = [table_header]

            for i, rec in enumerate(records, 1):
                status = rec.get("status", "")
                table_data.append([
                    str(i),
                    rec.get("timestamp", ""),
                    f"{rec.get('width_mm', 0.0):.3f}",
                    f"{rec.get('std_mm', 0.0):.4f}",
                    f"{rec.get('angle_deg', 0.0):.1f}",
                    status,
                ])

            col_widths = [
                10 * rl_mm, 35 * rl_mm, 30 * rl_mm,
                25 * rl_mm, 22 * rl_mm, 25 * rl_mm
            ]
            measures_table = Table(table_data, colWidths=col_widths, repeatRows=1)

            # Stile tabella con righe colorate per stato
            ts = [
                ('BACKGROUND', (0, 0), (-1, 0), rl_colors.HexColor("#0066B3")),
                ('TEXTCOLOR', (0, 0), (-1, 0), rl_colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('FONTNAME', (0, 1), (-1, -1), 'Courier'),
                ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                ('ALIGN', (2, 0), (-1, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, rl_colors.HexColor("#E5E7EB")),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                 [rl_colors.HexColor("#FFFFFF"), rl_colors.HexColor("#F9FAFB")]),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ]

            # Colora righe NOK in rosso chiaro
            for row_idx in range(1, len(table_data)):
                status = table_data[row_idx][5]
                if "NOK" in status.upper() or "ERROR" in status.upper():
                    ts.append((
                        'BACKGROUND', (0, row_idx), (-1, row_idx),
                        rl_colors.HexColor("#FEF2F2")
                    ))
                    ts.append((
                        'TEXTCOLOR', (5, row_idx), (5, row_idx),
                        rl_colors.HexColor("#DC2626")
                    ))

            measures_table.setStyle(TableStyle(ts))
            elements.append(measures_table)

            # ── Footer ──
            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(
                width="100%", thickness=0.5,
                color=rl_colors.HexColor("#E5E7EB")
            ))
            elements.append(Spacer(1, 4))
            footer_style = ParagraphStyle(
                name='Footer', parent=styles['Normal'],
                fontSize=7, textColor=rl_colors.HexColor("#9CA3AF"),
                alignment=TA_CENTER,
            )
            elements.append(Paragraph(
                f"Advanced Optical Profiler v1.0 — "
                f"Ideato e Realizzato da Pierpaolo Careddu — "
                f"Report generato il {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                footer_style
            ))

            doc.build(elements)
            logger.info(f"PDF esportato: {filepath}")
            return True

        except Exception as e:
            logger.error(f"Errore export PDF: {e}")
            return False