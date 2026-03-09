# Ideato e Realizzato da Pierpaolo Careddu

"""
MeasurementTable — Tabella professionale per visualizzazione misure.

Caratteristiche:
- QTableWidget con colonne: #, Larghezza [mm], σ [mm], Angolo [°],
  Contrasto, Scanlines, Tempo [s], Stato
- Formattazione condizionale: Verde per OK, Rosso per NOK
- Righe escluse in grigio barrato
- Menu contestuale (tasto destro): Escludi / Ripristina / Copia
- Ordinamento per colonna con click sull'header
- Scroll automatico all'ultima riga aggiunta

Light Theme: Tutti i colori sono espliciti e coerenti con la palette
metrologica chiara definita in theme_industriale.qss.
Sfondo bianco, testo antracite, accenti Blu Pirelli/Verde/Rosso.

Thread Safety: Tutti gli aggiornamenti passano via Signal/Slot
dal MeasurementController, garantendo che le modifiche alla tabella
avvengano sempre nel main thread (GUI thread).
"""

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QMenu,
    QAbstractItemView, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QSizePolicy, QApplication
)
from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import (
    QFont, QColor, QBrush, QAction, QCursor
)

from core.statistics_model import MeasurementRecord, ToleranceLimits

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# COSTANTI COLORI (Light Theme — Palette Metrologica)
# ═══════════════════════════════════════════════════════════════

class TableColors:
    """Palette colori Light Theme per la tabella."""
    # Sfondo righe
    ROW_BG_EVEN = QColor("#FFFFFF")
    ROW_BG_ODD = QColor("#F9FAFB")
    ROW_BG_SELECTED = QColor("#DBEAFE")

    # Testo
    TEXT_NORMAL = QColor("#1C1C1E")
    TEXT_SECONDARY = QColor("#6B7280")

    # Conformità
    TEXT_OK = QColor("#059669")              # Verde smeraldo
    TEXT_NOK = QColor("#DC2626")             # Rosso errore
    BG_OK = QColor(5, 150, 105, 18)         # Verde trasparente tenue
    BG_NOK = QColor(220, 38, 38, 18)        # Rosso trasparente tenue

    # Esclusi
    TEXT_EXCLUDED = QColor("#9CA3AF")
    BG_EXCLUDED = QColor("#F4F5F7")

    # Header
    HEADER_BG = QColor("#F9FAFB")
    HEADER_TEXT = QColor("#0066B3")           # Blu Pirelli
    HEADER_BORDER = QColor("#E5E7EB")

    # Griglia
    GRID_LINE = QColor("#E5E7EB")


# ═══════════════════════════════════════════════════════════════
# ITEM PERSONALIZZATO — Per ordinamento numerico corretto
# ═══════════════════════════════════════════════════════════════

class NumericTableItem(QTableWidgetItem):
    """
    QTableWidgetItem che implementa ordinamento numerico corretto.
    Qt di default ordina come stringhe → "9" > "10".
    Questa classe sovrascrive __lt__ per ordinamento float.
    """

    def __init__(self, value: float, display_format: str = "{:.3f}"):
        super().__init__(display_format.format(value))
        self._numeric_value = value
        self.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

    def __lt__(self, other):
        if isinstance(other, NumericTableItem):
            return self._numeric_value < other._numeric_value
        return super().__lt__(other)

    @property
    def numeric_value(self) -> float:
        return self._numeric_value


# ═══════════════════════════════════════════════════════════════
# WIDGET TABELLA PRINCIPALE
# ═══════════════════════════════════════════════════════════════

