import json
from pathlib import Path

from .logger import Logger

CONFIG_FILE = "config.json"
_CONFIG_PATH = Path(__file__).resolve().parent.parent / CONFIG_FILE

DEFAULT_CONFIG = {
    "area": "",
    "supervisor": "",
    "empresa": "",
    "delay_ms": 600,
    "reintentos": 3,
    "carpeta_watchdog": "",
    "chat_archivos": "",
    "perfil_playwright": "",
}


def cargar_config():
    if not _CONFIG_PATH.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return dict(DEFAULT_CONFIG)
        merged = dict(DEFAULT_CONFIG)
        merged.update(data)
        return merged
    except Exception as e:
        Logger.warn(f"[CONFIG] Error cargando {_CONFIG_PATH}: {e}")
        return dict(DEFAULT_CONFIG)


def guardar_config(data):
    try:
        payload = dict(DEFAULT_CONFIG)
        if isinstance(data, dict):
            payload.update(data)
        temp_file = _CONFIG_PATH.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=4)
        temp_file.replace(_CONFIG_PATH)
        Logger.info(f"[CONFIG] Configuración guardada: {_CONFIG_PATH}")
        return True
    except Exception as e:
        Logger.error(f"[CONFIG] Error guardando {_CONFIG_PATH}: {e}")
        return False
