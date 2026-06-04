import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from .logger import Logger

_FILE_PATH = Path(__file__).resolve().parent / "processed_messages.json"
_LOCK = threading.Lock()


def _cargar_datos():
    if not _FILE_PATH.exists():
        return {}
    try:
        with open(_FILE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        Logger.warn(f"[PROCESSED] Error cargando {_FILE_PATH}: {e}")
        return {}


def _guardar_datos(data):
    temp_file = _FILE_PATH.with_suffix(".tmp")
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    temp_file.replace(_FILE_PATH)


def normalizar_texto(texto: str) -> str:
    return " ".join(str(texto).split()).strip()


def calcular_hash(nombre_chat: str, texto: str) -> str:
    payload = f"{nombre_chat}||{normalizar_texto(texto)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ya_procesado(nombre_chat: str, hash_mensaje: str) -> bool:
    with _LOCK:
        data = _cargar_datos()
        historial = data.get(nombre_chat, [])
        return any(item.get("hash") == hash_mensaje for item in historial)


def registrar_procesado(nombre_chat: str, hash_mensaje: str, mensaje: str, estado: str = "enviado"):
    with _LOCK:
        data = _cargar_datos()
        historial = data.setdefault(nombre_chat, [])
        historial.append(
            {
                "hash": hash_mensaje,
                "mensaje": normalizar_texto(mensaje),
                "estado": estado,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        historial[:] = historial[-100:]
        _guardar_datos(data)
        Logger.info(f"[PROCESSED] Mensaje registrado para '{nombre_chat}' ({estado}).")

