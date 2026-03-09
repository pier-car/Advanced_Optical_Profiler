# Ideato e Realizzato da Pierpaolo Careddu

"""
CalibrationWizard — Wizard guidato per la calibrazione.

Fix critico:
    La firma reale di CalibrationEngine.calibrate_from_known_distance è:
        (self, point_a_px: np.ndarray, point_b_px: np.ndarray,
         known_distance_mm: float, image_shape: tuple)

    Il wizard passa i due punti come np.array e la shape del frame.
"""

import logging
import numpy as np
from typing import Optional
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QFrame, QMessageBox, QSizePolicy, QWidget
)
from PySide6.QtCore import Qt, Signal, Slot, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QFont, QColor, QPainter, QPen, QBrush, QPixmap, QImage,
    QMouseEvent, QPaintEvent
)

from core.calibration_engine import CalibrationEngine

logger = logging.getLogger(__name__)


class CalibrationImageView(QWidget):
    """Widget immagine cliccabile per selezione punti di calibrazione."""

    points_selected = Signal(QPointF, QPointF)
    points_cleared = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap: Optional[QPixmap] = None
        self._image_rect: QRectF = QRectF()
        self._point_a: Optional[QPointF] = None
        self._point_b: Optional[QPointF] = None
        self._mouse_pos: Optional[QPointF] = None
        self.setMinimumSize(500, 380)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setStyleSheet("background-color: #1E1E1E; border-radius: 6px;")

    def set_frame(self, frame: np.ndarray):
        if frame is None or frame.size == 0:
            return
        h, w = frame.shape[:2]
        if frame.ndim == 2:
            q_image = QImage(frame.data, w, h, w, QImage.Format.Format_Grayscale8)
        else:
            q_image = QImage(frame.data, w, h, w * 3, QImage.Format.Format_BGR888)
        self._pixmap = QPixmap.fromImage(q_image)
        self.clear_points()
        self.update()

    def clear_points(self):
        self._point_a = None
        self._point_b = None
        self.points_cleared.emit()
        self.update()

    @property
    def point_a(self) -> Optional[QPointF]:
        return self._point_a

    @property
    def point_b(self) -> Optional[QPointF]:
        return self._point_b

    @property
    def distance_px(self) -> float:
        if self._point_a is None or self._point_b is None:
            return 0.0
        dx = self._point_b.x() - self._point_a.x()
        dy = self._point_b.y() - self._point_a.y()
        return (dx ** 2 + dy ** 2) ** 0.5

    def _calculate_image_rect(self) -> QRectF:
        if self._pixmap is None:
            return QRectF()
        pw, ph = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        scale = min(ww / pw, wh / ph)
        sw, sh = pw * scale, ph * scale
        return QRectF((ww - sw) / 2.0, (wh - sh) / 2.0, sw, sh)

    def _widget_to_image(self, wx: float, wy: float) -> QPointF:
        if self._pixmap is None or self._image_rect.width() == 0:
            return QPointF(wx, wy)
        sx = self._pixmap.width() / self._image_rect.width()
        sy = self._pixmap.height() / self._image_rect.height()
        return QPointF(
            (wx - self._image_rect.x()) * sx,
            (wy - self._image_rect.y()) * sy,
        )

    def _image_to_widget(self, ix: float, iy: float) -> QPointF:
        if self._pixmap is None or self._pixmap.width() == 0:
            return QPointF(ix, iy)
        sx = self._image_rect.width() / self._pixmap.width()
        sy = self._image_rect.height() / self._pixmap.height()
        return QPointF(
            self._image_rect.x() + ix * sx,
            self._image_rect.y() + iy * sy,
        )

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._pixmap is None:
            return
        img_pos = self._widget_to_image(
            event.position().x(), event.position().y()
        )
        if (img_pos.x() < 0 or img_pos.x() > self._pixmap.width()
                or img_pos.y() < 0 or img_pos.y() > self._pixmap.height()):
            return
        if self._point_a is None:
            self._point_a = img_pos
            self.update()
        elif self._point_b is None:
            self._point_b = img_pos
            self.points_selected.emit(self._point_a, self._point_b)
            self.update()
        else:
            self._point_a = img_pos
            self._point_b = None
            self.points_cleared.emit()
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        self._mouse_pos = event.position()
        if self._point_a is not None and self._point_b is None:
            self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), QColor(30, 30, 30))

        if self._pixmap is None or self._pixmap.isNull():
            painter.setPen(QPen(QColor(140, 140, 140)))
            painter.setFont(QFont("Segoe UI", 14))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter,
                "Cattura un frame per iniziare"
            )
            painter.end()
            return

        self._image_rect = self._calculate_image_rect()
        painter.drawPixmap(self._image_rect.toRect(), self._pixmap)

        if self._point_a is not None:
            pa_w = self._image_to_widget(self._point_a.x(), self._point_a.y())
            self._draw_point(painter, pa_w, "A", QColor(0, 188, 212))
            if self._point_b is None and self._mouse_pos is not None:
                pen = QPen(QColor(0, 188, 212, 150), 2, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(pa_w, self._mouse_pos)

        if self._point_a is not None and self._point_b is not None:
            pa_w = self._image_to_widget(self._point_a.x(), self._point_a.y())
            pb_w = self._image_to_widget(self._point_b.x(), self._point_b.y())
            self._draw_point(painter, pb_w, "B", QColor(46, 204, 113))
            pen = QPen(QColor(255, 215, 0), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawLine(pa_w, pb_w)
            mid = QPointF((pa_w.x() + pb_w.x()) / 2, (pa_w.y() + pb_w.y()) / 2)
            dist_text = f"{self.distance_px:.1f} px"
            painter.setFont(QFont("Consolas", 10, QFont.Weight.Bold))
            fm = painter.fontMetrics()
            text_w = fm.horizontalAdvance(dist_text) + 16
            lr = QRectF(mid.x() - text_w / 2, mid.y() - 22, text_w, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(0, 0, 0, 200)))
            painter.drawRoundedRect(lr, 3, 3)
            painter.setPen(QPen(QColor(255, 215, 0)))
            painter.drawText(lr, Qt.AlignmentFlag.AlignCenter, dist_text)

        painter.end()

    def _draw_point(self, painter, pos, label, color):
        painter.setPen(QPen(color, 2))
        cs = 15
        painter.drawLine(QPointF(pos.x() - cs, pos.y()), QPointF(pos.x() + cs, pos.y()))
        painter.drawLine(QPointF(pos.x(), pos.y() - cs), QPointF(pos.x(), pos.y() + cs))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(pos, 8, 8)
        painter.setPen(QPen(color))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(QPointF(pos.x() + 12, pos.y() - 12), label)


class CalibrationWizard(QDialog):
    """Wizard guidato per la calibrazione del sistema."""

    calibration_completed = Signal(float)

    def __init__(
        self,
        calibration_engine: CalibrationEngine,
        current_frame: Optional[np.ndarray] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._cal_engine = calibration_engine
        self._current_frame = current_frame
        self._distance_px: float = 0.0
        self._scale_mm_per_px: float = 0.0

        self._setup_ui()
        self._connect_signals()

        if current_frame is not None:
            self._image_view.set_frame(current_frame)
            self._update_step_state()

    def _setup_ui(self):
        self.setWindowTitle("Calibrazione Sistema — Advanced Optical Profiler")
        self.setMinimumSize(780, 620)
        self.resize(900, 700)
        self.setModal(True)
        self.setStyleSheet("QDialog{background-color:#F4F5F7;}")

        ml = QVBoxLayout(self)
        ml.setContentsMargins(24, 20, 24, 20)
        ml.setSpacing(16)

        header = QLabel("⚙️  Calibrazione — Fattore di Scala")
        header.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        header.setStyleSheet("color:#0066B3;background:transparent;")
        ml.addWidget(header)

        self._lbl_instructions = QLabel(
            "① Cattura un frame con il campione di calibrazione\n"
            "② Clicca sui due estremi del campione\n"
            "③ Inserisci la distanza reale in mm e conferma"
        )
        self._lbl_instructions.setFont(QFont("Segoe UI", 10))
        self._lbl_instructions.setStyleSheet("color:#6B7280;background:transparent;")
        self._lbl_instructions.setWordWrap(True)
        ml.addWidget(self._lbl_instructions)

        self._image_view = CalibrationImageView()
        ml.addWidget(self._image_view, 1)

        cf = QFrame()
        cf.setStyleSheet(
            "QFrame{background:#FFFFFF;border:1px solid #E5E7EB;border-radius:8px;}"
        )
        cl = QVBoxLayout(cf)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(12)

        r1 = QHBoxLayout()
        r1.setSpacing(12)
        self._btn_capture = QPushButton("📸  Cattura Frame")
        self._btn_capture.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        self._btn_capture.setMinimumHeight(36)
        self._btn_capture.setStyleSheet(
            "QPushButton{background:#0066B3;color:white;border:none;"
            "border-radius:6px;padding:8px 20px;}"
            "QPushButton:hover{background:#004A82;}"
            "QPushButton:disabled{background:#D1D5DB;color:#9CA3AF;}"
        )
        r1.addWidget(self._btn_capture)
        self._btn_clear = QPushButton("🔄  Ripeti Selezione")
        self._btn_clear.setMinimumHeight(36)
        self._btn_clear.setEnabled(False)
        r1.addWidget(self._btn_clear)
        r1.addStretch()
        self._lbl_distance_px = QLabel("Distanza: — px")
        self._lbl_distance_px.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        self._lbl_distance_px.setStyleSheet("color:#0066B3;background:transparent;border:none;")
        r1.addWidget(self._lbl_distance_px)
        cl.addLayout(r1)

        r2 = QHBoxLayout()
        r2.setSpacing(12)
        lbl_real = QLabel("Distanza reale del campione:")
        lbl_real.setFont(QFont("Segoe UI", 10))
        lbl_real.setStyleSheet("color:#374151;background:transparent;border:none;")
        r2.addWidget(lbl_real)
        self._spin_real_mm = QDoubleSpinBox()
        self._spin_real_mm.setRange(0.1, 500.0)
        self._spin_real_mm.setValue(25.0)
        self._spin_real_mm.setDecimals(3)
        self._spin_real_mm.setSingleStep(0.1)
        self._spin_real_mm.setSuffix(" mm")
        self._spin_real_mm.setFont(QFont("Consolas", 12))
        self._spin_real_mm.setMinimumHeight(34)
        self._spin_real_mm.setMinimumWidth(140)
        r2.addWidget(self._spin_real_mm)
        r2.addStretch()
        self._lbl_result = QLabel("Scala: — mm/px")
        self._lbl_result.setFont(QFont("Consolas", 12, QFont.Weight.Bold))
        self._lbl_result.setStyleSheet("color:#6B7280;background:transparent;border:none;")
        r2.addWidget(self._lbl_result)
        cl.addLayout(r2)

        r3 = QHBoxLayout()
        self._lbl_current_cal = QLabel("")
        self._lbl_current_cal.setFont(QFont("Segoe UI", 9))
        self._lbl_current_cal.setStyleSheet("color:#9CA3AF;background:transparent;border:none;")
        self._update_current_calibration_label()
        r3.addWidget(self._lbl_current_cal)
        r3.addStretch()
        cl.addLayout(r3)

        ml.addWidget(cf)

        bl = QHBoxLayout()
        bl.setSpacing(12)
        bl.addStretch()
        self._btn_cancel = QPushButton("Annulla")
        self._btn_cancel.setMinimumHeight(38)
        self._btn_cancel.setMinimumWidth(100)
        bl.addWidget(self._btn_cancel)
        self._btn_save = QPushButton("✓  Salva Calibrazione")
        self._btn_save.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._btn_save.setMinimumHeight(38)
        self._btn_save.setMinimumWidth(180)
        self._btn_save.setEnabled(False)
        self._btn_save.setStyleSheet(
            "QPushButton{background:#059669;color:white;border:none;"
            "border-radius:6px;padding:8px 24px;}"
            "QPushButton:hover{background:#047857;}"
            "QPushButton:disabled{background:#D1D5DB;color:#9CA3AF;}"
        )
        bl.addWidget(self._btn_save)
        ml.addLayout(bl)

    def _connect_signals(self):
        self._btn_capture.clicked.connect(self._on_capture_frame)
        self._btn_clear.clicked.connect(self._on_clear_points)
        self._btn_cancel.clicked.connect(self.reject)
        self._btn_save.clicked.connect(self._on_save_calibration)
        self._image_view.points_selected.connect(self._on_points_selected)
        self._image_view.points_cleared.connect(self._on_points_cleared)
        self._spin_real_mm.valueChanged.connect(self._recalculate_scale)

    @Slot()
    def _on_capture_frame(self):
        if self._current_frame is not None and self._current_frame.size > 0:
            self._image_view.set_frame(self._current_frame)
            self._lbl_instructions.setText(
                "✓ Frame catturato — Clicca sui due estremi del campione"
            )
            self._lbl_instructions.setStyleSheet(
                "color:#059669;background:transparent;font-weight:bold;"
            )
            self._btn_clear.setEnabled(True)
        else:
            QMessageBox.warning(
                self, "Nessun Frame",
                "Nessun frame disponibile.\n"
                "Assicurati che la telecamera sia connessa e attiva."
            )

    def set_current_frame(self, frame: np.ndarray):
        self._current_frame = frame

    @Slot(QPointF, QPointF)
    def _on_points_selected(self, point_a, point_b):
        self._distance_px = self._image_view.distance_px
        self._lbl_distance_px.setText(f"Distanza: {self._distance_px:.1f} px")
        self._recalculate_scale()
        self._update_step_state()

    @Slot()
    def _on_points_cleared(self):
        self._distance_px = 0.0
        self._lbl_distance_px.setText("Distanza: — px")
        self._lbl_result.setText("Scala: — mm/px")
        self._lbl_result.setStyleSheet("color:#6B7280;background:transparent;border:none;")
        self._btn_save.setEnabled(False)

    @Slot()
    def _on_clear_points(self):
        self._image_view.clear_points()
        self._lbl_instructions.setText("Clicca sui due estremi del campione")
        self._lbl_instructions.setStyleSheet("color:#6B7280;background:transparent;")

    @Slot()
    def _recalculate_scale(self):
        if self._distance_px <= 0:
            return
        real_mm = self._spin_real_mm.value()
        if real_mm <= 0:
            return
        self._scale_mm_per_px = real_mm / self._distance_px
        self._lbl_result.setText(f"Scala: {self._scale_mm_per_px:.6f} mm/px")
        self._lbl_result.setStyleSheet("color:#059669;background:transparent;border:none;")
        self._btn_save.setEnabled(True)

    @Slot()
    def _on_save_calibration(self):
        """
        Salva la calibrazione usando la firma REALE del CalibrationEngine:
        calibrate_from_known_distance(
            point_a_px: np.ndarray,
            point_b_px: np.ndarray,
            known_distance_mm: float,
            image_shape: tuple
        )
        """
        if self._scale_mm_per_px <= 0:
            return

        pa = self._image_view.point_a
        pb = self._image_view.point_b
        if pa is None or pb is None:
            return

        # Converti QPointF → np.ndarray come richiesto dalla firma reale
        point_a_np = np.array([pa.x(), pa.y()])
        point_b_np = np.array([pb.x(), pb.y()])

        # Ottieni image_shape dal frame corrente
        if self._current_frame is not None:
            image_shape = self._current_frame.shape[:2]  # (H, W)
        else:
            image_shape = (480, 640)

        known_distance_mm = self._spin_real_mm.value()

        # Conferma
        confirm_text = (
            f"Confermare la nuova calibrazione?\n\n"
            f"Fattore di scala: {self._scale_mm_per_px:.6f} mm/px\n"
            f"Distanza campione: {known_distance_mm:.3f} mm\n"
            f"Distanza misurata: {self._distance_px:.1f} px\n"
        )

        if self._cal_engine.is_calibrated:
            old_scale = self._cal_engine.scale_factor
            delta_pct = abs(
                (self._scale_mm_per_px - old_scale) / old_scale * 100
            )
            confirm_text += (
                f"\nCalibrazione precedente: {old_scale:.6f} mm/px\n"
                f"Variazione: {delta_pct:.2f}%\n"
            )
            if delta_pct > 10.0:
                confirm_text += "\n⚠️ ATTENZIONE: Variazione >10%!"

        reply = QMessageBox.question(
            self, "Conferma Calibrazione", confirm_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # ═══ CHIAMATA CON FIRMA REALE ═══
        self._cal_engine.calibrate_from_known_distance(
            point_a_px=point_a_np,
            point_b_px=point_b_np,
            known_distance_mm=known_distance_mm,
            image_shape=image_shape,
        )
        #self._cal_engine.save()

        # Leggi il fattore calcolato dal engine (potrebbe differire leggermente)
        actual_scale = self._cal_engine.scale_factor

        logger.info(
            f"Calibrazione salvata: {actual_scale:.6f} mm/px "
            f"(campione: {known_distance_mm:.3f} mm = "
            f"{self._distance_px:.1f} px)"
        )

        self.calibration_completed.emit(actual_scale)

        QMessageBox.information(
            self, "Calibrazione Completata",
            f"✓ Calibrazione salvata con successo.\n\n"
            f"Fattore di scala: {actual_scale:.6f} mm/px\n"
            f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        self.accept()

    def _update_step_state(self):
        if self._image_view._pixmap is None:
            self._lbl_instructions.setText(
                "① Cattura un frame con il campione nel campo visivo"
            )
        elif self._distance_px <= 0:
            self._lbl_instructions.setText(
                "② Clicca sui due estremi del campione"
            )
        else:
            self._lbl_instructions.setText(
                "③ Verifica la distanza in mm e premi 'Salva Calibrazione'"
            )
            self._lbl_instructions.setStyleSheet(
                "color:#059669;background:transparent;font-weight:bold;"
            )

    def _update_current_calibration_label(self):
        if self._cal_engine.is_calibrated:
            age = self._cal_engine.age_days
            scale = self._cal_engine.scale_factor
            status = "scaduta" if self._cal_engine.is_expired else "valida"
            self._lbl_current_cal.setText(
                f"Calibrazione corrente: {scale:.6f} mm/px — "
                f"{age} giorni fa ({status})"
            )
        else:
            self._lbl_current_cal.setText("Nessuna calibrazione precedente")

    def sizeHint(self):
        return QSize(900, 700)