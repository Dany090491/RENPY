"""
file_watcher.py — Monitor de carpeta con Watchdog.

Observa una carpeta en busca de archivos nuevos (.pdf, .png, .jpg, .jpeg).
Cuando detecta uno, lo encola como evento de "orden de servicio por archivo"
para que core.py lo procese.
"""
import threading
import os
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from .logger import Logger
from .queue import agregarMensajeACola

# ============================
# EXTENSIONES MONITOREADAS
# ============================
EXTENSIONES = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
_ARCHIVOS_RECIENTES: dict[str, float] = {}
_VENTANA_DUPLICADOS = 2.0

# ============================
# Handler de eventos
# ============================

class _OrdenHandler(FileSystemEventHandler):
    """Reacciona a archivos nuevos en la carpeta monitoreada."""

    def __init__(self, nombre_chat_destino: str):
        super().__init__()
        self.nombre_chat_destino = nombre_chat_destino

    def on_created(self, event):
        if event.is_directory:
            return
        ruta = Path(event.src_path)
        if ruta.suffix.lower() not in EXTENSIONES:
            return
        clave = str(ruta).lower()
        ahora = time.time()
        ultimo = _ARCHIVOS_RECIENTES.get(clave, 0.0)
        if ahora - ultimo < _VENTANA_DUPLICADOS:
            return
        _ARCHIVOS_RECIENTES[clave] = ahora

        try:
            if not ruta.exists():
                Logger.warn(f"[FILE_WATCHER] Se ignoró archivo inexistente: {ruta}")
                return
        except Exception as e:
            Logger.warn(f"[FILE_WATCHER] No se pudo validar archivo '{ruta}': {e}")
            return

        Logger.info(f"[FILE_WATCHER] Archivo nuevo detectado: {ruta.name}")
        agregarMensajeACola(
            {
                "nombreChat": self.nombre_chat_destino,
                "mensaje": f"ARCHIVO_ORDEN: {ruta}",
                "archivo_ruta": str(ruta),
            }
        )


# ============================
# Observador (singleton)
# ============================

_observer: Observer | None = None
_lock = threading.Lock()


def iniciar_file_watcher(carpeta: str, nombre_chat_destino: str) -> bool:
    """
    Inicia el observador de carpeta.

    Args:
        carpeta: Ruta absoluta de la carpeta a monitorear.
        nombre_chat_destino: Chat de WhatsApp al que se asociarán los archivos
                             detectados (debe existir en motor.py como técnico
                             o puede ser cualquier nombre de chat monitorado).
    Returns:
        True si inició correctamente, False si ya estaba activo o hubo error.
    """
    global _observer
    with _lock:
        if _observer is not None and _observer.is_alive():
            Logger.warn("[FILE_WATCHER] Ya hay un observador activo.")
            return False

        carpeta = str(Path(carpeta).expanduser().resolve()) if carpeta else ""
        if not carpeta:
            Logger.warn("[FILE_WATCHER] Carpeta vacía; no se inicia observador.")
            return False

        if not nombre_chat_destino or not nombre_chat_destino.strip():
            Logger.warn("[FILE_WATCHER] Chat destino vacío; no se inicia observador.")
            return False

        if not os.path.isdir(carpeta):
            try:
                os.makedirs(carpeta, exist_ok=True)
                Logger.info(f"[FILE_WATCHER] Carpeta creada: {carpeta}")
            except Exception as e:
                Logger.error(f"[FILE_WATCHER] No se pudo crear la carpeta: {e}")
                return False

        handler = _OrdenHandler(nombre_chat_destino)
        _observer = Observer()
        _observer.schedule(handler, carpeta, recursive=False)
        _observer.daemon = True
        _observer.start()
        Logger.info(f"[FILE_WATCHER] Monitoreando: {carpeta} → chat: {nombre_chat_destino}")
        return True


def detener_file_watcher():
    """Detiene el observador de carpeta si está activo."""
    global _observer
    with _lock:
        if _observer and _observer.is_alive():
            _observer.stop()
            _observer.join(timeout=3)
            Logger.warn("[FILE_WATCHER] Observador detenido.")
        _observer = None
        _ARCHIVOS_RECIENTES.clear()


def file_watcher_activo() -> bool:
    return _observer is not None and _observer.is_alive()
