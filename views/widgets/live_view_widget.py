# Ideato e Realizzato da Pierpaolo Careddu
# PARTE A — incollare PARTE A e PARTE B in un unico file live_view_widget.py

"""
LiveViewWidget v4 — Fix zoom + misura manuale.

Fix rispetto a v3:
- _image_to_widget_raw(): conversione SENZA zoom per uso dentro
  il contesto painter già zoomato (misure manuali, bordi, scanline)
- _widget_to_image(): conversione CON compensazione zoom/pan
  per i click del mouse
- mousePressEvent: usa _widget_to_image (con zoom) per i click
- paintEvent: il blocco painter zoomato usa _image_to_widget_raw
  per tutti gli overlay che sono disegnati nel contesto trasformato

Regola:
  - Dentro painter.save()/restore() con zoom → _image_to_widget_raw()
  - Fuori (overlay fissi come focus bar, istogramma) → coordinate widget
  - Per i click mouse → _widget_to_image() (inversa con zoom)
"""

import numpy as np
import math
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtWidgets import QWidget, QSizePolicy
from PySide6.QtCore import Qt, Signal, Slot, QPointF, QRectF, QTimer, QSize
from PySide6.QtGui import (
    QPainter, QImage, QPixmap, QPen, QColor, QFont, QBrush,
    QLinearGradient, QPainterPath, QMouseEvent, QWheelEvent,
    QResizeEvent, QPaintEvent, QConicalGradient, QRadialGradient
)


class Colors:
    OK_GREEN = QColor(46, 204, 113)
    ERROR_RED = QColor(231, 76, 60)
    WARNING_AMBER = QColor(243, 156, 18)
    EDGE_CYAN = QColor(0, 188, 212)
    MEASURE_WHITE = QColor(255, 255, 255)
    CROSSHAIR = QColor(255, 255, 255, 120)
    MANUAL_LINE = QColor(255, 215, 0)
    FLASH_WHITE = QColor(255, 255, 255, 100)
    STABILITY_BG = QColor(0, 0, 0, 140)
    STABILITY_TRACK = QColor(255, 255, 255, 40)
    STABILITY_PROGRESS = QColor(0, 188, 212)
    STABILITY_READY = QColor(46, 204, 113)
    OVERLAY_BG = QColor(20, 20, 30, 200)
    OVERLAY_BORDER = QColor(255, 255, 255, 60)
    HIST_BG = QColor(255, 255, 255, 210)
    HIST_BORDER = QColor(0, 102, 179, 120)
    HIST_TEXT = QColor(28, 28, 30)
    HIST_LABEL = QColor(100, 100, 110)


class OSDSeverity(Enum):
    INFO = auto()
    WARNING = auto()
    ERROR = auto()


@dataclass
class OSDMessage:
    text: str
    severity: OSDSeverity
    duration_ms: int = 3000


@dataclass
class EdgeOverlayData:
    top_edge_points: Optional[np.ndarray] = None
    bottom_edge_points: Optional[np.ndarray] = None
    top_line_params: Optional[tuple] = None
    bottom_line_params: Optional[tuple] = None
    scanline_tops: Optional[np.ndarray] = None
    scanline_bottoms: Optional[np.ndarray] = None
    is_valid: bool = False
    angle_deg: float = 0.0
    width_mm: float = 0.0
    width_mm_std: float = 0.0


@dataclass
class ManualMeasurePoint:
    x: float
    y: float


@dataclass
class ManualMeasureResult:
    point_a: ManualMeasurePoint
    point_b: ManualMeasurePoint
    distance_px: float
    distance_mm: float


