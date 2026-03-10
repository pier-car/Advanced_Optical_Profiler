# 🔬 Advanced Optical Profiler — BandinaVision v1.0

> **Sistema metrologico ottico per il controllo dimensionale sub-pixel di bandine industriali.**
> Sviluppato per **Pirelli R&D Metrologia** — Ideato e Realizzato da **Pierpaolo Careddu**

---

## 📋 Indice

- [Panoramica](#-panoramica)
- [Funzionalità Principali](#-funzionalità-principali)
- [Architettura del Sistema](#-architettura-del-sistema)
- [Stack Tecnologico](#-stack-tecnologico)
- [Struttura del Progetto](#-struttura-del-progetto)
- [Pipeline Metrologica](#-pipeline-metrologica)
- [Installazione](#-installazione)
- [Avvio Rapido](#-avvio-rapido)
- [Calibrazione](#-calibrazione)
- [Modalità di Misura](#-modalità-di-misura)
- [Gestione Sessioni ed Export](#-gestione-sessioni-ed-export)
- [Test e Validazione](#-test-e-validazione)
- [Moduli Core — Review Tecnica](#-moduli-core--review-tecnica)
- [Problemi Noti e Roadmap](#-problemi-noti-e-roadmap)
- [Hardware di Riferimento](#-hardware-di-riferimento)

---

## 🔭 Panoramica

**BandinaVision** è un'applicazione desktop per la misura dimensionale di precisione di **bandine** (strisce di materiale gomma/composito) in ambiente industriale. L'applicazione acquisisce immagini da una telecamera industriale **Basler Ace2** e applica una pipeline algoritmica di computer vision per misurare la larghezza della bandina con precisione **sub-pixel**, convertendo il risultato in millimetri grazie a una calibrazione dedicata.

### 🎯 Prestazioni Target

| Parametro | Valore |
|---|---|
| Precisione | ±0.02 mm (con setup Basler Ace2 + Edmund 16mm + EuroBrite) |
| Risoluzione sub-pixel | < 0.5 px di errore medio |
| Frequenza acquisizione | fino a 45 fps (sensore Sony IMX546) |
| Range angolare bandina | ±30° rispetto all'asse orizzontale |
| Formato immagine | Greyscale 8-bit, 3840×2748 px |

---

## ✨ Funzionalità Principali

### 📸 Acquisizione Video
- Controllo completo della telecamera Basler Ace2 via **pypylon**
- Regolazione in tempo reale di **esposizione** (100 μs – 100 ms) e **guadagno** (0–24 dB)
- Modalità **simulata** integrata per sviluppo/test senza hardware fisico
- Buffer pre-allocati per l'acquisizione ad alta frequenza senza pressione sul garbage collector
- Zoom e pan interattivi sul live view

### 📐 Misura Automatica
- Pipeline a 8 step con precisione sub-pixel (vedere [sezione dedicata](#-pipeline-metrologica))
- **20 scanline perpendicolari** distribuite lungo tutta la bandina
- Fitting dei bordi con **RANSAC** robusto agli outlier
- Localizzazione sub-pixel via **fit parabolico del gradiente**
- Calcolo della larghezza ortogonale corretto per qualsiasi angolo di inclinazione

### 🎯 Auto-Trigger (StabilityDetector)
- Rileva automaticamente la convergenza temporale delle misure
- Configurable: buffer di 12 frame, soglia 0.05 mm, 8 frame stabili richiesti
- Cooldown di 2 secondi tra catture automatiche successive

### 📏 Misura Manuale
- Strumento point-and-click per misure a due punti sull'immagine live
- Conversione automatica pixel → millimetri con la scala di calibrazione

### 📊 Statistiche Real-Time
- Aggiornamento incrementale con **algoritmo di Welford** O(1) per ogni misura
- Media (μ), Deviazione Standard (σ), Min, Max, Range, Mediana
- **Indici di capacità di processo Cp e Cpk** con tolleranze configurabili
- Conteggio OK/NOK con evidenziazione visiva in tabella
- Thread-safe tramite `QMutex`

### 📋 Sessioni di Prova
- Ciclo di vita completo: Crea → Misura → Finalizza → Esporta
- Tolleranze configurabili (Nominale, USL, LSL) per classificazione OK/NOK
- Salvataggio automatico in formato **JSON** con tutti i metadati di tracciabilità
- Possibilità di escludere singole misure (undo) senza perdita dei dati

### 📄 Export Report
- **PDF** professionale con ReportLab: intestazione, tabella misure, statistiche, footer
- **CSV** compatibile Excel (delimitatore `;`, decimale `,`, encoding UTF-8 BOM)
- Righe NOK evidenziate in rosso nel PDF

---

## 🏗️ Architettura del Sistema

Il progetto segue un'architettura **MVC (Model-View-Controller)** con comunicazione basata sul pattern **Signal/Slot** di Qt.

```
┌─────────────────────────────────────────────────────────────┐
│                        MAIN THREAD                          │
│                                                             │
│  ┌───────────────┐    ┌──────────────────┐    ┌─────────┐  │
│  │ MainWindow    │    │   Controllers    │    │  Views  │  │
│  │ (orchestrat.) │◄──►│ - Acquisition    │◄──►│ Widgets │  │
│  │               │    │ - Measurement    │    │ Dialogs │  │
│  │               │    │ - Session        │    │         │  │
│  │               │    │ - Calibration    │    │         │  │
│  └───────────────┘    └──────────────────┘    └─────────┘  │
│          │                    │                             │
│          ▼                    ▼                             │
│  ┌───────────────┐    ┌──────────────────┐                 │
│  │  Core Engines │    │     Models       │                 │
│  │ - Metrology   │    │ - StatisticsModel│                 │
│  │ - Calibration │    │ - TestSession    │                 │
│  │ - ImageProc.  │    │                  │                 │
│  └───────────────┘    └──────────────────┘                 │
└─────────────────────────────────────────────────────────────┘
          ▲
          │ QThread (Signal/Slot)
          │
┌─────────────────────┐
│   GRAB WORKER       │
│ - Camera (Basler)   │
│ - Frame grab loop   │
│ - MetrologyEngine   │
│ - StabilityDetect.  │
└─────────────────────┘
```

### Flusso Dati Principale

```
CameraManager.grab_frame()
       │
       ▼
GrabWorker (QThread)
       │
       ├─[non calibrato]──► frame_ready Signal ──► LiveViewWidget (raw)
       │
       └─[calibrato + auto ON]──► MetrologyEngine.measure()
                                        │
                                        ├──► measurement_completed ──► LiveViewWidget (overlay)
                                        │
                                        └──► StabilityDetector.feed()
                                                    │
                                                    └─[stabile]──► measure_captured
                                                                        │
                                                                        ├──► MeasurementController
                                                                        │       └──► StatisticsModel
                                                                        │               └──► statistics_updated ──► StatisticsPanel
                                                                        │
                                                                        └──► SessionController
                                                                                └──► TestSession.add_record()
```

---

## 🛠️ Stack Tecnologico

| Categoria | Libreria | Versione | Utilizzo |
|---|---|---|---|
| **GUI** | PySide6 | 6.10.2 | Framework UI Qt, Signal/Slot, QThread |
| **Vision** | OpenCV (contrib) | 4.13.0 | Preprocessing, segmentazione, morfologia |
| **Algebra** | NumPy | 2.4.2 | Operazioni vettorizzate su array |
| **Scientific** | SciPy | 1.17.1 | Interpolazione cubica (`map_coordinates`) |
| **ML/Fitting** | scikit-learn | 1.8.0 | `RANSACRegressor` per fitting robusto bordi |
| **Camera** | pypylon | — | SDK Basler Pylon (opzionale) |
| **Report** | ReportLab | 4.4.10 | Generazione PDF professionali |
| **Persistenza** | PyYAML | 6.0.3 | Calibrazione su file YAML |
| **Test** | pytest | 9.0.2 | Suite di test automatici |
| **Copertura** | pytest-cov | 7.0.0 | Coverage report |

---

## 📁 Struttura del Progetto

```
Advanced_Optical_Profiler/
│
├── 📄 main.py                   # Entry point — setup Qt, palette, logging, login
├── ⚙️  config.py                 # Costanti globali centralizzate (zero magic numbers)
├── 📋 requirements.txt          # Dipendenze Python
├── 🧪 conftest.py               # Fixture pytest condivise
├── 📝 NOTE.txt                  # Report diagnostico interno
│
├── 🧠 core/                     # Motori algoritmici
│   ├── metrology_engine.py      # Pipeline misura sub-pixel (8 step)
│   ├── calibration_engine.py    # Calibrazione px↔mm con distorsione radiale
│   ├── camera_manager.py        # Driver Basler Ace2 + simulatore
│   ├── image_processor.py       # Pipeline preprocessing configurabile
│   ├── statistics_model.py      # Statistiche real-time (Welford) + Cp/Cpk
│   ├── test_session.py          # Modello dati sessione di prova
│   └── report_generator.py      # Export PDF e CSV
│
├── 🎮 controllers/              # Business logic (pattern MVC)
│   ├── acquisition_controller.py  # GrabWorker + StabilityDetector + Calibration Gate
│   ├── measurement_controller.py  # Flusso misure → Model → View
│   ├── session_controller.py      # Ciclo di vita sessione + export
│   └── calibration_controller.py  # Wizard calibrazione + propagazione
│
├── 🖼️  views/                    # Interfaccia grafica PySide6
│   ├── main_window.py           # Finestra principale (layout + connessioni)
│   ├── widgets/                 # Widget riusabili
│   │   ├── live_view_widget.py  # Vista live con overlay, zoom, pan
│   │   ├── measurement_table.py # Tabella misure con colori OK/NOK
│   │   ├── statistics_panel.py  # Pannello statistiche real-time
│   │   └── ...
│   └── dialogs/                 # Dialog modali
│       ├── export_dialog.py     # Scelta formato export PDF/CSV
│       └── ...
│
├── 🔧 utils/                    # Utility trasversali
│   ├── threading_utils.py       # MainThreadInvoker, Debouncer, Throttle
│   ├── math_utils.py            # Statistiche, Cp/Cpk, geometria 2D
│   ├── image_utils.py           # Helper immagini
│   └── validators.py            # Validatori input (TODO)
│
├── 🧪 tests/                    # Suite di test automatici
│   ├── synthetic_generator.py   # Generatore immagini sintetiche con ground truth
│   ├── test_metrology_engine.py # Validazione pipeline metrologica (6 scenari)
│   ├── test_calibration.py      # Test CalibrationEngine
│   └── test_statistics_model.py # Test StatisticsModel + Welford
│
└── 🎨 assets/
    └── styles/
        └── theme_industriale.qss  # Tema Qt professionale (Blu Pirelli)
```

---

## 🔬 Pipeline Metrologica

Il cuore del sistema è il `MetrologyEngine` che implementa una pipeline a **8 step** per la misura sub-pixel della larghezza della bandina.

```
Frame RAW (greyscale 8-bit)
        │
        ▼ Step 1: PREPROCESSING
   Smoothing Gaussiano (σ=1.0, kernel 5×5)
   + crop ROI opzionale
        │
        ▼ Step 2: SEGMENTAZIONE
   Binarizzazione Otsu (adattiva, invariante all'illuminazione)
   + pulizia morfologica (Close×2 + Open×1, kernel 5×5)
        │
        ▼ Step 3: ESTRAZIONE BORDI
   Orientamento adattivo: orizzontale (min/max per colonna)
   o verticale (min/max per riga)
   Implementazione vettorizzata: O(N log N), zero loop Python
        │
        ▼ Step 4: FITTING RANSAC
   RANSACRegressor su punti bordo superiore e inferiore
   (threshold=3 px, min_samples=50%, max_trials=1000)
   Angolo medio θ = (θ_top + θ_bot) / 2
        │
        ▼ Step 5: PROFILI PERPENDICOLARI
   20 scanline distribuite lungo la bandina
   Interpolazione cubica (scipy.ndimage.map_coordinates)
   nella direzione n̂ = (sin θ, -cos θ)
        │
        ▼ Step 6: LOCALIZZAZIONE SUB-PIXEL
   Fit parabolico su 5 punti attorno al picco del |gradiente|
   (il bordo defocato ~ erf → derivata ~ Gaussiana → picco parabolico)
   R² come indicatore qualità del fit
        │
        ▼ Step 7: LARGHEZZA ORTOGONALE
   width = |dot(d_vec, n̂)|   ← PROIEZIONE, non distanza euclidea
   Correzione distorsione radiale k1 applicata per ogni scanline
        │
        ▼ Step 8: AGGREGAZIONE
   Filtraggio outlier MAD (3σ robusti)
   Media, σ (ddof=1), contrasto da maschera binaria
   Valutazione qualità: contrasto, angolo, uniformità larghezza
        │
        ▼
   MeasurementResult
   (width_mm_mean ± width_mm_std, status, warnings)
```

### 🧮 Dettagli Algoritmici Notevoli

**Larghezza Ortogonale (Fix v1.1):**
La larghezza reale di una bandina inclinata non è la distanza euclidea tra i due bordi, ma la sua proiezione sulla direzione normale:
```
d_vec = edge_bottom_abs − edge_top_abs
width = |d_vec · n̂|    dove n̂ = (sin θ, −cos θ)
```
Questo è esatto per qualsiasi angolo θ, eliminando l'errore sistematico della versione precedente.

**Contrasto dalla Maschera (Fix v1.1):**
Invece di usare percentili globali (che falliscono quando la bandina occupa >50% del frame), il contrasto viene calcolato separando i pixel foreground (bandina) e background dalla maschera Otsu già calcolata:
```
contrast_ratio = mean(bg_pixels) / mean(fg_pixels)
```

**Filtraggio Outlier con MAD:**
```
σ_robusto = 1.4826 × median(|x_i − median(x)|)
inlier se |x_i − median| < 3 × σ_robusto
```

---

## 📦 Installazione

### Prerequisiti
- **Python** 3.11 o superiore
- **Windows 10/11** (sviluppato e testato su Windows; Linux compatibile senza pypylon)
- **Pylon SDK** (Basler) installato a livello di sistema (solo per camera reale)

### Setup Ambiente

```bash
# 1. Clona il repository
git clone https://github.com/pier-car/Advanced_Optical_Profiler.git
cd Advanced_Optical_Profiler

# 2. Crea un ambiente virtuale
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/macOS
source venv/bin/activate

# 3. Installa le dipendenze
# NOTA: il requirements.txt è in UTF-16 — convertirlo prima se pip si rifiuta
pip install -r requirements.txt

# Oppure installa manualmente le dipendenze principali:
pip install PySide6 opencv-contrib-python numpy scipy scikit-learn
pip install reportlab PyYAML pypylon pytest pytest-cov
```

> ⚠️ **Nota `requirements.txt`:** Il file è salvato in encoding UTF-16 che può causare problemi con `pip` su alcuni sistemi. In caso di errore, aprire il file con un editor di testo e salvarlo in **UTF-8** prima di eseguire l'installazione.

### Modalità Senza Camera Fisica

Per sviluppare o testare senza telecamera Basler collegata, impostare in `config.py`:

```python
CAMERA_SIMULATE = True
```

Il simulatore genera frame sintetici con una bandina animata (oscillazione + rumore) a 30 fps, riproducendo fedelmente le caratteristiche del sensore Sony IMX546.

---

## 🚀 Avvio Rapido

```bash
python main.py
```

**Sequenza di avvio:**
1. Inizializzazione Qt (Fusion Style + Light Palette forzata)
2. Caricamento tema `assets/styles/theme_industriale.qss`
3. Configurazione logging su file `logs/bandinavision_YYYYMMDD_HHMMSS.log`
4. Finestra di **Login** — inserire il nome operatore (obbligatorio)
5. **MainWindow** — se esiste una calibrazione precedente, viene caricata automaticamente

---

## 🎯 Calibrazione

La calibrazione stabilisce il fattore di conversione **pixel → millimetri** e deve essere eseguita prima di qualsiasi misura metrologica.

### Procedura di Calibrazione

1. Posizionare un **campione di riferimento** a distanza nota nel campo visivo (es. target USAF 1951, o distanziatore calibrato da 25 mm)
2. Premere **🎯 Nuova Calibrazione** nella toolbar
3. Nel wizard, attivare il live view e premere **📸 Cattura Frame**
4. Cliccare il **punto A** sul campione (crosshair ciano)
5. Cliccare il **punto B** sul campione (crosshair verde)
6. Inserire la **distanza reale in mm**
7. Premere **✓ Salva Calibrazione**

### Dati Calibrazione

Il sistema salva la calibrazione in `data/calibration/calibration.yaml`:

```yaml
scale_factor_mm_per_px: 0.018230
k1_radial: 0.0
cx: 1920.0
cy: 1374.0
calibration_date: '2026-03-01T09:30:00'
notes: ''
```

- **Scadenza:** 30 giorni (configurabile in `config.py` → `CALIBRATION_EXPIRY_DAYS`)
- **Correzione distorsione radiale k1:** opzionale, per setup con lenti grandangolari
- Alla scadenza l'applicazione emette un warning, le misure continuano ma con segnalazione

---

## 📐 Modalità di Misura

### 🤖 Misura Automatica Continua

Attivare il toggle **▶ Misura Auto** nella toolbar. Il `GrabWorker` analizza ogni frame acquisito e invia il risultato all'overlay in tempo reale.

### ⚡ Auto-Trigger

Attivare il toggle **🔁 Auto-Trigger**. Lo `StabilityDetector` registra automaticamente una misura quando il processo è stabile:

```
Buffer [W₁, W₂, ..., W₁₂] → delta = max − min
Se delta < 0.05 mm per 8 frame consecutivi → CAPTURE
Cooldown: 2 secondi tra catture
```

### 📸 Misura Singola

Premere **📸 Misura Singola** per catturare manualmente una singola misura sul frame corrente.

### 📏 Misura Manuale

Attivare **📐 Misura Manuale** → cliccare due punti sull'immagine live per misurare qualsiasi distanza. La conversione px→mm utilizza la scala di calibrazione corrente.

---

## 💾 Gestione Sessioni ed Export

### Avviare una Sessione

Premere **📋 Nuova Sessione** per aprire il dialog di configurazione:

- **Nome sessione** (obbligatorio): es. `Lotto_2026_03_01`
- **Valore nominale** (mm): larghezza attesa della bandina
- **Tolleranza superiore (USL)** e **inferiore (LSL)** in mm
- **Note** opzionali

Una sessione attiva registra automaticamente tutte le misure catturate e le classifica OK/NOK rispetto alle tolleranze.

### Terminare e Esportare

Premere **⏹ Termina Sessione** → finestra riepilogo → scelta formato export.

**Export CSV:**
```
Advanced Optical Profiler — Report Misure
Operatore: MARIO_ROSSI ; Data: 2026-03-01 ; ...
Calibrazione: 0.018230 mm/px

# ; Timestamp ; Larghezza [mm] ; sigma [mm] ; Angolo [deg] ; Stato ; N scanlines
1 ; 2026-03-01 09:31:05 ; 5,123 ; 0,0041 ; 0,3 ; OK ; 18
...

STATISTICHE AGGREGATE
N valide ; 47
Media [mm] ; 5,127
...
```

**Export PDF:** Report professionale A4 con intestazione blu Pirelli, tabella misure con righe NOK in rosso, sezione statistiche con Cp/Cpk.

---

## 🧪 Test e Validazione

Il progetto include una suite di test con **immagini sintetiche a ground truth noto** per validare la correttezza algoritmica indipendentemente dall'hardware.

### Eseguire i Test

```bash
# Tutti i test
pytest tests/ -v

# Solo MetrologyEngine
pytest tests/test_metrology_engine.py -v

# Con copertura
pytest tests/ --cov=core --cov-report=html
```

### Scenari di Test — MetrologyEngine

| Test | Descrizione | Criterio di Accettazione |
|---|---|---|
| `test_basic_accuracy` | Bandina orizzontale, rumore nominale | Errore medio < 0.5 px |
| `test_rotation_robustness` | Angoli da 0° a 15° | Errore max < 1.5 px |
| `test_noise_robustness` | Rumore σ = 10 DN | Errore < 3.0 px |
| `test_blur_robustness` | PSF da 1.0 a 5.0 px | Errore < 2.0 px |
| `test_width_linearity` | Larghezze da 200 a 1200 px | R² > 0.999 |
| `test_minimum_scanlines` | Verifica soglia 3 scanline valide | `MeasurementError` se < 3 |

### Generatore di Immagini Sintetiche

Il `SyntheticGenerator` simula fedelmente il setup fisico:
- Sfondo bianco (retroilluminazione EuroBrite ~240 DN)
- Bandina nera (gomma ~10 DN)
- Transizione bordo modellata come **erf** (integrale della Gaussiana — PSF lente)
- Shot noise del sensore Sony IMX546
- Rotazione arbitraria con coordinate polari ruotate

---

## 📚 Moduli Core — Review Tecnica

### `core/metrology_engine.py` ⭐⭐⭐⭐⭐

Il modulo più solido del progetto. Implementazione corretta e performante della pipeline metrologica. Punti di forza:

- Estrazione bordi **O(N log N)** vettorizzata con `np.minimum.reduceat` (zero loop Python)
- `PipelineConfig` come dataclass separata → configurabilità senza toccare il codice
- Lock `threading.Lock` in `set_calibration()` per thread safety
- Filtraggio outlier con **MAD** (robusto, appropriato per metrologia)
- Localizzazione sub-pixel con R² come indicatore di qualità del fit

> ⚠️ **Problema noto:** In `measure()`, il lock viene acquisito con `with self._calibration_lock: pass` — lo acquisisce e lo **rilascia immediatamente** senza proteggere la lettura degli attributi. Il fix corretto è acquisire uno snapshot atomico dei parametri all'interno del lock prima di usarli nella pipeline.

### `core/calibration_engine.py` ⭐⭐⭐⭐

Calibrazione lineare da distanza nota + correzione distorsione radiale k1. Persistenza YAML con validazione temporale (scadenza 30 giorni). Calcolo k1 via regressione su griglia di punti con soluzione ai minimi quadrati.

### `core/statistics_model.py` ⭐⭐⭐⭐⭐

Implementazione esemplare del pattern **Observer** Qt + **algoritmo di Welford** per aggiornamento O(1). Thread-safe via `QMutex`. Calcolo corretto di Cp/Cpk con gestione edge cases (un solo limite di tolleranza configurato). Snapshot immutabile emesso via Signal per la GUI.

### `core/camera_manager.py` ⭐⭐⭐⭐

Wrapper pulito per pypylon con import condizionale (funziona senza Pylon SDK). Simulatore ottimizzato con buffer pre-allocati e `np.random.Generator` moderno. Controllo esposizione e guadagno con clamp automatico nei range validi.

### `core/image_processor.py` ⭐⭐⭐⭐

Pipeline di preprocessing configurabile (ROI, grayscale, CLAHE, Gaussian, Median, B/C, Unsharp Mask) con ottimizzazione **zero-copy fast path**: il frame viene copiato solo prima della prima operazione distruttiva. Proprietà `is_identity` per saltare l'intera pipeline se nessuno step è attivo.

> ⚠️ **Problema noto:** Il modulo è completo ma **non è integrato nel flusso di acquisizione**. Nessun controller lo importa o lo usa. È funzionalmente codice morto.

### `core/test_session.py` ⭐⭐⭐⭐

Modello dati completo per il ciclo di vita di una sessione. Serializzazione JSON con gestione di `float('inf')` per le tolleranze illimitate. Calcolo Cp/Cpk alla finalizzazione. Metodo `remove_last_record()` per undo presente ma non collegato alla UI.

### `controllers/acquisition_controller.py` ⭐⭐⭐⭐

Implementa il **Calibration Gate**: senza calibrazione, solo video raw (nessuna misura). Il `GrabWorker` (QThread) gestisce il loop di acquisizione ad alta frequenza con bypass automatico quando la misura automatica è disattivata. `StabilityDetector` con buffer circolare e cooldown.

### `utils/threading_utils.py` ⭐⭐⭐⭐

Utility ben progettate: `MainThreadInvoker` (pattern comando via Signal per eseguire codice nel main thread da thread secondari), `Debouncer` (anti-rimbalzo per slider Qt), `Throttle` (limitatore frequenza). Tutte con gestione eccezioni e logging.

---

## 🐛 Problemi Noti e Roadmap

### 🔴 Critici (da risolvere prima del collaudo)

| ID | Problema | File | Effort |
|---|---|---|---|
| P0.1 | Verificare esistenza `MeasurementController.set_tolerance()` | `controllers/measurement_controller.py` | 15 min |
| P0.2 | Verificare firma segnale `measure_captured` (deve emettere `MeasurementResult`) | `controllers/acquisition_controller.py` | 10 min |
| P0.3 | Verificare esistenza `MeasurementController.activate()` | `controllers/measurement_controller.py` | 5 min |
| P0.4 | Connettere `statistics_model.statistics_updated` → `statistics_panel.update_statistics()` | `views/main_window.py` | 10 min |
| P0.5 | Propagare `calibration_scale` al `SessionController` all'avvio se calibrazione pre-esistente | `views/main_window.py` | 2 min |
| P0.6 | Passare `title=session_name` alla chiamata `export_pdf()` | `controllers/session_controller.py` | 2 min |
| P0.7 | Fix race condition in `MetrologyEngine.measure()`: il lock acquisisce uno snapshot atomico invece di `pass` | `core/metrology_engine.py` | 20 min |

**Fix P0.7 — esempio corretto:**
```python
# ATTUALE (non protegge nulla):
with self._calibration_lock:
    pass

# CORRETTO (snapshot atomico):
with self._calibration_lock:
    scale = self._scale_mm_per_px
    k1 = self._k1_radial
    center = self._optical_center
    calibrated = self._is_calibrated
# Usare le variabili locali nel resto della pipeline
```

### 🟡 Medi (prima del primo utilizzo reale)

| ID | Problema | Impatto |
|---|---|---|
| P1.1 | Misura manuale restituisce sempre `0.0 mm` | Operatore non può misurare manualmente in mm |
| P1.2 | Istogramma non alimentato dal `GrabWorker` | Overlay istogramma sempre vuoto |
| P1.3 | Sharpness/Focus non calcolata dal `GrabWorker` | Barra di fuoco sempre a zero |
| P1.4 | Edge overlay non emesso dal `GrabWorker` | Nessuna visualizzazione bordi sull'immagine |
| P1.5 | `quick_export()` genera record con `timestamp=""` | Log di produzione senza timestamp |

### 🟢 Tech Debt (futuro)

| ID | Azione |
|---|---|
| P2.1 | Integrare `ImageProcessor` nel flusso di acquisizione |
| P2.2 | Integrare `CalibrationController` e rimuovere logica inline dalla `MainWindow` |
| P2.3 | Rimuovere o integrare i widget orfani (`CameraControlPanel`, `FocusAssistWidget`, ecc.) |
| P2.4 | Implementare `validators.py` e collegarlo ai dialog |
| P2.5 | Allineare le fixture di test con le firme effettive delle classi |
| P2.6 | Salvare `requirements.txt` in UTF-8 (attualmente UTF-16) |
| P2.7 | Rimuovere `__pycache__` dal repository e verificare `.gitignore` |

---

## 🔧 Hardware di Riferimento

| Componente | Modello | Note |
|---|---|---|
| **Telecamera** | Basler a2A3840-45umBAS | USB3 Vision, Mono8, 45 fps |
| **Sensore** | Sony IMX546 | 3840×2748 px, global shutter |
| **Ottica** | Edmund Optics 16mm | f/4, campo ~70mm a distanza di lavoro |
| **Illuminazione** | EuroBrite (retroilluminazione) | ~240 DN sfondo, ~10 DN gomma |
| **Cavo** | USB3 locking 2m | — |
| **Scala di lavoro** | ~0.018 mm/px | ~70 mm campo visivo su 3840 px |

---

## 📜 Crediti

**Autore:** Pierpaolo Careddu
**Organizzazione:** Pirelli R&D Metrologia
**Versione:** 1.0.0
**Data:** Marzo 2026

---

*Advanced Optical Profiler — Sistema metrologico ottico sub-pixel per il controllo dimensionale industriale*
