"""
CameraManager — Wrapper per il controllo della telecamera Basler Ace2 via pypylon.

Interfaccia hardware:
- Basler Ace2 a2A3840-45umBAS USB3 Mono
- Connessione USB3 con cavo locking 2m
- Sensore Sony IMX546 monocromatico, 3840×2748 @ 45fps

Funzionalità:
- Connect/Disconnect con auto-detection della camera
- Grab singolo frame (greyscale 8-bit numpy array)
- Controllo Exposure Time (μs) e Gain (dB)
- Accesso alle proprietà del sensore (temperatura, device info)
- Gestione errori robusta con riconnessione

Note: pypylon richiede il Pylon SDK C++ installato a livello di sistema.
"""

import logging
import numpy as np
from typing import Optional

logger = logging.getLogger(__name__)

# Import condizionale di pypylon — permette di sviluppare la GUI
# anche senza la camera fisica collegata
try:
    from pypylon import pylon
    PYPYLON_AVAILABLE = True
except ImportError:
    PYPYLON_AVAILABLE = False
    logger.warning(
        "pypylon non disponibile. Il CameraManager funzionerà in modalità simulata."
    )


class CameraManager:
    """
    Gestisce la connessione e il controllo della telecamera Basler.

    Supporta due modalità:
    - Modalità reale: usa pypylon per controllare la camera hardware
    - Modalità simulata: genera frame sintetici per sviluppo/test senza camera

    Utilizzo:
        cam = CameraManager()
        cam.connect()
        frame = cam.grab_frame()  # np.ndarray (H, W) uint8
        cam.set_exposure(8000)    # μs
        cam.set_gain(2.0)         # dB
        cam.disconnect()
    """

    def __init__(self, simulate: bool = False):
        """
        Args:
            simulate: Se True, forza la modalità simulata anche se pypylon
                      è disponibile. Utile per test e sviluppo GUI.
        """
        self._simulate = simulate or not PYPYLON_AVAILABLE
        self._camera = None
        self._is_connected: bool = False
        self._is_grabbing: bool = False

        # Parametri correnti
        self._exposure_us: int = 8000
        self._gain_db: float = 0.0
        self._device_info: str = ""

        # Simulazione
        self._sim_frame_counter: int = 0
        self._sim_width: int = 3840
        self._sim_height: int = 2748

        if self._simulate:
            logger.info("CameraManager inizializzato in MODALITÀ SIMULATA")
        else:
            logger.info("CameraManager inizializzato (pypylon disponibile)")

    # ═══════════════════════════════════════════════════════════
    # CONNESSIONE
    # ═══════════════════════════════════════════════════════════

    def connect(self):
        """Connette alla prima telecamera Basler disponibile."""
        if self._is_connected:
            logger.warning("Camera già connessa")
            return

        if self._simulate:
            self._is_connected = True
            self._device_info = "SIMULATA — Basler a2A3840-45umBAS (virtuale)"
            logger.info(f"Camera simulata connessa: {self._device_info}")
            return

        # Connessione reale via pypylon
        try:
            tl_factory = pylon.TlFactory.GetInstance()
            devices = tl_factory.EnumerateDevices()

            if len(devices) == 0:
                raise ConnectionError(
                    "Nessuna telecamera Basler trovata. "
                    "Verificare il collegamento USB3 e i driver Pylon."
                )

            # Usa la prima camera disponibile
            self._camera = pylon.InstantCamera(
                tl_factory.CreateDevice(devices[0])
            )
            self._camera.Open()

            # Configurazione iniziale
            self._camera.PixelFormat.SetValue("Mono8")

            # Imposta parametri di default
            self._apply_exposure(self._exposure_us)
            self._apply_gain(self._gain_db)

            # Abilita acquisizione continua
            self._camera.AcquisitionMode.SetValue("Continuous")
            self._camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            self._is_grabbing = True

            # Info device
            self._device_info = (
                f"{devices[0].GetModelName()} "
                f"(SN: {devices[0].GetSerialNumber()})"
            )

            self._is_connected = True
            logger.info(f"Camera connessa: {self._device_info}")

        except Exception as e:
            self._is_connected = False
            self._camera = None
            logger.error(f"Errore connessione camera: {e}")
            raise

    def disconnect(self):
        """Disconnette la telecamera e rilascia le risorse."""
        if not self._is_connected:
            return

        if self._simulate:
            self._is_connected = False
            logger.info("Camera simulata disconnessa")
            return

        try:
            if self._camera is not None:
                if self._is_grabbing:
                    self._camera.StopGrabbing()
                    self._is_grabbing = False
                self._camera.Close()
                self._camera = None

            self._is_connected = False
            logger.info("Camera disconnessa")

        except Exception as e:
            logger.error(f"Errore disconnessione: {e}")
            self._is_connected = False
            self._camera = None

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    @property
    def device_info(self) -> str:
        return self._device_info

    # ═══════════════════════════════════════════════════════════
    # ACQUISIZIONE FRAME
    # ═══════════════════════════════════════════════════════════

    def grab_frame(self) -> Optional[np.ndarray]:
        """
        Acquisisce un singolo frame dalla telecamera.

        Returns:
            Frame greyscale 8-bit come numpy array (H, W), o None se fallisce.
        """
        if not self._is_connected:
            return None

        if self._simulate:
            return self._generate_simulated_frame()

        try:
            grab_result = self._camera.RetrieveResult(
                1000,  # Timeout 1 secondo
                pylon.TimeoutHandling_ThrowException
            )

            if grab_result.GrabSucceeded():
                frame = grab_result.Array.copy()
                grab_result.Release()
                return frame
            else:
                logger.warning(f"Grab fallito: {grab_result.ErrorCode}")
                grab_result.Release()
                return None

        except Exception as e:
            logger.error(f"Errore grab frame: {e}")
            return None

    # Claude-Opus4.6-Generated
    # def _generate_simulated_frame(self) -> np.ndarray:
    #     """
    #     Genera un frame simulato per sviluppo senza camera.
    #     Simula una bandina nera su sfondo bianco con leggera variazione.
    #     """
    #     self._sim_frame_counter += 1

    #     frame = np.full(
    #         (self._sim_height, self._sim_width), 240, dtype=np.uint8
    #     )

    #     # Bandina simulata (striscia nera orizzontale con leggera oscillazione)
    #     center_y = self._sim_height // 2
    #     half_width = 400
    #     offset = int(20 * np.sin(self._sim_frame_counter * 0.05))
    #     angle_variation = 0.02 * np.sin(self._sim_frame_counter * 0.03)

    #     for x in range(self._sim_width):
    #         y_center = center_y + offset + int(angle_variation * (x - self._sim_width // 2))
    #         y_top = max(0, y_center - half_width)
    #         y_bot = min(self._sim_height, y_center + half_width)
    #         frame[y_top:y_bot, x] = 10

    #     # Aggiungi rumore
    #     noise = np.random.normal(0, 3, frame.shape).astype(np.int16)
    #     frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    #     return frame
    def _generate_simulated_frame(self) -> np.ndarray:
        """
        Versione ottimizzata (vectorized) per ridurre il carico CPU.
        Genera un frame 720p in pochi millisecondi.
        """
        self._sim_frame_counter += 1

        # Crea sfondo bianco
        frame = np.full((self._sim_height, self._sim_width), 240, dtype=np.uint8)

        # Calcolo oscillazione (stesse dinamiche di prima)
        center_y = self._sim_height // 2
        half_band_w = 400 
        offset = int(20 * np.sin(self._sim_frame_counter * 0.05))
        angle_var = 0.02 * np.sin(self._sim_frame_counter * 0.03)

        # Creiamo una rampa per l'inclinazione
        x_indices = np.arange(self._sim_width)
        y_centers = center_y + offset + (angle_var * (x_indices - self._sim_width // 2))
        
        # Calcoliamo i limiti superiore e inferiore per ogni colonna (vectorized)
        y_tops = np.clip(y_centers - half_band_w, 0, self._sim_height).astype(int)
        y_bots = np.clip(y_centers + half_band_w, 0, self._sim_height).astype(int)

        # Disegniamo la bandina senza cicli for espliciti
        # (Usiamo una maschera booleana 2D per velocità massima)
        yy, xx = np.ogrid[:self._sim_height, :self._sim_width]
        mask = (yy >= y_tops) & (yy < y_bots)
        frame[mask] = 10

        # Aggiunta rumore (solo se necessario per i test, altrimenti commenta per velocità)
        noise = np.random.randint(-3, 4, (self._sim_height, self._sim_width), dtype=np.int16)
        frame = np.clip(frame.astype(np.int16) + noise, 0, 255).astype(np.uint8)

        return frame

    # ═══════════════════════════════════════════════════════════
    # CONTROLLO PARAMETRI
    # ═══════════════════════════════════════════════════════════

    def set_exposure(self, value_us: int):
        """Imposta il tempo di esposizione in microsecondi."""
        self._exposure_us = max(100, min(1000000, value_us))
        if self._is_connected and not self._simulate:
            self._apply_exposure(self._exposure_us)

    def _apply_exposure(self, value_us: int):
        """Applica il valore di esposizione alla camera hardware."""
        try:
            if self._camera is not None:
                self._camera.ExposureTime.SetValue(float(value_us))
        except Exception as e:
            logger.error(f"Errore impostazione esposizione: {e}")

    def set_gain(self, value_db: float):
        """Imposta il guadagno in dB."""
        self._gain_db = max(0.0, min(24.0, value_db))
        if self._is_connected and not self._simulate:
            self._apply_gain(self._gain_db)

    def _apply_gain(self, value_db: float):
        """Applica il valore di guadagno alla camera hardware."""
        try:
            if self._camera is not None:
                self._camera.Gain.SetValue(float(value_db))
        except Exception as e:
            logger.error(f"Errore impostazione guadagno: {e}")

    @property
    def exposure(self) -> int:
        return self._exposure_us

    @property
    def gain(self) -> float:
        return self._gain_db

    def get_sensor_temperature(self) -> Optional[float]:
        """Legge la temperatura del sensore (se supportato)."""
        if self._simulate:
            return 42.0 + np.random.normal(0, 0.5)

        try:
            if self._camera is not None and hasattr(self._camera, 'DeviceTemperature'):
                return float(self._camera.DeviceTemperature.GetValue())
        except Exception:
            pass
        return None