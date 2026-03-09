# Ideato e Realizzato da Pierpaolo Careddu

"""
BandinaVision — Entry Point dell'applicazione.

Sequenza di avvio:
1. Inizializza QApplication con Fusion style
2. Forza una QPalette chiara (indipendente dal tema OS)
3. Carica il foglio di stile theme_industriale.qss
4. Configura logging su file + console
5. Mostra LoginDialog (obbligatorio)
6. Se login OK → mostra MainWindow
7. Se login annullato → exit

Nota critica: La QPalette DEVE essere impostata PRIMA del caricamento
del QSS e della creazione di qualsiasi widget, altrimenti l'OS theme
scuro interferisce con i colori degli input (testo bianco su bianco).
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor, QFont

from views.main_window import MainWindow


def setup_logging() -> logging.Logger:
    """Configura il sistema di logging su file rotativo e console."""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    log_filename = log_dir / f"bandinavision_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_filename, encoding='utf-8'),
            logging.StreamHandler(sys.stdout),
        ]
    )

    logger = logging.getLogger()
    logger.info("=" * 60)
    logger.info("  BandinaVision v1.0 — Advanced Optical Profiler")
    logger.info("  Ideato e Realizzato da Pierpaolo Careddu")
    logger.info("=" * 60)

    return logger


def create_light_palette() -> QPalette:
    """
    Crea una QPalette Light forzata, completamente indipendente
    dalle impostazioni del sistema operativo.

    Questa palette sovrascrive OGNI ruolo colore di Qt, garantendo
    che nessun widget erediti colori dal tema scuro dell'OS.

    Palette Metrologica Professionale:
        Sfondo finestra:  #F4F5F7  (Grigio Perla)
        Sfondo widget:    #FFFFFF  (Bianco Puro)
        Testo primario:   #1C1C1E  (Antracite)
        Testo secondario: #6B7280  (Grigio Medio)
        Accento:          #0066B3  (Blu Pirelli Istituzionale)
        Selezione:        #0066B3  con testo bianco
        Bordi:            #D1D5DB  (Grigio Chiaro)
        Disabilitato:     #9CA3AF  (Grigio Tenue)
    """
    palette = QPalette()

    # ─── Gruppo Active (stato normale) ───
    palette.setColor(QPalette.ColorRole.Window, QColor("#F4F5F7"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#1C1C1E"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#F0F1F3"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#1C1C1E"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#E5E7EB"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#1C1C1E"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#1C1C1E"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#0066B3"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#0066B3"))
    palette.setColor(QPalette.ColorRole.LinkVisited, QColor("#004A82"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9CA3AF"))
    palette.setColor(QPalette.ColorRole.Light, QColor("#FFFFFF"))
    palette.setColor(QPalette.ColorRole.Midlight, QColor("#E5E7EB"))
    palette.setColor(QPalette.ColorRole.Mid, QColor("#D1D5DB"))
    palette.setColor(QPalette.ColorRole.Dark, QColor("#6B7280"))
    palette.setColor(QPalette.ColorRole.Shadow, QColor("#374151"))

    # ─── Gruppo Disabled (widget disabilitati) ───
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor("#9CA3AF")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#9CA3AF")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#9CA3AF")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor("#F0F1F3")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor("#D1D5DB")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.HighlightedText, QColor("#9CA3AF")
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor("#F4F5F7")
    )

    return palette


def load_stylesheet(app: QApplication, filepath: str):
    """Carica il foglio di stile QSS dall'asset."""
    qss_path = Path(filepath)
    if qss_path.exists():
        with open(qss_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
        logging.info(f"Foglio di stile caricato: {qss_path}")
    else:
        logging.warning(f"File di stile non trovato: {qss_path}")


def main():
    """Entry point principale dell'applicazione."""
    logger = setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("BandinaVision")
    app.setOrganizationName("Pirelli R&D Metrologia")
    app.setApplicationVersion("1.0.0")

    # ─── STEP 1: Forza Fusion style (rendering identico su ogni OS) ───
    app.setStyle("Fusion")

    # ─── STEP 2: Forza Light Palette (PRIMA di qualsiasi widget) ───
    light_palette = create_light_palette()
    app.setPalette(light_palette)

    # ─── STEP 3: Font di default globale ───
    default_font = QFont("Segoe UI", 10)
    default_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    app.setFont(default_font)

    # ─── STEP 4: Carica QSS (sovrascrive palette dove specificato) ───
    load_stylesheet(app, "assets/styles/theme_industriale.qss")

    # ─── STEP 5: Crea MainWindow ───
    window = MainWindow()

    # ─── STEP 6: Login obbligatorio ───
    if not window.show_login_and_start():
        logger.info("Login annullato dall'utente. Uscita.")
        sys.exit(0)

    window.show()
    logger.info("MainWindow visualizzata. Applicazione pronta.")

    sys.exit(app.exec())


if __name__ == "__main__":
    main()