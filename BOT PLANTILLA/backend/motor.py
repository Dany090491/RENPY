import re
import json
import pathlib
import urllib.parse
import unicodedata
from .logger import Logger

# ============================
# RUTA DE PERSISTENCIA
# ============================

_DATA_FILE = pathlib.Path(__file__).parent.parent / "datos_tecnicos.json"

# ============================
# DATOS POR DEFECTO
# ============================

_TECNICOS_DEFAULT = []

AREA_DEFECTO = ""
SUPERVISOR_DEFECTO = ""
EMPRESA_DEFECTO = ""

# ============================
# CARGA / GUARDADO
# ============================

def _cargar() -> list:
    if _DATA_FILE.exists():
        try:
            with open(_DATA_FILE, "r", encoding="utf-8") as f:
                tecnicos = json.load(f)
            for t in tecnicos:
                t.setdefault("activo", True)
            return tecnicos
        except Exception as e:
            Logger.warn(f"[MOTOR] Error cargando {_DATA_FILE}: {e}")
    return list(_TECNICOS_DEFAULT)


def _guardar(tecnicos: list):
    try:
        with open(_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(tecnicos, f, ensure_ascii=False, indent=2)
    except Exception as e:
        Logger.warn(f"[MOTOR] Error guardando {_DATA_FILE}: {e}")


# Lista activa en memoria
type_tecnicos: list = _cargar()

# ============================
# API PÚBLICA DE TÉCNICOS
# ============================

def get_tecnicos() -> list:
    return list(type_tecnicos)


def get_chats_monitoreados() -> list[str]:
    """Retorna solo los chats de técnicos marcados como activos."""
    return [t["nombreChat"] for t in type_tecnicos if t.get("activo", True)]


def agregar_tecnico(nombreChat: str, nombreTecnico: str, expediente: str,
                    telefono: str, cope: str):
    """Agrega un técnico a la lista y guarda en disco."""
    if not nombreChat.strip() or not nombreTecnico.strip():
        Logger.warn("[MOTOR] agregar_tecnico: nombreChat y nombreTecnico son obligatorios.")
        return False

    for t in type_tecnicos:
        if t["nombreChat"].lower() == nombreChat.lower():
            Logger.warn(f"[MOTOR] Técnico con chat '{nombreChat}' ya existe.")
            return False

    tipo = {
        "nombreChat": nombreChat.strip(),
        "nombreTecnico": nombreTecnico.strip().upper(),
        "expediente": expediente.strip(),
        "telefono": telefono.strip(),
        "cope": cope.strip().upper(),
        "activo": True,
    }
    _validar_tecnico(tipo)
    type_tecnicos.append(tipo)
    _guardar(type_tecnicos)
    Logger.info(f"[MOTOR] Técnico agregado: {nombreTecnico}")
    return True


def _validar_tecnico(t: dict):
    if not t["telefono"]:
        Logger.warn(f"[MOTOR] Técnico '{t['nombreTecnico']}' sin teléfono.")
    if not t["expediente"]:
        Logger.warn(f"[MOTOR] Técnico '{t['nombreTecnico']}' sin expediente.")
    if not t["cope"]:
        Logger.warn(f"[MOTOR] Técnico '{t['nombreTecnico']}' sin COPE.")


def set_tecnico_activo(nombreChat: str, activo: bool) -> bool:
    """Activa o desactiva un técnico para el procesamiento del bot."""
    for t in type_tecnicos:
        if t["nombreChat"].lower() == nombreChat.lower():
            t["activo"] = activo
            _guardar(type_tecnicos)
            estado = "activado" if activo else "desactivado"
            Logger.info(f"[MOTOR] Técnico '{nombreChat}' {estado}.")
            return True
    return False


def eliminar_tecnico(nombreChat: str) -> bool:
    """Elimina un técnico por su nombre de chat y guarda en disco."""
    global type_tecnicos
    antes = len(type_tecnicos)
    type_tecnicos = [t for t in type_tecnicos
                     if t["nombreChat"].lower() != nombreChat.lower()]
    if len(type_tecnicos) < antes:
        _guardar(type_tecnicos)
        Logger.info(f"[MOTOR] Técnico eliminado: {nombreChat}")
        return True
    return False

# ============================
# DETECTOR DE INTENCIÓN
# ============================

FRASES_ACTIVACION = [
    "ayuda",
    "ayudame",
    "ayúdame",
    "plantilla",
    "objecion",
    "objeción",
    "paro con la plantilla",
    "me ayuda",
    "me apoya",
    "comentario",
    "memo",
    "motivo",
    "observaciones",
    "observacion",
    "observación",
]


def esIntentoPlantilla(mensaje: str) -> bool:
    t = mensaje.lower()
    return any(f in t for f in FRASES_ACTIVACION)


# ============================
# DETECTOR DE TÉCNICO
# ============================

def obtenerDatosTecnicoPorChat(nombreChat: str):
    for t in type_tecnicos:
        if t["nombreChat"].lower() == nombreChat.lower():
            return t
    return None


# ============================
# EXTRACTOR DE DISTRITO
# ============================

REGEX_DISTRITO = re.compile(
    r"\b([A-Z]{3}0[0-9]{3}FO(?:[A-Z][0-9])?(?:[1-9]|10)?)\b"
)


def extraerDistrito(texto: str) -> str:
    m = re.search(r"(?:distrito|distrito asignado|zona)\s*[:\-]?\s*([A-Z]{3}0[0-9]{3}FO(?:[A-Z][0-9])?(?:[1-9]|10)?)", texto, re.I)
    if not m:
        m = REGEX_DISTRITO.search(texto)
    return m.group(1) if m else ""


# ============================
# EXTRACTORES DE CAMPO POR LÍNEA
# ============================

def _extraer_valor_por_etiquetas(texto: str, etiquetas: list[str]) -> str:
    def _normalizar(valor: str) -> str:
        valor = unicodedata.normalize("NFD", valor)
        valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
        return " ".join(valor.lower().split()).strip()

    lineas = [linea.strip() for linea in texto.splitlines()]
    for indice, linea in enumerate(lineas):
        if not linea:
            continue
        for etiqueta in etiquetas:
            etiqueta_norm = _normalizar(etiqueta)
            linea_norm = _normalizar(linea)
            if linea_norm == etiqueta_norm:
                for siguiente in lineas[indice + 1 :]:
                    if siguiente:
                        return siguiente.strip()
            if linea_norm.startswith(f"{etiqueta_norm}:") or linea_norm.startswith(f"{etiqueta_norm} -"):
                valor = linea.split(":", 1)[-1].strip() if ":" in linea else linea.split("-", 1)[-1].strip()
                if valor and _normalizar(valor) != etiqueta_norm:
                    return valor.strip()
    return ""


# ============================
# EXTRACTOR DE OS COMPLETA
# ============================

def extraerDatosOS(texto: str):
    def _valor_linea(etiquetas: list[str]) -> str:
        def _normalizar(valor: str) -> str:
            valor = unicodedata.normalize("NFD", valor)
            valor = "".join(ch for ch in valor if unicodedata.category(ch) != "Mn")
            return " ".join(valor.lower().split()).strip()

        lineas = [linea.strip() for linea in texto.splitlines()]
        etiquetas_norm = [_normalizar(etiqueta) for etiqueta in etiquetas]
        for indice, linea in enumerate(lineas):
            if not linea:
                continue
            linea_norm = _normalizar(linea)
            for etiqueta_norm in etiquetas_norm:
                if linea_norm == etiqueta_norm:
                    for siguiente in lineas[indice + 1 :]:
                        if siguiente:
                            return siguiente.strip()
                if linea_norm.startswith(f"{etiqueta_norm}:") or linea_norm.startswith(f"{etiqueta_norm} -"):
                    valor = linea.split(":", 1)[-1].strip() if ":" in linea else linea.split("-", 1)[-1].strip()
                    if valor:
                        return valor.strip()
        return ""

    folio = _extraer_valor_por_etiquetas(texto, ["orden de trabajo", "folio os", "folio", "os"])
    if not folio:
        m_folio = re.search(r"\b([A-Z]{0,4}\d{6,})\b", texto, re.I)
        folio = m_folio.group(1) if m_folio else ""
    folio = re.sub(r"^(?:QROO|OS|FOLIO)\s*", "", folio, flags=re.I).strip()

    telefono = _extraer_valor_por_etiquetas(texto, ["teléfono", "telefono", "teléfono contrato", "telefono contrato", "id de contrato"])
    if not telefono:
        m_tel = re.search(r"\b(4[0-9]{9,10})\b", texto)
        telefono = m_tel.group(1) if m_tel else ""
    distrito = extraerDistrito(texto)

    cliente = _extraer_valor_por_etiquetas(texto, ["nombre", "cliente", "nombre contacto"])

    tel_contacto = _extraer_valor_por_etiquetas(texto, ["teléfono móvil", "telefono movil", "teléfono de contacto", "telefono de contacto", "tel contacto", "contacto"])
    tel_contacto_adicional = _extraer_valor_por_etiquetas(texto, ["contacto adicional", "teléfono adicional", "telefono adicional", "teléfono secundario", "telefono secundario"])
    if not tel_contacto:
        _tel_ya_capturado = telefono or None
        for _m in re.finditer(r"(\d{10,11})", texto):
            if _m.group(1) != _tel_ya_capturado:
                tel_contacto = _m.group(1)
                break

    direccion = _valor_linea(["dirección", "direccion", "domicilio"])
    ciudad = _valor_linea(["ciudad"])
    estado = _valor_linea(["estado"])
    codigo_postal = _valor_linea(["código postal", "codigo postal", "cp"])
    subnumero = _valor_linea(["subnumero", "subnúmero", "subnumero"])
    manzana = _valor_linea(["manzana"])
    partes_domicilio = [p for p in [direccion, subnumero if subnumero != "-" else "", manzana if manzana != "-" else "", ciudad, estado, codigo_postal] if p]
    domicilio = ", ".join(dict.fromkeys(partes_domicilio))
    if not domicilio:
        domicilio = direccion

    coordenadas = _extraer_valor_por_etiquetas(texto, ["coordenadas", "ubicación", "ubicacion"])
    if not coordenadas:
        m = re.search(r"(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)", texto)
        if m:
            coordenadas = f"{m.group(1)}, {m.group(2)}"

    return {
        "folioOS": folio,
        "telefonoContrato": telefono,
        "distrito": distrito,
        "cliente": cliente,
        "telContacto": tel_contacto,
        "telContactoAdicional": tel_contacto_adicional,
        "domicilio": domicilio,
        "direccion": direccion,
        "ciudad": ciudad,
        "estado": estado,
        "codigoPostal": codigo_postal,
        "coordenadas": coordenadas,
    }


# ============================
# EXTRACTOR DE MEMO DINÁMICO
# ============================

def extraerMemo(texto: str) -> str:
    """Extrae memo dinámico. Prioriza calificador/motivo; si no, usa el comentario completo."""
    texto = texto.strip()
    cal = _extraer_valor_por_etiquetas(texto, ["calificador", "calificación", "clasificación"])
    mot = _extraer_valor_por_etiquetas(texto, ["motivo", "memo", "comentario", "observación", "observaciones"])
    if cal and mot:
        return f"Calificador Objeción: {cal.strip()}\nMotivo: {mot.strip()}"
    if cal:
        return f"Calificador Objeción: {cal.strip()}"
    if mot:
        return mot.strip()
    if texto:
        return texto
    return ""


# ============================
# ESTADO DE CONVERSACIÓN
# ============================

CAMPOS_REQUERIDOS = ["folioOS", "telefonoContrato", "cliente", "domicilio"]

_NOMBRE_CAMPO = {
    "folioOS": "el Folio OS (ej. QROO071369635)",
    "telefonoContrato": "el Teléfono / ID de contrato",
    "cliente": "el Nombre del cliente",
    "distrito": "el Distrito",
    "telContacto": "el Teléfono de contacto",
    "domicilio": "el Domicilio",
    "coordenadas": "las Coordenadas",
    "memo": "el comentario o memo de objeción",
}

_conversaciones: dict = {}


def iniciar_conversacion(nombreChat: str, tecnico: dict, datos_os: dict, memo: str = "", hashes=None):
    """Inicia una nueva sesión de llenado de plantilla para un chat."""
    _conversaciones[nombreChat] = {
        "tecnico": tecnico,
        "datos_os": datos_os,
        "memo": memo,
        "campo_actual": None,
        "hashes": list(hashes or []),
    }


def tiene_conversacion_activa(nombreChat: str) -> bool:
    return nombreChat in _conversaciones


def obtener_conversacion(nombreChat: str) -> dict | None:
    return _conversaciones.get(nombreChat)


def actualizar_memo_conv(nombreChat: str, memo: str):
    if nombreChat in _conversaciones:
        _conversaciones[nombreChat]["memo"] = memo
        _conversaciones[nombreChat]["campo_actual"] = None


def actualizar_campo_os_conv(nombreChat: str, campo: str, valor: str):
    if nombreChat in _conversaciones:
        _conversaciones[nombreChat]["datos_os"][campo] = valor
        _conversaciones[nombreChat]["campo_actual"] = None


def cerrar_conversacion(nombreChat: str):
    _conversaciones.pop(nombreChat, None)


def primer_campo_faltante(datos_os: dict, memo: str) -> str | None:
    """Retorna el primer campo requerido vacío, o None si todo está completo."""
    for campo in CAMPOS_REQUERIDOS:
        if not str(datos_os.get(campo, "")).strip():
            return campo
    if not str(memo).strip():
        return "memo"
    return None


def nombre_campo_legible(campo: str) -> str:
    return _NOMBRE_CAMPO.get(campo, campo)


# ============================
# GENERADOR DE PLANTILLA
# ============================

def generarPlantilla(tecnico, os, memo, config=None):
    config = config or {}
    area = str(config.get("area", AREA_DEFECTO)).strip()
    supervisor = str(config.get("supervisor", SUPERVISOR_DEFECTO)).strip()
    empresa = str(config.get("empresa", EMPRESA_DEFECTO)).strip()
    tel_contacto = str(os.get("telContacto", "")).strip()
    tel_contacto_adicional = str(os.get("telContactoAdicional", "")).strip()
    if tel_contacto and tel_contacto_adicional:
        tel_contacto = f"{tel_contacto} y {tel_contacto_adicional}"
    domicilio = str(os.get("domicilio", "")).strip()
    if not domicilio:
        domicilio = ", ".join([x for x in [os.get("direccion", ""), os.get("ciudad", ""), os.get("estado", ""), os.get("codigoPostal", "")] if str(x).strip()])
    return (
        "PLANTILLA DE OBJECIÓN\n"
        "\n"
        f"◼️ *ÁREA:* {area}\n"
        f"◼️ *COPE:* {tecnico.get('cope', '')}\n"
        f"◼️ *OS:* {os.get('folioOS', '')}\n"
        f"◼️ *TELÉFONO:* {os.get('telefonoContrato', '')}\n"
        f"◼️ *DISTRITO:* {os.get('distrito', '')}\n"
        "\n"
        f"◼️ *CLIENTE:* {os.get('cliente', '')}\n"
        f"◼️ *TEL CONTACTO:* {tel_contacto}\n"
        f"◼️ *DOMICILIO:* {domicilio}\n"
        f"◼️ *COORDENADAS:* {os.get('coordenadas', '')}\n"
        "\n"
        f"◼️ *SUPERVISOR:* {supervisor}\n"
        f"◼️ *TÉCNICO:* {tecnico.get('nombreTecnico', '')}\n"
        f"◼️  *CEL:* {tecnico.get('telefono', '')}\n"
        f"◼️ *EMPRESA:* {empresa}\n"
        "\n"
        "◼️ *MEMO:*"
        "\n"
        f"{memo}"
    )


async def geocodificar_domicilio(page, domicilio: str) -> str:
    """
    Abre una segunda pestaña en el contexto Playwright ya activo,
    consulta Nominatim (OpenStreetMap, gratuito, sin API key),
    extrae lat/lon del JSON de respuesta y cierra la pestaña.
    Retorna 'lat, lon' o '' si no encuentra resultado o falla.
    """
    if not domicilio.strip():
        return ""
    query = urllib.parse.quote(f"{domicilio}, Mexico")
    url = (
        f"https://nominatim.openstreetmap.org/search"
        f"?q={query}&format=json&limit=1&countrycodes=mx"
    )
    nueva_pagina = None
    try:
        nueva_pagina = await page.context.new_page()
        await nueva_pagina.goto(url, timeout=15000)
        contenido = await nueva_pagina.locator("body").inner_text()
        data = json.loads(contenido)
        if data:
            return f"{data[0]['lat']}, {data[0]['lon']}"
        return ""
    except Exception as e:
        Logger.warn(f"[GEOCODER] Error geocodificando '{domicilio[:40]}': {e}")
        return ""
    finally:
        if nueva_pagina:
            try:
                await nueva_pagina.close()
            except Exception:
                pass
