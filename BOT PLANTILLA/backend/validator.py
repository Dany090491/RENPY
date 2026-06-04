def campos_faltantes(datos_os: dict, memo: str) -> list[str]:
    faltantes = []
    if not str(datos_os.get("folioOS", "")).strip():
        faltantes.append("folioOS")
    if not str(datos_os.get("cliente", "")).strip():
        faltantes.append("cliente")
    if not str(datos_os.get("domicilio", "")).strip():
        faltantes.append("domicilio")
    if not str(datos_os.get("telefonoContrato", "")).strip():
        faltantes.append("telefonoContrato")
    if not str(datos_os.get("distrito", "")).strip():
        faltantes.append("distrito")
    if not str(memo or "").strip():
        faltantes.append("memo")
    return faltantes


def mensaje_para_campo(campo: str) -> str:
    if campo == "coordenadas":
        return "No pude obtener las coordenadas. Envíame las coordenadas coordenadas."
    mensajes = {
        "folioOS": "Me falta el folio de la OS.",
        "cliente": "Me falta el nombre del cliente.",
        "domicilio": "Me falta el domicilio.",
        "telefonoContrato": "Me falta el teléfono de la OS.",
        "distrito": "Me falta el distrito.",
        "memo": "Me falta el memo o comentario de la objeción.",
    }
    return mensajes.get(campo, f"Me falta {campo}.")

