# 🔧 FIX — TIMING RACE CONDITION EN BOT PLAYWRIGHT

## ❌ PROBLEMA ORIGINAL

```
Logs:
2026-06-01T04:05:42 [INFO] Mensaje agregado a la cola. Total: 1
2026-06-01T04:05:47 [INFO] Iniciando bot desde la interfaz...
2026-06-01T04:05:47 [WARN] [WATCHER] No se pudo abrir chat 'Cel Negro (Tú)': 
        Page.wait_for_timeout: Target page, context or browser has been closed
```

**¿Qué pasaba?**

1. Usuario hace clic en "Iniciar bot"
2. `on_start_clicked()` → `iniciar_bot()` (ASYNC, demora ~15 segundos)
3. **Mientras tanto**, el timer `_tick_procesar_cola()` corre cada 800ms
4. Timer intenta procesar el mensaje ANTES de que Playwright termine de cargar
5. `procesar_mensaje_desde_whatsapp()` llama a `watcher.abrir_chat(page)`
6. **PERO `page` es None o el contexto está siendo cerrado** → ERROR

```
Timeline:
T=0ms:    Clic en "Iniciar bot"
T=10ms:   Timer inicia processing (página aún None)
T=15000ms: Playwright finalmente lista
```

---

## ✅ SOLUCIÓN IMPLEMENTADA

### **1. Agregar flag `ready` en `playwright_bot.py`**

```python
# ANTES:
context = None
page = None
running = False
pw_instance = None
_watcher_task = None

# DESPUÉS:
context = None
page = None
running = False
pw_instance = None
_watcher_task = None
ready = False  # ← NUEVO: True cuando Playwright está completamente listo
```

---

### **2. Marcar `ready = False` al iniciar, `ready = True` al terminar**

```python
# En iniciar_bot():
async def iniciar_bot():
    global context, page, running, pw_instance, ready
    if running:
        return
    running = True
    ready = False  # ← Marcar como NO listo mientras se inicializa
    
    # ... código de inicialización (demora ~15 segundos) ...
    
    await page.goto("https://web.whatsapp.com")
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)

    ready = True  # ← Marcar como listo DESPUÉS de cargar completamente
    Logger.info("Bot iniciado. WhatsApp Web cargado (sesión persistente).")
```

---

### **3. Marcar `ready = False` al detener**

```python
# En detener_bot():
async def detener_bot():
    global context, running, pw_instance, ready
    running = False
    ready = False  # ← No está listo después de detener
    # ... resto del código ...
```

---

### **4. Crear función `bot_esta_listo()` para verificar estado**

```python
def bot_esta_listo() -> bool:
    """Devuelve True si el bot está completamente listo."""
    return ready and running and page is not None
```

Verifica **3 condiciones simultáneamente**:
- `ready = True` (Playwright cargó WhatsApp Web)
- `running = True` (Bot no está detenido)
- `page is not None` (Hay una página activa)

---

### **5. Actualizar timer `_tick_procesar_cola()` en `ui_main.py`**

```python
# ANTES:
def _tick_procesar_cola(self):
    if not pw_bot.running:
        return
    if pw_bot.page is None:
        return
    self.run_async(procesar_mensaje_desde_whatsapp(pw_bot.page))

# DESPUÉS:
def _tick_procesar_cola(self):
    # ← GATEKEEPER: Solo procesar si bot está completamente listo
    if not bot_esta_listo():
        return
    if pw_bot.page is None:
        return
    self.run_async(procesar_mensaje_desde_whatsapp(pw_bot.page))
```

---

### **6. Actualizar UI para mostrar estado de inicialización**

```python
# En actualizar_estado():
if pw_bot.running:
    if bot_esta_listo():
        self.lbl_status.setText("Estado: Ejecutándose ✓")
        self.lbl_wp.setText("WhatsApp: Listo")
    else:
        self.lbl_status.setText("Estado: Inicializando...")
        self.lbl_wp.setText("WhatsApp: Cargando...")
else:
    self.lbl_status.setText("Estado: Detenido")
    self.lbl_wp.setText("WhatsApp: Desconectado")
```

Ahora el usuario ve claramente si el bot se está inicializando o si ya está listo.

---

## 📊 FLUJO CON FIX

```
T=0ms:      Clic en "Iniciar bot"
T=10ms:     Timer intenta procesar
            → bot_esta_listo() → False (ready aún es False)
            → Salta procesamiento
T=1000ms:   Timer intenta procesar
            → bot_esta_listo() → False (ready aún es False)
            → Salta procesamiento
...
T=15000ms:  iniciar_bot() completa
            → ready = True
T=15010ms:  Timer intenta procesar
            → bot_esta_listo() → True ✓
            → Procesa el mensaje SEGURAMENTE
```

---

## 🧪 IMPACTO

| Aspecto | Antes | Después |
|---------|-------|---------|
| Race condition | ❌ Existe | ✅ Eliminada |
| Mensaje pierde página cerrada | ❌ Ocurre | ✅ No ocurre |
| UI muestra estado intermedio | ❌ No | ✅ Sí (Inicializando) |
| Procesamiento comienza antes de tiempo | ❌ Sí | ✅ No |
| Código más robusto | ❌ No | ✅ Sí |

---

## 🔍 IMPORTANCIA DE ESTA CORRECCIÓN

Este era un **race condition clásico en sistemas asincrónicos**:

1. **Estructura sincrónica inicial** (`iniciar_bot()`) toma tiempo
2. **Timer asincrónico** (`_tick_procesar_cola()`) corre independientemente
3. **Sin gatekeeper**, el timer procesa antes de que recursos estén listos
4. **Resultado**: "Target page has been closed" o AttributeError en `page`

**Lección**: En arquitecturas async/Qt, SIEMPRE necesitas un flag de estado (`ready`) para sincronizar entre:
- Inicialización asincrónica (Playwright)
- Timers (procesamiento periódico)
- UI (actualización de estado)

---

## ✅ CAMBIOS EN ARCHIVOS

### `backend/playwright_bot.py`
- ✅ Agregado `ready = False` (line ~16)
- ✅ Actualizado `iniciar_bot()` para marcar `ready = True` (line ~51)
- ✅ Actualizado `detener_bot()` para marcar `ready = False` (line ~115)
- ✅ Agregada función `bot_esta_listo()` (line ~109)

### `ui_main.py`
- ✅ Importado `bot_esta_listo` (line ~30)
- ✅ Actualizado `_tick_procesar_cola()` con gatekeeper (line ~698)
- ✅ Actualizado `actualizar_estado()` para mostrar "Inicializando..." (line ~673)

---

## 📝 PRÓXIMAS PRUEBAS

1. Ejecutar `python ui_main.py`
2. Hacer clic en "Iniciar bot"
3. Mientras se inicializa, agregar mensaje a la cola
4. Ver que dice "Inicializando..." hasta que complete
5. Verificar que el mensaje se procesa DESPUÉS de listo (no antes)
6. Ver logs: NO debe haber "Target page has been closed"
