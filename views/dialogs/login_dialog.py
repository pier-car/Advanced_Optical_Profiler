# Ideato e Realizzato da Pierpaolo Careddu

"""
LoginDialog — Dialog modale obbligatorio all'avvio dell'applicazione.

Funzionalità:
- L'operatore deve inserire il proprio ID/Nome prima di accedere al sistema
- Validazione input: minimo 2 caratteri, solo alfanumerici e punti
- Storico operatori recenti (salvato in file locale)
- Il dato viene passato al SessionController per la tracciabilità
- L'applicazione non si avvia se il login viene annullato

Design: Light Theme professionale — tutti i colori sono espliciti per
garantire indipendenza dal tema del sistema operativo.
"""

import json
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QComboBox, QPushButton, QFrame, QMessageBox, QSizePolicy
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QColor

# Percorso file storico operatori
OPERATORS_HISTORY_FILE = Path("data/operators_history.json")
MAX_RECENT_OPERATORS = 20


class LoginDialog(QDialog):
    """
    Dialog modale per l'identificazione dell'operatore.

    Signals:
        login_accepted(str): Emesso quando l'operatore effettua il login.
                             Porta l'ID operatore validato.
    """

    login_accepted = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._operator_id: str = ""
        self._recent_operators: list[str] = []

        self._load_recent_operators()
        self._setup_ui()
        self._connect_signals()

    # ─── SETUP UI ──────────────────────────────────────────────

    def _setup_ui(self):
        """Costruisce l'interfaccia del dialog con Light Theme forzato."""
        self.setWindowTitle("A.O.P. — Identificazione Operatore")
        self.setFixedSize(520, 440)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.CustomizeWindowHint
        )
        self.setModal(True)

        # ─── Sfondo forzato chiaro ───
        self.setStyleSheet("""
            QDialog {
                background-color: #F4F5F7;
            }
        """)

        # Layout principale
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(32, 28, 32, 24)
        main_layout.setSpacing(16)

        # ─── Header ───
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background-color: #0066B3;
                border-radius: 10px;
                padding: 0px;
            }
        """)
        header_layout = QVBoxLayout(header_frame)
        header_layout.setContentsMargins(20, 18, 20, 18)
        header_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_label = QLabel("Advanced Optical Profiler")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title_label.setStyleSheet(
            "color: #FFFFFF; background: transparent; border: none;"
        )
        header_layout.addWidget(title_label)

        subtitle_label = QLabel("Sistema Metrologico — Pirelli R&D")
        subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_label.setFont(QFont("Segoe UI", 10))
        subtitle_label.setStyleSheet(
            "color: rgba(255, 255, 255, 0.8); background: transparent; border: none;"
        )
        header_layout.addWidget(subtitle_label)

        main_layout.addWidget(header_frame)

        # ─── Istruzioni ───
        instruction_label = QLabel(
            "Identificazione obbligatoria prima dell'accesso.\n"
            "Inserire il proprio ID operatore o selezionarlo dalla lista."
        )
        instruction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        instruction_label.setFont(QFont("Segoe UI", 10))
        instruction_label.setStyleSheet("color: #6B7280; background: transparent;")
        instruction_label.setWordWrap(True)
        main_layout.addWidget(instruction_label)

        # ─── Form ───
        form_frame = QFrame()
        form_frame.setStyleSheet("""
            QFrame {
                background-color: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 8px;
            }
        """)
        form_layout = QVBoxLayout(form_frame)
        form_layout.setContentsMargins(20, 16, 20, 16)
        form_layout.setSpacing(10)

        # Label campo
        id_label = QLabel("👤  ID Operatore:")
        id_label.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        id_label.setStyleSheet(
            "color: #374151; background: transparent; border: none;"
        )
        form_layout.addWidget(id_label)

        # ComboBox editabile (dropdown + input libero)
        self._operator_combo = QComboBox()
        self._operator_combo.setEditable(True)
        self._operator_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._operator_combo.lineEdit().setPlaceholderText(
            "Es: ROSSI.M, BIANCHI.L ..."
        )
        self._operator_combo.setFont(QFont("Consolas", 13))
        self._operator_combo.setMinimumHeight(42)

        # Stile esplicito per TUTTI gli stati — nessuna ereditarietà dal tema OS
        self._operator_combo.setStyleSheet("""
            QComboBox {
                background-color: #FFFFFF;
                color: #1C1C1E;
                border: 2px solid #D1D5DB;
                border-radius: 6px;
                padding: 6px 12px;
                font-family: "Consolas";
                font-size: 13px;
            }
            QComboBox:focus {
                border-color: #0066B3;
            }
            QComboBox::drop-down {
                border: none;
                border-left: 1px solid #E5E7EB;
                width: 32px;
                background-color: #F9FAFB;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
            }
            QComboBox QAbstractItemView {
                background-color: #FFFFFF;
                color: #1C1C1E;
                selection-background-color: #DBEAFE;
                selection-color: #1C1C1E;
                border: 1px solid #D1D5DB;
                border-radius: 4px;
                font-size: 12px;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                padding: 8px 12px;
                min-height: 28px;
            }
            QComboBox QAbstractItemView::item:hover {
                background-color: #F0F7FF;
            }
            QComboBox QLineEdit {
                background-color: #FFFFFF;
                color: #1C1C1E;
                border: none;
                padding: 0px;
                selection-background-color: #DBEAFE;
                selection-color: #1C1C1E;
            }
        """)

        # Forza esplicitamente il colore del testo sul QLineEdit interno
        line_edit = self._operator_combo.lineEdit()
        line_edit.setStyleSheet("""
            QLineEdit {
                background-color: #FFFFFF;
                color: #1C1C1E;
                border: none;
                padding: 0px;
                selection-background-color: #DBEAFE;
                selection-color: #1C1C1E;
            }
        """)

        # Popola con operatori recenti
        if self._recent_operators:
            self._operator_combo.addItems(self._recent_operators)
            self._operator_combo.setCurrentIndex(-1)  # Nessuna selezione iniziale

        form_layout.addWidget(self._operator_combo)

        # Hint validazione
        self._validation_label = QLabel("")
        self._validation_label.setFont(QFont("Segoe UI", 9))
        self._validation_label.setStyleSheet(
            "color: #6B7280; background: transparent; border: none;"
        )
        self._validation_label.setMinimumHeight(20)
        form_layout.addWidget(self._validation_label)

        main_layout.addWidget(form_frame)

        # ─── Pulsanti ───
        main_layout.addSpacing(4)
        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)

        self._btn_cancel = QPushButton("  Esci")
        self._btn_cancel.setFont(QFont("Segoe UI", 11))
        self._btn_cancel.setMinimumHeight(44)
        self._btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_cancel.setStyleSheet("""
            QPushButton {
                background-color: #FFFFFF;
                color: #6B7280;
                border: 1px solid #D1D5DB;
                border-radius: 8px;
                padding: 10px 24px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #F9FAFB;
                color: #374151;
                border-color: #9CA3AF;
            }
            QPushButton:pressed {
                background-color: #F0F1F3;
            }
        """)
        button_layout.addWidget(self._btn_cancel)

        self._btn_login = QPushButton("  Accedi  →")
        self._btn_login.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        self._btn_login.setMinimumHeight(44)
        self._btn_login.setDefault(True)
        self._btn_login.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_login.setStyleSheet("""
            QPushButton {
                background-color: #0066B3;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                padding: 10px 32px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: #004A82;
            }
            QPushButton:pressed {
                background-color: #003366;
            }
            QPushButton:disabled {
                background-color: #D1D5DB;
                color: #9CA3AF;
            }
        """)
        button_layout.addWidget(self._btn_login)

        main_layout.addLayout(button_layout)

        # ─── Footer ───
        footer_label = QLabel(
            f"v1.0 — Ideato e Realizzato da Pierpaolo Careddu — "
            f"{datetime.now().strftime('%Y-%m-%d')}"
        )
        footer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer_label.setFont(QFont("Segoe UI", 8))
        footer_label.setStyleSheet("color: #9CA3AF; background: transparent;")
        main_layout.addWidget(footer_label)

        # Stato iniziale
        self._update_validation()

    # ─── SIGNAL/SLOT ───────────────────────────────────────────

    def _connect_signals(self):
        """Collega i segnali ai rispettivi slot."""
        self._operator_combo.lineEdit().textChanged.connect(self._update_validation)
        self._operator_combo.lineEdit().returnPressed.connect(self._on_login_clicked)
        self._btn_login.clicked.connect(self._on_login_clicked)
        self._btn_cancel.clicked.connect(self._on_cancel_clicked)

    def _update_validation(self):
        """Aggiorna lo stato di validazione in tempo reale."""
        text = self._operator_combo.currentText().strip()
        is_valid = self._validate_operator_id(text)

        self._btn_login.setEnabled(is_valid)

        if len(text) == 0:
            self._validation_label.setText("")
            self._validation_label.setStyleSheet(
                "color: #6B7280; background: transparent; border: none;"
            )
        elif is_valid:
            self._validation_label.setText("✓  ID valido")
            self._validation_label.setStyleSheet(
                "color: #059669; background: transparent; border: none; "
                "font-weight: bold;"
            )
        else:
            self._validation_label.setText(
                "Minimo 2 caratteri. Solo lettere, numeri, punti e underscore."
            )
            self._validation_label.setStyleSheet(
                "color: #DC2626; background: transparent; border: none;"
            )

    def _validate_operator_id(self, text: str) -> bool:
        """
        Valida l'ID operatore.
        Regole: minimo 2 caratteri, solo alfanumerici, punti e underscore.
        """
        if len(text) < 2:
            return False
        allowed_chars = set(
            "abcdefghijklmnopqrstuvwxyz"
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            "0123456789._"
        )
        return all(c in allowed_chars for c in text)

    def _on_login_clicked(self):
        """Gestisce il click su Accedi."""
        text = self._operator_combo.currentText().strip().upper()

        if not self._validate_operator_id(text):
            return

        self._operator_id = text
        self._save_operator_to_history(text)
        self.login_accepted.emit(text)
        self.accept()

    def _on_cancel_clicked(self):
        """Gestisce il click su Esci — chiude l'applicazione."""
        reply = QMessageBox.question(
            self,
            "Conferma Uscita",
            "Uscire dall'applicazione?\nNessuna sessione verrà avviata.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.reject()

    # ─── PERSISTENZA OPERATORI RECENTI ─────────────────────────

    def _load_recent_operators(self):
        """Carica la lista degli operatori recenti dal file JSON."""
        try:
            if OPERATORS_HISTORY_FILE.exists():
                with open(OPERATORS_HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._recent_operators = data.get("recent_operators", [])
        except (json.JSONDecodeError, IOError, KeyError):
            self._recent_operators = []

    def _save_operator_to_history(self, operator_id: str):
        """Salva l'operatore nella lista recenti (in cima, senza duplicati)."""
        if operator_id in self._recent_operators:
            self._recent_operators.remove(operator_id)
        self._recent_operators.insert(0, operator_id)
        self._recent_operators = self._recent_operators[:MAX_RECENT_OPERATORS]

        try:
            OPERATORS_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(OPERATORS_HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(
                    {
                        "recent_operators": self._recent_operators,
                        "last_login": datetime.now().isoformat(),
                    },
                    f,
                    indent=2,
                    ensure_ascii=False
                )
        except IOError:
            pass

    # ─── API PUBBLICA ──────────────────────────────────────────

    @property
    def operator_id(self) -> str:
        """Restituisce l'ID operatore inserito."""
        return self._operator_id

    @staticmethod
    def get_operator(parent=None) -> tuple[str, bool]:
        """
        Metodo statico di convenienza. Mostra il dialog e restituisce
        (operator_id, accepted).
        """
        dialog = LoginDialog(parent)
        result = dialog.exec()
        accepted = result == QDialog.DialogCode.Accepted
        return dialog.operator_id, accepted