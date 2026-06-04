import threading
from dataclasses import dataclass, field
from typing import Any

from .logger import Logger
from .motor import esIntentoPlantilla, extraerDatosOS, extraerMemo
from .processed_messages import calcular_hash, ya_procesado


@dataclass
class BufferEstado:
    mensajes: list[dict[str, Any]] = field(default_factory=list)
    activacion: str = ""
    comentario: str = ""
    texto_os: str = ""
    hash_ordenado: list[str] = field(default_factory=list)


_LOCK = threading.Lock()
_BUFFER: dict[str, BufferEstado] = {}


def _es_comentario(texto: str) -> bool:
    t = texto.lower()
    return any(keyword in t for keyword in ["comentario:", "memo:", "motivo:", "observación", "observaciones"])


def _es_os(texto: str) -> bool:
    datos = extraerDatosOS(texto)
    campos_significativos = [
        datos.get("folioOS"),
        datos.get("telefonoContrato"),
        datos.get("cliente"),
        datos.get("domicilio"),
        datos.get("telContacto"),
        datos.get("direccion"),
    ]
    return any(str(valor).strip() for valor in campos_significativos)


def _crear_payload(nombre_chat: str, estado: BufferEstado) -> dict[str, Any]:
    mensaje_combinado = "\n\n".join(item["mensaje"] for item in estado.mensajes)
    return {
        "nombreChat": nombre_chat,
        "mensaje_combinado": mensaje_combinado,
        "activacion": estado.activacion,
        "comentario": estado.comentario,
        "texto_os": estado.texto_os,
        "hashes": list(estado.hash_ordenado),
        "mensaje_hash": calcular_hash(nombre_chat, mensaje_combinado),
        "ready": True,
    }


def registrar_mensaje(nombre_chat: str, mensaje: str):
    mensaje = str(mensaje or "").strip()
    if not nombre_chat or not mensaje:
        return None

    hash_mensaje = calcular_hash(nombre_chat, mensaje)
    if ya_procesado(nombre_chat, hash_mensaje):
        Logger.info(f"[BUFFER] Mensaje ya procesado en '{nombre_chat}', se ignora.")
        return None

    with _LOCK:
        estado = _BUFFER.setdefault(nombre_chat, BufferEstado())
        if hash_mensaje in estado.hash_ordenado:
            return None

        estado.mensajes.append({"mensaje": mensaje, "hash": hash_mensaje})
        estado.hash_ordenado.append(hash_mensaje)

        if esIntentoPlantilla(mensaje):
            estado.activacion = mensaje
        if _es_comentario(mensaje):
            estado.comentario = mensaje
        if _es_os(mensaje):
            estado.texto_os = mensaje

        if estado.activacion and estado.comentario and estado.texto_os:
            return _crear_payload(nombre_chat, estado)

        return {
            "nombreChat": nombre_chat,
            "mensaje_combinado": "",
            "activacion": estado.activacion,
            "comentario": estado.comentario,
            "texto_os": estado.texto_os,
            "hashes": list(estado.hash_ordenado),
            "mensaje_hash": hash_mensaje,
            "ready": False,
        }


def limpiar(nombre_chat: str | None = None):
    with _LOCK:
        if nombre_chat:
            _BUFFER.pop(nombre_chat, None)
        else:
            _BUFFER.clear()


def obtener_estado(nombre_chat: str) -> BufferEstado | None:
    with _LOCK:
        return _BUFFER.get(nombre_chat)