class LiveViewWidget(QWidget):
    manual_measure_completed = Signal(float, float)
    frame_clicked = Signal(float, float)
    calibration_point_clicked = Signal(int, int)  # (sensor_x, sensor_y)

    FOCUS_BAR_LEFT_MARGIN = 50
    FOCUS_BAR_WIDTH = 22
    HISTOGRAM_WIDTH = 200
    HISTOGRAM_HEIGHT = 90
    HISTOGRAM_MARGIN = 14
    MEASUREMENT_BOX_WIDTH = 280
    MEASUREMENT_BOX_HEIGHT = 72
    STABILITY_CX = 110
    STABILITY_CY = 70
    STABILITY_RADIUS = 28

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_frame: Optional[np.ndarray] = None
        self._pixmap: Optional[QPixmap] = None
        self._image_rect: QRectF = QRectF()
        self._edge_data = EdgeOverlayData()
        self._show_edges: bool = True
        self._osd_messages: list[OSDMessage] = []
        self._persistent_osd: Optional[OSDMessage] = None
        self._sharpness_value: float = 0.0
        self._sharpness_max: float = 500.0
        self._sharpness_history: list[float] = []
        self._show_focus_bar: bool = True
        self._histogram: Optional[np.ndarray] = None
        self._show_histogram: bool = True
        self._manual_mode: bool = False
        self._manual_point_a: Optional[ManualMeasurePoint] = None
        self._manual_point_b: Optional[ManualMeasurePoint] = None
        self._manual_current_pos: Optional[QPointF] = None
        self._manual_results: list[ManualMeasureResult] = []
        self._calibration_scale: float = 0.0  # mm/px, 0 = non calibrato
        self._zoom_factor: float = 1.0
        self._pan_offset: QPointF = QPointF(0.0, 0.0)
        self._is_panning: bool = False
        self._pan_start: QPointF = QPointF()
        self._fps: float = 0.0
        self._stability_progress: float = 0.0
        self._flash_active: bool = False
        self._flash_opacity: float = 0.0
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(16)
        self._flash_timer.timeout.connect(self._animate_flash)
        # USAF Click-to-Calibrate
        self._usaf_calib_mode: bool = False
        self._usaf_calib_result: Optional[dict] = None
        self.setMinimumSize(640, 480)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setStyleSheet("background-color: #1E1E1E;")
        self._osd_timer = QTimer(self)
        self._osd_timer.setInterval(100)
        self._osd_timer.timeout.connect(self._cleanup_osd_messages)

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA
    # ═══════════════════════════════════════════════════════════

    @Slot(np.ndarray)
    def update_frame(self, frame: np.ndarray):
        if frame is None or frame.size == 0:
            return
        self._current_frame = frame
        h, w = frame.shape[:2]
        if frame.ndim == 2:
            q_image = QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            q_image = QImage(frame.data, w, h, w * 3, QImage.Format.Format_BGR888)
        self._pixmap = QPixmap.fromImage(q_image)
        self.update()

    @Slot(object)
    def update_edge_overlay(self, edge_data: EdgeOverlayData):
        self._edge_data = edge_data
        self.update()

    @Slot(float)
    def update_sharpness(self, value: float):
        self._sharpness_value = value
        self._sharpness_history.append(value)
        if len(self._sharpness_history) > 60:
            self._sharpness_history.pop(0)
        if value > self._sharpness_max * 0.8:
            self._sharpness_max = value * 1.3
        self.update()

    @Slot(np.ndarray)
    def update_histogram(self, histogram: np.ndarray):
        self._histogram = histogram
        self.update()

    @Slot(float)
    def update_fps(self, fps: float):
        self._fps = fps

    @Slot(float)
    def update_stability_progress(self, progress: float):
        self._stability_progress = max(0.0, min(1.0, progress))
        self.update()

    def trigger_capture_flash(self):
        self._flash_active = True
        self._flash_opacity = 0.7
        if not self._flash_timer.isActive():
            self._flash_timer.start()
        self.update()

    def set_flash_active(self, active: bool):
        if not active:
            self._flash_active = False
            self._flash_opacity = 0.0
            self._flash_timer.stop()
            self.update()

    def show_osd_message(self, text, severity, duration_ms=3000):
        msg = OSDMessage(text=text, severity=severity, duration_ms=duration_ms)
        self._osd_messages.append(msg)
        if not self._osd_timer.isActive():
            self._osd_timer.start()
        self.update()

    def set_persistent_osd(self, text, severity):
        self._persistent_osd = OSDMessage(text=text, severity=severity, duration_ms=0)
        self.update()

    def clear_persistent_osd(self):
        self._persistent_osd = None
        self.update()

    def set_manual_mode(self, enabled):
        self._manual_mode = enabled
        self._manual_point_a = None
        self._manual_point_b = None
        self._manual_current_pos = None
        self.setCursor(
            Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor
        )
        self.update()

    def clear_manual_measurements(self):
        self._manual_results.clear()
        self.update()

    def set_show_edges(self, show):
        self._show_edges = show
        self.update()

    def get_current_frame(self) -> Optional[np.ndarray]:
        """
        Restituisce una copia thread-safe del frame corrente.

        Usare al posto dell'accesso diretto a _current_frame.
        Garantisce un'istantanea isolata: il GrabWorker può sovrascrivere
        _current_frame senza invalidare il frame già estratto (R1).

        Returns:
            Copia del frame corrente, o None se nessun frame disponibile.
        """
        frame = self._current_frame
        if frame is not None:
            return frame.copy()
        return None

    def set_show_focus_bar(self, show):
        self._show_focus_bar = show
        self.update()

    def set_show_histogram(self, show):
        self._show_histogram = show
        self.update()
        
    def set_calibration_scale(self, scale_mm_per_px: float):
        """Imposta il fattore di scala per le misure manuali."""
        self._calibration_scale = scale_mm_per_px

    def set_usaf_calibration_mode(self, active: bool):
        """
        Attiva/disattiva la modalità Click-to-Calibrate USAF 1951.

        Quando attiva, il cursore diventa una croce e il prossimo click
        sinistro emette il segnale calibration_point_clicked.
        """
        self._usaf_calib_mode = active
        if active:
            self.setCursor(Qt.CursorShape.CrossCursor)
            self.set_persistent_osd(
                "📐 Modalità calibrazione USAF — Clicca su un gap del target",
                OSDSeverity.INFO,
            )
        else:
            # Ripristina cursore appropriato
            self.setCursor(
                Qt.CursorShape.CrossCursor if self._manual_mode
                else Qt.CursorShape.ArrowCursor
            )
            self.clear_persistent_osd()
        self.update()

    def set_usaf_calibration_result(self, result: Optional[dict]):
        """Memorizza il risultato della calibrazione USAF per l'overlay."""
        self._usaf_calib_result = result
        self.update()

    def reset_zoom(self):
        self._zoom_factor = 1.0
        self._pan_offset = QPointF(0.0, 0.0)
        self.update()

    def _animate_flash(self):
        self._flash_opacity -= 0.05
        if self._flash_opacity <= 0.0:
            self._flash_opacity = 0.0
            self._flash_active = False
            self._flash_timer.stop()
        self.update()

    # ═══════════════════════════════════════════════════════════
    # CONVERSIONE COORDINATE
    # ═══════════════════════════════════════════════════════════

    def _calculate_image_rect(self, widget_rect) -> QRectF:
        if self._pixmap is None:
            return QRectF()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = widget_rect.width(), widget_rect.height()
        scale = min(ww / pw, wh / ph)
        sw, sh = pw * scale, ph * scale
        return QRectF((ww - sw) / 2.0, (wh - sh) / 2.0, sw, sh)

    def _image_to_widget_raw(self, img_x: float, img_y: float) -> QPointF:
        """
        Converti coordinate immagine → coordinate image_rect (SENZA zoom).
        Usare DENTRO il contesto painter.save()/restore() dove lo zoom
        è già applicato dalla trasformazione del painter.
        """
        if self._pixmap is None or self._pixmap.width() == 0:
            return QPointF(img_x, img_y)
        sx = self._image_rect.width() / self._pixmap.width()
        sy = self._image_rect.height() / self._pixmap.height()
        return QPointF(
            self._image_rect.x() + img_x * sx,
            self._image_rect.y() + img_y * sy,
        )

    def _widget_to_image(self, widget_x: float, widget_y: float) -> QPointF:
        """
        Converti coordinate widget (click mouse) → coordinate immagine.
        Tiene conto di zoom e pan correnti.
        """
        if self._pixmap is None or self._pixmap.width() == 0:
            return QPointF(widget_x, widget_y)
        center = self._image_rect.center()
        # Inverti la trasformazione: translate(center+pan), scale(zoom), translate(-center)
        unzoomed_x = (
            (widget_x - center.x() - self._pan_offset.x())
            / self._zoom_factor + center.x()
        )
        unzoomed_y = (
            (widget_y - center.y() - self._pan_offset.y())
            / self._zoom_factor + center.y()
        )
        sx = self._pixmap.width() / self._image_rect.width()
        sy = self._pixmap.height() / self._image_rect.height()
        return QPointF(
            (unzoomed_x - self._image_rect.x()) * sx,
            (unzoomed_y - self._image_rect.y()) * sy,
        )

    # ═══════════════════════════════════════════════════════════
    # PAINT EVENT
    # ═══════════════════════════════════════════════════════════

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        widget_rect = self.rect()
        painter.fillRect(widget_rect, QColor(30, 30, 30))

        if self._pixmap is not None and not self._pixmap.isNull():
            self._image_rect = self._calculate_image_rect(widget_rect)

            # === BLOCCO ZOOMATO ===
            # Tutto dentro save/restore usa _image_to_widget_raw
            painter.save()
            center = self._image_rect.center()
            painter.translate(center + self._pan_offset)
            painter.scale(self._zoom_factor, self._zoom_factor)
            painter.translate(-center)

            painter.drawPixmap(self._image_rect.toRect(), self._pixmap)

            if self._show_edges:
                self._paint_edge_overlay(painter)

            self._paint_manual_measurements(painter)
            self._paint_usaf_calibration_overlay(painter)

            if self._manual_mode:
                self._paint_manual_in_progress(painter)

            painter.restore()
            # === FINE BLOCCO ZOOMATO ===

            # Overlay fissi (coordinate widget, NON zoomati)
            if self._show_focus_bar:
                self._paint_focus_bar(painter, widget_rect)
            if self._show_histogram and self._histogram is not None:
                self._paint_histogram(painter, widget_rect)
            self._paint_current_measurement(painter, widget_rect)
            self._paint_stability_indicator(painter, widget_rect)
            self._paint_osd_messages(painter, widget_rect)
            self._paint_info_bar(painter, widget_rect)
            if self._flash_active and self._flash_opacity > 0:
                self._paint_capture_flash(painter, widget_rect)
        else:
            self._paint_no_signal(painter, widget_rect)

        painter.end()

    # ═══════════════════════════════════════════════════════════
    # PAINT: OVERLAY BORDI (dentro contesto zoomato)
    # ═══════════════════════════════════════════════════════════

    def _paint_edge_overlay(self, painter):
        ed = self._edge_data
        if ed.top_edge_points is None or ed.bottom_edge_points is None:
            return
        edge_color = Colors.EDGE_CYAN if ed.is_valid else Colors.ERROR_RED
        line_width = 2.0 if ed.is_valid else 3.0
        pen = QPen(edge_color, line_width)
        pen.setCosmetic(True)
        painter.setPen(pen)

        if ed.top_line_params is not None and ed.bottom_line_params is not None:
            self._draw_fitted_line(painter, ed.top_line_params, edge_color, line_width)
            self._draw_fitted_line(painter, ed.bottom_line_params, edge_color, line_width)

        if ed.scanline_tops is not None and ed.scanline_bottoms is not None:
            marker_pen = QPen(Colors.MEASURE_WHITE, 1.0)
            marker_pen.setCosmetic(True)
            painter.setPen(marker_pen)
            painter.setBrush(QBrush(edge_color))
            for i in range(len(ed.scanline_tops)):
                pt_top = self._image_to_widget_raw(
                    ed.scanline_tops[i, 0], ed.scanline_tops[i, 1]
                )
                pt_bot = self._image_to_widget_raw(
                    ed.scanline_bottoms[i, 0], ed.scanline_bottoms[i, 1]
                )
                painter.drawEllipse(pt_top, 4, 4)
                painter.drawEllipse(pt_bot, 4, 4)
                sl_pen = QPen(Colors.MEASURE_WHITE, 1.0, Qt.PenStyle.DashLine)
                sl_pen.setCosmetic(True)
                painter.setPen(sl_pen)
                painter.drawLine(pt_top, pt_bot)
                painter.setPen(marker_pen)
                painter.setBrush(QBrush(edge_color))

    def _draw_fitted_line(self, painter, line_params, color, width):
        if self._pixmap is None:
            return
        m, q = line_params
        img_w = self._pixmap.width()
        p1 = self._image_to_widget_raw(0.0, q)
        p2 = self._image_to_widget_raw(float(img_w), m * img_w + q)
        pen = QPen(color, width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(p1, p2)

    # ═══════════════════════════════════════════════════════════
    # PAINT: MISURE MANUALI (dentro contesto zoomato)
    # ═══════════════════════════════════════════════════════════

    def _paint_manual_measurements(self, painter):
        """Disegna misure manuali completate — dentro contesto zoomato."""
        for result in self._manual_results:
            # Usa _image_to_widget_raw perché siamo nel painter zoomato
            p1 = self._image_to_widget_raw(result.point_a.x, result.point_a.y)
            p2 = self._image_to_widget_raw(result.point_b.x, result.point_b.y)

            pen = QPen(Colors.MANUAL_LINE, 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawLine(p1, p2)

            painter.setBrush(QBrush(Colors.MANUAL_LINE))
            painter.drawEllipse(p1, 5, 5)
            painter.drawEllipse(p2, 5, 5)

            mid = QPointF((p1.x() + p2.x()) / 2, (p1.y() + p2.y()) / 2)
            if result.distance_mm > 0:
                label_text = f"{result.distance_mm:.3f} mm"
            else:
                label_text = f"{result.distance_px:.1f} px"
            font = QFont("Consolas", 11, QFont.Weight.Bold)
            painter.setFont(font)
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(label_text)
            th = fm.height()
            lr = QRectF(mid.x() - tw / 2 - 6, mid.y() - th - 8, tw + 12, th + 6)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(Colors.OVERLAY_BG))
            painter.drawRoundedRect(lr, 3, 3)
            painter.setPen(QPen(Colors.MANUAL_LINE))
            painter.drawText(lr, Qt.AlignmentFlag.AlignCenter, label_text)

    def _paint_manual_in_progress(self, painter):
        """Linea tratteggiata dal punto A al mouse — dentro contesto zoomato."""
        if self._manual_point_a is None or self._manual_current_pos is None:
            return
        p1 = self._image_to_widget_raw(
            self._manual_point_a.x, self._manual_point_a.y
        )
        # Il mouse pos è in coordinate widget, dobbiamo convertirlo
        # alle coordinate del contesto zoomato del painter
        # Invertiamo la trasformazione del painter
        center = self._image_rect.center()
        mx = (
            (self._manual_current_pos.x() - center.x() - self._pan_offset.x())
            / self._zoom_factor + center.x()
        )
        my = (
            (self._manual_current_pos.y() - center.y() - self._pan_offset.y())
            / self._zoom_factor + center.y()
        )
        p2 = QPointF(mx, my)

        pen = QPen(Colors.MANUAL_LINE, 2, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLine(p1, p2)
        painter.setBrush(QBrush(Colors.MANUAL_LINE))
        painter.drawEllipse(p1, 5, 5)

    # ═══ FINE PARTE A — CONTINUA IN PARTE B ═══
    
    # ═══ INIZIO PARTE B — continuazione della classe LiveViewWidget ═══

    # ═══════════════════════════════════════════════════════════
    # PAINT: OVERLAY CALIBRAZIONE USAF (dentro contesto zoomato)
    # ═══════════════════════════════════════════════════════════

    def _paint_usaf_calibration_overlay(self, painter):
        """
        Disegna l'overlay del risultato della calibrazione USAF 1951.
        Deve essere chiamato dentro il blocco painter.save()/restore() zoomato.
        """
        result = self._usaf_calib_result
        if result is None:
            return

        click_pt = self._image_to_widget_raw(
            float(result.get("click_x", 0)),
            float(result.get("click_y", 0)),
        )

        if not result.get("ok", False):
            # Croce rossa sul click in caso di errore
            pen = QPen(QColor(231, 76, 60), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            r = 10
            painter.drawLine(
                QPointF(click_pt.x() - r, click_pt.y() - r),
                QPointF(click_pt.x() + r, click_pt.y() + r),
            )
            painter.drawLine(
                QPointF(click_pt.x() + r, click_pt.y() - r),
                QPointF(click_pt.x() - r, click_pt.y() + r),
            )
            return

        # ── Risultato OK ───────────────────────────────────────────────
        profile_y = float(result.get("profile_y", result.get("click_y", 0)))
        x_lo = float(result.get("x_lo", 0))
        x_hi = float(result.get("x_hi", 0))
        edge1_x = float(result.get("edge1_x", 0))
        edge2_x = float(result.get("edge2_x", 0))
        gap_px = float(result.get("gap_px", 0))
        mm_per_px = float(result.get("mm_per_px", 0))

        p_lo = self._image_to_widget_raw(x_lo, profile_y)
        p_hi = self._image_to_widget_raw(x_hi, profile_y)
        p_e1 = self._image_to_widget_raw(edge1_x, profile_y)
        p_e2 = self._image_to_widget_raw(edge2_x, profile_y)

        # Linea profilo orizzontale (rossa)
        red_pen = QPen(QColor(231, 76, 60), 1, Qt.PenStyle.DashLine)
        red_pen.setCosmetic(True)
        painter.setPen(red_pen)
        painter.drawLine(p_lo, p_hi)

        # Cerchi gialli sugli edge
        yellow_pen = QPen(QColor(255, 215, 0), 2)
        yellow_pen.setCosmetic(True)
        painter.setPen(yellow_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(p_e1, 8, 8)
        painter.drawEllipse(p_e2, 8, 8)

        # Tick verticali sugli edge
        tick_h = 12
        painter.drawLine(
            QPointF(p_e1.x(), p_e1.y() - tick_h),
            QPointF(p_e1.x(), p_e1.y() + tick_h),
        )
        painter.drawLine(
            QPointF(p_e2.x(), p_e2.y() - tick_h),
            QPointF(p_e2.x(), p_e2.y() + tick_h),
        )

        # Linea dimensione verde (con punte a freccia) 30px sotto il profilo
        green_pen = QPen(QColor(46, 204, 113), 2)
        green_pen.setCosmetic(True)
        painter.setPen(green_pen)
        arrow_y = p_e1.y() + 30
        painter.drawLine(QPointF(p_e1.x(), arrow_y), QPointF(p_e2.x(), arrow_y))
        # Punte a freccia
        arr = 6
        painter.drawLine(
            QPointF(p_e1.x(), arrow_y),
            QPointF(p_e1.x() + arr, arrow_y - arr),
        )
        painter.drawLine(
            QPointF(p_e1.x(), arrow_y),
            QPointF(p_e1.x() + arr, arrow_y + arr),
        )
        painter.drawLine(
            QPointF(p_e2.x(), arrow_y),
            QPointF(p_e2.x() - arr, arrow_y - arr),
        )
        painter.drawLine(
            QPointF(p_e2.x(), arrow_y),
            QPointF(p_e2.x() - arr, arrow_y + arr),
        )

        # Etichetta gap (verde)
        gap_label = f"distanza = {gap_px:.1f} px"
        mid_x = (p_e1.x() + p_e2.x()) / 2.0
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        fm = painter.fontMetrics()
        tw = fm.horizontalAdvance(gap_label)
        painter.setPen(QPen(QColor(46, 204, 113)))
        painter.drawText(QPointF(mid_x - tw / 2, arrow_y + 16), gap_label)

        # Etichetta scala (gialla)
        scale_label = f"1 px = {mm_per_px:.6f} mm"
        painter.setPen(QPen(QColor(255, 215, 0)))
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        fm2 = painter.fontMetrics()
        tw2 = fm2.horizontalAdvance(scale_label)
        painter.drawText(QPointF(mid_x - tw2 / 2, arrow_y + 30), scale_label)

        # Croce rossa sul click
        red_solid = QPen(QColor(231, 76, 60), 2)
        red_solid.setCosmetic(True)
        painter.setPen(red_solid)
        r2 = 8
        painter.drawLine(
            QPointF(click_pt.x() - r2, click_pt.y()),
            QPointF(click_pt.x() + r2, click_pt.y()),
        )
        painter.drawLine(
            QPointF(click_pt.x(), click_pt.y() - r2),
            QPointF(click_pt.x(), click_pt.y() + r2),
        )

    # ═══════════════════════════════════════════════════════════
    # PAINT: FOCUS BAR (overlay fisso, coordinate widget)
    # ═══════════════════════════════════════════════════════════

    def _paint_focus_bar(self, painter, widget_rect):
        bar_width = self.FOCUS_BAR_WIDTH
        bar_x = self.FOCUS_BAR_LEFT_MARGIN
        bar_top = 50
        bar_height = max(150, widget_rect.height() - 120)

        bg_rect = QRectF(bar_x - 6, bar_top - 6, bar_width + 12, bar_height + 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(Colors.OVERLAY_BG))
        painter.drawRoundedRect(bg_rect, 6, 6)

        bar_rect = QRectF(bar_x, bar_top, bar_width, bar_height)
        gradient = QLinearGradient(bar_x, bar_top + bar_height, bar_x, bar_top)
        gradient.setColorAt(0.0, QColor(231, 76, 60))
        gradient.setColorAt(0.5, QColor(243, 156, 18))
        gradient.setColorAt(1.0, QColor(46, 204, 113))
        painter.setBrush(QBrush(gradient))
        painter.setPen(QPen(Colors.OVERLAY_BORDER, 1))
        painter.drawRoundedRect(bar_rect, 3, 3)

        normalized = min(1.0, self._sharpness_value / max(self._sharpness_max, 1.0))
        indicator_y = bar_top + bar_height * (1.0 - normalized)

        triangle = QPainterPath()
        tri_x = bar_x + bar_width + 4
        triangle.moveTo(tri_x, indicator_y)
        triangle.lineTo(tri_x + 10, indicator_y - 6)
        triangle.lineTo(tri_x + 10, indicator_y + 6)
        triangle.closeSubpath()

        if normalized > 0.6:
            ic = Colors.OK_GREEN
        elif normalized > 0.3:
            ic = Colors.WARNING_AMBER
        else:
            ic = Colors.ERROR_RED

        painter.setBrush(QBrush(ic))
        painter.setPen(QPen(Colors.MEASURE_WHITE, 1))
        painter.drawPath(triangle)

        painter.setPen(QPen(Colors.MEASURE_WHITE, 2))
        painter.drawLine(QPointF(bar_x, indicator_y), QPointF(bar_x + bar_width, indicator_y))

        painter.setPen(QPen(Colors.MEASURE_WHITE))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.save()
        painter.translate(bar_x - 4, bar_top + bar_height / 2)
        painter.rotate(-90)
        painter.drawText(QRectF(-bar_height / 2, -15, bar_height, 15), Qt.AlignmentFlag.AlignCenter, "FUOCO")
        painter.restore()

        painter.setPen(QPen(ic))
        painter.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        painter.drawText(
            QRectF(bar_x - 8, bar_top + bar_height + 8, bar_width + 16, 18),
            Qt.AlignmentFlag.AlignCenter, f"{normalized * 100:.0f}%"
        )

    # ═══════════════════════════════════════════════════════════
    # PAINT: ISTOGRAMMA (overlay fisso)
    # ═══════════════════════════════════════════════════════════

    def _paint_histogram(self, painter, widget_rect):
        if self._histogram is None:
            return
        hw, hh = self.HISTOGRAM_WIDTH, self.HISTOGRAM_HEIGHT
        margin = self.HISTOGRAM_MARGIN
        hx = widget_rect.width() - hw - margin
        hy = widget_rect.height() - hh - margin - 25

        bg_rect = QRectF(hx - 8, hy - 20, hw + 16, hh + 36)
        painter.setPen(QPen(Colors.HIST_BORDER, 1.5))
        painter.setBrush(QBrush(Colors.HIST_BG))
        painter.drawRoundedRect(bg_rect, 6, 6)

        painter.setPen(QPen(Colors.HIST_TEXT))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(
            QRectF(hx - 4, hy - 16, hw + 8, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom, "ISTOGRAMMA"
        )

        hist = self._histogram
        max_val = hist.max() if hist.max() > 0 else 1.0
        n_bins = 80
        bin_size = max(1, len(hist) // n_bins)
        bar_wpx = hw / n_bins

        for i in range(n_bins):
            si = i * bin_size
            ei = min(si + bin_size, len(hist))
            if si >= len(hist):
                break
            bv = hist[si:ei].max()
            bh = (bv / max_val) * hh * 0.85
            bxp = hx + i * bar_wpx
            intensity = int(200 * i / n_bins)
            bc = QColor(intensity // 2, intensity // 2, intensity, 180)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(bc))
            painter.drawRect(QRectF(bxp, hy + hh - bh, max(1.0, bar_wpx - 0.5), bh))

        painter.setPen(QPen(Colors.HIST_LABEL))
        painter.setFont(QFont("Consolas", 7))
        ly = hy + hh + 2
        painter.drawText(QRectF(hx, ly, hw / 3, 12), Qt.AlignmentFlag.AlignLeft, "0")
        painter.drawText(QRectF(hx + hw * 2 / 3, ly, hw / 3, 12), Qt.AlignmentFlag.AlignRight, "255")

    # ═══════════════════════════════════════════════════════════
    # PAINT: MISURA CORRENTE (overlay fisso)
    # ═══════════════════════════════════════════════════════════

    def _paint_current_measurement(self, painter, widget_rect):
        ed = self._edge_data
        if not ed.is_valid or ed.width_mm <= 0:
            return
        bw, bh = self.MEASUREMENT_BOX_WIDTH, self.MEASUREMENT_BOX_HEIGHT
        margin = 15
        bx = widget_rect.width() - bw - margin
        by = margin
        border_color = Colors.OK_GREEN if ed.is_valid else Colors.ERROR_RED
        painter.setPen(QPen(border_color, 2))
        painter.setBrush(QBrush(Colors.OVERLAY_BG))
        painter.drawRoundedRect(QRectF(bx, by, bw, bh), 8, 8)

        painter.setPen(QPen(Colors.MEASURE_WHITE))
        painter.setFont(QFont("Consolas", 26, QFont.Weight.Bold))
        painter.drawText(
            QRectF(bx + 10, by + 5, bw - 20, 42),
            Qt.AlignmentFlag.AlignCenter, f"{ed.width_mm:.3f} mm"
        )
        painter.setPen(QPen(QColor(180, 180, 180)))
        painter.setFont(QFont("Segoe UI", 9))
        painter.drawText(
            QRectF(bx + 10, by + 47, bw - 20, 18),
            Qt.AlignmentFlag.AlignCenter,
            f"σ={ed.width_mm_std:.3f} mm  │  θ={ed.angle_deg:+.1f}°"
        )

    # ═══════════════════════════════════════════════════════════
    # PAINT: STABILITÀ (overlay fisso)
    # ═══════════════════════════════════════════════════════════

    def _paint_stability_indicator(self, painter, widget_rect):
        progress = self._stability_progress
        if progress <= 0.0 and not self._edge_data.is_valid:
            return
        cx, cy = float(self.STABILITY_CX), float(self.STABILITY_CY)
        r = float(self.STABILITY_RADIUS)
        tw = 5.0

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(Colors.STABILITY_BG))
        painter.drawEllipse(QPointF(cx, cy), r + 8, r + 8)

        tp = QPen(Colors.STABILITY_TRACK, tw)
        tp.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(tp)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r, r)

        if progress > 0.0:
            ac = Colors.STABILITY_READY if progress >= 1.0 else Colors.STABILITY_PROGRESS
            ap = QPen(ac, tw)
            ap.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(ap)
            ar = QRectF(cx - r, cy - r, r * 2, r * 2)
            painter.drawArc(ar, 90 * 16, int(-progress * 360 * 16))

        if progress >= 1.0:
            txt, tc, fs = "✓", Colors.STABILITY_READY, 16
        elif progress > 0.0:
            txt, tc, fs = f"{int(progress * 100)}", Colors.STABILITY_PROGRESS, 12
        else:
            txt, tc, fs = "—", QColor(100, 100, 100), 12

        painter.setPen(QPen(tc))
        painter.setFont(QFont("Segoe UI", fs, QFont.Weight.Bold))
        painter.drawText(QRectF(cx - r, cy - r, r * 2, r * 2), Qt.AlignmentFlag.AlignCenter, txt)

        painter.setPen(QPen(QColor(150, 150, 150)))
        painter.setFont(QFont("Segoe UI", 7))
        painter.drawText(QRectF(cx - 28, cy + r + 10, 56, 14), Qt.AlignmentFlag.AlignCenter, "STABILITÀ")

    # ═══════════════════════════════════════════════════════════
    # PAINT: FLASH, OSD, INFO BAR, NO SIGNAL
    # ═══════════════════════════════════════════════════════════

    def _paint_capture_flash(self, painter, widget_rect):
        if self._flash_opacity <= 0:
            return
        alpha = int(self._flash_opacity * 255)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(255, 255, 255, alpha)))
        painter.drawRect(widget_rect)
        if self._flash_opacity > 0.3:
            ba = int(min(1.0, self._flash_opacity * 1.5) * 255)
            painter.setPen(QPen(QColor(46, 204, 113, ba), 4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(widget_rect.adjusted(2, 2, -2, -2))

    def _paint_osd_messages(self, painter, widget_rect):
        if self._persistent_osd is not None:
            self._draw_osd_centered(painter, widget_rect, self._persistent_osd)
        y_off = widget_rect.height() - 55
        for msg in reversed(self._osd_messages[-5:]):
            self._draw_osd_bottom(painter, widget_rect, msg, y_off)
            y_off -= 35

    def _draw_osd_centered(self, painter, widget_rect, msg):
        tc = {OSDSeverity.ERROR: Colors.ERROR_RED, OSDSeverity.WARNING: Colors.WARNING_AMBER}.get(msg.severity, Colors.OK_GREEN)
        cx, cy = widget_rect.width() / 2, widget_rect.height() / 2
        bw = min(550, widget_rect.width() - 120)
        br = QRectF(cx - bw / 2, cy - 36, bw, 72)
        painter.setPen(QPen(tc, 3))
        painter.setBrush(QBrush(Colors.OVERLAY_BG))
        painter.drawRoundedRect(br, 10, 10)
        painter.setPen(QPen(tc))
        painter.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        painter.drawText(br, Qt.AlignmentFlag.AlignCenter, msg.text)

    def _draw_osd_bottom(self, painter, widget_rect, msg, yp):
        tc = {OSDSeverity.ERROR: Colors.ERROR_RED, OSDSeverity.WARNING: Colors.WARNING_AMBER}.get(msg.severity, Colors.OK_GREEN)
        margin = self.FOCUS_BAR_LEFT_MARGIN + self.FOCUS_BAR_WIDTH + 30
        br = QRectF(margin, yp, widget_rect.width() - margin - 220, 28)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(Colors.OVERLAY_BG))
        painter.drawRoundedRect(br, 4, 4)
        painter.setPen(QPen(tc))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(br.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, msg.text)

    def _paint_info_bar(self, painter, widget_rect):
        margin = self.FOCUS_BAR_LEFT_MARGIN + self.FOCUS_BAR_WIDTH + 30
        yp = widget_rect.height() - 22
        painter.setPen(QPen(QColor(150, 150, 150)))
        painter.setFont(QFont("Consolas", 8))
        parts = [f"FPS: {self._fps:.1f}"]
        if self._zoom_factor != 1.0:
            parts.append(f"Zoom: {self._zoom_factor:.1f}x")
        if self._current_frame is not None:
            h, w = self._current_frame.shape[:2]
            parts.append(f"{w}×{h}")
        painter.drawText(QPointF(margin, yp), "  │  ".join(parts))

    def _paint_no_signal(self, painter, widget_rect):
        painter.setPen(QPen(QColor(140, 140, 140)))
        painter.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        painter.drawText(widget_rect, Qt.AlignmentFlag.AlignCenter, "📷  NESSUN SEGNALE")
        painter.setPen(QPen(QColor(100, 100, 100)))
        painter.setFont(QFont("Segoe UI", 11))
        sr = QRectF(widget_rect)
        sr.moveTop(sr.top() + 40)
        painter.drawText(sr, Qt.AlignmentFlag.AlignCenter, "Collegare la telecamera e premere 'Connetti'")

    # ═══════════════════════════════════════════════════════════
    # EVENTI MOUSE
    # ═══════════════════════════════════════════════════════════

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            # USAF Click-to-Calibrate ha la precedenza sulla misura manuale
            if self._usaf_calib_mode:
                img_pos = self._widget_to_image(
                    event.position().x(), event.position().y()
                )
                self.calibration_point_clicked.emit(int(img_pos.x()), int(img_pos.y()))
                return
            if self._manual_mode:
                # Converti click widget → coordinate immagine (con zoom)
                img_pos = self._widget_to_image(
                    event.position().x(), event.position().y()
                )
                if self._manual_point_a is None:
                    self._manual_point_a = ManualMeasurePoint(
                        x=img_pos.x(), y=img_pos.y()
                    )
                    self._manual_current_pos = event.position()
                else:
                    self._manual_point_b = ManualMeasurePoint(
                        x=img_pos.x(), y=img_pos.y()
                    )
                    self._complete_manual_measurement()
            else:
                img_pos = self._widget_to_image(
                    event.position().x(), event.position().y()
                )
                self.frame_clicked.emit(img_pos.x(), img_pos.y())
        elif event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.RightButton:
            if self._manual_mode:
                self._manual_point_a = None
                self._manual_current_pos = None
                self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_panning:
            delta = event.position() - self._pan_start
            self._pan_offset += delta
            self._pan_start = event.position()
            self.update()
        elif self._manual_mode and self._manual_point_a is not None:
            self._manual_current_pos = event.position()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._is_panning = False
            self.setCursor(
                Qt.CursorShape.CrossCursor if self._manual_mode else Qt.CursorShape.ArrowCursor
            )

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        step = 1.15
        if delta > 0:
            self._zoom_factor *= step
        else:
            self._zoom_factor /= step
        self._zoom_factor = max(0.5, min(10.0, self._zoom_factor))
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and not self._manual_mode:
            self.reset_zoom()

    def _complete_manual_measurement(self):
        if self._manual_point_a is None or self._manual_point_b is None:
            return
        pa, pb = self._manual_point_a, self._manual_point_b
        dx, dy = pb.x - pa.x, pb.y - pa.y
        dist_px = (dx ** 2 + dy ** 2) ** 0.5

        # P1.1 — Conversione automatica in mm se calibrato
        if self._calibration_scale > 0:
            dist_mm = dist_px * self._calibration_scale
        else:
            dist_mm = 0.0

        result = ManualMeasureResult(
            point_a=pa, point_b=pb, distance_px=dist_px, distance_mm=dist_mm
        )
        self._manual_results.append(result)
        self.manual_measure_completed.emit(dist_px, dist_mm)
        self._manual_point_a = None
        self._manual_point_b = None
        self._manual_current_pos = None
        self.update()

    def update_last_manual_measurement_mm(self, distance_mm: float):
        if self._manual_results:
            self._manual_results[-1].distance_mm = distance_mm
            self.update()

    def _cleanup_osd_messages(self):
        to_remove = []
        for msg in self._osd_messages:
            msg.duration_ms -= 100
            if msg.duration_ms <= 0:
                to_remove.append(msg)
        for msg in to_remove:
            self._osd_messages.remove(msg)
        if not self._osd_messages:
            self._osd_timer.stop()
        self.update()

    def sizeHint(self):
        return QSize(960, 720)

    def minimumSizeHint(self):
        return QSize(640, 480)