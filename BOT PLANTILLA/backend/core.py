import asyncio
import re
from .logger import Logger
from .queue import obtener_siguiente
from .watcher import abrir_chat
import backend.playwright_bot as pw_bot
from .session_buffer import registrar_mensaje as registrar_mensaje_buffer, limpiar as limpiar_buffer
from .processed_messages import ya_procesado, registrar_procesado, calcular_hash
from .validator import campos_faltantes, mensaje_para_campo

from .motor import (
    esIntentoPlantilla,
    obtenerDatosTecnicoPorChat,
    extraerDatosOS,
    extraerMemo,
    _extraer_valor_por_etiquetas,
    generarPlantilla,
    iniciar_conversacion,
    tiene_conversacion_activa,
    obtener_conversacion,
    actualizar_memo_conv,
    actualizar_campo_os_conv,
    cerrar_conversacion,
)
from .config import cargar_config
from .geocoder import obtener_coordenadas

def _marcar_procesado(nombre_chat: str, hashes: list[str], mensaje: str):
    for hash_mensaje in hashes or []:
        registrar_procesado(nombre_chat, hash_mensaje, mensaje)


async def _enviar_mensaje_o_pedir_retroalimentacion(page, nombre_chat: str, texto: str, campo_faltante: str | None = None):
    pw_bot.procesando_plantilla = True
    try:
        if not await abrir_chat(page, nombre_chat):
            Logger.error(f"[CORE] No se pudo abrir el chat '{nombre_chat}'.")
            return False
        await asyncio.sleep(0.4)
        if not await pw_bot.responder_texto(page, texto):
            Logger.error(f"[CORE] No se pudo enviar mensaje a '{nombre_chat}'.")
            return False
        if campo_faltante == "coordenadas":
            Logger.info(f"[CORE] Se solicitó geolocalización manual a '{nombre_chat}'.")
        return True
    finally:
        pw_bot.procesando_plantilla = False

