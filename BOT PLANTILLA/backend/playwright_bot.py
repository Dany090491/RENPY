# backend/playwright_bot.py
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from .logger import Logger
from .retry import intentar
from .config import cargar_config

_DEFAULT_PROFILE_DIR = Path(__file__).resolve().parent.parent / "playwright_profile"

context = None
page = None
running = False
pw_instance = None
_watcher_task = None
ready = False  # ← Flag: True cuando Playwright está completamente listo

# ← NUEVO: flag global para bloquear el watcher mientras se escribe plantilla
procesando_plantilla = False

_mensajes_enviados_por_bot: set[str] = set()
_mensajes_enviados_hash: set[int] = set()


def _normalizar_texto(texto: str) -> str:
    return " ".join(texto.split()).strip()


def es_mensaje_enviado_por_bot(texto: str) -> bool:
    normalizado = _normalizar_texto(texto)
    return normalizado in _mensajes_enviados_por_bot or hash(normalizado) in _mensajes_enviados_hash


async def responder_texto(page, texto: str):
    """Escribe y envía un mensaje de texto en el chat activo de WhatsApp Web.
    Usa Shift+Enter para saltos de línea internos y Enter solo al final,
    evitando que WhatsApp envíe cada línea como mensaje separado.
    """
    async def _obtener_caja():
        candidatos = [
            "footer div[contenteditable='true'][role='textbox']",
            "footer div[contenteditable='true']",
            "div[contenteditable='true'][data-tab='10']",
            "div[contenteditable='true'][role='textbox']",
            "div[contenteditable='true']",
        ]
        for selector in candidatos:
            loc = page.locator(selector).last
            try:
                if await loc.count() > 0 and await loc.is_visible():
                    return loc
            except Exception:
                continue
        return None

    async def _send():
        await page.wait_for_timeout(500)
        caja = await _obtener_caja()
        if not caja:
            Logger.error("No se encontró el input de WhatsApp.")
            return False
        try:
            await caja.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass
        await caja.click()
        try:
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
        except Exception:
            await page.keyboard.press("Delete")
        await asyncio.sleep(0.2)  # Esperar a que el campo esté limpio
        lineas = texto.split("\n")
        for i, linea in enumerate(lineas):
            if linea:
                await caja.type(linea, delay=40)
            if i < len(lineas) - 1:
                await page.keyboard.down("Shift")
                await page.keyboard.press("Enter")
                await page.keyboard.up("Shift")
                await asyncio.sleep(0.1)
        await asyncio.sleep(0.2)
        await caja.press("Enter")
        return True

    try:
        resultado = await intentar(_send)
        if resultado:
            normalizado = _normalizar_texto(texto)
            _mensajes_enviados_por_bot.add(normalizado)
            _mensajes_enviados_hash.add(hash(normalizado))
        return bool(resultado)
    except Exception as e:
        Logger.error(f"[BOT] Error enviando texto: {e}")
        return False


async def iniciar_bot():
    """
    Abre WhatsApp Web usando sesión persistente.
    Si ya hay sesión guardada en USER_DATA_DIR, NO pedirá QR.
    Si es la primera vez, mostrará el QR para escanear.
    """
    global context, page, running, pw_instance, ready
    if running:
        return
    running = True
    ready = False  # ← Marcar como no listo mientras se inicializa

    config = cargar_config()
    user_data_dir = config.get("perfil_playwright") or str(_DEFAULT_PROFILE_DIR)
    Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    pw_instance = await async_playwright().start()
    context = await pw_instance.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        args=["--no-sandbox"],
    )

    if context.pages:
        page = context.pages[0]
    else:
        page = await context.new_page()

    await page.goto("https://web.whatsapp.com")
    try:
        await page.wait_for_selector("div[contenteditable='true']", timeout=30000)
    except Exception as e:
        Logger.warn(f"[BOT] Selector de chat no disponible aún: {e}")
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

    ready = True  # ← Marcar como listo DESPUÉS de que cargue completamente
    Logger.info("Bot iniciado. WhatsApp Web cargado (sesión persistente).")


async def iniciar_escucha():
    """
    Lanza el ciclo de escucha de chats en segundo plano.
    Llámalo después de confirmar que WhatsApp Web cargó correctamente.
    """
    global _watcher_task
    if _watcher_task and not _watcher_task.done():
        Logger.warn("[BOT] La escucha ya está activa.")
        return
    if page is None:
        Logger.error("[BOT] No hay página activa. Inicia el bot primero.")
        return

    from .motor import get_chats_monitoreados
    from .watcher import ciclo_escucha

    _watcher_task = asyncio.create_task(
        ciclo_escucha(page, get_chats_monitoreados)
    )
    Logger.info("[BOT] Escucha de chats iniciada en segundo plano.")


async def detener_escucha():
    """Cancela el ciclo de escucha de WhatsApp Web."""
    global _watcher_task
    if _watcher_task and not _watcher_task.done():
        _watcher_task.cancel()
        try:
            await _watcher_task
        except asyncio.CancelledError:
            pass
    _watcher_task = None
    Logger.info("[BOT] Escucha de chats detenida.")


def escucha_activa() -> bool:
    return _watcher_task is not None and not _watcher_task.done()


def bot_esta_listo() -> bool:
    """Devuelve True si el bot está completamente listo (Playwright cargado y funcional)."""
    return ready and running and page is not None


async def obtener_ultimo_mensaje_enviado(page=None):
    page = page or globals().get("page")
    if page is None:
        return ""
    try:
        locators = page.locator("div.message-out")
        count = await locators.count()
        if count == 0:
            return ""
        texto = await locators.nth(count - 1).inner_text()
        return texto.strip()
    except Exception:
        return ""


async def detener_bot():
    """Detiene la escucha, cierra el contexto Playwright y libera recursos."""
    global context, running, pw_instance, ready
    running = False
    ready = False  # ← No está listo después de detener
    await detener_escucha()
    if context:
        await context.close()
        context = None
        Logger.warn("Bot detenido (contexto cerrado).")
    if pw_instance:
        await pw_instance.stop()
        pw_instance = None
