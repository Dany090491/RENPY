import asyncio
from .logger import Logger

async def intentar(fn, intentos=3):
    error_final = None
    for i in range(1, intentos + 1):
        try:
            return await fn()
        except Exception as e:
            error_final = e
            Logger.warn(f"[RETRY] Intento {i}/{intentos} falló: {e}")
            await asyncio.sleep(0.5 * i)
    Logger.error(f"[RETRY] Error permanente: {error_final}")
    raise error_final
