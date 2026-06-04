import asyncio

from .logger import Logger
from .queue import agregarMensajeACola
from .playwright_bot import es_mensaje_enviado_por_bot, procesando_plantilla

_estado: dict[str, set] = {}

_SEARCH_SELECTORS = [
    'input[data-tab="3"]',
    'input[aria-label*="chat"]',
    'input[aria-label*="Search"]',
    'div[contenteditable="true"][data-tab="3"]',
    '[data-testid="chat-list-search"]',
]


async def _encontrar_buscador(page):
    await page.wait_for_timeout(300)
    for sel in _SEARCH_SELECTORS:
        loc = page.locator(sel)
        try:
            if await loc.count() > 0:
                return loc.first
        except Exception:
            continue
    return None


async def abrir_chat(page, nombre_chat: str) -> bool:
    if page is None:
        Logger.error("[WATCHER] No hay página activa para abrir chat.")
        return False
    try:
        search = await _encontrar_buscador(page)
        if search is None:
            Logger.warn("[WATCHER] No se encontró el buscador de WhatsApp Web.")
            return False

        await search.click(timeout=6000)
        await search.click(click_count=3)
        await page.keyboard.press("Delete")
        await page.keyboard.type(nombre_chat, delay=40)
        await page.wait_for_timeout(1200)

        candidatos = [
            f'span[title="{nombre_chat}"]',
            'div[data-testid="cell-frame-container"]',
            'div[role="listitem"]',
            '#pane-side div[tabindex="-1"]',
        ]
        for sel in candidatos:
            try:
                loc = page.locator(sel).first
                if await loc.count() > 0:
                    await loc.click(timeout=3000)
                    await page.wait_for_timeout(700)
                    return True
            except Exception:
                continue

        await page.keyboard.press("ArrowDown")
        await page.wait_for_timeout(250)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(700)
        return True
    except Exception as e:
        Logger.warn(f"[WATCHER] No se pudo abrir chat '{nombre_chat}': {e}")
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
        return False


async def _extraer_ultimos_textos(page, max_mensajes: int = 5):
    mensajes = page.locator('div[data-testid="msg-container"]')
    count = await mensajes.count()
    if count == 0:
        return []

    resultados = []
    for i in range(count - 1, max(count - max_mensajes, -1), -1):
        try:
            msg = mensajes.nth(i)
            es_mensaje_chat = await msg.evaluate(
                "el => !!el.closest('div.message-in')"
            )
            if not es_mensaje_chat:
                continue
            texto = await msg.inner_text()
            texto = texto.strip()
            if texto:
                resultados.append(texto)
        except Exception:
            continue
    resultados.reverse()
    return resultados


async def ciclo_escucha(page, obtener_chats_fn, intervalo=8.0):
    Logger.info("[WATCHER] Ciclo de escucha iniciado.")
    while True:
        if procesando_plantilla:
            await asyncio.sleep(1)
            continue

        try:
            if page.is_closed():
                Logger.warn("[WATCHER] Página cerrada, se detiene la escucha.")
                return
        except Exception:
            pass

        chats = [c for c in obtener_chats_fn() if c and not c.endswith("(Tú)")]
        for nombre_chat in chats:
            try:
                if not await abrir_chat(page, nombre_chat):
                    continue

                if nombre_chat not in _estado:
                    _estado[nombre_chat] = set()

                vistos = _estado[nombre_chat]
                nuevos = []
                for texto in await _extraer_ultimos_textos(page):
                    msg_id = hash(texto)
                    if msg_id in vistos:
                        continue
                    if es_mensaje_enviado_por_bot(texto):
                        vistos.add(msg_id)
                        continue
                    vistos.add(msg_id)
                    nuevos.append(texto)

                for texto in nuevos:
                    Logger.info(f"[WATCHER] Nuevo mensaje en '{nombre_chat}': {texto[:80]}...")
                    agregarMensajeACola({"nombreChat": nombre_chat, "mensaje": texto})

            except Exception as e:
                Logger.warn(f"[WATCHER] Error procesando '{nombre_chat}': {e}")

        await asyncio.sleep(intervalo)


def resetear_estado():
    global _estado
    _estado.clear()
    Logger.info("[WATCHER] Estado reseteado.")
