import sys
import asyncio
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QIcon, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTextEdit,
    QListWidget,
    QListWidgetItem,
    QFrame,
    QTabWidget,
    QLineEdit,
    QSpinBox,
    QGridLayout,
)
from pathlib import Path

# ============================
# IMPORTS BACKEND REAL
# ============================

from backend.logger import Logger
from backend.queue import agregarMensajeACola, obtener_tamano_cola, comenzar_procesamiento, terminar_procesamiento, cola_en_proceso
import backend.playwright_bot as pw_bot
from backend.playwright_bot import (
    iniciar_bot,
    detener_bot,
    iniciar_escucha,
    detener_escucha,
    escucha_activa,
    bot_esta_listo,
    procesando_plantilla,   # ← IMPORTANTE
)
from backend.file_watcher import iniciar_file_watcher, detener_file_watcher, file_watcher_activo
from backend.core import procesar_mensaje_desde_whatsapp
from backend.motor import get_tecnicos, agregar_tecnico, eliminar_tecnico, get_chats_monitoreados, set_tecnico_activo
from backend.config import cargar_config, guardar_config

# ============================
# ESTILO COPILOT OSCURO (QSS)
# ============================

COPILOT_DARK_QSS = """
QMainWindow {
    background-color: #050814;
}

QWidget {
    background-color: #050814;
    color: #F5F7FF;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}

QLabel#TitleLabel {
    font-size: 18pt;
    font-weight: 600;
    color: #F5F7FF;
}

QLabel#SubtitleLabel {
    font-size: 10pt;
    color: #9CA3AF;
}

QFrame#Card {
    background-color: #0B1020;
    border-radius: 12px;
    border: 1px solid #1F2937;
}

QPushButton {
    background-color: #1D4ED8;
    color: #F9FAFB;
    border-radius: 8px;
    padding: 8px 16px;
    border: none;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #2563EB;
}

QPushButton:pressed {
    background-color: #1E40AF;
}

QPushButton#DangerButton {
    background-color: #B91C1C;
}

QPushButton#DangerButton:hover {
    background-color: #DC2626;
}

QPushButton#DangerButton:pressed {
    background-color: #7F1D1D;
}

QPushButton#ListenButton {
    background-color: #065F46;
}

QPushButton#ListenButton:hover {
    background-color: #047857;
}

QPushButton#ListenButton:pressed {
    background-color: #064E3B;
}

QTextEdit, QListWidget, QLineEdit {
    background-color: #020617;
    border-radius: 8px;
    border: 1px solid #1F2937;
    color: #E5E7EB;
}

QTabWidget::pane {
    border: none;
}

QTabBar::tab {
    background-color: #020617;
    color: #9CA3AF;
    padding: 6px 14px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
}

QTabBar::tab:selected {
    background-color: #0B1120;
    color: #F9FAFB;
}

QSpinBox {
    background-color: #020617;
    border-radius: 6px;
    border: 1px solid #1F2937;
    color: #E5E7EB;
    padding: 2px 6px;
}
"""


# ============================
# CLASE PRINCIPAL
# ============================

