# Ideato e Realizzato da Pierpaolo Careddu

"""
AcquisitionController v3 — Con Calibration Gate obbligatorio.

REGOLA FONDAMENTALE:
    Nessuna misura metrologica può essere eseguita se il sistema
    non è calibrato. Il fattore mm/px DEVE essere valido.
    Senza calibrazione: solo RAW video (specchio).

Architettura:
    MainThread: AcquisitionController (Qt Signals/Slots)
         │
         └─→ QThread: GrabWorker
                 │
                 ├─ [auto_measure OFF o !calibrato] → RAW bypass
                 │
                 └─ [auto_measure ON e calibrato] → MetrologyEngine
                         │
                         ├─→ measurement_completed → overlay (alta freq)
                         └─→ StabilityDetector → measure_captured (bassa freq)
"""

import time
import logging
import numpy as np
from collections import deque
from typing import Optional

from PySide6.QtCore import (
    QObject, Signal, Slot, QThread, QTimer, Qt
)

try:
    import cv2 as _cv2  # P5 — import a livello modulo (non dentro il metodo)
    _HAS_CV2 = True
except ImportError:
    _cv2 = None
    _HAS_CV2 = False

from core.camera_manager import CameraManager
from core.metrology_engine import (
    MetrologyEngine, MeasurementResult, MeasurementStatus, PipelineConfig
)
from core.calibration_engine import CalibrationEngine
from core.image_processor import ImageProcessor
from views.widgets.live_view_widget import (
    LiveViewWidget, EdgeOverlayData, OSDSeverity
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# STABILITY DETECTOR
# ═══════════════════════════════════════════════════════════════

class StabilityDetector:
    """
    Rileva convergenza temporale delle misure per auto-trigger.

    Buffer circolare delle ultime N misure. Quando il delta
    (max - min) nel buffer è < threshold per M frame consecutivi,
    scatta il trigger. Cooldown di 2s tra catture.
    """

    def __init__(
        self,
        buffer_size: int = 12,
        threshold_mm: float = 0.05,
        required_stable_frames: int = 8,
        cooldown_seconds: float = 2.0,
    ):
        self._buffer_size = buffer_size
        self._threshold_mm = threshold_mm
        self._required_stable = required_stable_frames
        self._cooldown_s = cooldown_seconds
        self._buffer: deque[float] = deque(maxlen=buffer_size)
        self._stable_count: int = 0
        self._last_trigger_time: float = 0.0
        self._last_result: Optional[MeasurementResult] = None

    def feed(self, result: MeasurementResult) -> bool:
        self._last_result = result

        if result.status in (
            MeasurementStatus.ERROR_NO_EDGES,
            MeasurementStatus.ERROR_INVALID_GEOMETRY,
        ):
            self._stable_count = 0
            return False

        self._buffer.append(result.width_mm_mean)

        if len(self._buffer) < min(
            self._required_stable, self._buffer_size
        ):
            self._stable_count = 0
            return False

        buf = list(self._buffer)
        delta = max(buf) - min(buf)

        if delta < self._threshold_mm:
            self._stable_count += 1
        else:
            self._stable_count = 0

        if self._stable_count >= self._required_stable:
            now = time.perf_counter()
            if (now - self._last_trigger_time) < self._cooldown_s:
                return False
            self._last_trigger_time = now
            self._stable_count = 0
            self._buffer.clear()
            return True

        return False

    @property
    def progress(self) -> float:
        if self._required_stable <= 0:
            return 0.0
        return min(1.0, self._stable_count / self._required_stable)

    @property
    def last_result(self) -> Optional[MeasurementResult]:
        return self._last_result

    @property
    def is_in_cooldown(self) -> bool:
        return (
            time.perf_counter() - self._last_trigger_time
        ) < self._cooldown_s

    def reset(self):
        self._buffer.clear()
        self._stable_count = 0
        self._last_result = None

    def set_parameters(
        self,
        threshold_mm: Optional[float] = None,
        required_stable_frames: Optional[int] = None,
        cooldown_seconds: Optional[float] = None,
    ):
        if threshold_mm is not None:
            self._threshold_mm = threshold_mm
        if required_stable_frames is not None:
            self._required_stable = required_stable_frames
        if cooldown_seconds is not None:
            self._cooldown_s = cooldown_seconds
        self.reset()
        
# ═══════════════════════════════════════════════════════════════
# SingleMeasure WORKER
# ═══════════════════════════════════════════════════════════════

class _SingleMeasureWorker(QObject):
    """
    Worker per eseguire una misura singola in un thread separato.
    Evita il freeze della UI durante la pipeline metrologica.
    """

    finished = Signal(object)   # MeasurementResult
    error = Signal(str)

    def __init__(self, engine: MetrologyEngine, frame: np.ndarray):
        super().__init__()
        self._engine = engine
        self._frame = frame

    @Slot()
    def run(self):
        try:
            result = self._engine.measure(self._frame)
            self.finished.emit(result)
        except (ValueError, RuntimeError) as e:
            self.error.emit(str(e))
        except Exception as e:
            logger.error(f"_SingleMeasureWorker: errore inatteso: {e}")
            self.error.emit(f"Errore inatteso: {e}")


# ═══════════════════════════════════════════════════════════════
# GRAB WORKER
# ═══════════════════════════════════════════════════════════════

class GrabWorker(QObject):
    """Worker acquisizione frame in thread separato."""

    frame_ready = Signal(np.ndarray)
    measurement_completed = Signal(object)
    histogram_ready = Signal(np.ndarray)
    sharpness_ready = Signal(float)
    error_occurred = Signal(str)

    def __init__(
        self,
        camera_manager: CameraManager,
        metrology_engine: MetrologyEngine,
        image_processor: Optional[ImageProcessor] = None,
    ):
        super().__init__()
        self._camera = camera_manager
        self._engine = metrology_engine
        # P8 — ImageProcessor opzionale per preprocessing nel grab thread
        self._processor: Optional[ImageProcessor] = image_processor
        self._running: bool = False
        self._auto_measure: bool = False
        self._frame_count: int = 0
        self._measure_every_n: int = 1
        # P1+P7 — Decimazione visual aids: istogramma e nitidezza
        # ogni N frame (default: 3) per risparmiare ~60-70% CPU
        self._visual_aids_every_n: int = 3
        self._fps_timer_start: float = 0.0
        self._fps_frame_count: int = 0
        self._last_fps: float = 0.0

    @Slot()
    def run(self):
        self._running = True
        self._fps_timer_start = time.perf_counter()
        self._fps_frame_count = 0
        logger.info("GrabWorker: loop avviato")

        while self._running:
            try:
                frame = self._camera.grab_frame()
                if frame is None:
                    time.sleep(0.01)
                    continue

                self._frame_count += 1
                self._fps_frame_count += 1

                elapsed = time.perf_counter() - self._fps_timer_start
                if elapsed >= 1.0:
                    self._last_fps = self._fps_frame_count / elapsed
                    self._fps_frame_count = 0
                    self._fps_timer_start = time.perf_counter()

                # P8 — Preprocessing opzionale nel grab thread
                if (
                    self._processor is not None
                    and not self._processor.is_identity
                ):
                    frame = self._processor.process(frame)

                self.frame_ready.emit(frame)

                # P1+P7 — Visual aids solo ogni N frame
                if (self._frame_count % self._visual_aids_every_n) == 0:
                    histogram = np.histogram(
                        frame.ravel(), bins=256, range=(0, 256)
                    )[0]
                    self.histogram_ready.emit(histogram.astype(np.float32))

                    sharpness = self._compute_sharpness(frame)
                    self.sharpness_ready.emit(sharpness)

                if self._auto_measure:
                    if (self._frame_count % self._measure_every_n) == 0:
                        try:
                            result = self._engine.measure(frame)
                            self.measurement_completed.emit(result)
                        except (ValueError, RuntimeError) as e:
                            logger.debug(f"GrabWorker: misura fallita: {e}")

            except Exception as e:
                logger.error(f"GrabWorker: errore: {e}")
                self.error_occurred.emit(str(e))
                time.sleep(0.1)

        logger.info("GrabWorker: loop terminato")

    def stop(self):
        self._running = False

    def set_auto_measure(self, enabled: bool):
        self._auto_measure = enabled

    def set_decimation(self, every_n: int):
        self._measure_every_n = max(1, every_n)

    def set_visual_aids_decimation(self, every_n: int):
        """
        Imposta ogni quanti frame calcolare istogramma e nitidezza (P7).
        Default: 3 (aggiornamento ~15fps a 45fps — fluido e leggero).
        """
        self._visual_aids_every_n = max(1, every_n)

    @property
    def fps(self) -> float:
        return self._last_fps

    @staticmethod
    def _compute_sharpness(frame: np.ndarray) -> float:
        # P5 — cv2 importato a livello modulo, non qui dentro
        if not _HAS_CV2:
            return 0.0
        if frame.ndim == 3:
            gray = _cv2.cvtColor(frame, _cv2.COLOR_BGR2GRAY)
        else:
            gray = frame
        small = gray[::4, ::4]
        laplacian = _cv2.Laplacian(small, _cv2.CV_64F)
        return float(laplacian.var())


# ═══════════════════════════════════════════════════════════════
# ACQUISITION CONTROLLER
# ═══════════════════════════════════════════════════════════════

class AcquisitionController(QObject):
    """
    Controller acquisizione con Calibration Gate obbligatorio.

    CALIBRATION GATE:
        - set_auto_measure(True) → RIFIUTATO se non calibrato
        - set_auto_trigger(True) → RIFIUTATO se non calibrato
        - trigger_single_measure() → RIFIUTATO se non calibrato
        - Solo RAW video è consentito senza calibrazione

    Signals:
        camera_connected(bool)
        measurement_completed(object): overlay live (alta freq)
        measure_captured(object): cattura ufficiale (bassa freq)
        calibration_required(): emesso quando si tenta misura non calibrata
        status_message(str)
    """

    camera_connected = Signal(bool)
    measurement_completed = Signal(object)
    measure_captured = Signal(object)
    calibration_required = Signal()
    fps_updated = Signal(float)
    status_message = Signal(str)

    def __init__(
        self,
        live_view: LiveViewWidget,
        camera_manager: CameraManager,
        metrology_engine: MetrologyEngine,
        calibration_engine: CalibrationEngine,
        image_processor: Optional[ImageProcessor] = None,
        parent=None,
    ):
        super().__init__(parent)

        self._live_view = live_view
        self._camera = camera_manager
        self._engine = metrology_engine
        self._calibration = calibration_engine
        # P8 — ImageProcessor opzionale (passato al GrabWorker)
        self._image_processor: Optional[ImageProcessor] = image_processor

        self._auto_measure: bool = False
        self._auto_trigger: bool = False
        self._manual_mode: bool = False

        self._grab_thread: Optional[QThread] = None
        self._grab_worker: Optional[GrabWorker] = None
        self._is_grabbing: bool = False

        self._stability_detector = StabilityDetector(
            buffer_size=12,
            threshold_mm=0.05,
            required_stable_frames=8,
            cooldown_seconds=2.0,
        )

        self._fps_timer = QTimer(self)
        self._fps_timer.setInterval(1000)
        self._fps_timer.timeout.connect(self._update_fps_display)

        self._stability_ui_timer = QTimer(self)
        self._stability_ui_timer.setInterval(100)
        self._stability_ui_timer.timeout.connect(self._update_stability_ui)

    # ═══════════════════════════════════════════════════════════
    # CALIBRATION GATE — Verifica obbligatoria
    # ═══════════════════════════════════════════════════════════

    def _check_calibration(self, action_name: str) -> bool:
        """
        Verifica che il sistema sia calibrato.
        Se non calibrato, emette segnale e mostra avviso.
        Returns True se calibrato, False altrimenti.
        """
        if self._calibration.is_calibrated:
            if self._calibration.is_expired:
                self._live_view.show_osd_message(
                    "⚠️ CALIBRAZIONE SCADUTA — Risultati non garantiti",
                    OSDSeverity.WARNING, 3000
                )
                logger.warning(
                    f"{action_name}: calibrazione scaduta, "
                    f"misura consentita con avviso"
                )
                # Scaduta ma presente: consenti con warning
                return True
            return True

        # NON CALIBRATO: blocco totale
        self._live_view.show_osd_message(
            "🔴 CALIBRAZIONE OBBLIGATORIA — Impossibile misurare",
            OSDSeverity.ERROR, 4000
        )
        self.calibration_required.emit()
        self.status_message.emit(
            f"🔴 {action_name}: calibrazione obbligatoria! "
            f"Eseguire la calibrazione prima di misurare."
        )
        logger.warning(
            f"{action_name}: BLOCCATO — sistema non calibrato"
        )
        return False

    # ═══════════════════════════════════════════════════════════
    # CONNESSIONE / DISCONNESSIONE CAMERA
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def connect_camera(self):
        try:
            if self._camera.is_connected:
                logger.info("Camera già connessa, skip")
                self.camera_connected.emit(True)
                self.status_message.emit(
                    f"📷 Camera già connessa: "
                    f"{self._camera.device_info}"
                )
                return

            result = self._camera.connect()
            is_connected = bool(result) or self._camera.is_connected

            if is_connected:
                logger.info(
                    f"Camera connessa: {self._camera.device_info}"
                )
                self.camera_connected.emit(True)
                self.status_message.emit(
                    f"📷 Camera connessa: {self._camera.device_info}"
                )
            else:
                logger.warning("Connessione camera fallita")
                self.camera_connected.emit(False)
                self.status_message.emit(
                    "⚠️ Connessione camera fallita"
                )
        except Exception as e:
            logger.error(f"Errore connessione camera: {e}")
            self.camera_connected.emit(False)
            self.status_message.emit(f"❌ Errore camera: {e}")

    @Slot()
    def disconnect_camera(self):
        self.stop_grabbing()
        try:
            self._camera.disconnect()
            logger.info("Camera disconnessa")
            self.camera_connected.emit(False)
            self.status_message.emit("📷 Camera disconnessa")
        except Exception as e:
            logger.error(f"Errore disconnessione: {e}")

    # ═══════════════════════════════════════════════════════════
    # START / STOP ACQUISIZIONE (RAW video sempre consentito)
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def start_grabbing(self):
        if self._is_grabbing:
            return
        if not self._camera.is_connected:
            self.status_message.emit(
                "⚠️ Camera non connessa"
            )
            return

        self._grab_thread = QThread()
        self._grab_worker = GrabWorker(
            camera_manager=self._camera,
            metrology_engine=self._engine,
            image_processor=self._image_processor,  # P8
        )
        self._grab_worker.moveToThread(self._grab_thread)

        self._grab_thread.started.connect(self._grab_worker.run)

        self._grab_worker.frame_ready.connect(
            self._live_view.update_frame,
            type=Qt.ConnectionType.QueuedConnection
        )
        self._grab_worker.histogram_ready.connect(
            self._live_view.update_histogram,
            type=Qt.ConnectionType.QueuedConnection
        )
        self._grab_worker.sharpness_ready.connect(
            self._live_view.update_sharpness,
            type=Qt.ConnectionType.QueuedConnection
        )
        self._grab_worker.measurement_completed.connect(
            self._on_measurement_from_worker,
            type=Qt.ConnectionType.QueuedConnection
        )
        self._grab_worker.error_occurred.connect(
            self._on_worker_error,
            type=Qt.ConnectionType.QueuedConnection
        )

        self._grab_worker.set_auto_measure(self._auto_measure)
        self._grab_thread.start()
        self._is_grabbing = True
        self._fps_timer.start()

        logger.info("Acquisizione avviata")
        self.status_message.emit("▶ Acquisizione avviata (RAW video)")

    @Slot()
    def stop_grabbing(self):
        if not self._is_grabbing:
            return

        self._fps_timer.stop()
        self._stability_ui_timer.stop()

        if self._grab_worker:
            self._grab_worker.stop()

        if self._grab_thread:
            self._grab_thread.quit()
            self._grab_thread.wait(3000)
            if self._grab_thread.isRunning():
                self._grab_thread.terminate()
                self._grab_thread.wait(1000)

        self._grab_worker = None
        self._grab_thread = None
        self._is_grabbing = False

        self._stability_detector.reset()
        self._live_view.update_stability_progress(0.0)

        logger.info("Acquisizione fermata")
        self.status_message.emit("⏹ Acquisizione fermata")

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA — proprietà e helper (R2)
    # ═══════════════════════════════════════════════════════════

    @property
    def is_grabbing(self) -> bool:
        """
        True se il GrabWorker è attivo e sta acquisendo frame (R2).
        Sostituisce l'accesso diretto a _is_grabbing dall'esterno.
        """
        return self._is_grabbing

    def connect_frame_feed(self, slot) -> bool:
        """
        Connette uno slot al segnale frame_ready del GrabWorker (R2).

        Deve essere chiamato DOPO start_grabbing(). Sostituisce l'accesso
        diretto a _grab_worker.frame_ready.connect(...) dall'esterno.

        Args:
            slot: callable da connettere al segnale frame_ready

        Returns:
            True se la connessione è riuscita, False se il GrabWorker
            non è ancora attivo (start_grabbing() non ancora chiamato).
        """
        if self._grab_worker is not None:
            self._grab_worker.frame_ready.connect(
                slot, type=Qt.ConnectionType.QueuedConnection
            )
            return True
        logger.warning(
            "connect_frame_feed: GrabWorker non ancora avviato. "
            "Chiamare start_grabbing() prima di connect_frame_feed()."
        )
        return False

    # ═══════════════════════════════════════════════════════════
    # TOGGLE: AUTO MEASURE — CON CALIBRATION GATE
    # ═══════════════════════════════════════════════════════════

    @Slot(bool)
    def set_auto_measure(self, enabled: bool):
        if enabled:
            if not self._check_calibration("Misura Auto"):
                return  # Bloccato: la MainWindow dovrà unchecked il toggle

        self._auto_measure = enabled
        if self._grab_worker:
            self._grab_worker.set_auto_measure(enabled)

        if enabled:
            logger.info("Pipeline metrologica ATTIVATA")
            self.status_message.emit("📏 Misura automatica attivata")
        else:
            if self._auto_trigger:
                self.set_auto_trigger(False)
            self._live_view.update_edge_overlay(EdgeOverlayData())
            self._live_view.update_stability_progress(0.0)
            self._stability_detector.reset()
            logger.info("Pipeline metrologica DISATTIVATA")
            self.status_message.emit(
                "�� Modalità RAW — pipeline disattivata"
            )

    # ═══════════════════════════════════════════════════════════
    # TOGGLE: AUTO TRIGGER — CON CALIBRATION GATE
    # ═══════════════════════════════════════════════════════════

    @Slot(bool)
    def set_auto_trigger(self, enabled: bool):
        if enabled:
            if not self._check_calibration("Auto-Trigger"):
                return

        self._auto_trigger = enabled
        if enabled:
            self._stability_detector.reset()
            self._stability_ui_timer.start()
            logger.info("Auto-trigger ATTIVATO")
            self.status_message.emit(
                "🎯 Auto-trigger attivato"
            )
        else:
            self._stability_ui_timer.stop()
            self._stability_detector.reset()
            self._live_view.update_stability_progress(0.0)
            logger.info("Auto-trigger DISATTIVATO")
            self.status_message.emit("🎯 Auto-trigger disattivato")

    # ═══════════════════════════════════════════════════════════
    # TOGGLE: MISURA MANUALE
    # ═══════════════════════════════════════════════════════════

    @Slot(bool)
    def set_manual_mode(self, enabled: bool):
        self._manual_mode = enabled
        self._live_view.set_manual_mode(enabled)
        if enabled:
            if not self._calibration.is_calibrated:
                self.status_message.emit(
                    "📐 Misura manuale (SOLO PIXEL — non calibrato)"
                )
            else:
                self.status_message.emit(
                    "📐 Misura manuale: clicca due punti"
                )
        else:
            self.status_message.emit("📐 Misura manuale disattivata")

    # ═══════════════════════════════════════════════════════════
    # MISURA SINGOLA — CON CALIBRATION GATE
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def trigger_single_measure(self):
        """
        Misura singola NON-BLOCCANTE.
        Esegue la pipeline metrologica in un thread worker
        per non congelare la UI.
        """
        if not self._check_calibration("Misura Singola"):
            return

        frame = self._live_view.get_current_frame()
        if frame is None or frame.size == 0:
            self.status_message.emit("⚠️ Nessun frame disponibile")
            return

        # get_current_frame() restituisce già una copia thread-safe
        self.status_message.emit("📸 Misura in corso...")
        self._live_view.show_osd_message(
            "📸 Misura in corso...", OSDSeverity.INFO, 1500
        )

        # Worker thread per non bloccare la UI
        self._single_thread = QThread()
        self._single_worker = _SingleMeasureWorker(
            engine=self._engine,
            frame=frame,
        )
        self._single_worker.moveToThread(self._single_thread)

        self._single_thread.started.connect(self._single_worker.run)
        self._single_worker.finished.connect(
            self._on_single_measure_done
        )
        self._single_worker.error.connect(
            self._on_single_measure_error
        )
        self._single_worker.finished.connect(self._single_thread.quit)
        self._single_worker.error.connect(self._single_thread.quit)
        self._single_thread.finished.connect(
            self._single_thread.deleteLater
        )

        self._single_thread.start()

    @Slot(object)
    def _on_single_measure_done(self, result: MeasurementResult):
        """Callback dal worker: misura singola completata."""
        if result.status in (
            MeasurementStatus.ERROR_NO_EDGES,
            MeasurementStatus.ERROR_INVALID_GEOMETRY,
        ):
            self.status_message.emit(
                f"⚠️ Misura fallita: {result.status.name}"
            )
            self._live_view.show_osd_message(
                "MISURA FALLITA", OSDSeverity.ERROR, 2000
            )
            return

        self.measure_captured.emit(result)
        self._live_view.trigger_capture_flash()
        self._update_live_overlay(result)

        logger.info(
            f"Misura singola: {result.width_mm_mean:.3f} ± "
            f"{result.width_mm_std:.3f} mm"
        )
        self.status_message.emit(
            f"📸 Misura: {result.width_mm_mean:.3f} mm"
        )

    @Slot(str)
    def _on_single_measure_error(self, error_msg: str):
        """Callback dal worker: errore misura singola."""
        logger.error(f"Errore misura singola: {error_msg}")
        self.status_message.emit(f"❌ Errore: {error_msg}")
        self._live_view.show_osd_message(
            f"ERRORE: {error_msg}", OSDSeverity.ERROR, 3000
        )
    # ═══════════════════════════════════════════════════════════
    # RICEZIONE MISURE DAL WORKER
    # ═══════════════════════════════════════════════════════════

    @Slot(object)
    def _on_measurement_from_worker(self, result: MeasurementResult):
        if not isinstance(result, MeasurementResult):
            return

        self._update_live_overlay(result)
        self.measurement_completed.emit(result)

        if self._auto_trigger:
            is_stable = self._stability_detector.feed(result)
            if is_stable:
                stable_result = self._stability_detector.last_result
                if stable_result is not None:
                    self.measure_captured.emit(stable_result)
                    self._live_view.trigger_capture_flash()
                    self._live_view.show_osd_message(
                        f"✓ CATTURA: "
                        f"{stable_result.width_mm_mean:.3f} mm",
                        OSDSeverity.INFO, 2000
                    )
                    logger.info(
                        f"Auto-trigger: "
                        f"{stable_result.width_mm_mean:.3f} mm"
                    )

    def _update_live_overlay(self, result: MeasurementResult):
        edge_data = EdgeOverlayData(
            top_edge_points=getattr(
                result, 'top_edge_points', None
            ),
            bottom_edge_points=getattr(
                result, 'bottom_edge_points', None
            ),
            top_line_params=getattr(
                result, 'top_line_params', None
            ),
            bottom_line_params=getattr(
                result, 'bottom_line_params', None
            ),
            scanline_tops=getattr(result, 'scanline_tops', None),
            scanline_bottoms=getattr(
                result, 'scanline_bottoms', None
            ),
            is_valid=(result.status not in (
                MeasurementStatus.ERROR_NO_EDGES,
                MeasurementStatus.ERROR_INVALID_GEOMETRY,
            )),
            angle_deg=result.theta_avg_deg,
            width_mm=result.width_mm_mean,
            width_mm_std=result.width_mm_std,
        )
        self._live_view.update_edge_overlay(edge_data)

    # ═══════════════════════════════════════════════════════════
    # TIMER CALLBACKS
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def _update_fps_display(self):
        if self._grab_worker:
            fps = self._grab_worker.fps
            self._live_view.update_fps(fps)
            self.fps_updated.emit(fps)

    @Slot()
    def _update_stability_ui(self):
        if self._auto_trigger:
            progress = self._stability_detector.progress
            self._live_view.update_stability_progress(progress)

    @Slot(str)
    def _on_worker_error(self, error_msg: str):
        logger.error(f"Errore worker: {error_msg}")
        self._live_view.show_osd_message(
            f"ERRORE: {error_msg}", OSDSeverity.ERROR, 5000
        )
        self.status_message.emit(f"❌ {error_msg}")

    # ═══════════════════════════════════════════════════════════
    # CONTROLLO CAMERA
    # ═══════════════════════════════════════════════════════════

    @Slot(int)
    def set_exposure(self, value_us: int):
        try:
            self._camera.set_exposure(value_us)
        except Exception as e:
            logger.warning(f"Errore esposizione: {e}")

    @Slot(float)
    def set_gain(self, value_db: float):
        try:
            self._camera.set_gain(value_db)
        except Exception as e:
            logger.warning(f"Errore gain: {e}")

    def configure_stability(
        self, threshold_mm=0.05, required_frames=8, cooldown_s=2.0
    ):
        self._stability_detector.set_parameters(
            threshold_mm=threshold_mm,
            required_stable_frames=required_frames,
            cooldown_seconds=cooldown_s,
        )

    def cleanup(self):
        logger.info("AcquisitionController: cleanup")
        self.stop_grabbing()
        try:
            if self._camera.is_connected:
                self._camera.disconnect()
        except Exception as e:
            logger.warning(f"Cleanup camera: {e}")
        logger.info("AcquisitionController: cleanup completato")