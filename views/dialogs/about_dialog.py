# Ideato e Realizzato da Pierpaolo Careddu

"""
AboutDialog — Informazioni sull'applicazione.

Credits, versione, descrizione del sistema.
Light Theme compatibile con theme_industriale.qss.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont, QPixmap

from config import APP_NAME, APP_CODENAME, APP_VERSION, APP_AUTHOR, APP_ORG


class AboutDialog(QDialog):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Informazioni — {APP_NAME}")
        self.setFixedSize(460, 420)
        self.setModal(True)
        self.setStyleSheet("QDialog{background-color:#F4F5F7;}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 24)
        layout.setSpacing(12)

        # Logo / Icona
        icon_label = QLabel("🔬")
        icon_label.setFont(QFont("Segoe UI", 48))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("background:transparent;")
        layout.addWidget(icon_label)

        # Nome applicazione
        name_label = QLabel(APP_NAME)
        name_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name_label.setStyleSheet("color:#0066B3;background:transparent;")
        layout.addWidget(name_label)

        # Codename e versione
        ver_label = QLabel(f"{APP_CODENAME} — Versione {APP_VERSION}")
        ver_label.setFont(QFont("Segoe UI", 11))
        ver_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ver_label.setStyleSheet("color:#6B7280;background:transparent;")
        layout.addWidget(ver_label)

        layout.addSpacing(8)

        # Separatore
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background:#E5E7EB;max-height:1px;")
        layout.addWidget(sep)

        layout.addSpacing(8)

        # Descrizione
        desc = QLabel(
            "Sistema metrologico ottico per il controllo dimensionale\n"
            "di bandine in gomma mediante profilometria avanzata.\n\n"
            "Funzionalità principali:\n"
            "• Acquisizione video in tempo reale\n"
            "• Misurazione automatica con stabilizzazione temporale\n"
            "• Calibrazione ottica con compensazione distorsioni\n"
            "• Analisi statistica SPC (Cp, Cpk)\n"
            "• Export report PDF e CSV"
        )
        desc.setFont(QFont("Segoe UI", 9))
        desc.setAlignment(Qt.AlignmentFlag.AlignLeft)
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#374151;background:transparent;")
        layout.addWidget(desc)

        layout.addSpacing(8)

        # Separatore
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("background:#E5E7EB;max-height:1px;")
        layout.addWidget(sep2)

        layout.addSpacing(4)

        # Credits
        credits_label = QLabel(
            f"Ideato e Realizzato da {APP_AUTHOR}"
        )
        credits_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        credits_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits_label.setStyleSheet("color:#0066B3;background:transparent;")
        layout.addWidget(credits_label)

        org_label = QLabel(f"{APP_ORG} — Dipartimento R&D")
        org_label.setFont(QFont("Segoe UI", 9))
        org_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        org_label.setStyleSheet("color:#6B7280;background:transparent;")
        layout.addWidget(org_label)

        layout.addSpacing(12)

        # Pulsante chiudi
        btn_close = QPushButton("Chiudi")
        btn_close.setMinimumHeight(34)
        btn_close.setMinimumWidth(100)
        btn_close.clicked.connect(self.accept)
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def sizeHint(self):
        return QSize(460, 420)