# ---------------- PROCESADOR ----------------
async def procesar_mensaje_desde_whatsapp(page):
    page = page or pw_bot.page

    if pw_bot.procesando_plantilla:
        return None

    if page is None:
        Logger.warn("[CORE] No hay página activa para procesar WhatsApp.")
        return None

    ctx = obtener_siguiente()
    if not ctx:
        return None

    nombreChat = ctx["nombreChat"]
    mensaje = ctx["mensaje"]
    hash_mensaje = calcular_hash(nombreChat, mensaje)

    if ya_procesado(nombreChat, hash_mensaje):
        Logger.info(f"[CORE] Mensaje duplicado ignorado en '{nombreChat}'.")
        return None

    if tiene_conversacion_activa(nombreChat):
        conv = obtener_conversacion(nombreChat)
        campo = conv.get("campo_actual")
        if campo == "memo":
            actualizar_memo_conv(nombreChat, mensaje.strip())
        elif campo:
            nuevos = extraerDatosOS(mensaje)
            memo = extraerMemo(mensaje)
            if campo in nuevos and str(nuevos.get(campo, "")).strip():
                actualizar_campo_os_conv(nombreChat, campo, nuevos[campo])
            elif campo == "coordenadas":
                conv["datos_os"]["coordenadas"] = mensaje.strip()
            else:
                if any(v for v in nuevos.values()):
                    for c, v in nuevos.items():
                        if v:
                            conv["datos_os"][c] = v
                    if memo and not conv.get("memo"):
                        conv["memo"] = memo
                else:
                    actualizar_campo_os_conv(nombreChat, campo, mensaje.strip())
        else:
            nuevos = extraerDatosOS(mensaje)
            for c, v in nuevos.items():
                if v and not conv["datos_os"].get(c):
                    conv["datos_os"][c] = v
            memo = extraerMemo(mensaje)
            if memo and not conv.get("memo"):
                conv["memo"] = memo

        faltan = campos_faltantes(conv["datos_os"], conv["memo"])
        if faltan:
            campo = faltan[0]
            conv["campo_actual"] = campo
            if campo == "coordenadas" and not conv["datos_os"].get("coordenadas"):
                texto = mensaje_para_campo(campo)
            else:
                texto = mensaje_para_campo(campo)
            await _enviar_mensaje_o_pedir_retroalimentacion(page, nombreChat, texto, campo)
            return None

        if not conv["datos_os"].get("coordenadas"):
            coords = await obtener_coordenadas(page, conv["datos_os"].get("domicilio", ""))
            if coords:
                conv["datos_os"]["coordenadas"] = coords
            else:
                conv["campo_actual"] = "coordenadas"
                await _enviar_mensaje_o_pedir_retroalimentacion(
                    page,
                    nombreChat,
                    mensaje_para_campo("coordenadas"),
                    "coordenadas",
                )
                return None

        plantilla = generarPlantilla(conv["tecnico"], conv["datos_os"], conv["memo"], cargar_config())
        if await _enviar_mensaje_o_pedir_retroalimentacion(page, nombreChat, plantilla):
            _marcar_procesado(nombreChat, conv.get("hashes", [hash_mensaje]), plantilla)
            cerrar_conversacion(nombreChat)
            limpiar_buffer(nombreChat)
            Logger.info(
                f"Plantilla completada para '{conv['tecnico']['nombreTecnico']}' | Folio: {conv['datos_os'].get('folioOS','')}"
            )
            return plantilla
        return None

    combinado = registrar_mensaje_buffer(nombreChat, mensaje)
    if not combinado or not combinado.get("ready"):
        return None
    Logger.info(f"Procesando mensaje de '{nombreChat}'")

    try:
        tecnico = obtenerDatosTecnicoPorChat(nombreChat)
        if not tecnico:
            if await _enviar_mensaje_o_pedir_retroalimentacion(page, nombreChat, "No encontré tus datos como técnico."):
                limpiar_buffer(nombreChat)
            return None

        mensaje_combinado = combinado["mensaje_combinado"]
        texto_os = combinado.get("texto_os") or mensaje_combinado
        datos_os = extraerDatosOS(mensaje_combinado)
        memo = extraerMemo(combinado["comentario"] or mensaje_combinado)

        direccion_match = re.search(r"(?:^|\n)\s*Dirección\s*\n([^\n]+)", texto_os, re.I)
        direccion = direccion_match.group(1).strip() if direccion_match else _extraer_valor_por_etiquetas(texto_os, ["dirección", "direccion", "domicilio"])
        ciudad_match = re.search(r"(?:^|\n)\s*Ciudad\s*\n([^\n]+)", texto_os, re.I)
        ciudad = ciudad_match.group(1).strip() if ciudad_match else _extraer_valor_por_etiquetas(texto_os, ["ciudad"])
        estado_match = re.search(r"(?:^|\n)\s*Estado\s*\n([^\n]+)", texto_os, re.I)
        estado = estado_match.group(1).strip() if estado_match else _extraer_valor_por_etiquetas(texto_os, ["estado"])
        cp_match = re.search(r"(?:^|\n)\s*C[oó]digo postal\s*\n([0-9]{4,6})", texto_os, re.I)
        codigo_postal = cp_match.group(1).strip() if cp_match else _extraer_valor_por_etiquetas(texto_os, ["código postal", "codigo postal", "cp"])
        subnumero_match = re.search(r"(?:^|\n)\s*Subnumero\s*\n([^\n]+)", texto_os, re.I)
        subnumero = subnumero_match.group(1).strip() if subnumero_match else _extraer_valor_por_etiquetas(texto_os, ["subnumero", "subnúmero"])
        manzana_match = re.search(r"(?:^|\n)\s*Manzana\s*\n([^\n]+)", texto_os, re.I)
        manzana = manzana_match.group(1).strip() if manzana_match else _extraer_valor_por_etiquetas(texto_os, ["manzana"])

        if direccion:
            datos_os["direccion"] = direccion
        if ciudad:
            datos_os["ciudad"] = ciudad
        if estado:
            datos_os["estado"] = estado
        if codigo_postal:
            datos_os["codigoPostal"] = codigo_postal
        domicilio_partes = [p for p in [direccion, subnumero if subnumero != "-" else "", manzana if manzana != "-" else "", ciudad, estado, codigo_postal] if p]
        if domicilio_partes:
            datos_os["domicilio"] = ", ".join(dict.fromkeys(domicilio_partes))

        Logger.info(f"[CORE] Datos extraídos para '{nombreChat}': {datos_os}")
        Logger.info(f"[CORE] Memo extraído para '{nombreChat}': {memo}")

        iniciar_conversacion(nombreChat, tecnico, datos_os, memo, hashes=combinado.get("hashes", []))
        conv = obtener_conversacion(nombreChat)

        faltantes = campos_faltantes(datos_os, memo)
        if faltantes:
            faltante = faltantes[0]
            conv["campo_actual"] = faltante
            if faltante == "coordenadas":
                await _enviar_mensaje_o_pedir_retroalimentacion(
                    page,
                    nombreChat,
                    mensaje_para_campo("coordenadas"),
                    "coordenadas",
                )
            else:
                await _enviar_mensaje_o_pedir_retroalimentacion(page, nombreChat, mensaje_para_campo(faltante), faltante)
            limpiar_buffer(nombreChat)
            return None

        if not datos_os.get("coordenadas"):
            coords = await obtener_coordenadas(page, datos_os.get("domicilio", ""))
            if coords:
                datos_os["coordenadas"] = coords
            else:
                conv["campo_actual"] = "coordenadas"
                await _enviar_mensaje_o_pedir_retroalimentacion(
                    page,
                    nombreChat,
                    mensaje_para_campo("coordenadas"),
                    "coordenadas",
                )
                limpiar_buffer(nombreChat)
                return None

        plantilla = generarPlantilla(tecnico, datos_os, memo, cargar_config())

        if not await _enviar_mensaje_o_pedir_retroalimentacion(page, nombreChat, plantilla):
            limpiar_buffer(nombreChat)
            return None

        _marcar_procesado(nombreChat, conv.get("hashes", []) or [hash_mensaje], plantilla)
        cerrar_conversacion(nombreChat)
        limpiar_buffer(nombreChat)
        Logger.info(
            f"Plantilla completada para '{tecnico['nombreTecnico']}' | Folio: {datos_os.get('folioOS','')}"
        )
        return plantilla

    finally:
        pw_bot.procesando_plantilla = False
