import asyncio
import json
import urllib.parse

from .logger import Logger


async def obtener_coordenadas(page, domicilio: str) -> str:
    if page is None or not domicilio or not domicilio.strip():
        return ""

    query = urllib.parse.quote(f"{domicilio}, Mexico")
    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?q={query}&format=json&limit=1&countrycodes=mx"
    )

    nueva = None
    try:
        nueva = await page.context.new_page()
        await nueva.goto(url, timeout=30000)
        await nueva.wait_for_timeout(3000)
        contenido = await nueva.locator("body").inner_text()
        data = json.loads(contenido)
        if data:
            return f"{data[0]['lat']}, {data[0]['lon']}"
        return ""
    except Exception as e:
        Logger.warn(f"[GEOCODER] No se pudieron obtener coordenadas para '{domicilio[:60]}': {e}")
        return ""
    finally:
        if nueva:
            try:
                await nueva.close()
            except Exception:
                pass

