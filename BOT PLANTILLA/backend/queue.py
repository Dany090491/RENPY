from collections import deque
import threading
import time

from .logger import Logger

_cola = deque()
_lock = threading.Lock()
procesando = False


def agregarMensajeACola(mensaje):
    item = dict(mensaje)
    item["timestamp"] = time.time()
    with _lock:
        _cola.append(item)
        tam = len(_cola)
    Logger.info(f"[QUEUE] Mensaje agregado a la cola. Total: {tam}")


def obtener_siguiente():
    with _lock:
        if not _cola:
            return None
        return _cola.popleft()


def obtener_mensajes_recientes(nombre_chat: str, limite_segundos: int = 60):
    ahora = time.time()
    with _lock:
        return [
            dict(m)
            for m in list(_cola)
            if m.get("nombreChat") == nombre_chat and (ahora - m.get("timestamp", ahora)) <= limite_segundos
        ]


def obtener_tamano_cola():
    with _lock:
        return len(_cola)


def comenzar_procesamiento():
    global procesando
    with _lock:
        if procesando:
            return False
        procesando = True
        return True


def terminar_procesamiento():
    global procesando
    with _lock:
        procesando = False


def cola_en_proceso():
    with _lock:
        return procesando
