# Ideato e Realizzato da Pierpaolo Careddu

"""
MainWindow v7 — Integrazione completa widget specializzati.

Architettura:
- CameraControlPanel: gestione hardware telecamera
- StatusBarWidget: barra di stato con LED e orologio
- LiveViewWidget: video live con overlay metrologici
- MeasurementTable: tabella misure
- StatisticsPanel: statistiche in tempo reale
- CalibrationWizard: wizard calibrazione
- SessionController: ciclo vita prova
- MeasurementController: pipeline misura → model
- AcquisitionController: grabbing + metrologia

Tutti i fix P0/P1 integrati:
- P0.4: statistics_updated → panel
- P0.5: propagazione calibrazione pre-esistente
- P0.7: threading lock in MetrologyEngine
- P1.1: scala calibrazione al LiveView per misure manuali
- Calibration Gate: misure bloccate senza calibrazione
- Warning ricalibrazione su cambio parametri ottici
- Misura singola non-bloccante (_SingleMeasureWorker)
- Terminologia "Prova di Misura" coerente
"""

import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QFrame, QLabel, QPushButton, QGroupBox, QToolBar, QMessageBox,
    QSizePolicy, QCheckBox, QScrollArea, QComboBox
)
from PySide6.QtCore import Qt, Signal, Slot, QSize, QTimer
from PySide6.QtGui import QFont, QAction