class MainWindow(QMainWindow):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        super().__init__()

        self.loop = loop
        self.procesando = False  # ← LOCK LOCAL (UI)
        self._loading_config = True
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.timeout.connect(self._guardar_configuracion_silenciosa)

        self.setWindowTitle("Objeciones - Panel (Estilo Copilot)")
        self.setMinimumSize(1100, 650)
        self.setWindowIcon(QIcon())

        central = QWidget()
        self.setCentralWidget(central)

        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(16)

        left_panel = self._build_left_panel()
        right_panel = self._build_right_panel()

        root_layout.addWidget(left_panel, 1)
        root_layout.addWidget(right_panel, 2)

        Logger.callbacks.append(self.append_log)

        self.config = cargar_config()
        Logger.info(f"[CONFIG] Cargada configuración desde config.json")

        # Timers
        self.timer_estado = QTimer()
        self.timer_estado.timeout.connect(self.actualizar_estado)
        self.timer_estado.start(1000)

        self.timer_procesar = QTimer()
        self.timer_procesar.timeout.connect(self._tick_procesar_cola)
        self.timer_procesar.start(800)

        # Cargar lista de técnicos
        self._recargar_lista_tecnicos()

        self._aplicar_configuracion()
        self._conectar_autoguardado()
        self._loading_config = False

    # -------------------------
    # PANEL IZQUIERDO
    # -------------------------

    def _build_left_panel(self) -> QWidget:
        container = QFrame()
        container.setObjectName("Card")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Bot de Objeciones")
        title.setObjectName("TitleLabel")

        subtitle = QLabel("Técnicos configurados")
        subtitle.setObjectName("SubtitleLabel")

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(8)

        self.lbl_status = QLabel("Estado: Detenido")
        self.lbl_status.setObjectName("SubtitleLabel")

        self.lbl_wp = QLabel("WhatsApp: Desconectado")
        self.lbl_wp.setObjectName("SubtitleLabel")

        self.lbl_cola = QLabel("Cola de mensajes: 0")
        self.lbl_cola.setObjectName("SubtitleLabel")

        self.lbl_chats = QLabel("Chats monitoreados: 0")
        self.lbl_chats.setObjectName("SubtitleLabel")

        layout.addWidget(self.lbl_status)
        layout.addWidget(self.lbl_wp)
        layout.addWidget(self.lbl_cola)
        layout.addWidget(self.lbl_chats)

        layout.addSpacing(12)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("Iniciar bot")
        self.btn_stop = QPushButton("Detener bot")
        self.btn_stop.setObjectName("DangerButton")

        self.btn_start.clicked.connect(self.on_start_clicked)
        self.btn_stop.clicked.connect(self.on_stop_clicked)

        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        layout.addLayout(btn_row)

        layout.addSpacing(8)

        self.lbl_escucha = QLabel("Escucha: Inactiva")
        self.lbl_escucha.setObjectName("SubtitleLabel")
        layout.addWidget(self.lbl_escucha)

        self.btn_escucha = QPushButton("▶ Iniciar escucha")
        self.btn_escucha.setObjectName("ListenButton")
        self.btn_escucha.clicked.connect(self.on_escucha_clicked)
        layout.addWidget(self.btn_escucha)

        layout.addSpacing(16)

        lbl_last = QLabel("Última plantilla generada")
        lbl_last.setObjectName("SubtitleLabel")
        layout.addWidget(lbl_last)

        self.txt_last_template = QTextEdit()
        self.txt_last_template.setReadOnly(True)
        self.txt_last_template.setMinimumHeight(260)
        layout.addWidget(self.txt_last_template)

        layout.addStretch(1)
        return container

    # -------------------------
    # PANEL DERECHO
    # -------------------------

    def _build_right_panel(self) -> QWidget:
        container = QFrame()
        container.setObjectName("Card")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        tabs = QTabWidget()
        tabs.addTab(self._build_logs_tab(), "Logs")
        tabs.addTab(self._build_tecnicos_tab(), "Técnicos")
        tabs.addTab(self._build_test_tab(), "Pruebas")
        tabs.addTab(self._build_config_tab(), "Configuración")

        layout.addWidget(tabs)
        return container

    # -------------------------
    # TAB LOGS
    # -------------------------

    def _build_logs_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(8)

        self.txt_logs = QTextEdit()
        self.txt_logs.setReadOnly(True)
        l.addWidget(self.txt_logs)
        return w

    # -------------------------
    # TAB TÉCNICOS
    # -------------------------

    def _build_tecnicos_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(8)

        lbl_lista = QLabel("Técnicos configurados")
        lbl_lista.setObjectName("SubtitleLabel")
        l.addWidget(lbl_lista)

        self.list_tecnicos = QListWidget()
        self.list_tecnicos.setMinimumHeight(160)
        self.list_tecnicos.itemChanged.connect(self._on_tecnico_check_changed)
        l.addWidget(self.list_tecnicos)

        btn_row_lista = QHBoxLayout()
        btn_actualizar = QPushButton("Actualizar lista")
        btn_actualizar.clicked.connect(self._recargar_lista_tecnicos)
        btn_eliminar = QPushButton("Eliminar seleccionado")
        btn_eliminar.setObjectName("DangerButton")
        btn_eliminar.clicked.connect(self._eliminar_tecnico_seleccionado)
        btn_row_lista.addWidget(btn_actualizar)
        btn_row_lista.addWidget(btn_eliminar)
        l.addLayout(btn_row_lista)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        l.addWidget(sep)

        lbl_form = QLabel("Agregar técnico nuevo")
        lbl_form.setObjectName("SubtitleLabel")
        l.addWidget(lbl_form)

        grid = QGridLayout()
        grid.setSpacing(6)

        grid.addWidget(QLabel("Nombre del chat WhatsApp:"), 0, 0)
        self.txt_chat = QLineEdit()
        self.txt_chat.setPlaceholderText("Debe coincidir EXACTAMENTE con el nombre en WhatsApp")
        grid.addWidget(self.txt_chat, 0, 1)

        grid.addWidget(QLabel("Nombre completo técnico:"), 1, 0)
        self.txt_nombre_tec = QLineEdit()
        grid.addWidget(self.txt_nombre_tec, 1, 1)

        grid.addWidget(QLabel("Expediente:"), 2, 0)
        self.txt_exp = QLineEdit()
        grid.addWidget(self.txt_exp, 2, 1)

        grid.addWidget(QLabel("Teléfono:"), 3, 0)
        self.txt_tel_tec = QLineEdit()
        grid.addWidget(self.txt_tel_tec, 3, 1)

        grid.addWidget(QLabel("COPE:"), 4, 0)
        self.txt_cope = QLineEdit("CTSIL")
        grid.addWidget(self.txt_cope, 4, 1)

        l.addLayout(grid)

        btn_agregar = QPushButton("Agregar técnico")
        btn_agregar.clicked.connect(self._agregar_tecnico)
        l.addWidget(btn_agregar)

        return w

    def _recargar_lista_tecnicos(self):
        self.list_tecnicos.blockSignals(True)
        self.list_tecnicos.clear()
        for t in get_tecnicos():
            texto = f"{t['nombreChat']} · {t['nombreTecnico']} · {t['cope']}"
            item = QListWidgetItem(texto)
            item.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            estado = Qt.CheckState.Checked if t.get("activo", True) else Qt.CheckState.Unchecked
            item.setCheckState(estado)
            self.list_tecnicos.addItem(item)
        self.list_tecnicos.blockSignals(False)

    def _on_tecnico_check_changed(self, item: QListWidgetItem):
        texto = item.text()
        nombre_chat = texto.split(" · ")[0]
        if nombre_chat.endswith("(Tú)"):
            Logger.warn("No puedes monitorear tu propio chat '(Tú)'.")
            item.setCheckState(Qt.CheckState.Unchecked)
            return
        activo = item.checkState() == Qt.CheckState.Checked
        set_tecnico_activo(nombre_chat, activo)

    def _eliminar_tecnico_seleccionado(self):
        item = self.list_tecnicos.currentItem()
        if not item:
            Logger.warn("No hay técnico seleccionado para eliminar.")
            return
        nombre_chat = item.text().split(" · ")[0]
        ok = eliminar_tecnico(nombre_chat)
        if ok:
            self._recargar_lista_tecnicos()
            Logger.info(f"Técnico '{nombre_chat}' eliminado desde la UI.")
        else:
            Logger.warn(f"No se encontró el técnico '{nombre_chat}' para eliminar.")

    def _agregar_tecnico(self):
        ok = agregar_tecnico(
            nombreChat=self.txt_chat.text().strip(),
            nombreTecnico=self.txt_nombre_tec.text().strip(),
            expediente=self.txt_exp.text().strip(),
            telefono=self.txt_tel_tec.text().strip(),
            cope=self.txt_cope.text().strip(),
        )
        if ok:
            self._recargar_lista_tecnicos()
            for w in [self.txt_chat, self.txt_nombre_tec, self.txt_exp, self.txt_tel_tec]:
                w.clear()
            Logger.info("Técnico agregado desde la UI.")
        else:
            Logger.warn("No se pudo agregar el técnico (ya existe o datos inválidos).")

    # -------------------------
    # TAB PRUEBAS
    # -------------------------

    def _build_test_tab(self) -> QWidget:
        w = QWidget()
        l = QVBoxLayout(w)
        l.setContentsMargins(8, 8, 8, 8)
        l.setSpacing(8)

        lbl = QLabel("Prueba de extracción y plantilla")
        lbl.setObjectName("SubtitleLabel")
        l.addWidget(lbl)

        self.txt_test_input = QTextEdit()
        self.txt_test_input.setPlaceholderText("Pega aquí una OS o mensaje de técnico para probar...")
        l.addWidget(self.txt_test_input)

        btn = QPushButton("Simular envío a la cola")
        btn.clicked.connect(self.on_test_generate)
        l.addWidget(btn)

        self.txt_test_output = QTextEdit()
        self.txt_test_output.setReadOnly(True)
        l.addWidget(self.txt_test_output)

        return w

    # -------------------------
    # TAB CONFIG
    # -------------------------

    def _build_config_tab(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(8, 8, 8, 8)
        grid.setSpacing(8)

        row = 0

        lbl_delay = QLabel("Delay entre mensajes (ms):")
        lbl_delay.setObjectName("SubtitleLabel")
        self.spin_delay = QSpinBox()
        self.spin_delay.setRange(50, 5000)
        self.spin_delay.setValue(300)
        grid.addWidget(lbl_delay, row, 0)
        grid.addWidget(self.spin_delay, row, 1)
        row += 1

        lbl_retries = QLabel("Reintentos Playwright:")
        lbl_retries.setObjectName("SubtitleLabel")
        self.spin_retries = QSpinBox()
        self.spin_retries.setRange(1, 10)
        self.spin_retries.setValue(3)
        grid.addWidget(lbl_retries, row, 0)
        grid.addWidget(self.spin_retries, row, 1)
        row += 1

        lbl_area = QLabel("Área:")
        lbl_area.setObjectName("SubtitleLabel")
        self.txt_area = QLineEdit("")
        grid.addWidget(lbl_area, row, 0)
        grid.addWidget(self.txt_area, row, 1)
        row += 1

        lbl_super = QLabel("Supervisor:")
        lbl_super.setObjectName("SubtitleLabel")
        self.txt_super = QLineEdit("")
        grid.addWidget(lbl_super, row, 0)
        grid.addWidget(self.txt_super, row, 1)
        row += 1

        lbl_empresa = QLabel("Empresa:")
        lbl_empresa.setObjectName("SubtitleLabel")
        self.txt_empresa = QLineEdit("")
        grid.addWidget(lbl_empresa, row, 0)
        grid.addWidget(self.txt_empresa, row, 1)
        row += 1

        # Separador
        sep_fw = QFrame()
        sep_fw.setFrameShape(QFrame.Shape.HLine)
        sep_fw.setFrameShadow(QFrame.Shadow.Sunken)
        grid.addWidget(sep_fw, row, 0, 1, 2)
        row += 1

        lbl_fw_title = QLabel("📁 Monitor de carpeta (Watchdog)")
        lbl_fw_title.setObjectName("SubtitleLabel")
        grid.addWidget(lbl_fw_title, row, 0, 1, 2)
        row += 1

        lbl_carpeta = QLabel("Carpeta a monitorear:")
        lbl_carpeta.setObjectName("SubtitleLabel")
        self.txt_carpeta = QLineEdit(str(Path(__file__).resolve().parent / "ordenes"))
        grid.addWidget(lbl_carpeta, row, 0)
        grid.addWidget(self.txt_carpeta, row, 1)
        row += 1

        lbl_chat_fw = QLabel("Chat destino para archivos:")
        lbl_chat_fw.setObjectName("SubtitleLabel")
        self.txt_chat_fw = QLineEdit("")
        grid.addWidget(lbl_chat_fw, row, 0)
        grid.addWidget(self.txt_chat_fw, row, 1)
        row += 1

        lbl_perfil = QLabel("Perfil Playwright (sesión):")
        lbl_perfil.setObjectName("SubtitleLabel")
        self.txt_perfil = QLineEdit(str(Path(__file__).resolve().parent / "playwright_profile"))
        grid.addWidget(lbl_perfil, row, 0)
        grid.addWidget(self.txt_perfil, row, 1)
        row += 1

        btn_fw_row = QHBoxLayout()
        self.btn_fw_start = QPushButton("▶ Iniciar Watchdog")
        self.btn_fw_start.setObjectName("ListenButton")
        self.btn_fw_start.clicked.connect(self._on_fw_start)
        self.btn_fw_stop = QPushButton("⏹ Detener Watchdog")
        self.btn_fw_stop.setObjectName("DangerButton")
        self.btn_fw_stop.clicked.connect(self._on_fw_stop)
        btn_fw_row.addWidget(self.btn_fw_start)
        btn_fw_row.addWidget(self.btn_fw_stop)
        grid.addLayout(btn_fw_row, row, 0, 1, 2)
        row += 1

        self.lbl_fw_status = QLabel("Watchdog: Inactivo")
        self.lbl_fw_status.setObjectName("SubtitleLabel")
        grid.addWidget(self.lbl_fw_status, row, 0, 1, 2)
        row += 1

        # Botón guardar configuración
        grid.addWidget(QFrame(), row, 0, 1, 2)
        row += 1
        btn_guardar_config = QPushButton("💾 Guardar configuración")
        btn_guardar_config.clicked.connect(self._guardar_configuracion)
        grid.addWidget(btn_guardar_config, row, 0, 1, 2)
        row += 1

        grid.setRowStretch(row, 1)
        return w

    # -------------------------
    # HANDLERS
    # -------------------------

    def on_start_clicked(self):
        if pw_bot.running:
            return
        Logger.info("Iniciando bot desde la interfaz...")
        self.run_async(iniciar_bot())
        self.lbl_status.setText("Estado: Ejecutándose")
        self.lbl_wp.setText("WhatsApp: Esperando conexión...")

    def on_stop_clicked(self):
        if not pw_bot.running:
            return
        Logger.warn("Deteniendo bot desde la interfaz...")
        self.run_async(detener_bot())
        self.lbl_status.setText("Estado: Detenido")
        self.lbl_wp.setText("WhatsApp: Desconectado")

    def on_escucha_clicked(self):
        if not pw_bot.running:
            Logger.warn("El bot no está activo. Inicia el bot antes de iniciar la escucha.")
            return
        if escucha_activa():
            self.run_async(detener_escucha())
            self.btn_escucha.setText("▶ Iniciar escucha")
            self.lbl_escucha.setText("Escucha: Inactiva")
        else:
            self.run_async(iniciar_escucha())
            self.btn_escucha.setText("⏹ Detener escucha")
            self.lbl_escucha.setText("Escucha: Activa ✓")

    def on_test_generate(self):
        texto = self.txt_test_input.toPlainText().strip()
        if not texto:
            self.txt_test_output.setPlainText("No hay texto de prueba.")
            return

        item = self.list_tecnicos.currentItem()
        if not item:
            Logger.warn("No hay técnico seleccionado.")
            self.txt_test_output.setPlainText("Error: Selecciona un técnico de la lista.")
            return

        nombre_chat = item.text().split(" · ")[0]

        ctx = {
            "nombreChat": nombre_chat,
            "mensaje": texto,
        }
        agregarMensajeACola(ctx)
        Logger.info(f"Mensaje de prueba agregado a la cola para '{nombre_chat}' desde la interfaz.")
        self.txt_test_output.setPlainText(
            f"Plantilla enviada a la cola para {nombre_chat}.\nVerifica la ejecución en la pestaña de logs..."
        )

    def _on_fw_start(self):
        carpeta = self.txt_carpeta.text().strip()
        chat_dest = self.txt_chat_fw.text().strip()
        if not carpeta or not chat_dest:
            Logger.warn("Watchdog: debes especificar carpeta y chat destino.")
            return
        ok = iniciar_file_watcher(carpeta, chat_dest)
        if ok:
            Logger.info(f"Watchdog iniciado: {carpeta} → {chat_dest}")
        else:
            Logger.warn("Watchdog: no se pudo iniciar (ya activo o error de carpeta).")

    def _on_fw_stop(self):
        detener_file_watcher()
        Logger.info("Watchdog detenido.")

    def _guardar_configuracion(self):
        config = {
            "delay_ms": self.spin_delay.value(),
            "reintentos": self.spin_retries.value(),
            "area": self.txt_area.text().strip(),
            "supervisor": self.txt_super.text().strip(),
            "empresa": self.txt_empresa.text().strip(),
            "carpeta_watchdog": self.txt_carpeta.text().strip(),
            "chat_archivos": self.txt_chat_fw.text().strip(),
            "perfil_playwright": self.txt_perfil.text().strip(),
        }
        if guardar_config(config):
            self.config = config
            Logger.info("✓ Configuración guardada exitosamente.")
        else:
            Logger.warn("✗ Error guardando configuración.")

    def _guardar_configuracion_silenciosa(self):
        if self._loading_config:
            return
        self._guardar_configuracion()

    def _conectar_autoguardado(self):
        self.spin_delay.valueChanged.connect(self._schedule_config_save)
        self.spin_retries.valueChanged.connect(self._schedule_config_save)
        for widget in [
            self.txt_area,
            self.txt_super,
            self.txt_empresa,
            self.txt_carpeta,
            self.txt_chat_fw,
            self.txt_perfil,
        ]:
            widget.textChanged.connect(self._schedule_config_save)

    def _schedule_config_save(self, *_):
        if self._loading_config:
            return
        self._autosave_timer.start(400)

    def _aplicar_configuracion(self):
        self.spin_delay.setValue(int(self.config.get("delay_ms", 300)))
        self.spin_retries.setValue(int(self.config.get("reintentos", 3)))
        self.txt_area.setText(self.config.get("area", ""))
        self.txt_super.setText(self.config.get("supervisor", ""))
        self.txt_empresa.setText(self.config.get("empresa", ""))
        self.txt_carpeta.setText(self.config.get("carpeta_watchdog", ""))
        self.txt_chat_fw.setText(self.config.get("chat_archivos", ""))
        self.txt_perfil.setText(self.config.get("perfil_playwright", ""))

    # -------------------------
    # ESTADO Y COLA
    # -------------------------

    def actualizar_estado(self):
        tam = obtener_tamano_cola()
        self.lbl_cola.setText(f"Cola de mensajes: {tam}")
        self.lbl_chats.setText(f"Chats monitoreados: {len(get_chats_monitoreados())}")
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

        if escucha_activa():
            self.lbl_escucha.setText("Escucha: Activa ✓")
            self.btn_escucha.setText("⏹ Detener escucha")
        else:
            self.lbl_escucha.setText("Escucha: Inactiva")
            self.btn_escucha.setText("▶ Iniciar escucha")

        if hasattr(self, "lbl_fw_status"):
            if file_watcher_activo():
                self.lbl_fw_status.setText("Watchdog: Activo ✓")
                self.btn_fw_start.setEnabled(False)
                self.btn_fw_stop.setEnabled(True)
            else:
                self.lbl_fw_status.setText("Watchdog: Inactivo")
                self.btn_fw_start.setEnabled(True)
                self.btn_fw_stop.setEnabled(False)

    def _tick_procesar_cola(self):
        # No procesar si el bot no está listo
        if not bot_esta_listo():
            return
        # No procesar si Playwright no tiene página
        if pw_bot.page is None:
            return
        # No procesar si ya hay una plantilla en curso (flag global)
        if procesando_plantilla:
            return
        # No procesar si ya hay una corrutina de procesamiento en curso (lock UI)
        if self.procesando or cola_en_proceso():
            return

        if not comenzar_procesamiento():
            return
        self.procesando = True

        async def _wrap():
            try:
                plantilla = await procesar_mensaje_desde_whatsapp(pw_bot.page)
                if plantilla:
                    self.txt_last_template.setPlainText(plantilla)
            finally:
                self.procesando = False
                terminar_procesamiento()

        self.run_async(_wrap())

    # -------------------------
    # LOGS
    # -------------------------

    def append_log(self, line: str):
        self.txt_logs.append(line)
        self.txt_logs.moveCursor(QTextCursor.MoveOperation.End)

    # -------------------------
    # UTILIDAD ASYNC
    # -------------------------

    def run_async(self, coro):
        self.loop.create_task(coro)


# ============================
# MAIN
# ============================

def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(COPILOT_DARK_QSS)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    win = MainWindow(loop)
    win.show()

    def _tick_asyncio():
        loop.call_soon(loop.stop)
        loop.run_forever()

    async_timer = QTimer()
    async_timer.timeout.connect(_tick_asyncio)
    async_timer.start(10)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