class MeasurementTable(QWidget):
    """
    Tabella professionale per la visualizzazione delle misure.

    Signals:
        measurement_excluded(int):  Richiesta di esclusione misura (indice)
        measurement_restored(int):  Richiesta di ripristino misura (indice)
        row_selected(int):          Indice della misura selezionata
    """

    measurement_excluded = Signal(int)
    measurement_restored = Signal(int)
    row_selected = Signal(int)

    # Definizione colonne
    COLUMNS = [
        ("#",              55,  "index"),
        ("Larghezza [mm]", 140, "width_mm"),
        ("σ [mm]",         90,  "std_mm"),
        ("Angolo [°]",     85,  "angle"),
        ("Contrasto",      80,  "contrast"),
        ("Scanlines",      70,  "scanlines"),
        ("Tempo [s]",      80,  "time"),
        ("Stato",          75,  "status"),
    ]

    def __init__(self, parent=None):
        super().__init__(parent)

        self._records: dict[int, MeasurementRecord] = {}
        self._row_index_map: dict[int, int] = {}  # row → measurement index
        self._tolerance = ToleranceLimits()
        self._auto_scroll: bool = True

        self._setup_ui()
        self._connect_signals()

    # ─── SETUP UI ──────────────────────────────────────────────

    def _setup_ui(self):
        """Costruisce l'interfaccia della tabella con Light Theme."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header con titolo e contatore
        header_frame = QFrame()
        header_frame.setFixedHeight(34)
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border-bottom: 2px solid #0066B3;
                border-radius: 0px;
            }
        """)
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(12, 4, 12, 4)

        title_label = QLabel("📊  REGISTRO MISURE")
        title_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        title_label.setStyleSheet(
            "color: #0066B3; background: transparent; border: none;"
        )
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self._lbl_count = QLabel("0 misure")
        self._lbl_count.setFont(QFont("Consolas", 9))
        self._lbl_count.setStyleSheet(
            "color: #6B7280; background: transparent; border: none;"
        )
        header_layout.addWidget(self._lbl_count)

        layout.addWidget(header_frame)

        # Tabella
        self._table = QTableWidget()
        self._table.setColumnCount(len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels([col[0] for col in self.COLUMNS])

        # Configurazione header
        header = self._table.horizontalHeader()
        header.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(True)
        header.setStretchLastSection(False)

        for i, (_, width, _) in enumerate(self.COLUMNS):
            header.resizeSection(i, width)

        # La colonna "Larghezza" si espande
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        # Configurazione tabella
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self._table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._table.setAlternatingRowColors(False)  # Gestito manualmente
        self._table.setShowGrid(True)
        self._table.setGridStyle(Qt.PenStyle.SolidLine)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(30)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._table.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu
        )
        self._table.setSortingEnabled(True)

        # Stile tabella Light Theme esplicito
        self._table.setStyleSheet("""
            QTableWidget {
                background-color: #FFFFFF;
                color: #1C1C1E;
                gridline-color: #E5E7EB;
                border: 1px solid #E5E7EB;
                border-top: none;
                border-radius: 0px;
                font-family: "Consolas", "Courier New", monospace;
                font-size: 10px;
                selection-background-color: #DBEAFE;
                selection-color: #1C1C1E;
            }
            QTableWidget::item {
                padding: 4px 8px;
                border-bottom: 1px solid #F0F1F3;
            }
            QTableWidget::item:selected {
                background-color: #DBEAFE;
                color: #1C1C1E;
            }
            QHeaderView::section {
                background-color: #F9FAFB;
                color: #374151;
                border: none;
                border-bottom: 2px solid #0066B3;
                border-right: 1px solid #E5E7EB;
                padding: 6px 4px;
                font-weight: bold;
                font-size: 9px;
            }
            QHeaderView::section:hover {
                background-color: #F0F7FF;
                color: #0066B3;
            }
            QScrollBar:vertical {
                background-color: #F4F5F7;
                width: 10px;
                border: none;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background-color: #D1D5DB;
                border-radius: 5px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #9CA3AF;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical {
                height: 0px;
            }
        """)

        layout.addWidget(self._table)

    def _connect_signals(self):
        """Collega i segnali interni."""
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.currentCellChanged.connect(self._on_cell_changed)

    # ═══════════════════════════════════════════════════════════
    # API PUBBLICA (chiamata via Signal dal Controller)
    # ═══════════════════════════════════════════════════════════

    @Slot(object)
    def add_record(self, record: MeasurementRecord):
        """
        Aggiunge una riga alla tabella per il record specificato.
        Deve essere chiamato dal main thread (GUI).
        """
        self._table.setSortingEnabled(False)

        row = self._table.rowCount()
        self._table.insertRow(row)

        self._records[record.index] = record
        self._row_index_map[row] = record.index

        self._populate_row(row, record)
        self._apply_row_style(row, record)

        self._table.setSortingEnabled(True)

        # Aggiorna contatore
        valid_count = sum(
            1 for r in self._records.values() if not r.is_excluded
        )
        self._lbl_count.setText(f"{valid_count} misure")

        # Auto-scroll all'ultima riga
        if self._auto_scroll:
            self._table.scrollToBottom()

    @Slot(int)
    def mark_excluded(self, index: int):
        """Marca una riga come esclusa (grigio barrato)."""
        row = self._find_row_for_index(index)
        if row is None:
            return

        record = self._records.get(index)
        if record:
            record.is_excluded = True
            self._apply_row_style(row, record)

        valid_count = sum(
            1 for r in self._records.values() if not r.is_excluded
        )
        self._lbl_count.setText(f"{valid_count} misure")

    @Slot(int)
    def mark_restored(self, index: int):
        """Ripristina lo stile di una riga precedentemente esclusa."""
        row = self._find_row_for_index(index)
        if row is None:
            return

        record = self._records.get(index)
        if record:
            record.is_excluded = False
            self._apply_row_style(row, record)

        valid_count = sum(
            1 for r in self._records.values() if not r.is_excluded
        )
        self._lbl_count.setText(f"{valid_count} misure")

    @Slot()
    def clear_all(self):
        """Rimuove tutte le righe dalla tabella."""
        self._table.setRowCount(0)
        self._records.clear()
        self._row_index_map.clear()
        self._lbl_count.setText("0 misure")

    def set_tolerance(self, tolerance: ToleranceLimits):
        """Aggiorna le tolleranze e riformatta tutte le righe."""
        self._tolerance = tolerance

        for row in range(self._table.rowCount()):
            index = self._row_index_map.get(row)
            if index is None:
                continue
            record = self._records.get(index)
            if record is None:
                continue

            record.is_within_tolerance = tolerance.is_within_tolerance(
                record.width_mm
            )
            self._apply_row_style(row, record)

    def set_auto_scroll(self, enabled: bool):
        """Attiva/disattiva lo scroll automatico."""
        self._auto_scroll = enabled

    # ═══════════════════════════════════════════════════════════
    # COSTRUZIONE RIGHE
    # ═══════════════════════════════════════════════════════════

    def _populate_row(self, row: int, record: MeasurementRecord):
        """Popola una riga con i dati del record."""

        # Colonna 0: Indice
        item_index = NumericTableItem(float(record.index), "{:.0f}")
        item_index.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 0, item_index)

        # Colonna 1: Larghezza [mm] — valore principale, font più grande
        item_width = NumericTableItem(record.width_mm, "{:.3f}")
        item_width.setFont(QFont("Consolas", 11, QFont.Weight.Bold))
        self._table.setItem(row, 1, item_width)

        # Colonna 2: σ [mm]
        item_std = NumericTableItem(record.width_mm_std, "{:.4f}")
        self._table.setItem(row, 2, item_std)

        # Colonna 3: Angolo [°]
        item_angle = NumericTableItem(record.angle_deg, "{:+.2f}")
        self._table.setItem(row, 3, item_angle)

        # Colonna 4: Contrasto
        item_contrast = NumericTableItem(record.contrast_ratio, "{:.1f}")
        self._table.setItem(row, 4, item_contrast)

        # Colonna 5: Scanlines
        item_scanlines = NumericTableItem(float(record.n_scanlines), "{:.0f}")
        item_scanlines.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self._table.setItem(row, 5, item_scanlines)

        # Colonna 6: Tempo [s]
        item_time = NumericTableItem(record.timestamp_s, "{:.1f}")
        self._table.setItem(row, 6, item_time)

        # Colonna 7: Stato
        if record.is_within_tolerance:
            item_status = QTableWidgetItem("✓ OK")
        else:
            item_status = QTableWidgetItem("✗ NOK")
        item_status.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item_status.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        self._table.setItem(row, 7, item_status)

    def _apply_row_style(self, row: int, record: MeasurementRecord):
        """Applica lo stile condizionale a una riga intera."""
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item is None:
                continue

            if record.is_excluded:
                # Riga esclusa: grigio con testo barrato
                item.setForeground(QBrush(TableColors.TEXT_EXCLUDED))
                item.setBackground(QBrush(TableColors.BG_EXCLUDED))
                font = item.font()
                font.setStrikeOut(True)
                item.setFont(font)

            elif record.is_within_tolerance:
                # Riga OK: valore verde, resto antracite, sfondo verde tenue
                if col == 1:
                    item.setForeground(QBrush(TableColors.TEXT_OK))
                elif col == 7:
                    item.setForeground(QBrush(TableColors.TEXT_OK))
                else:
                    item.setForeground(QBrush(TableColors.TEXT_NORMAL))

                bg = (
                    TableColors.BG_OK if row % 2 == 0
                    else QColor(5, 150, 105, 10)
                )
                item.setBackground(QBrush(bg))

                font = item.font()
                font.setStrikeOut(False)
                item.setFont(font)

            else:
                # Riga NOK: valore rosso, resto antracite, sfondo rosso tenue
                if col == 1:
                    item.setForeground(QBrush(TableColors.TEXT_NOK))
                elif col == 7:
                    item.setForeground(QBrush(TableColors.TEXT_NOK))
                else:
                    item.setForeground(QBrush(TableColors.TEXT_NORMAL))

                bg = (
                    TableColors.BG_NOK if row % 2 == 0
                    else QColor(220, 38, 38, 10)
                )
                item.setBackground(QBrush(bg))

                font = item.font()
                font.setStrikeOut(False)
                item.setFont(font)

        # Aggiorna cella Stato con icona corretta
        status_item = self._table.item(row, 7)
        if status_item:
            if record.is_excluded:
                status_item.setText("—")
                status_item.setForeground(QBrush(TableColors.TEXT_EXCLUDED))
            elif record.is_within_tolerance:
                status_item.setText("✓ OK")
                status_item.setForeground(QBrush(TableColors.TEXT_OK))
            else:
                status_item.setText("✗ NOK")
                status_item.setForeground(QBrush(TableColors.TEXT_NOK))

    # ═══════════════════════════════════════════════════════════
    # MENU CONTESTUALE
    # ═══════════════════════════════════════════════════════════

    def _show_context_menu(self, position):
        """Mostra il menu contestuale al click destro."""
        row = self._table.rowAt(position.y())
        if row < 0:
            return

        index = self._row_index_map.get(row)
        if index is None:
            return

        record = self._records.get(index)
        if record is None:
            return

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #FFFFFF;
                color: #1C1C1E;
                border: 1px solid #D1D5DB;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #F0F7FF;
                color: #0066B3;
            }
            QMenu::separator {
                height: 1px;
                background-color: #E5E7EB;
                margin: 4px 8px;
            }
        """)

        if record.is_excluded:
            act_restore = QAction("♻  Ripristina Misura", self)
            act_restore.triggered.connect(
                lambda: self.measurement_restored.emit(index)
            )
            menu.addAction(act_restore)
        else:
            act_exclude = QAction("🚫  Escludi Misura", self)
            act_exclude.triggered.connect(
                lambda: self.measurement_excluded.emit(index)
            )
            menu.addAction(act_exclude)

        menu.addSeparator()

        act_copy_value = QAction("📋  Copia Valore", self)
        act_copy_value.triggered.connect(lambda: self._copy_value(row))
        menu.addAction(act_copy_value)

        act_copy_row = QAction("📋  Copia Riga Completa", self)
        act_copy_row.triggered.connect(lambda: self._copy_row(row))
        menu.addAction(act_copy_row)

        menu.exec(QCursor.pos())

    def _copy_value(self, row: int):
        """Copia il valore della larghezza negli appunti."""
        item = self._table.item(row, 1)
        if item:
            clipboard = QApplication.clipboard()
            clipboard.setText(item.text())
            logger.debug(f"Valore copiato: {item.text()}")

    def _copy_row(self, row: int):
        """Copia tutti i dati della riga negli appunti (tab-separated)."""
        parts = []
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item:
                parts.append(item.text())
        line = "\t".join(parts)
        clipboard = QApplication.clipboard()
        clipboard.setText(line)
        logger.debug(f"Riga copiata: {line}")

    # ═══════════════════════════════════════════════════════════
    # UTILITÀ INTERNE
    # ═══════════════════════════════════════════════════════════

    def _find_row_for_index(self, index: int) -> Optional[int]:
        """Trova la riga corrispondente a un indice di misura."""
        for row, idx in self._row_index_map.items():
            if idx == index:
                return row
        return None

    @Slot(int, int, int, int)
    def _on_cell_changed(self, current_row, current_col, prev_row, prev_col):
        """Gestisce il cambio di selezione riga."""
        if current_row < 0:
            return
        index = self._row_index_map.get(current_row)
        if index is not None:
            self.row_selected.emit(index)

    def sizeHint(self) -> QSize:
        return QSize(700, 280)

    def minimumSizeHint(self) -> QSize:
        return QSize(500, 150)