from views.widgets.live_view_widget import LiveViewWidget, OSDSeverity
from views.widgets.measurement_table import MeasurementTable
from views.widgets.statistics_panel import StatisticsPanel
from views.widgets.camera_control_panel import CameraControlPanel
from views.widgets.status_bar_widget import StatusBarWidget
from views.dialogs.login_dialog import LoginDialog
from controllers.acquisition_controller import AcquisitionController
from controllers.measurement_controller import MeasurementController
from controllers.session_controller import SessionController
from core.camera_manager import CameraManager
from core.metrology_engine import (
    MetrologyEngine, MeasurementResult, MeasurementStatus, PipelineConfig
)
from core.calibration_engine import CalibrationEngine
from core.statistics_model import StatisticsModel
from config import (
    CAMERA_SIMULATE, CAMERA_DEFAULT_EXPOSURE_US, CAMERA_DEFAULT_GAIN_DB,
    CAMERA_EXPOSURE_RANGE, CAMERA_GAIN_RANGE,
    METROLOGY_NUM_SCANLINES, METROLOGY_PROFILE_HALF_LENGTH,
    METROLOGY_RANSAC_MAX_TRIALS,
    UI_MIN_WINDOW_WIDTH, UI_MIN_WINDOW_HEIGHT,
    UI_LEFT_PANEL_MIN_WIDTH, UI_LEFT_PANEL_MAX_WIDTH,
    UI_LIVE_VIEW_MIN_HEIGHT, UI_STATS_PANEL_MIN_HEIGHT, UI_TABLE_MIN_HEIGHT,
    UI_SPLITTER_RATIOS, SESSIONS_DIR, EXPORT_DIR,
    APP_NAME, APP_VERSION, APP_AUTHOR,
)

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self._operator_id: str = ""
        self._session_start: Optional[datetime] = None

        # ── Core Engine ──
        self._camera_manager = CameraManager(simulate=CAMERA_SIMULATE)
        self._metrology_engine = MetrologyEngine(PipelineConfig(
            num_scanlines=METROLOGY_NUM_SCANLINES,
            profile_half_length=METROLOGY_PROFILE_HALF_LENGTH,
            ransac_max_trials=METROLOGY_RANSAC_MAX_TRIALS,
        ))
        self._calibration_engine = CalibrationEngine()
        # commento per togliere il loading della calibrazione. ad ogni avvio deve necessariamente ricalibrare
        # self._calibration_engine.load()
        # if self._calibration_engine.is_calibrated:
        #     self._metrology_engine.set_calibration(
        #         scale_mm_per_px=self._calibration_engine.scale_factor,
        #         k1_radial=self._calibration_engine.k1_radial,
        #         optical_center=self._calibration_engine.optical_center,
        #     )
        self._statistics_model = StatisticsModel(parent=self)

        # ── UI Construction ──
        self._setup_window()
        self._create_widgets()
        self._create_left_panel()
        self._create_center_area()
        self._create_toolbar()
        self._create_status_bar()
        self._assemble_layout()

        # ── Controllers ──
        self._acquisition_controller = AcquisitionController(
            live_view=self._live_view,
            camera_manager=self._camera_manager,
            metrology_engine=self._metrology_engine,
            calibration_engine=self._calibration_engine,
            parent=self,
        )
        self._measurement_controller = MeasurementController(
            statistics_model=self._statistics_model,
            measurement_table=self._measurement_table,
            statistics_panel=self._statistics_panel,
            parent=self,
        )
        self._session_controller = SessionController(
            statistics_model=self._statistics_model,
            sessions_dir=SESSIONS_DIR,
            exports_dir=EXPORT_DIR,
            parent=self,
        )

        # ── CalibrationController (USAF Click-to-Calibrate) ──
        from controllers.calibration_controller import CalibrationController
        self._calibration_controller = CalibrationController(
            calibration_engine=self._calibration_engine,
            metrology_engine=self._metrology_engine,
            live_view=self._live_view,
            operator_id=self._operator_id,
            parent=self,
        )

        # P0.5 — Propagare calibrazione pre-esistente
        if self._calibration_engine.is_calibrated:
            self._session_controller.set_calibration_scale(
                self._calibration_engine.scale_factor
            )
            self._session_controller.set_operator(self._operator_id)

        # P1.1 — Scala calibrazione al LiveView per misure manuali
        if self._calibration_engine.is_calibrated:
            self._live_view.set_calibration_scale(
                self._calibration_engine.scale_factor
            )

        # ── Cablaggio e stato iniziale ──
        self._connect_signals()
        self._camera_panel.update_connection_state(False)
        self._update_calibration_ui()
        self._update_calibration_gate()
        self._update_session_ui()
        self._status_bar_widget.update_camera_status(False)
        self._status_bar_widget.update_calibration_status(
            self._calibration_engine.is_calibrated,
            f"{self._calibration_engine.scale_factor:.6f} mm/px"
            if self._calibration_engine.is_calibrated else ""
        )

    def _setup_window(self):
        self.setWindowTitle(
            f"{APP_NAME} v{APP_VERSION} — Sistema Metrologico R&D"
        )
        self.setMinimumSize(UI_MIN_WINDOW_WIDTH, UI_MIN_WINDOW_HEIGHT)

    def _create_widgets(self):
        self._live_view = LiveViewWidget()
        self._measurement_table = MeasurementTable()
        self._statistics_panel = StatisticsPanel()
        self._camera_panel = CameraControlPanel()
        self._status_bar_widget = StatusBarWidget()

        # Configura range camera dal config
        self._camera_panel.set_exposure_range(
            CAMERA_EXPOSURE_RANGE[0],
            CAMERA_EXPOSURE_RANGE[1],
            CAMERA_DEFAULT_EXPOSURE_US,
        )
        self._camera_panel.set_gain_range(
            CAMERA_GAIN_RANGE[0],
            CAMERA_GAIN_RANGE[1],
            CAMERA_DEFAULT_GAIN_DB,
        )

    # ═══════════════════════════════════════════════════════════
    # LEFT PANEL — Sidebar con widget specializzati
    # ═══════════════════════════════════════════════════════════

    def _create_left_panel(self):
        self._left_scroll = QScrollArea()
        self._left_scroll.setWidgetResizable(True)
        self._left_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._left_scroll.setMinimumWidth(UI_LEFT_PANEL_MIN_WIDTH)
        self._left_scroll.setMaximumWidth(UI_LEFT_PANEL_MAX_WIDTH)
        self._left_scroll.setStyleSheet(
            "QScrollArea{border:none;background:transparent;}"
            "QScrollBar:vertical{width:6px;background:transparent;}"
            "QScrollBar::handle:vertical{background:#D1D5DB;"
            "border-radius:3px;min-height:30px;}"
        )

        self._left_panel = QWidget()
        ll = QVBoxLayout(self._left_panel)
        ll.setContentsMargins(10, 12, 10, 12)
        ll.setSpacing(12)

        # ── Camera Control Panel (widget specializzato) ──
        ll.addWidget(self._camera_panel)

        # ── Calibrazione ──
        calg = QGroupBox("⚙️  CALIBRAZIONE")
        call = QVBoxLayout(calg)
        call.setContentsMargins(12, 22, 12, 12)
        call.setSpacing(6)
        self._lbl_cal_status = QLabel("⚪  Non calibrato")
        self._lbl_cal_status.setFont(
            QFont("Segoe UI", 9, QFont.Weight.Bold)
        )
        call.addWidget(self._lbl_cal_status)
        self._lbl_cal_scale = QLabel("Scala: — mm/px")
        self._lbl_cal_scale.setFont(QFont("Consolas", 8))
        call.addWidget(self._lbl_cal_scale)
        self._lbl_cal_date = QLabel("Data: —")
        self._lbl_cal_date.setFont(QFont("Segoe UI", 8))
        call.addWidget(self._lbl_cal_date)
        call.addSpacing(4)
        self._btn_calibrate = QPushButton("🎯  Nuova Calibrazione")
        self._btn_calibrate.setMinimumHeight(32)
        call.addWidget(self._btn_calibrate)

        # ── Calibrazione Rapida USAF ──
        usaf_separator = QLabel("─── Calibrazione Rapida USAF ───")
        usaf_separator.setFont(QFont("Segoe UI", 8))
        usaf_separator.setStyleSheet("color:#9CA3AF;")
        usaf_separator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        call.addWidget(usaf_separator)

        # Selettore gruppo
        group_row = QHBoxLayout()
        group_row.setSpacing(6)
        lbl_group = QLabel("Gruppo:")
        lbl_group.setFont(QFont("Segoe UI", 9))
        group_row.addWidget(lbl_group)
        self._combo_usaf_group = QComboBox()
        for g in range(-2, 8):
            self._combo_usaf_group.addItem(f"G{g}", g)
        self._combo_usaf_group.setCurrentIndex(0)
        group_row.addWidget(self._combo_usaf_group)
        call.addLayout(group_row)

        # Selettore elemento
        elem_row = QHBoxLayout()
        elem_row.setSpacing(6)
        lbl_elem = QLabel("Elemento:")
        lbl_elem.setFont(QFont("Segoe UI", 9))
        elem_row.addWidget(lbl_elem)
        self._combo_usaf_element = QComboBox()
        for e in range(1, 7):
            self._combo_usaf_element.addItem(f"E{e}", e)
        self._combo_usaf_element.setCurrentIndex(0)
        elem_row.addWidget(self._combo_usaf_element)
        call.addLayout(elem_row)

        # Etichetta dimensione (mostra la larghezza fisica per la selezione corrente)
        self._lbl_usaf_dimension = QLabel("Larghezza barra: 0.2500 mm")
        self._lbl_usaf_dimension.setFont(QFont("Consolas", 8))
        self._lbl_usaf_dimension.setStyleSheet("color:#6B7280;")
        call.addWidget(self._lbl_usaf_dimension)

        # Pulsante calibrazione USAF (checkable)
        self._btn_usaf_calib = QPushButton("📐 Calibrazione USAF (Click)")
        self._btn_usaf_calib.setCheckable(True)
        self._btn_usaf_calib.setMinimumHeight(32)
        self._btn_usaf_calib.setToolTip(
            "Calibrazione rapida: clicca su un gap del target USAF 1951"
        )
        call.addWidget(self._btn_usaf_calib)

        ll.addWidget(calg)

        # ── Prova di Misura ──
        sg = QGroupBox("📋  PROVA DI MISURA")
        sgl = QVBoxLayout(sg)
        sgl.setContentsMargins(12, 22, 12, 12)
        sgl.setSpacing(6)
        self._lbl_session_name = QLabel("Nessuna prova attiva")
        self._lbl_session_name.setFont(
            QFont("Segoe UI", 9, QFont.Weight.Bold)
        )
        self._lbl_session_name.setWordWrap(True)
        sgl.addWidget(self._lbl_session_name)
        self._lbl_operator = QLabel("Operatore: —")
        self._lbl_operator.setFont(QFont("Segoe UI", 9))
        sgl.addWidget(self._lbl_operator)
        self._lbl_session_time = QLabel("Inizio: —")
        self._lbl_session_time.setFont(QFont("Segoe UI", 8))
        sgl.addWidget(self._lbl_session_time)
        self._lbl_measure_count = QLabel("Misure: 0")
        self._lbl_measure_count.setFont(QFont("Consolas", 9))
        sgl.addWidget(self._lbl_measure_count)
        sgl.addSpacing(4)
        self._btn_new_session = QPushButton("📋  Nuova Prova")
        self._btn_new_session.setProperty("cssClass", "primary")
        self._btn_new_session.setMinimumHeight(32)
        sgl.addWidget(self._btn_new_session)
        self._btn_end_session = QPushButton("⏹  Termina Prova")
        self._btn_end_session.setMinimumHeight(32)
        self._btn_end_session.setEnabled(False)
        sgl.addWidget(self._btn_end_session)
        ll.addWidget(sg)

        # ── Visualizzazione ──
        vg = QGroupBox("🎨  VISUALIZZAZIONE")
        vl = QVBoxLayout(vg)
        vl.setContentsMargins(12, 22, 12, 12)
        vl.setSpacing(8)
        self._chk_show_edges = QCheckBox("Mostra bordi")
        self._chk_show_edges.setChecked(True)
        vl.addWidget(self._chk_show_edges)
        self._chk_show_focus = QCheckBox("Barra di fuoco")
        self._chk_show_focus.setChecked(True)
        vl.addWidget(self._chk_show_focus)
        self._chk_show_histogram = QCheckBox("Istogramma")
        self._chk_show_histogram.setChecked(True)
        vl.addWidget(self._chk_show_histogram)
        ll.addWidget(vg)

        # ── Stretch + Export ──
        ll.addStretch(1)

        self._btn_export_pdf = QPushButton("📄  Esporta PDF")
        self._btn_export_pdf.setMinimumHeight(34)
        self._btn_export_pdf.setEnabled(False)
        ll.addWidget(self._btn_export_pdf)
        self._btn_export_csv = QPushButton("📊  Esporta CSV")
        self._btn_export_csv.setMinimumHeight(34)
        self._btn_export_csv.setEnabled(False)
        ll.addWidget(self._btn_export_csv)

        self._left_scroll.setWidget(self._left_panel)

    # ═══════════════════════════════════════════════════════════
    # CENTER AREA
    # ═══════════════════════════════════════════════════════════

    def _create_center_area(self):
        self._center_widget = QWidget()
        center_layout = QVBoxLayout(self._center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)

        # Banner calibrazione
        self._calibration_banner = QFrame()
        self._calibration_banner.setFixedHeight(32)
        self._calibration_banner.setStyleSheet(
            "QFrame{background:#FEF2F2;border:1px solid #FECACA;}"
        )
        bl = QHBoxLayout(self._calibration_banner)
        bl.setContentsMargins(12, 4, 12, 4)
        self._lbl_cal_banner = QLabel(
            "🔴  SISTEMA NON CALIBRATO — Misure bloccate."
        )
        self._lbl_cal_banner.setFont(
            QFont("Segoe UI", 9, QFont.Weight.Bold)
        )
        self._lbl_cal_banner.setStyleSheet(
            "color:#DC2626;background:transparent;border:none;"
        )
        bl.addWidget(self._lbl_cal_banner)
        bl.addStretch()
        self._btn_cal_banner = QPushButton("Calibra Ora")
        self._btn_cal_banner.setStyleSheet(
            "QPushButton{background:#DC2626;color:white;border:none;"
            "border-radius:4px;padding:2px 12px;"
            "font-weight:bold;font-size:9px;}"
            "QPushButton:hover{background:#B91C1C;}"
        )
        self._btn_cal_banner.setFixedHeight(24)
        bl.addWidget(self._btn_cal_banner)
        center_layout.addWidget(self._calibration_banner)

        # Splitter verticale: LiveView / Statistics / Table
        self._v_splitter = QSplitter(Qt.Orientation.Vertical)
        self._v_splitter.setChildrenCollapsible(False)
        self._v_splitter.setHandleWidth(5)
        self._v_splitter.setStyleSheet(
            "QSplitter::handle{background:#E5E7EB;}"
            "QSplitter::handle:hover{background:#0066B3;}"
        )
        self._live_view.setMinimumHeight(UI_LIVE_VIEW_MIN_HEIGHT)
        self._v_splitter.addWidget(self._live_view)
        self._statistics_panel.setMinimumHeight(UI_STATS_PANEL_MIN_HEIGHT)
        self._v_splitter.addWidget(self._statistics_panel)
        self._measurement_table.setMinimumHeight(UI_TABLE_MIN_HEIGHT)
        self._v_splitter.addWidget(self._measurement_table)
        for i, ratio in enumerate(UI_SPLITTER_RATIOS):
            self._v_splitter.setStretchFactor(i, ratio)
        center_layout.addWidget(self._v_splitter, 1)

    # ═══════════════════════════════════════════════════════════
    # TOOLBAR
    # ═══════════════════���═══════════════════════════════════════

    def _create_toolbar(self):
        self._toolbar = QToolBar("Strumenti")
        self._toolbar.setMovable(False)
        self._toolbar.setIconSize(QSize(18, 18))

        # Live
        self._act_start_grab = QAction("▶  Avvia Live", self)
        self._act_start_grab.setCheckable(True)
        self._act_start_grab.setToolTip(
            "Avvia/ferma il video dalla telecamera"
        )
        self._toolbar.addAction(self._act_start_grab)
        self._toolbar.addSeparator()

        # Misura
        self._act_auto_measure = QAction("📏  Misura Auto", self)
        self._act_auto_measure.setCheckable(True)
        self._act_auto_measure.setEnabled(False)
        self._act_auto_measure.setToolTip(
            "Attiva la misurazione automatica continua"
        )
        self._toolbar.addAction(self._act_auto_measure)

        self._act_auto_trigger = QAction("🎯  Auto-Trigger", self)
        self._act_auto_trigger.setCheckable(True)
        self._act_auto_trigger.setEnabled(False)
        self._act_auto_trigger.setToolTip(
            "Cattura automatica su stabilità"
        )
        self._toolbar.addAction(self._act_auto_trigger)

        self._act_single_measure = QAction("📸  Misura Singola", self)
        self._act_single_measure.setEnabled(False)
        self._act_single_measure.setToolTip("Misura il frame corrente")
        self._toolbar.addAction(self._act_single_measure)
        self._toolbar.addSeparator()

        # Misura manuale
        self._act_manual_measure = QAction("📐  Misura Manuale", self)
        self._act_manual_measure.setCheckable(True)
        self._act_manual_measure.setToolTip(
            "Misura manuale punto-a-punto"
        )
        self._toolbar.addAction(self._act_manual_measure)

        self._act_clear_manual = QAction("🗑  Cancella Manuali", self)
        self._toolbar.addAction(self._act_clear_manual)
        self._toolbar.addSeparator()

        # Prova
        self._act_new_session = QAction("📋  Nuova Prova", self)
        self._act_new_session.setToolTip(
            "Configura e avvia una nuova prova di misura"
        )
        self._toolbar.addAction(self._act_new_session)

        self._act_end_session = QAction("⏹  Termina Prova", self)
        self._act_end_session.setEnabled(False)
        self._act_end_session.setToolTip(
            "Termina, salva ed esporta la prova"
        )
        self._toolbar.addAction(self._act_end_session)
        self._toolbar.addSeparator()

        # Strumenti
        self._act_reset_zoom = QAction("🔍  Reset Zoom", self)
        self._toolbar.addAction(self._act_reset_zoom)

        self._act_clear_data = QAction("🗑  Cancella Dati", self)
        self._act_clear_data.setToolTip("Cancella tutte le misure")
        self._toolbar.addAction(self._act_clear_data)
        self._toolbar.addSeparator()

        # Info
        self._act_about = QAction("ℹ️  Informazioni", self)
        self._toolbar.addAction(self._act_about)

        self.addToolBar(self._toolbar)

    # ═══════════════════════════════════════════════════════════
    # STATUS BAR — Widget specializzato
    # ═══════════════════════════════════════════════════════════

    # def _create_status_bar(self):
    #     self.setStatusBar(self._status_bar_widget)
    def _create_status_bar(self):
        # 1. Creiamo una QStatusBar standard (quella che piace a Qt)
        from PySide6.QtWidgets import QStatusBar
        self._main_status_bar = QStatusBar()
        
        # 2. Inseriamo il TUO widget personalizzato dentro la barra standard
        # Usiamo addWidget con stretch=1 per fargli occupare tutto lo spazio
        self._main_status_bar.addWidget(self._status_bar_widget, 1)
        
        # 3. Impostiamo la barra standard come barra ufficiale della finestra
        self.setStatusBar(self._main_status_bar)

    # ═══════════════════════════════════════════════════════════
    # ASSEMBLE LAYOUT
    # ═══════════════════════════════════════════════════════════

    def _assemble_layout(self):
        central = QWidget()
        ml = QHBoxLayout(central)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(0)
        self._h_splitter = QSplitter(Qt.Orientation.Horizontal)
        self._h_splitter.setChildrenCollapsible(False)
        self._h_splitter.setHandleWidth(5)
        self._h_splitter.setStyleSheet(
            "QSplitter::handle{background:#E5E7EB;}"
            "QSplitter::handle:hover{background:#0066B3;}"
        )
        self._h_splitter.addWidget(self._left_scroll)
        self._h_splitter.addWidget(self._center_widget)
        self._h_splitter.setStretchFactor(0, 0)
        self._h_splitter.setStretchFactor(1, 1)
        ml.addWidget(self._h_splitter)
        self.setCentralWidget(central)

    # ═══════════════════════════════════════════════════════════
    # CALIBRATION GATE
    # ═══════════════════════════════════════════════════════════

    def _update_calibration_gate(self):
        is_cal = self._calibration_engine.is_calibrated
        self._calibration_banner.setVisible(not is_cal)
        if not is_cal:
            self._act_auto_measure.setEnabled(False)
            self._act_auto_measure.setChecked(False)
            self._act_auto_trigger.setEnabled(False)
            self._act_auto_trigger.setChecked(False)
            self._act_single_measure.setEnabled(False)

    # ═══════════════════════════════════════════════════════════
    # CONNESSIONE SEGNALI
    # ═══════════════════════════════════════════════════════════

    def _connect_signals(self):
        # ── CameraControlPanel → AcquisitionController ──
        self._camera_panel.connect_requested.connect(
            self._on_connect_camera
        )
        self._camera_panel.disconnect_requested.connect(
            self._on_disconnect_camera
        )
        self._camera_panel.start_grabbing_requested.connect(
            self._on_start_grabbing
        )
        self._camera_panel.stop_grabbing_requested.connect(
            self._on_stop_grabbing
        )
        self._camera_panel.exposure_changed.connect(
            self._acquisition_controller.set_exposure
        )
        self._camera_panel.gain_changed.connect(
            self._acquisition_controller.set_gain
        )

        # Warning ricalibrazione su cambio parametri ottici
        self._camera_panel.exposure_changed.connect(
            self._on_optical_change
        )
        self._camera_panel.gain_changed.connect(
            self._on_optical_change
        )

        # ── AcquisitionController → CameraControlPanel ──
        self._acquisition_controller.camera_connected.connect(
            self._camera_panel.update_connection_state
        )
        self._acquisition_controller.camera_connected.connect(
            self._on_camera_connected
        )
        self._acquisition_controller.fps_updated.connect(
            self._camera_panel.update_fps
        )

        # ── AcquisitionController → StatusBarWidget ──
        self._acquisition_controller.camera_connected.connect(
            self._status_bar_widget.update_camera_status
        )
        self._acquisition_controller.status_message.connect(
            self._status_bar_widget.show_message
        )

        # ── Toolbar — Live ──
        self._act_start_grab.toggled.connect(
            self._on_toggle_grabbing_from_toolbar
        )

        # ── Toolbar — Misura ──
        self._act_auto_measure.toggled.connect(
            self._on_toggle_auto_measure
        )
        self._act_auto_trigger.toggled.connect(
            self._on_toggle_auto_trigger
        )
        self._act_single_measure.triggered.connect(
            self._acquisition_controller.trigger_single_measure
        )
        self._act_manual_measure.toggled.connect(
            self._acquisition_controller.set_manual_mode
        )
        self._act_clear_manual.triggered.connect(
            self._live_view.clear_manual_measurements
        )
        self._act_reset_zoom.triggered.connect(
            self._live_view.reset_zoom
        )
        self._act_clear_data.triggered.connect(self._on_clear_data)

        # ── Toolbar — Prova ──
        self._act_new_session.triggered.connect(self._on_new_session)
        self._act_end_session.triggered.connect(self._on_end_session)
        self._btn_new_session.clicked.connect(self._on_new_session)
        self._btn_end_session.clicked.connect(self._on_end_session)
        self._act_about.triggered.connect(self._on_about)

        # ── Sidebar — Export ── con formato distinto
        self._btn_export_pdf.clicked.connect(
            lambda: self._on_quick_export("pdf")
        )
        self._btn_export_csv.clicked.connect(
            lambda: self._on_quick_export("csv")
        )
        
        # ── Misura Manuale → flusso dati standard ──
        self._live_view.manual_measure_completed.connect(
            self._on_manual_measure_completed
        )    

        # ── Sidebar — Visualizzazione ──
        self._chk_show_edges.toggled.connect(
            self._live_view.set_show_edges
        )
        self._chk_show_focus.toggled.connect(
            self._live_view.set_show_focus_bar
        )
        self._chk_show_histogram.toggled.connect(
            self._live_view.set_show_histogram
        )

        # ── Calibrazione ──
        self._btn_calibrate.clicked.connect(self._on_calibrate)
        self._btn_cal_banner.clicked.connect(self._on_calibrate)
        self._acquisition_controller.calibration_required.connect(
            self._on_calibration_required
        )

        # ── USAF Click-to-Calibrate ──
        self._btn_usaf_calib.toggled.connect(self._on_usaf_calib_toggled)
        self._combo_usaf_group.currentIndexChanged.connect(
            self._on_usaf_selection_changed
        )
        self._combo_usaf_element.currentIndexChanged.connect(
            self._on_usaf_selection_changed
        )
        self._calibration_controller.calibration_applied.connect(
            self._on_calibration_done
        )
        self._calibration_controller.calibration_applied.connect(
            lambda _: self._btn_usaf_calib.setChecked(False)
        )
        self._calibration_controller.status_message.connect(
            self._status_bar_widget.show_message
        )

        # ── AcquisitionController → flusso dati misura ──
        self._acquisition_controller.measure_captured.connect(
            self._measurement_controller.on_measure_captured
        )
        self._acquisition_controller.measure_captured.connect(
            self._session_controller.on_measure_captured
        )
        self._acquisition_controller.measurement_completed.connect(
            self._on_measurement_updated
        )

        # ── MeasurementController ──
        self._measurement_controller.status_message.connect(
            self._status_bar_widget.show_message
        )

        # ── SessionController ──
        self._session_controller.session_started.connect(
            self._on_session_started
        )
        self._session_controller.session_ended.connect(
            self._on_session_ended
        )
        self._session_controller.status_message.connect(
            self._status_bar_widget.show_message
        )
        self._session_controller.tolerances_changed.connect(
            self._measurement_controller.set_tolerance
        )

        # ── StatisticsModel → UI ──
        self._statistics_model.record_added.connect(
            self._on_record_changed
        )
        self._statistics_model.record_removed.connect(
            lambda _: self._on_record_changed()
        )
        self._statistics_model.data_cleared.connect(
            self._on_data_cleared
        )
        self._statistics_model.statistics_updated.connect(
            self._on_stats_for_export
        )

        # P0.4 — Model → Pannello statistiche (aggiornamento diretto)
        self._statistics_model.statistics_updated.connect(
            self._statistics_panel.update_statistics
        )

    # ═══════════════════════════════════════════════════════════
    # SLOT — Camera (via CameraControlPanel)
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def _on_connect_camera(self):
        self._acquisition_controller.connect_camera()

    @Slot()
    def _on_disconnect_camera(self):
        if self._acquisition_controller._is_grabbing:
            self._on_stop_grabbing()
        self._acquisition_controller.disconnect_camera()

    @Slot(bool)
    def _on_camera_connected(self, connected):
        """Aggiorna elementi UI che dipendono dallo stato camera."""
        if connected:
            model = self._camera_manager.device_info
            self._camera_panel.update_model_info(model)
            self._status_bar_widget.update_camera_model(model)
            self._act_start_grab.setEnabled(True)
        else:
            self._act_start_grab.setEnabled(False)
            self._act_start_grab.blockSignals(True)
            self._act_start_grab.setChecked(False)
            self._act_start_grab.setText("▶  Avvia Live")
            self._act_start_grab.blockSignals(False)
            self._act_auto_measure.setEnabled(False)
            self._act_auto_measure.setChecked(False)
            self._act_auto_trigger.setEnabled(False)
            self._act_auto_trigger.setChecked(False)
            self._act_single_measure.setEnabled(False)
            self._camera_panel.update_grabbing_state(False)

    @Slot()
    def _on_start_grabbing(self):
        self._acquisition_controller.start_grabbing()
        self._camera_panel.update_grabbing_state(True)
        self._act_start_grab.blockSignals(True)
        self._act_start_grab.setChecked(True)
        self._act_start_grab.setText("⏹  Ferma Live")
        self._act_start_grab.blockSignals(False)
        is_cal = self._calibration_engine.is_calibrated
        self._act_auto_measure.setEnabled(is_cal)
        self._act_single_measure.setEnabled(is_cal)
        self._measurement_controller.activate()

    @Slot()
    def _on_stop_grabbing(self):
        self._act_auto_measure.setChecked(False)
        self._act_auto_trigger.setChecked(False)
        self._acquisition_controller.stop_grabbing()
        self._camera_panel.update_grabbing_state(False)
        self._act_start_grab.blockSignals(True)
        self._act_start_grab.setChecked(False)
        self._act_start_grab.setText("▶  Avvia Live")
        self._act_start_grab.blockSignals(False)
        self._act_auto_measure.setEnabled(False)
        self._act_auto_trigger.setEnabled(False)
        self._act_single_measure.setEnabled(False)

    # ═══════════════════════════════════════════════════════════
    # SLOT — Optical Change Warning
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def _on_optical_change(self):
        """
        Avvisa l'operatore che un cambio di parametri ottici
        potrebbe invalidare la calibrazione corrente.
        """
        if not self._calibration_engine.is_calibrated:
            return
        self._lbl_cal_status.setText("🟡  Ricalibrazione consigliata")
        self._lbl_cal_status.setStyleSheet(
            "color:#D97706;font-weight:bold;"
        )
        self._status_bar_widget.update_calibration_status(
            True, "⚠ Ricalibrazione consigliata"
        )
        self._live_view.show_osd_message(
            "⚠️ Parametri ottici modificati — Ricalibrazione consigliata",
            OSDSeverity.WARNING, 4000
        )
        
    @Slot(float, float)
    def _on_manual_measure_completed(self, dist_px: float, dist_mm: float):
        """
        Riceve una misura manuale dal LiveViewWidget e la registra
        nel flusso dati standard (tabella, statistiche, report).

        Registra direttamente nel StatisticsModel senza costruire
        un MeasurementResult fittizio — approccio pulito.
        """
        import time

        # Se non calibrato, dist_mm è 0 — non registrare nei dati
        if dist_mm <= 0:
            self._status_bar_widget.show_message(
                "📐 Misura manuale: solo pixel "
                "(non calibrato — non registrata nei dati)"
            )
            return

        # Registra direttamente nel StatisticsModel
        record = self._statistics_model.add_measurement(
            width_mm=dist_mm,
            std_mm=0.0,
            width_px=dist_px,
            angle_deg=0.0,
            contrast_ratio=0.0,
            n_scanlines=0,
            timestamp_s=time.perf_counter(),
        )

        # Registra anche nella sessione attiva (se presente)
        if self._session_controller.has_active_session:
            from core.test_session import MeasureRecord
            session_record = MeasureRecord(
                width_mm=dist_mm,
                std_mm=0.0,
                angle_deg=0.0,
                n_scanlines=0,
                is_valid=True,
                source="manual",
            )
            self._session_controller.current_session.add_record(
                session_record
            )

        # Feedback operatore
        status_icon = "✅" if record.is_within_tolerance else "❌"
        self._status_bar_widget.show_message(
            f"📐 Misura manuale #{record.index}: "
            f"{dist_mm:.3f} mm {status_icon}"
        )
        self._live_view.show_osd_message(
            f"📐 {dist_mm:.3f} mm — registrata",
            OSDSeverity.INFO, 2000
        )
        logger.info(
            f"Misura manuale #{record.index}: {dist_mm:.3f} mm "
            f"({dist_px:.1f} px) — "
            f"{'OK' if record.is_within_tolerance else 'NOK'}"
        )
    # ═══════════════════════════════════════════════════════════
    # SLOT — Toolbar Live (sync con CameraControlPanel)
    # ═══════════════════════════════════════════════════════════

    @Slot(bool)
    def _on_toggle_grabbing_from_toolbar(self, checked):
        """Chiamato dal toggle della toolbar, sincronizza col panel."""
        if checked:
            self._on_start_grabbing()
        else:
            self._on_stop_grabbing()

    @Slot(bool)
    def _on_toggle_auto_measure(self, checked):
        self._acquisition_controller.set_auto_measure(checked)
        if checked:
            self._act_auto_trigger.setEnabled(True)
        else:
            self._act_auto_trigger.setEnabled(False)
            self._act_auto_trigger.setChecked(False)

    @Slot(bool)
    def _on_toggle_auto_trigger(self, checked):
        self._acquisition_controller.set_auto_trigger(checked)

    @Slot()
    def _on_clear_data(self):
        if self._statistics_model.count == 0:
            self._status_bar_widget.show_message(
                "ℹ️  Nessun dato da cancellare"
            )
            return
        reply = QMessageBox.question(
            self, "Conferma Cancellazione",
            f"Cancellare tutte le {self._statistics_model.count} misure?"
            f"\n\nQuesta azione è irreversibile.",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._measurement_controller.clear_session_data()

    # ═══════════════════════════════════════════════════════════
    # SLOT — Calibration Gate
    # ═══════════════════════════════════════════════════════════

    @Slot()
    def _on_calibration_required(self):
        self._act_auto_measure.blockSignals(True)
        self._act_auto_measure.setChecked(False)
        self._act_auto_measure.blockSignals(False)
        self._act_auto_trigger.blockSignals(True)
        self._act_auto_trigger.setChecked(False)
        self._act_auto_trigger.blockSignals(False)

    @Slot(bool)
    def _on_usaf_calib_toggled(self, checked: bool):
        if checked:
            group = self._combo_usaf_group.currentData()
            element = self._combo_usaf_element.currentData()
            self._calibration_controller.set_usaf_group_element(group, element)
            self._calibration_controller.start_usaf_click_calibration()
            # Passa la camera simulata alla modalità USAF target
            self._camera_manager.set_simulation_mode("usaf_target")
        else:
            self._calibration_controller.stop_usaf_click_calibration()
            # Ripristina la camera simulata alla modalità bandina
            self._camera_manager.set_simulation_mode("bandina")

    @Slot()
    def _on_usaf_selection_changed(self):
        """Aggiorna l'etichetta dimensione quando cambia gruppo/elemento."""
        from core.usaf_target import usaf_line_width_mm
        group = self._combo_usaf_group.currentData()
        element = self._combo_usaf_element.currentData()
        if group is not None and element is not None:
            try:
                w_mm = usaf_line_width_mm(group, element)
                self._lbl_usaf_dimension.setText(f"Larghezza barra: {w_mm:.4f} mm")
            except ValueError:
                pass
            # Aggiorna il controller se la modalità è attiva
            if self._btn_usaf_calib.isChecked():
                self._calibration_controller.set_usaf_group_element(group, element)

    @Slot()
    def _on_calibrate(self):
        from views.widgets.calibration_wizard import CalibrationWizard
        frame = self._live_view.get_current_frame()
        wizard = CalibrationWizard(
            calibration_engine=self._calibration_engine,
            current_frame=frame,
            parent=self,
        )
        if (self._acquisition_controller.is_grabbing
                and self._acquisition_controller._grab_worker is not None):
            self._acquisition_controller._grab_worker.frame_ready.connect(
                wizard.set_current_frame
            )
        wizard.calibration_completed.connect(self._on_calibration_done)
        wizard.exec()

    @Slot(float)
    def _on_calibration_done(self, scale):
        self._metrology_engine.set_calibration(
            scale_mm_per_px=scale,
            k1_radial=self._calibration_engine.k1_radial,
            optical_center=self._calibration_engine.optical_center,
        )
        self._update_calibration_ui()
        self._update_calibration_gate()
        self._session_controller.set_calibration_scale(scale)
        self._live_view.set_calibration_scale(scale)
        self._status_bar_widget.update_calibration_status(
            True, f"{scale:.6f} mm/px"
        )
        logger.info(f"Calibrazione applicata: {scale:.6f} mm/px")
        self._status_bar_widget.show_message(
            f"⚙️ Calibrazione applicata: {scale:.6f} mm/px"
        )
        if self._acquisition_controller._is_grabbing:
            self._act_auto_measure.setEnabled(True)
            self._act_single_measure.setEnabled(True)
        # Ripristina la camera simulata alla modalità bandina
        self._camera_manager.set_simulation_mode("bandina")

    def _update_calibration_ui(self):
        cal = self._calibration_engine
        if cal.is_calibrated:
            expired = cal.is_expired
            if expired:
                self._lbl_cal_status.setText("🟡  Scaduta")
                self._lbl_cal_status.setStyleSheet(
                    "color:#D97706;font-weight:bold;"
                )
                self._status_bar_widget.set_calibration_expired()
            else:
                self._lbl_cal_status.setText("🟢  Calibrato")
                self._lbl_cal_status.setStyleSheet(
                    "color:#059669;font-weight:bold;"
                )
                self._status_bar_widget.update_calibration_status(
                    True, f"{cal.scale_factor:.6f} mm/px"
                )
            self._lbl_cal_scale.setText(
                f"Scala: {cal.scale_factor:.6f} mm/px"
            )
            if cal.calibration_date:
                self._lbl_cal_date.setText(
                    f"Data: {cal.calibration_date.strftime('%Y-%m-%d')} "
                    f"({cal.age_days}g fa)"
                )
        else:
            self._lbl_cal_status.setText("🔴  Non calibrato")
            self._lbl_cal_status.setStyleSheet(
                "color:#DC2626;font-weight:bold;"
            )
            self._lbl_cal_scale.setText("Scala: — mm/px")
            self._lbl_cal_date.setText("Data: —")
            self._status_bar_widget.update_calibration_status(False)

    # ═══════════════════════════════════════════════════════════
    # SLOT — Prova di Misura
    # ═══════════════════════════════════════════════════════════

    def _update_session_ui(self):
        if self._session_controller.has_active_session:
            name = self._session_controller.session_name
            self._lbl_session_name.setText(f"📋  {name}")
            self._lbl_session_name.setStyleSheet("color:#059669;")
            self._btn_new_session.setEnabled(False)
            self._btn_end_session.setEnabled(True)
            self._act_new_session.setEnabled(False)
            self._act_end_session.setEnabled(True)
            self._status_bar_widget.update_session_name(name)
        else:
            self._lbl_session_name.setText("Nessuna prova attiva")
            self._lbl_session_name.setStyleSheet("color:#6B7280;")
            self._btn_new_session.setEnabled(True)
            self._btn_end_session.setEnabled(False)
            self._act_new_session.setEnabled(True)
            self._act_end_session.setEnabled(False)
            self._status_bar_widget.clear_session()

    @Slot()
    def _on_new_session(self):
        self._session_controller.set_operator(self._operator_id)
        if self._calibration_engine.is_calibrated:
            self._session_controller.set_calibration_scale(
                self._calibration_engine.scale_factor
            )
        self._session_controller.new_session()

    @Slot()
    def _on_end_session(self):
        self._session_controller.end_session()

    @Slot(str)
    def _on_session_started(self, name):
        self._update_session_ui()
        self._live_view.show_osd_message(
            f"📋 Prova avviata: {name}", OSDSeverity.INFO, 3000
        )

    @Slot(str)
    def _on_session_ended(self, name):
        self._update_session_ui()
        self._live_view.show_osd_message(
            f"📋 Prova terminata: {name}", OSDSeverity.INFO, 3000
        )

    @Slot()
    def _on_quick_export(self, fmt: str = "pdf"):
        """
        Export rapido con formato specificato.
        Args:
            fmt: "pdf" o "csv"
        """
        self._session_controller.set_operator(self._operator_id)
        if self._calibration_engine.is_calibrated:
            self._session_controller.set_calibration_scale(
                self._calibration_engine.scale_factor
            )
        self._session_controller.quick_export(fmt=fmt)

    @Slot()
    def _on_about(self):
        from views.dialogs.about_dialog import AboutDialog
        dialog = AboutDialog(parent=self)
        dialog.exec()

    # ═══════════════════════════════════════════════════════════
    # SLOT — Aggiornamenti dati
    # ═══════════════════════════════════════════════════════════

    @Slot(object)
    def _on_measurement_updated(self, result):
        """Aggiornamento live ad ogni frame misurato (alta frequenza)."""
        pass

    @Slot()
    def _on_record_changed(self, _arg=None):
        valid = self._statistics_model.count_valid
        total = self._statistics_model.count
        if total != valid:
            self._lbl_measure_count.setText(
                f"Misure: {valid} / {total}"
            )
        else:
            self._lbl_measure_count.setText(f"Misure: {total}")
        self._status_bar_widget.update_measure_count(total)

    @Slot()
    def _on_data_cleared(self):
        self._lbl_measure_count.setText("Misure: 0")
        self._status_bar_widget.update_measure_count(0)

    @Slot(object)
    def _on_stats_for_export(self, snapshot):
        from core.statistics_model import StatisticsSnapshot
        if isinstance(snapshot, StatisticsSnapshot):
            has_data = snapshot.count_valid > 0
            self._btn_export_pdf.setEnabled(has_data)
            self._btn_export_csv.setEnabled(has_data)

    # ═══════════════════════════════════════════════════════════
    # LOGIN E AVVIO
    # ═══════════════════════════════════════════════════════════

    def show_login_and_start(self) -> bool:
        operator_id, accepted = LoginDialog.get_operator(self)
        if not accepted:
            return False
        self._operator_id = operator_id
        self._session_start = datetime.now()
        self._lbl_operator.setText(f"Operatore: {operator_id}")
        self._lbl_session_time.setText(
            f"Inizio: {self._session_start.strftime('%H:%M:%S')}"
        )
        self._status_bar_widget.update_operator(operator_id)
        self.setWindowTitle(
            f"{APP_NAME} v{APP_VERSION} — {operator_id} — "
            f"Sistema Metrologico R&D"
        )
        self.showMaximized()
        logger.info(
            f"Applicazione avviata: operatore={operator_id}"
        )
        return True

    # ═══════════════════════════════════════════════════════════
    # CHIUSURA
    # ═══════════════════════════════════════════════════════════

    def closeEvent(self, event):
        info = f"Operatore: {self._operator_id}"
        if self._session_start:
            info += (
                f"\nInizio: "
                f"{self._session_start.strftime('%H:%M:%S')}"
            )
        n = self._statistics_model.count
        if n > 0:
            info += f"\nMisure: {n}"
        if self._session_controller.has_active_session:
            info += (
                f"\n\n⚠️ Prova "
                f"'{self._session_controller.session_name}' attiva!"
            )
            info += "\nVerrà salvata automaticamente."

        reply = QMessageBox.question(
            self, "Conferma Uscita",
            f"Chiudere {APP_NAME}?\n\n{info}",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            logger.info("Chiusura applicazione")
            self._calibration_controller.cleanup()
            self._session_controller.cleanup()
            self._measurement_controller.cleanup()
            self._acquisition_controller.cleanup()
            event.accept()
        else:
            event.ignore()