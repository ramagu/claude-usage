"""CLAUDE USAGE — uso de los límites de Claude en el área de notificación.

Utilidad de bandeja de Windows en un solo archivo, solo biblioteca estándar.
tkinter para el panel, ctypes contra la API de Windows para el icono, los
avisos y el cifrado de la clave.

    pythonw ClaudeUsage.pyw            abre el panel al arrancar
    pythonw ClaudeUsage.pyw --silent   arranca solo en la bandeja

Interacción con el icono:
  - Pasar el ratón: tarjeta con todos los límites y la proyección.
  - Clic izquierdo: abre y cierra el panel. Se cierra también con Esc o con
    la X de la cabecera; el programa sigue en la bandeja.
  - Clic derecho: menú contextual nativo (abrir, actualizar, inicio con
    Windows, acerca de, salir).

Datos de cada usuario, en %LOCALAPPDATA%\\ClaudeUsage (nunca en una carpeta
compartida: la SessionKey es personal):
  - config.json      preferencias, avisos ya enviados y la clave cifrada (DPAPI)
  - historial.db     lecturas de los últimos 730 días (SQLite)
  - diagnostico.log  registro de cambios de estado, sin datos sensibles

La aplicación usa la interfaz interna de claude.ai, no una API pública. Puede
dejar de funcionar si Claude la cambia. Claude y sus marcas pertenecen a
Anthropic; esta herramienta no es un producto oficial de Anthropic.

Copyright (C) 2026 ramagu. Software libre bajo la licencia GNU GPL v3: puede
redistribuirse y modificarse en sus términos, SIN NINGUNA GARANTÍA. Texto
completo en LICENSE. El logo de Claude no está cubierto por esta licencia.
"""

from __future__ import annotations

import base64
import csv
import json
import math
import os
import queue
import re
import sqlite3
import struct
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.error
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "1.2.0"
APP_NAME = "ClaudeUsage"
TITULO = "Claude Usage"

ES_WINDOWS = sys.platform == "win32"


# =========================================================================== #
# Aspecto — Nocturne
# =========================================================================== #
C = {
    "fondo": "#1D1F2D",          # panel
    "fondo_pie": "#191B28",
    "hundido": "#161826",        # campos de texto
    "superficie": "#232532",     # menú
    "banda": "#2B2741",          # cabecera del menú, hover de botones
    "banda_borde": "#423A6A",
    "linea": "#2C2E3B",
    "borde": "#3F424D",
    "pista": "#292B31",          # fondo de las barras
    "gris_barra": "#595D6C",
    "texto": "#E9E9ED",
    "texto_2": "#CFD3E5",
    "suave": "#B2B6CA",
    "tenue": "#9397AB",
    "muy_tenue": "#75798C",
    "acento": "#9184D9",
    "acento_claro": "#D2CEFD",
    "acento_medio": "#B5ABFC",
}
AZUL = "#3B82F6"      # icono genérico: sin cuenta, cargando, menú
GRIS = "#91919B"      # sin conexión o sesión caducada

# Paleta optimizada en OKLCH. "oscuro": panel y barra de tareas oscura.
# "claro": solo el icono cuando Windows usa la barra de tareas clara.
PALETAS = {
    "normal": {
        "oscuro": {"green": "#0BE35E", "yellow": "#FFDE09", "orange": "#FE7802", "red": "#F12941"},
        "claro": {"green": "#048634", "yellow": "#938010", "orange": "#AC5107", "red": "#BA0329"},
        "nombres": {"green": "Verde", "yellow": "Amarillo", "orange": "Naranja", "red": "Rojo"},
    },
    "accesible": {
        "oscuro": {"green": "#63B0FC", "yellow": "#FFD16B", "orange": "#FD6A25", "red": "#DF2187"},
        "claro": {"green": "#066BB8", "yellow": "#A1790C", "orange": "#B44200", "red": "#B30169"},
        "nombres": {"green": "Azul", "yellow": "Ámbar", "orange": "Bermellón", "red": "Magenta"},
    },
}
ORDEN_COLORES = ("green", "yellow", "orange", "red")
UMBRALES_DEFECTO = [[0, "green"], [50, "yellow"], [70, "orange"], [85, "red"]]
MAX_TRAMOS = 4

FAMILIAS = ("Inter", "Segoe UI Variable Text", "Segoe UI")
FAMILIA_MONO = ("Cascadia Mono", "Consolas")

ANCHO_PANEL = 344
REFRESCOS = (30, 60, 120, 300)
DIAS_HISTORIAL = 730
VENTANA_5H = 5 * 3600
VENTANA_SEMANA = 7 * 86400
TOLERANCIA_SESION = 300        # segundos: resets_at varía unos segundos entre lecturas
FALLOS_PARA_AVISO = 3

LIMIT_LABELS = {
    "five_hour": "5 h",
    "seven_day": "Semana",
    "seven_day_oauth": "Semana",
    "seven_day_opus": "Opus",
    "seven_day_sonnet": "Sonnet",
    "seven_day_haiku": "Haiku",
    "seven_day_fable": "Fable",
}
CLAVES_SEMANA = ("seven_day", "seven_day_oauth")
MAX_FILAS_LIMITES = 6

PASOS_SESSIONKEY = (
    ("Abre claude.ai en Chrome o Edge con tu cuenta iniciada.", ""),
    ("Pulsa F12 para abrir las herramientas de desarrollo.", "F12  ·  Ctrl+Mayús+I"),
    ("Arriba, entra en la pestaña Application (Almacenamiento en Firefox). Si no aparece, pulsa ».", "Application"),
    ("En la columna izquierda, despliega Cookies y elige claude.ai.", "Storage › Cookies › https://claude.ai"),
    ("Escribe «session» en el filtro y selecciona la fila sessionKey.", "sessionKey"),
    ("Doble clic en la columna Value, Ctrl+A y Ctrl+C. Empieza así:", "sk-ant-sid01-…"),
    ("Pégala en el campo y pulsa Validar. Si cierras sesión en claude.ai, la clave deja de valer.", ""),
)

MESES_C = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
DIAS_C = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
DIAS_L = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES_C_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DIAS_C_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
DIAS_L_EN = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


# =========================================================================== #
# Idiomas — el texto de origen es el español; EN lo traduce al inglés
# =========================================================================== #
IDIOMAS = ("auto", "es", "en")

EN = {
    # Pasos para copiar la SessionKey
    "Abre claude.ai en Chrome o Edge con tu cuenta iniciada.": "Open claude.ai in Chrome or Edge, signed in to your account.",
    "Pulsa F12 para abrir las herramientas de desarrollo.": "Press F12 to open the developer tools.",
    "F12  ·  Ctrl+Mayús+I": "F12  ·  Ctrl+Shift+I",
    "Arriba, entra en la pestaña Application (Almacenamiento en Firefox). Si no aparece, pulsa ».":
        "At the top, open the Application tab (Storage in Firefox). If you can't see it, click ».",
    "En la columna izquierda, despliega Cookies y elige claude.ai.": "In the left column, expand Cookies and choose claude.ai.",
    "Escribe «session» en el filtro y selecciona la fila sessionKey.": "Type “session” in the filter and select the sessionKey row.",
    "Doble clic en la columna Value, Ctrl+A y Ctrl+C. Empieza así:": "Double-click the Value column, then Ctrl+A and Ctrl+C. It starts like this:",
    "Pégala en el campo y pulsa Validar. Si cierras sesión en claude.ai, la clave deja de valer.":
        "Paste it into the field and click Validate. If you sign out of claude.ai, the key stops working.",
    # Límites, fechas y tiempos
    "Semana": "Week",
    "ahora": "now",
    "Hoy": "Today",
    "Ayer": "Yesterday",
    "hoy": "today",
    "ayer": "yesterday",
    "{dia} {n} {mes}": "{dia}, {mes} {n}",
    "{n} {mes}": "{mes} {n}",
    # Errores de claude.ai que pueden llegar a verse
    "Bloqueado por Cloudflare": "Blocked by Cloudflare",
    "Respuesta no válida": "Invalid response",
    "Sin organizaciones": "No organizations",
    "La respuesta no contiene límites": "The response contains no limits",
    "Ninguna organización devuelve datos de uso": "No organization returns usage data",
    # Menú del icono y textos del icono
    "Abrir panel": "Open panel",
    "Cerrar panel": "Close panel",
    "Actualizar ahora": "Refresh now",
    "Iniciar con Windows": "Start with Windows",
    "Acerca de Claude Usage": "About Claude Usage",
    "Salir": "Quit",
    "sin configurar": "not set up",
    "cargando…": "loading…",
    "sesión caducada": "session expired",
    "sin conexión": "offline",
    "Claude · {nombre} {pct} · reinicia {cuando}": "Claude · {nombre} {pct} · resets {cuando}",
    # Avisos de Windows
    "SessionKey caducada": "SessionKey expired",
    "Haz clic aquí para pegar una nueva y seguir viendo el uso.": "Click here to paste a new one and keep tracking your usage.",
    "Sin conexión con claude.ai": "No connection to claude.ai",
    "Desde las {desde}. Se reintenta solo y se mantiene el último dato.":
        "Since {desde}. It retries on its own and keeps the last reading.",
    "de 5 h": "5-hour",
    "semanal": "weekly",
    "semanal de {modelo}": "{modelo} weekly",
    "Límite {nombre} disponible": "{nombre} limit available",
    "Se ha reiniciado a las {hora}. Vuelves a tener el 100 %.": "It reset at {hora}. You have 100% available again.",
    "hasta las {hora}": "until {hora}",
    "hasta el {cuando}": "until {cuando}",
    "Límite {nombre} alcanzado": "{nombre} limit reached",
    "No podrás usar Claude {cuando}, dentro de {falta}.": "You can't use Claude {cuando} (in {falta}).",
    "Sesión de 5 h al {v} %": "5-hour session at {v}%",
    "Reinicia a las {hora}, en {falta}.": "Resets at {hora}, in {falta}.",
    " A este ritmo llegarás al 100 % a las {hora}.": " At this pace you'll hit 100% at {hora}.",
    "Uso semanal al {v} %": "Weekly usage at {v}%",
    "{modelo} (semanal) al {v} %": "{modelo} (weekly) at {v}%",
    "Reinicia el {cuando}, en {falta}.": "Resets {cuando}, in {falta}.",
    # SessionKey
    "No es una SessionKey válida. Debe empezar por sk-ant-sid01- y copiarse entera, sin espacios.":
        "That's not a valid SessionKey. It must start with sk-ant-sid01- and be copied in full, without spaces.",
    "claude.ai ha rechazado la clave. Puede haber caducado: vuelve a copiarla.":
        "claude.ai rejected the key. It may have expired: copy it again.",
    "No se pudo comprobar la clave ({detalle}). Revisa la conexión.": "Couldn't check the key ({detalle}). Check your connection.",
    "No se pudo comprobar la clave ({detalle}).": "Couldn't check the key ({detalle}).",
    "La clave es válida, pero no se pudo guardar cifrada en este equipo.":
        "The key is valid, but it couldn't be saved encrypted on this computer.",
    # Cabecera
    "ACTUALIZAR": "REFRESH",
    "PLEGAR GRÁFICO": "HIDE CHARTS",
    "VER EVOLUCIÓN": "VIEW TRENDS",
    "MENÚ": "MENU",
    "CERRAR": "CLOSE",
    "Validando…": "Validating…",
    "Sin configurar": "Not set up",
    "Caducada · dato {hora}": "Expired · data from {hora}",
    "Sin conexión · dato {hora}": "Offline · data from {hora}",
    "Cargando…": "Loading…",
    "{hora} · cada {cada}": "{hora} · every {cada}",
    # Panel principal
    "Sin datos todavía.": "No data yet.",
    "Consultando claude.ai…": "Checking claude.ai…",
    "Sesión · 5 h": "Session · 5 h",
    "reinicia a las {hora}": "resets at {hora}",
    "en {falta}": "in {falta}",
    "ritmo ideal ahora {n} %": "ideal pace now {n}%",
    "en ritmo": "on pace",
    "{signo}{n} pts por encima": "{signo}{n} pts above",
    "{signo}{n} pts por debajo": "{signo}{n} pts below",
    "Semanales": "Weekly",
    "{cuando} · en {falta}": "{cuando} · in {falta}",
    "La SessionKey ha caducado": "Your SessionKey has expired",
    "Los datos son de las {hora}. Pega una nueva para seguir.": "Data is from {hora}. Paste a new one to continue.",
    "Renovar": "Renew",
    "No se puede conectar con claude.ai": "Can't connect to claude.ai",
    "{n} intentos fallidos. Se reintenta solo.": "{n} failed attempts. Retrying automatically.",
    "Reintentar": "Retry",
    "Conecta tu cuenta de Claude": "Connect your Claude account",
    "El widget lee tu uso con la SessionKey de tu sesión en claude.ai.":
        "The widget reads your usage with the SessionKey from your claude.ai session.",
    "Conectar": "Connect",
    "Se guarda cifrada con DPAPI solo para tu usuario de Windows. No la compartas.":
        "It's stored encrypted with DPAPI for your Windows user only. Don't share it.",
    "A este ritmo, 100 % a las {hora}": "At this pace, 100% at {hora}",
    "{falta} antes del reinicio · ritmo +{n} %/h": "{falta} before reset · pace +{n}%/h",
    "A este ritmo llegas al reinicio con {n} % sin usar": "At this pace, {n}% left unused at reset",
    "Ritmo +{n} %/h · reinicio a las {hora}": "Pace +{n}%/h · resets at {hora}",
    "Consumo estable": "Steady usage",
    "Reinicio a las {hora}": "Resets at {hora}",
    # Evolución de la sesión y consumo por minutos
    "Evolución de la sesión": "Session trend",
    "Uso real": "Actual usage",
    "Ritmo ideal": "Ideal pace",
    "Proyección": "Projection",
    "Consumo por minutos": "Usage by minute",
    "mayor pico · {r}× el ideal": "highest peak · {r}× ideal",
    "{r}× el ritmo ideal": "{r}× the ideal pace",
    "Bajo el ideal": "Below ideal",
    "Parejo": "On par",
    "Algo más": "A bit more",
    "Pico": "Peak",
    "Ritmo ideal {pct} cada {g} min (100 % en {h} h)": "Ideal pace {pct} every {g} min (100% in {h} h)",
    # Historial
    "Historial": "History",
    "Sesiones": "Sessions",
    "Uso semanal": "Weekly usage",
    "3 m": "3 mo",
    "6 m": "6 mo",
    "1 año": "1 yr",
    "2 años": "2 yrs",
    "{signo}{n} pts en {rango}": "{signo}{n} pts in {rango}",
    "media {n} %": "avg {n}%",
    "Semana a {fecha}": "Week as of {fecha}",
    "Todavía no hay sesiones cerradas en este periodo.": "No closed sessions in this period yet.",
    "Semanas anteriores": "Previous weeks",
    "Sesiones anteriores": "Previous sessions",
    "uso al cierre": "usage at close",
    "Semana del {n} {mes}": "Week of {mes} {n}",
    "llegó al límite": "hit the limit",
    "Exportar CSV": "Export CSV",
    "Guardado en {carpeta} · {archivo}": "Saved to {carpeta} · {archivo}",
    "No se pudo exportar el historial.": "Couldn't export the history.",
    "fecha_hora": "datetime",
    "limite": "limit",
    "uso_pct": "usage_pct",
    "reinicio": "resets_at",
    # Menú
    "Conexión": "Connection",
    "Caducada": "Expired",
    "Válida · cifrada con DPAPI": "Valid · encrypted with DPAPI",
    "Cerrar": "Close",
    "Validar": "Validate",
    "¿Cómo consigo la SessionKey?": "How do I get the SessionKey?",
    "Borrar campo": "Clear field",
    "Avisos": "Alerts",
    "Umbrales y color del icono": "Thresholds and icon color",
    "Editar": "Edit",
    "Desde": "From",
    "Notificaciones": "Notifications",
    "Umbrales de la sesión (5 h)": "Session thresholds (5 h)",
    "Umbrales semanales": "Weekly thresholds",
    "Avisar cuando se reinicie": "Notify when it resets",
    "Sonido": "Sound",
    "Preferencias": "Preferences",
    "Paleta accesible": "Accessible palette",
    "Refresco": "Refresh rate",
    "Idioma": "Language",
    "Volver": "Back",
    "Cómo conseguir la SessionKey": "How to get the SessionKey",
    # Tarjeta del icono
    "Clic para conectar tu cuenta": "Click to connect your account",
    "Sesión caducada · clic para renovar": "Session expired · click to renew",
    "Sin conexión · reintentando": "Offline · retrying",
    "A este ritmo, {n} % sin usar al reinicio": "At this pace, {n}% unused at reset",
    "Consumo estable · reinicia a las {hora}": "Steady usage · resets at {hora}",
    # Acerca de
    "Uso de los límites de Claude en la bandeja de Windows.": "Claude usage limits in the Windows system tray.",
    "Usa la interfaz interna de claude.ai: puede dejar de funcionar si Claude la cambia. "
    "Claude es una marca de Anthropic; esta herramienta no es oficial.":
        "Uses claude.ai's internal interface: it may stop working if Claude changes it. "
        "Claude is a trademark of Anthropic; this tool is not official.",
    "Datos": "Data",
}

_idioma = "es"


def idioma_sistema() -> str:
    """Español si Windows está en español, catalán, gallego o euskera; inglés en el resto."""
    if ES_WINDOWS:
        try:
            import ctypes
            primario = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
            return "es" if primario in (0x0A, 0x03, 0x56, 0x2D) else "en"
        except (AttributeError, OSError):
            pass
    return "es" if os.environ.get("LANG", "").lower().startswith(("es", "ca", "gl", "eu")) else "en"


def poner_idioma(preferencia: str) -> None:
    global _idioma
    _idioma = idioma_sistema() if preferencia == "auto" else preferencia


def T(texto: str, **campos) -> str:
    """Traduce un texto de la interfaz. Sin traducción, se queda en español."""
    if _idioma == "en":
        texto = EN.get(texto, texto)
    return texto.format(**campos) if campos else texto


def mes_c(d: datetime) -> str:
    return (MESES_C_EN if _idioma == "en" else MESES_C)[d.month - 1]


def dia_c(d: datetime) -> str:
    return (DIAS_C_EN if _idioma == "en" else DIAS_C)[d.weekday()]


def dia_l(d: datetime) -> str:
    return (DIAS_L_EN if _idioma == "en" else DIAS_L)[d.weekday()]


def nombre_limite(clave: str) -> str:
    if clave in LIMIT_LABELS:
        return T(LIMIT_LABELS[clave])
    return str(clave).replace("_", " ").strip().capitalize()


def ventana_limite(clave: str) -> int:
    return VENTANA_5H if clave == "five_hour" else VENTANA_SEMANA


# =========================================================================== #
# Rutas y registro
# =========================================================================== #
def esta_congelado() -> bool:
    return getattr(sys, "frozen", False)


def carpeta_base() -> Path:
    if esta_congelado():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def carpeta_config() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / APP_NAME
    return Path.home() / ".config" / APP_NAME


def ruta_asset(nombre: str) -> Path:
    return carpeta_base() / "assets" / nombre


LIMITE_REGISTRO = 128 * 1024


def registrar(mensaje: str) -> None:
    """Solo cambios de estado. Nunca la clave, cuerpos de respuesta ni UUID completos."""
    try:
        destino = carpeta_config() / "diagnostico.log"
        destino.parent.mkdir(parents=True, exist_ok=True)
        if destino.exists() and destino.stat().st_size > LIMITE_REGISTRO:
            cola = destino.read_text(encoding="utf-8", errors="replace")
            destino.write_text(cola[-LIMITE_REGISTRO // 2:], encoding="utf-8")
        with open(destino, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')}  {mensaje}\n")
    except OSError:
        pass


def escribir_json(ruta: Path, datos) -> None:
    """Escritura atómica: temporal al lado y reemplazo."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(datos, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, ruta)


# =========================================================================== #
# SessionKey cifrada con DPAPI (ámbito: usuario actual de Windows)
# =========================================================================== #
def _dpapi(proteger: bool, datos: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(datos, len(datos))
    entrada = DATA_BLOB(len(datos), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    salida = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    fn = crypt32.CryptProtectData if proteger else crypt32.CryptUnprotectData
    if not fn(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(salida)):
        raise OSError("DPAPI falló")
    try:
        return ctypes.string_at(salida.pbData, salida.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(salida.pbData)


def cifrar_clave(texto: str) -> str:
    """Si DPAPI falla, la clave NO se guarda: nunca en claro."""
    if not texto or not ES_WINDOWS:
        return ""
    try:
        return base64.b64encode(_dpapi(True, texto.encode("utf-8"))).decode("ascii")
    except Exception as exc:  # noqa: BLE001
        registrar(f"no se pudo cifrar la clave: {type(exc).__name__}")
        return ""


def descifrar_clave(cifrada: str) -> str:
    if not cifrada or not ES_WINDOWS:
        return ""
    try:
        return _dpapi(False, base64.b64decode(cifrada)).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        registrar(f"no se pudo descifrar la clave: {type(exc).__name__}")
        return ""


def formato_clave_valido(clave: str) -> bool:
    return bool(re.fullmatch(r"sk-ant-sid\d{2}-[A-Za-z0-9_\-]{20,}", clave.strip()))


# =========================================================================== #
# Configuración de cada usuario
# =========================================================================== #
class Config:
    def __init__(self):
        self.ruta = carpeta_config() / "config.json"
        self.clave_cifrada = ""
        self.org_id = ""
        self.refresco = 30
        self.umbrales = [list(u) for u in UMBRALES_DEFECTO]
        self.accesible = False
        self.notif_5h = True
        self.notif_semana = True
        self.aviso_reinicio = True
        self.sonido = False
        self.idioma = "auto"
        # "clave_limite|umbral" -> resets_at ISO de la sesión en la que ya se avisó.
        # Así cada aviso salta una sola vez por sesión, aunque se reinicie el programa.
        self.avisados = {}

    @classmethod
    def cargar(cls) -> "Config":
        cfg = cls()
        try:
            crudo = json.loads(cfg.ruta.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cfg
        if not isinstance(crudo, dict):
            return cfg
        cfg.clave_cifrada = str(crudo.get("session_key_enc", "") or "")
        cfg.org_id = str(crudo.get("org_id", "") or "")
        try:
            cfg.refresco = int(crudo.get("refresco", 30))
        except (TypeError, ValueError):
            cfg.refresco = 30
        if cfg.refresco not in REFRESCOS:
            cfg.refresco = 30
        cfg.umbrales = normalizar_umbrales(crudo.get("umbrales"))
        cfg.accesible = bool(crudo.get("accesible", False))
        cfg.notif_5h = bool(crudo.get("notif_5h", True))
        cfg.notif_semana = bool(crudo.get("notif_semana", True))
        cfg.aviso_reinicio = bool(crudo.get("aviso_reinicio", True))
        cfg.sonido = bool(crudo.get("sonido", False))
        cfg.idioma = crudo.get("idioma", "auto") if crudo.get("idioma") in IDIOMAS else "auto"
        avisados = crudo.get("avisados", {})
        cfg.avisados = {str(k): str(v) for k, v in avisados.items()} if isinstance(avisados, dict) else {}
        return cfg

    def guardar(self) -> bool:
        datos = {
            "version": VERSION,
            "session_key_enc": self.clave_cifrada,
            "org_id": self.org_id,
            "refresco": self.refresco,
            "umbrales": self.umbrales,
            "accesible": self.accesible,
            "notif_5h": self.notif_5h,
            "notif_semana": self.notif_semana,
            "aviso_reinicio": self.aviso_reinicio,
            "sonido": self.sonido,
            "idioma": self.idioma,
            "avisados": self.avisados,
        }
        try:
            escribir_json(self.ruta, datos)
            return True
        except OSError as exc:
            registrar(f"no se pudo guardar config.json: {exc}")
            return False

    @property
    def clave(self) -> str:
        return descifrar_clave(self.clave_cifrada)


def normalizar_umbrales(valor) -> list:
    """Tramos [desde_%, color]. El primero empieza siempre en 0; cada color una vez."""
    salida, vistos_v, vistos_c = [], set(), set()
    if isinstance(valor, list):
        for item in valor:
            try:
                v, c = int(item[0]), str(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if not 0 <= v <= 99 or c not in ORDEN_COLORES or v in vistos_v or c in vistos_c:
                continue
            salida.append([v, c])
            vistos_v.add(v)
            vistos_c.add(c)
    if not salida:
        return [list(u) for u in UMBRALES_DEFECTO]
    salida.sort(key=lambda u: u[0])
    if salida[0][0] != 0:
        libre = next((c for c in ORDEN_COLORES if c not in vistos_c), None)
        if libre:
            salida.insert(0, [0, libre])
        else:
            salida[0][0] = 0
    return salida[:MAX_TRAMOS]


# =========================================================================== #
# Tiempo y formato
# =========================================================================== #
def ahora() -> datetime:
    return datetime.now(timezone.utc)


def leer_iso(texto) -> datetime | None:
    if not texto:
        return None
    try:
        d = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def misma_sesion(a: datetime | None, b: datetime | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs((a - b).total_seconds()) <= TOLERANCIA_SESION


def hora(d: datetime | None) -> str:
    return d.astimezone().strftime("%H:%M") if d else "—"


def hora_ts(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M")


def falta(d: datetime | None, desde: datetime | None = None) -> str:
    if not d:
        return ""
    s = int((d - (desde or ahora())).total_seconds())
    if s <= 0:
        return T("ahora")
    h, r = divmod(s, 3600)
    m = r // 60
    if h >= 24:
        return f"{h // 24} d {h % 24} h"
    return f"{h} h {m} min" if h else f"{m} min"


def cuando_reinicia(d: datetime | None, corto: bool = False) -> str:
    """'12:40' si es hoy; 'lunes 09:00' (o 'lun 09:00') si es otro día."""
    if not d:
        return "—"
    local = d.astimezone()
    if local.date() == datetime.now().date():
        return local.strftime("%H:%M")
    dia = dia_c(local) if corto else dia_l(local)
    return f"{dia} {local.strftime('%H:%M')}"


def fecha_corta(d: datetime, minuscula: bool = False) -> str:
    """'Ayer · 12:35' o 'dom 1 nov · 22:35'. Con minuscula, 'ayer' y 'hoy' para ir a media frase."""
    local = d.astimezone()
    dias = (datetime.now().date() - local.date()).days
    if dias == 0:
        dia = T("hoy" if minuscula else "Hoy")
    elif dias == 1:
        dia = T("ayer" if minuscula else "Ayer")
    else:
        dia = T("{dia} {n} {mes}", dia=dia_c(local), n=local.day, mes=mes_c(local))
    return f"{dia} · {local.strftime('%H:%M')}"


def porcentaje(v) -> str:
    """'40 %' en español, '40%' en inglés."""
    return f"{v}%" if _idioma == "en" else f"{v} %"


def pct_txt(v: float) -> str:
    return porcentaje(round(v))


def decimal_txt(v: float) -> str:
    texto = f"{v:.1f}"
    return texto if _idioma == "en" else texto.replace(".", ",")


# =========================================================================== #
# claude.ai — interfaz interna, solo lectura
# =========================================================================== #
CABECERAS = {
    "accept": "*/*",
    "accept-language": "es-ES,es;q=0.9,en;q=0.8",
    "content-type": "application/json",
    "anthropic-client-platform": "web_claude_ai",
    "anthropic-client-version": "1.0.0",
    "user-agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "origin": "https://claude.ai",
    "referer": "https://claude.ai/settings/usage",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}


class ErrorClave(Exception):
    """401/403: la clave no vale o ha caducado."""


class ErrorConexion(Exception):
    """Red, tiempo agotado, Cloudflare o respuesta inesperada."""


class ClaudeAPI:
    BASE = "https://claude.ai/api"
    REESCANEO_CERO = 1800

    def __init__(self, clave: str, org_id: str = ""):
        self.clave = clave.strip()
        self.org_id = org_id or ""
        self._orgs = []
        self._ultimo_escaneo = 0.0

    def _get(self, ruta: str):
        peticion = urllib.request.Request(self.BASE + ruta, headers=dict(CABECERAS))
        peticion.add_header("Cookie", f"sessionKey={self.clave}")
        try:
            with urllib.request.urlopen(peticion, timeout=15) as r:
                cuerpo = r.read()
        except urllib.error.HTTPError as exc:
            try:
                inicio = exc.read(64)
            except Exception:  # noqa: BLE001
                inicio = b""
            if exc.code == 401:
                raise ErrorClave("claude.ai ha rechazado la clave (401).") from None
            if exc.code == 403:
                if b"<!DOCTYPE" in inicio or b"<html" in inicio:
                    raise ErrorConexion("Bloqueado por Cloudflare") from None
                raise ErrorClave("Acceso denegado (403).") from None
            raise ErrorConexion(f"HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ErrorConexion(type(exc).__name__) from None
        try:
            return json.loads(cuerpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ErrorConexion("Respuesta no válida") from None

    def organizaciones(self) -> list:
        datos = self._get("/organizations")
        if isinstance(datos, list):
            salida = [o["uuid"] for o in datos if isinstance(o, dict) and "uuid" in o]
        elif isinstance(datos, dict) and "uuid" in datos:
            salida = [datos["uuid"]]
        else:
            salida = []
        if salida:
            self._orgs = salida
        return salida

    @staticmethod
    def leer_limites(crudo) -> list:
        """Solo límites con etiqueta en LIMIT_LABELS.

        claude.ai devuelve a veces códigos internos (por ejemplo «nimbus») que no
        corresponden a nada que el usuario conozca: se ignoran. Para mostrar un
        límite nuevo basta con añadirlo a LIMIT_LABELS.
        """
        salida = []
        if not isinstance(crudo, dict):
            return salida
        for clave, valor in crudo.items():
            if clave not in LIMIT_LABELS or not isinstance(valor, dict) or valor.get("utilization") is None:
                continue
            try:
                pct = max(0.0, float(valor["utilization"]))
            except (TypeError, ValueError):
                continue
            salida.append({
                "clave": clave,
                "nombre": nombre_limite(clave),
                "pct": pct,
                "reinicio": leer_iso(valor.get("resets_at") or valor.get("reset_at")),
            })
        return ordenar_limites(salida)

    def _escanear(self) -> list:
        uuids = self._orgs or self.organizaciones()
        if not uuids:
            raise ErrorConexion("Sin organizaciones")
        salida = []
        for uuid in uuids:
            try:
                salida.append((uuid, self.leer_limites(self._get(f"/organizations/{uuid}/usage"))))
            except ErrorClave:
                raise
            except ErrorConexion:
                continue
        return salida

    def leer(self) -> list:
        """Límites de la organización donde de verdad se consume.

        Si la organización fijada devuelve todo a 0, puede ser una sesión recién
        reiniciada o la organización equivocada: se revalida cada 30 minutos.
        """
        if self.org_id:
            limites = self.leer_limites(self._get(f"/organizations/{self.org_id}/usage"))
            if any(l["pct"] > 0 for l in limites):
                return limites
            if limites and time.monotonic() - self._ultimo_escaneo < self.REESCANEO_CERO:
                return limites
            self._ultimo_escaneo = time.monotonic()
            for uuid, otros in self._escanear():
                if any(l["pct"] > 0 for l in otros):
                    if uuid != self.org_id:
                        registrar("organización de uso actualizada tras revalidar")
                    self.org_id = uuid
                    return otros
            if limites:
                return limites
            raise ErrorConexion("La respuesta no contiene límites")
        escaneo = self._escanear()
        activos = [(u, l) for u, l in escaneo if any(x["pct"] > 0 for x in l)]
        elegido = max(activos, key=lambda it: max(x["pct"] for x in it[1]), default=None)
        if elegido is None:
            elegido = next(((u, l) for u, l in escaneo if l), None)
        if elegido is None:
            raise ErrorConexion("Ninguna organización devuelve datos de uso")
        self.org_id, limites = elegido
        registrar("organización de uso seleccionada")
        return limites


def ordenar_limites(limites: list) -> list:
    """5 h y Semana fijos arriba; los de modelo por consumo descendente. Máximo 6."""
    fijos = [l for l in limites if l["clave"] == "five_hour"]
    semana = [l for l in limites if l["clave"] in CLAVES_SEMANA][:1]
    resto = [l for l in limites if l["clave"] != "five_hour" and l["clave"] not in CLAVES_SEMANA]
    resto.sort(key=lambda l: -l["pct"])
    return (fijos + semana + resto)[:MAX_FILAS_LIMITES]


# =========================================================================== #
# Historial local — SQLite, 730 días
# =========================================================================== #
class Historial:
    def __init__(self):
        self.ruta = carpeta_config() / "historial.db"
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ultimo = {}       # clave -> (ts, pct, reinicio) de la última fila escrita
        with self._con() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS lecturas(
                           ts REAL NOT NULL, clave TEXT NOT NULL,
                           pct REAL NOT NULL, reinicio REAL)""")
            c.execute("CREATE INDEX IF NOT EXISTS i_lecturas ON lecturas(clave, ts)")
            c.execute("DELETE FROM lecturas WHERE ts < ?", (time.time() - DIAS_HISTORIAL * 86400,))

    def _con(self):
        return sqlite3.connect(self.ruta, timeout=10)

    def anotar(self, limites: list) -> None:
        """Solo se escribe si el uso cambia, si empieza sesión o cada 5 minutos.

        Con un refresco de 30 s, guardar todas las lecturas serían millones de filas
        en dos años; así el archivo se queda en unos pocos megas.
        """
        t = time.time()
        filas = []
        for l in limites:
            reinicio = l["reinicio"].timestamp() if l["reinicio"] else None
            previo = self._ultimo.get(l["clave"])
            misma = previo is not None and (previo[2] == reinicio or (
                previo[2] is not None and reinicio is not None and abs(previo[2] - reinicio) <= TOLERANCIA_SESION))
            if previo and misma and abs(previo[1] - l["pct"]) < 0.1 and t - previo[0] < 300:
                continue
            filas.append((t, l["clave"], l["pct"], reinicio))
            self._ultimo[l["clave"]] = (t, l["pct"], reinicio)
        if filas:
            with self._lock, self._con() as c:
                c.executemany("INSERT INTO lecturas VALUES (?,?,?,?)", filas)

    def serie(self, clave: str, desde: float) -> list:
        with self._lock, self._con() as c:
            return c.execute(
                "SELECT ts, pct, reinicio FROM lecturas WHERE clave=? AND ts>=? ORDER BY ts",
                (clave, desde)).fetchall()

    def serie_agrupada(self, clave: str, desde: float, cubos: int = 700) -> list:
        """Como serie(), pero con un máximo de ~`cubos` filas: el pico de cada intervalo."""
        paso = max(60.0, (time.time() - desde) / cubos)
        with self._lock, self._con() as c:
            return c.execute(
                "SELECT MAX(ts), MAX(pct), MAX(reinicio) FROM lecturas WHERE clave=? AND ts>=? "
                "GROUP BY CAST(ts / ? AS INTEGER), CAST(IFNULL(reinicio, 0) / 600 AS INTEGER) ORDER BY 1",
                (clave, desde, paso)).fetchall()

    def tramos(self, clave: str, desde: float) -> list:
        """Agrupa lecturas por sesión (mismo reinicio)."""
        grupos = []
        for ts, pct, reinicio in self.serie_agrupada(clave, desde):
            if (grupos and reinicio and grupos[-1]["reinicio"]
                    and abs(grupos[-1]["reinicio"] - reinicio) <= TOLERANCIA_SESION):
                g = grupos[-1]
                g["fin"], g["cierre"] = ts, pct
                g["puntos"].append((ts, pct))
            else:
                grupos.append({"fin": ts, "cierre": pct, "reinicio": reinicio, "puntos": [(ts, pct)]})
        return grupos

    def exportar_csv(self, destino: Path) -> bool:
        # Separadores como los espera Excel en cada idioma: ";" y coma decimal en español, "," y punto en inglés.
        separador = "," if _idioma == "en" else ";"
        try:
            with self._lock, self._con() as c, open(destino, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh, delimiter=separador)
                w.writerow([T("fecha_hora"), T("limite"), T("uso_pct"), T("reinicio")])
                for ts, clave, pct, reinicio in c.execute("SELECT ts, clave, pct, reinicio FROM lecturas ORDER BY ts"):
                    w.writerow([datetime.fromtimestamp(ts).isoformat(timespec="seconds"), nombre_limite(clave),
                                decimal_txt(pct),
                                datetime.fromtimestamp(reinicio).isoformat(timespec="minutes") if reinicio else ""])
            return True
        except (OSError, sqlite3.Error) as exc:
            registrar(f"exportación CSV fallida: {exc}")
            return False


# =========================================================================== #
# Análisis: ritmo, proyección
# =========================================================================== #
def ritmo_por_hora(puntos: list, ventana_min: int = 20, minimo: int = 3) -> float | None:
    """Pendiente %/h por mínimos cuadrados sobre los últimos minutos. None si es plana."""
    if len(puntos) < minimo:
        return None
    fin = puntos[-1][0]
    usados = [p for p in puntos if fin - p[0] <= ventana_min * 60]
    if len(usados) < minimo:
        usados = puntos[-minimo:]
    xs = [(p[0] - usados[0][0]) / 3600 for p in usados]
    ys = [p[1] for p in usados]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den <= 0:
        return None
    pendiente = sum((xs[i] - mx) * (ys[i] - my) for i in range(n)) / den
    return pendiente if pendiente > 0.2 else None


def proyectar(pct: float, ritmo: float | None, reinicio: datetime | None) -> dict:
    """eta_100: cuándo se llegaría al 100 % antes del reinicio; sobra: % sin usar al reiniciar."""
    if not ritmo or not reinicio:
        return {"eta_100": None, "sobra": None}
    horas = (reinicio - ahora()).total_seconds() / 3600
    if horas <= 0:
        return {"eta_100": None, "sobra": None}
    horas_100 = (100 - pct) / ritmo
    if horas_100 < horas:
        return {"eta_100": ahora() + timedelta(hours=horas_100), "sobra": 0}
    return {"eta_100": None, "sobra": max(0, round(100 - (pct + ritmo * horas)))}


def fraccion_transcurrida(reinicio: datetime | None, ventana: int) -> float:
    if not reinicio:
        return 0.0
    restante = (reinicio - ahora()).total_seconds()
    return max(0.0, min(1.0, 1 - restante / ventana))


def color_de(pct: float, umbrales: list, tonos: dict) -> str:
    tramos = sorted(umbrales)
    color = tramos[0][1] if tramos else "green"
    for desde, c in tramos:
        if pct >= desde:
            color = c
    return tonos[color]


# =========================================================================== #
# Windows: DPI, iconos, bandeja, avisos
# =========================================================================== #
if ES_WINDOWS:
    import ctypes
    from ctypes import wintypes

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

    WM_NULL, WM_DESTROY, WM_CONTEXTMENU = 0x0000, 0x0002, 0x007B
    WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
    WM_BANDEJA = 0x8000 + 1

    NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
    NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x01, 0x02, 0x04, 0x10
    NOTIFYICON_VERSION_4 = 4
    NIIF_USER, NIIF_NOSOUND, NIIF_LARGE_ICON = 0x04, 0x10, 0x20
    NIN_SELECT, NIN_KEYSELECT = 0x0400, 0x0401
    NIN_BALLOONUSERCLICK, NIN_POPUPOPEN, NIN_POPUPCLOSE = 0x0405, 0x0406, 0x0407

    MF_STRING, MF_CHECKED, MF_SEPARATOR = 0x0000, 0x0008, 0x0800
    TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100
    PM_REMOVE = 0x0001
    SM_CXSMICON, SM_CXICON = 49, 11
    SPI_GETWORKAREA = 0x0030
    ERROR_ALREADY_EXISTS = 183
    IDI_APPLICATION = 32512

    ID_PANEL, ID_ACTUALIZAR, ID_AUTOSTART, ID_ACERCA, ID_SALIR = 1, 2, 3, 4, 5

    class GUID(ctypes.Structure):
        _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_byte * 8)]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
            ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
            ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
            ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
            ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
            ("guidItem", GUID), ("hBalloonIcon", wintypes.HICON),
        ]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
        ]

    class ICONINFO(ctypes.Structure):
        _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                    ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    _FIRMAS = False

    def declarar_firmas() -> None:
        """argtypes/restype de todo lo que toca un handle: en 64 bits, sin esto se truncan."""
        global _FIRMAS
        if _FIRMAS:
            return
        u, g, k, s = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32, ctypes.windll.shell32
        k.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        k.GetModuleHandleW.restype = wintypes.HMODULE
        k.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
        k.CreateMutexW.restype = wintypes.HANDLE
        u.RegisterClassW.argtypes = (ctypes.c_void_p,)
        u.RegisterClassW.restype = wintypes.ATOM
        u.CreateWindowExW.argtypes = (
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
        u.CreateWindowExW.restype = wintypes.HWND
        u.DestroyWindow.argtypes = (wintypes.HWND,)
        u.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        u.DefWindowProcW.restype = LRESULT
        u.RegisterWindowMessageW.argtypes = (wintypes.LPCWSTR,)
        u.RegisterWindowMessageW.restype = wintypes.UINT
        u.PeekMessageW.argtypes = (ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
        u.PeekMessageW.restype = wintypes.BOOL
        u.TranslateMessage.argtypes = (ctypes.c_void_p,)
        u.DispatchMessageW.argtypes = (ctypes.c_void_p,)
        u.DispatchMessageW.restype = LRESULT
        u.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        u.CreatePopupMenu.restype = wintypes.HMENU
        u.AppendMenuW.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_void_p, wintypes.LPCWSTR)
        u.SetMenuDefaultItem.argtypes = (wintypes.HMENU, wintypes.UINT, wintypes.UINT)
        u.TrackPopupMenu.argtypes = (wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     wintypes.HWND, ctypes.c_void_p)
        u.TrackPopupMenu.restype = wintypes.BOOL
        u.DestroyMenu.argtypes = (wintypes.HMENU,)
        u.SetForegroundWindow.argtypes = (wintypes.HWND,)
        u.GetCursorPos.argtypes = (ctypes.c_void_p,)
        u.GetSystemMetrics.argtypes = (ctypes.c_int,)
        u.GetSystemMetrics.restype = ctypes.c_int
        u.SystemParametersInfoW.argtypes = (wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT)
        u.SystemParametersInfoW.restype = wintypes.BOOL
        u.GetParent.argtypes = (wintypes.HWND,)
        u.GetParent.restype = wintypes.HWND
        u.MessageBoxW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT)
        u.LoadIconW.argtypes = (wintypes.HINSTANCE, wintypes.LPCWSTR)
        u.LoadIconW.restype = wintypes.HICON
        u.CreateIconIndirect.argtypes = (ctypes.c_void_p,)
        u.CreateIconIndirect.restype = wintypes.HICON
        u.DestroyIcon.argtypes = (wintypes.HICON,)
        u.GetDC.argtypes = (wintypes.HWND,)
        u.GetDC.restype = wintypes.HDC
        u.ReleaseDC.argtypes = (wintypes.HWND, wintypes.HDC)
        g.CreateDIBSection.argtypes = (wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD)
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.CreateBitmap.argtypes = (ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p)
        g.CreateBitmap.restype = wintypes.HBITMAP
        g.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
        s.Shell_NotifyIconW.argtypes = (wintypes.DWORD, ctypes.c_void_p)
        s.Shell_NotifyIconW.restype = wintypes.BOOL
        _FIRMAS = True


def activar_conciencia_dpi() -> None:
    if not ES_WINDOWS:
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


_MUTEX = None


def es_unica_instancia() -> bool:
    global _MUTEX
    if not ES_WINDOWS:
        return True
    declarar_firmas()
    _MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\" + APP_NAME)
    return ctypes.windll.kernel32.GetLastError() != ERROR_ALREADY_EXISTS


def barra_tareas_clara() -> bool:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 1
    except (OSError, ImportError):
        return False


def area_trabajo():
    """(izq, arriba, der, abajo) sin la barra de tareas, en píxeles físicos."""
    if ES_WINDOWS:
        declarar_firmas()
        r = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0):
            return r.left, r.top, r.right, r.bottom
    return None


def redondear_esquinas(ventana) -> None:
    """Windows 11: esquinas redondeadas también en ventanas sin marco."""
    if not ES_WINDOWS:
        return
    try:
        declarar_firmas()
        hwnd = ctypes.windll.user32.GetParent(ventana.winfo_id()) or ventana.winfo_id()
        valor = ctypes.c_int(2)   # DWMWCP_ROUND
        ctypes.windll.dwmapi.DwmSetWindowAttribute(wintypes.HWND(hwnd), 33, ctypes.byref(valor), 4)
    except (AttributeError, OSError):
        pass


# --- logo: PNG → RGBA, sin Pillow ------------------------------------------ #
def leer_png(ruta: Path):
    """Decodificador PNG mínimo (8 bits, sin entrelazar). Devuelve (ancho, alto, RGBA)."""
    datos = ruta.read_bytes()
    if datos[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("no es un PNG")
    pos, idat, paleta, trns = 8, b"", None, None
    ancho = alto = tipo = profundidad = entrelazado = 0
    while pos < len(datos):
        largo, = struct.unpack(">I", datos[pos:pos + 4])
        nombre = datos[pos + 4:pos + 8]
        cuerpo = datos[pos + 8:pos + 8 + largo]
        pos += 12 + largo
        if nombre == b"IHDR":
            ancho, alto, profundidad, tipo, _, _, entrelazado = struct.unpack(">IIBBBBB", cuerpo)
        elif nombre == b"PLTE":
            paleta = cuerpo
        elif nombre == b"tRNS":
            trns = cuerpo
        elif nombre == b"IDAT":
            idat += cuerpo
        elif nombre == b"IEND":
            break
    if profundidad != 8 or entrelazado:
        raise ValueError("PNG no soportado")
    canales = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[tipo]
    crudo = zlib.decompress(idat)
    paso = ancho * canales
    filas, anterior, i = [], bytearray(paso), 0
    for _ in range(alto):
        filtro = crudo[i]
        linea = bytearray(crudo[i + 1:i + 1 + paso])
        i += 1 + paso
        for x in range(paso):
            a = linea[x - canales] if x >= canales else 0
            b = anterior[x]
            c = anterior[x - canales] if x >= canales else 0
            if filtro == 1:
                linea[x] = (linea[x] + a) & 255
            elif filtro == 2:
                linea[x] = (linea[x] + b) & 255
            elif filtro == 3:
                linea[x] = (linea[x] + ((a + b) >> 1)) & 255
            elif filtro == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                linea[x] = (linea[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        filas.append(linea)
        anterior = linea
    rgba = bytearray()
    for linea in filas:
        for x in range(ancho):
            px = linea[x * canales:(x + 1) * canales]
            if tipo == 6:
                rgba += px
            elif tipo == 2:
                rgba += px + b"\xff"
            elif tipo == 0:
                rgba += bytes((px[0], px[0], px[0], 255))
            elif tipo == 4:
                rgba += bytes((px[0], px[0], px[0], px[1]))
            else:
                j = px[0]
                alfa = trns[j] if trns and j < len(trns) else 255
                rgba += paleta[j * 3:j * 3 + 3] + bytes((alfa,))
    return ancho, alto, bytes(rgba)


_PNG = {}
_ALFA_CACHE = {}


def mascara_logo(lado: int) -> list:
    """Alfa del logo reducido a `lado` px, filas de arriba abajo (0..255)."""
    if lado in _ALFA_CACHE:
        return _ALFA_CACHE[lado]
    try:
        if "logo" not in _PNG:
            _PNG["logo"] = leer_png(ruta_asset("claude-logo-256.png"))
        w, h, rgba = _PNG["logo"]
    except (OSError, ValueError, KeyError, zlib.error):
        # Sin imagen: un disco, para no quedarse sin icono.
        c = (lado - 1) / 2
        alfa = [[255 if (x - c) ** 2 + (y - c) ** 2 <= (lado / 2.2) ** 2 else 0 for x in range(lado)]
                for y in range(lado)]
        _ALFA_CACHE[lado] = alfa
        return alfa
    escala = w / lado
    alfa = []
    for y in range(lado):
        fila = []
        y0 = int(y * escala)
        y1 = max(y0 + 1, int((y + 1) * escala))
        for x in range(lado):
            x0 = int(x * escala)
            x1 = max(x0 + 1, int((x + 1) * escala))
            total = n = 0
            for yy in range(y0, min(y1, h)):
                base = yy * w * 4
                for xx in range(x0, min(x1, w)):
                    total += rgba[base + xx * 4 + 3]
                    n += 1
            fila.append(total // max(1, n))
        alfa.append(fila)
    _ALFA_CACHE[lado] = alfa
    return alfa


def hex_rgb(color: str):
    color = color.lstrip("#")
    return int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)


def mezclar(a: str, b: str, k: float) -> str:
    """Color `a` sobre `b` con opacidad k."""
    ra, ga, ba = hex_rgb(a)
    rb, gb, bb = hex_rgb(b)
    return "#%02x%02x%02x" % (round(rb + (ra - rb) * k), round(gb + (ga - gb) * k), round(bb + (ba - bb) * k))


def foto_logo(maestro, lado: int, color: str, fondo: str) -> tk.PhotoImage:
    """Logo teñido y fundido sobre un fondo conocido (tk no mezcla alfa)."""
    alfa = mascara_logo(lado)
    r, g, b = hex_rgb(color)
    fr, fg, fb = hex_rgb(fondo)
    img = tk.PhotoImage(master=maestro, width=lado, height=lado)
    filas = []
    for fila in alfa:
        px = []
        for a in fila:
            k = a / 255
            px.append("#%02x%02x%02x" % (round(fr + (r - fr) * k), round(fg + (g - fg) * k), round(fb + (b - fb) * k)))
        filas.append("{" + " ".join(px) + "}")
    img.put(" ".join(filas))
    return img


def foto_forma(maestro, w: int, h: int, radio: float, relleno: str, borde, fondo: str,
               grosor: float = 1.0, pomo=None) -> tk.PhotoImage:
    """Rectángulo redondeado con antialias (supermuestreo 3×3), fundido sobre `fondo`.

    tk dibuja sin suavizado: los óvalos del Canvas salen dentados. pomo=(a_la_derecha, color)
    añade el círculo de un interruptor.
    """
    n = 3
    fr = hex_rgb(fondo)
    rr = hex_rgb(relleno)
    br = hex_rgb(borde) if borde else rr
    pr = hex_rgb(pomo[1]) if pomo else None
    cx, cy = w / 2, h / 2
    ex, ey = w / 2 - radio, h / 2 - radio
    kr = h / 2 - max(2.0, h * 0.14)
    kx = (w - h / 2) if pomo and pomo[0] else h / 2
    t = n * n
    filas = []
    for y in range(h):
        fila = []
        for x in range(w):
            cf = cb = ck = 0
            for sy in range(n):
                py = y + (sy + 0.5) / n
                for sx in range(n):
                    px = x + (sx + 0.5) / n
                    qx, qy = abs(px - cx) - ex, abs(py - cy) - ey
                    d = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radio
                    if d > 0:
                        continue
                    if borde and d > -grosor:
                        cb += 1
                    else:
                        cf += 1
                        if pr and (px - kx) ** 2 + (py - cy) ** 2 <= kr * kr:
                            ck += 1
            c = [fr[i] * (t - cf - cb) + rr[i] * (cf - ck) + br[i] * cb + (pr[i] * ck if pr else 0) for i in range(3)]
            fila.append("#%02x%02x%02x" % tuple(min(255, round(v / t)) for v in c))
        filas.append("{" + " ".join(fila) + "}")
    img = tk.PhotoImage(master=maestro, width=w, height=h)
    img.put(" ".join(filas))
    return img


_ICONOS = {}


def hicono(color: str, lado: int):
    """HICON del logo teñido. Se cachea por color y tamaño: se crean una vez."""
    if not ES_WINDOWS:
        return None
    clave = (color, lado)
    if clave in _ICONOS:
        return _ICONOS[clave]
    declarar_firmas()
    user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
    r, g, b = hex_rgb(color)
    alfa = mascara_logo(lado)
    hbm_color = hbm_mascara = hdc = None
    resultado = None
    try:
        cab = BITMAPINFOHEADER()
        cab.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        cab.biWidth, cab.biHeight, cab.biPlanes, cab.biBitCount = lado, -lado, 1, 32
        info = BITMAPINFO()
        info.bmiHeader = cab
        hdc = user32.GetDC(None)
        bits = ctypes.c_void_p()
        hbm_color = gdi32.CreateDIBSection(hdc, ctypes.byref(info), 0, ctypes.byref(bits), None, 0)
        if not hbm_color or not bits:
            raise OSError("CreateDIBSection")
        plano = bytearray()
        for fila in alfa:
            for a in fila:
                plano += bytes((b, g, r, a))
        ctypes.memmove(bits, bytes(plano), len(plano))
        stride = ((lado + 15) // 16) * 2
        hbm_mascara = gdi32.CreateBitmap(lado, lado, 1, 1, bytes(stride * lado))
        icono = ICONINFO(True, 0, 0, hbm_mascara, hbm_color)
        resultado = user32.CreateIconIndirect(ctypes.byref(icono))
    except (OSError, ValueError, AttributeError) as exc:
        registrar(f"no se pudo crear el icono: {exc!r}")
    finally:
        if hdc:
            user32.ReleaseDC(None, hdc)
        for h in (hbm_color, hbm_mascara):
            if h:
                gdi32.DeleteObject(h)
    if not resultado:
        resultado = user32.LoadIconW(None, ctypes.cast(ctypes.c_void_p(IDI_APPLICATION), wintypes.LPCWSTR))
    _ICONOS[clave] = resultado
    return resultado


def lado_icono(grande: bool = False) -> int:
    if not ES_WINDOWS:
        return 16
    declarar_firmas()
    v = ctypes.windll.user32.GetSystemMetrics(SM_CXICON if grande else SM_CXSMICON)
    return max(16, min(v or (32 if grande else 16), 96))


# --- área de notificación ------------------------------------------------- #
class Bandeja:
    """Icono con Shell_NotifyIcon, versión 4, sin dependencias.

    Todo ocurre en el hilo de Tk: una ventana oculta recibe los avisos del icono
    y sus mensajes se bombean desde `root.after`. Lo que pide el usuario se
    apunta y se ejecuta después, fuera del despacho de mensajes de Windows
    (entrar en Tk desde dentro de DispatchMessage tiraba el proceso).

    Con la versión 4 y sin NIF_SHOWTIP, Windows no pinta su tooltip y avisa con
    NIN_POPUPOPEN / NIN_POPUPCLOSE: ahí se muestra y se oculta la tarjeta propia.
    """

    CLASE = "ClaudeUsageTrayWnd"

    def __init__(self, root, acciones):
        self.root = root
        self.acciones = acciones
        self.hwnd = None
        self.icono = None
        self.tip = TITULO
        self.version4 = False
        self._vivo = False
        self._pendientes = []
        self._ocupado = False
        self._job = self._vigia = None
        declarar_firmas()
        self._u, self._s, self._k = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32
        self._msg_taskbar = self._u.RegisterWindowMessageW("TaskbarCreated")
        # Las referencias al callback y a la clase deben sobrevivir al GC.
        self._wndproc = WNDPROC(self._procesar)
        self._clase = None
        self._crear_ventana()
        self.icono = hicono(AZUL, lado_icono())
        self._poner_icono(exigir=True)
        self._vivo = True
        self._bombear()
        self._vigia = self.root.after(5000, self._vigilar)
        registrar(f"bandeja lista (versión 4: {self.version4})")

    def _crear_ventana(self) -> None:
        hinst = self._k.GetModuleHandleW(None)
        clase = WNDCLASSW()
        clase.lpfnWndProc = self._wndproc
        clase.hInstance = hinst
        clase.lpszClassName = self.CLASE
        self._clase = clase
        self._u.RegisterClassW(ctypes.byref(clase))
        self.hwnd = self._u.CreateWindowExW(0, self.CLASE, TITULO, 0, 0, 0, 0, 0, None, None, hinst, None)
        if not self.hwnd:
            raise ctypes.WinError()

    def _datos(self, flags):
        d = NOTIFYICONDATAW()
        d.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        d.hWnd = self.hwnd
        d.uID = 1
        d.uFlags = flags
        d.uCallbackMessage = WM_BANDEJA
        d.hIcon = self.icono or 0
        d.szTip = self.tip[:127]
        return d

    def _poner_icono(self, exigir: bool = False) -> None:
        d = self._datos(NIF_MESSAGE | NIF_ICON | NIF_TIP)
        if not self._s.Shell_NotifyIconW(NIM_ADD, ctypes.byref(d)):
            if not self._s.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(d)):
                registrar("NIM_ADD y NIM_MODIFY fallaron")
                if exigir:
                    raise ctypes.WinError()
                return
        v = self._datos(0)
        v.uVersion = NOTIFYICON_VERSION_4
        self.version4 = bool(self._s.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(v)))

    def actualizar(self, color: str, tip: str) -> None:
        if not self._vivo:
            return
        self.icono = hicono(color, lado_icono())
        self.tip = tip
        self._s.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._datos(NIF_ICON | NIF_TIP)))

    def avisar(self, titulo: str, texto: str, color: str, sonido: bool) -> None:
        """Globo NIF_INFO: Windows 11 lo muestra como aviso, con el icono del tramo."""
        if not self._vivo:
            return
        d = self._datos(NIF_INFO)
        d.szInfoTitle = titulo[:63]
        d.szInfo = texto[:255]
        d.dwInfoFlags = NIIF_USER | NIIF_LARGE_ICON | (0 if sonido else NIIF_NOSOUND)
        d.hBalloonIcon = hicono(color, lado_icono(grande=True))
        self._s.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(d))

    def _procesar(self, hwnd, msg, wparam, lparam):
        try:
            return self._despachar(hwnd, msg, wparam, lparam)
        except BaseException as exc:  # noqa: BLE001
            registrar(f"EXCEPCIÓN en el WndProc: {exc!r}")
            return 0

    def _despachar(self, hwnd, msg, wparam, lparam):
        if msg == WM_BANDEJA:
            evento = lparam & 0xFFFF
            if self.version4:
                if evento in (NIN_SELECT, NIN_KEYSELECT):
                    self._pendientes.append("alternar")
                elif evento == WM_CONTEXTMENU:
                    self._pendientes.append("menu")
                elif evento == NIN_POPUPOPEN:
                    x = ctypes.c_short(wparam & 0xFFFF).value
                    self._pendientes.append(("tarjeta", x))
                elif evento == NIN_POPUPCLOSE:
                    self._pendientes.append("ocultar_tarjeta")
                elif evento == NIN_BALLOONUSERCLICK:
                    self._pendientes.append("clic_aviso")
            else:
                if evento == WM_LBUTTONUP:
                    self._pendientes.append("alternar")
                elif evento == WM_RBUTTONUP:
                    self._pendientes.append("menu")
                elif evento == NIN_BALLOONUSERCLICK:
                    self._pendientes.append("clic_aviso")
            return 0
        if self._msg_taskbar and msg == self._msg_taskbar:
            self._poner_icono()
            return 0
        if msg == WM_DESTROY:
            return 0
        return self._u.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self) -> None:
        u = self._u
        menu = u.CreatePopupMenu()
        if not menu:
            return
        abierto = self.acciones["panel_abierto"]()
        u.AppendMenuW(menu, MF_STRING, ID_PANEL, T("Cerrar panel") if abierto else T("Abrir panel"))
        u.SetMenuDefaultItem(menu, ID_PANEL, 0)
        u.AppendMenuW(menu, MF_STRING, ID_ACTUALIZAR, T("Actualizar ahora"))
        u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        marcado = MF_CHECKED if autostart_activo() else 0
        u.AppendMenuW(menu, MF_STRING | marcado, ID_AUTOSTART, T("Iniciar con Windows"))
        u.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        u.AppendMenuW(menu, MF_STRING, ID_ACERCA, T("Acerca de Claude Usage"))
        u.AppendMenuW(menu, MF_STRING, ID_SALIR, T("Salir"))
        punto = wintypes.POINT()
        u.GetCursorPos(ctypes.byref(punto))
        # Sin traer la ventana al frente y sin el WM_NULL, el menú se queda pegado.
        u.SetForegroundWindow(self.hwnd)
        elegido = u.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, punto.x, punto.y, 0, self.hwnd, None)
        u.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        u.DestroyMenu(menu)
        if elegido:
            self._pendientes.append(elegido)

    def _bombear(self) -> None:
        if not self._vivo:
            return
        if self._ocupado:
            # TrackPopupMenu tiene su propio bucle y Tk puede volver a llamar aquí: no anidar.
            self._job = self.root.after(50, self._bombear)
            return
        self._ocupado = True
        try:
            self._bombear_una_vez()
        finally:
            self._ocupado = False
        if self._vivo:
            try:
                self._job = self.root.after(50, self._bombear)
            except tk.TclError:
                self._vivo = False

    def _bombear_una_vez(self) -> None:
        m = wintypes.MSG()
        while self._u.PeekMessageW(ctypes.byref(m), self.hwnd, 0, 0, PM_REMOVE):
            self._u.TranslateMessage(ctypes.byref(m))
            self._u.DispatchMessageW(ctypes.byref(m))
        while self._pendientes and self._vivo:
            pedido = self._pendientes.pop(0)
            nombre, args = (pedido[0], pedido[1:]) if isinstance(pedido, tuple) else (pedido, ())
            # El menú se abre aquí, fuera de DispatchMessage: abrirlo dentro del WndProc
            # hacía que Tk entrase desde el callback de Windows y el proceso se cerraba.
            accion = self._menu if nombre == "menu" else self.acciones.get(nombre)
            if accion:
                try:
                    accion(*args)
                except BaseException as exc:  # noqa: BLE001
                    registrar(f"EXCEPCIÓN en la acción {nombre}: {exc!r}")

    def _vigilar(self) -> None:
        if not self._vivo:
            return
        if not self._s.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(self._datos(NIF_MESSAGE | NIF_ICON | NIF_TIP))):
            registrar("el icono había desaparecido: reponiendo")
            self._poner_icono()
        try:
            self._vigia = self.root.after(5000, self._vigilar)
        except tk.TclError:
            self._vivo = False

    def cerrar(self) -> None:
        if not self._vivo:
            return
        self._vivo = False
        for job in (self._job, self._vigia):
            if job:
                try:
                    self.root.after_cancel(job)
                except tk.TclError:
                    pass
        try:
            self._s.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._datos(NIF_MESSAGE)))
        except OSError:
            pass
        for h in _ICONOS.values():
            try:
                self._u.DestroyIcon(h)
            except OSError:
                pass
        _ICONOS.clear()
        if self.hwnd:
            self._u.DestroyWindow(self.hwnd)
            self.hwnd = None


# =========================================================================== #
# Inicio automático con Windows
# =========================================================================== #
CLAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _winreg():
    try:
        import winreg
    except ImportError:
        return None
    return winreg


def _interprete() -> Path:
    actual = Path(sys.executable).resolve()
    if actual.name.lower() == "python.exe":
        sin_consola = actual.with_name("pythonw.exe")
        if sin_consola.exists():
            return sin_consola
    return actual


def comando_arranque() -> str:
    if esta_congelado():
        return f'"{Path(sys.executable).resolve()}" --silent'
    return f'"{_interprete()}" "{Path(__file__).resolve()}" --silent'


def _objetivo(comando: str) -> str:
    texto = (comando or "").strip()
    if not texto:
        return ""
    if texto.startswith('"'):
        fin = texto.find('"', 1)
        return (texto[1:fin] if fin > 0 else texto[1:]).casefold()
    return texto.split()[0].casefold()


def autostart_activo() -> bool:
    w = _winreg()
    if w is None:
        return False
    try:
        with w.OpenKey(w.HKEY_CURRENT_USER, CLAVE_RUN) as k:
            valor, _ = w.QueryValueEx(k, APP_NAME)
    except OSError:
        return False
    # La app es portable: si se movió, la entrada antigua ya no cuenta.
    return isinstance(valor, str) and _objetivo(valor) == _objetivo(comando_arranque())


def autostart_poner(activar: bool) -> bool:
    w = _winreg()
    if w is None:
        return False
    try:
        with w.CreateKeyEx(w.HKEY_CURRENT_USER, CLAVE_RUN, 0, w.KEY_SET_VALUE) as k:
            if activar:
                w.SetValueEx(k, APP_NAME, 0, w.REG_SZ, comando_arranque())
            else:
                try:
                    w.DeleteValue(k, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


# =========================================================================== #
# Interfaz — tkinter
# =========================================================================== #
class Estilo:
    """Medidas escaladas al DPI y fuentes resueltas una sola vez."""

    def __init__(self, root: tk.Tk):
        self.root = root
        try:
            self.escala = max(1.0, root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            self.escala = 1.0
        disponibles = set(tkfont.families(root))
        self.familia = next((f for f in FAMILIAS if f in disponibles), "TkDefaultFont")
        self.mono = next((f for f in FAMILIA_MONO if f in disponibles), "TkFixedFont")
        self._fuentes = {}

    def px(self, v: float) -> int:
        return max(1, int(round(v * self.escala)))

    def f(self, tam: float, peso: str = "normal", mono: bool = False) -> tkfont.Font:
        clave = (tam, peso, mono)
        if clave not in self._fuentes:
            self._fuentes[clave] = tkfont.Font(root=self.root, family=self.mono if mono else self.familia,
                                               size=-self.px(tam), weight=peso)
        return self._fuentes[clave]


def _trazar_icono(cv, nombre: str, x: float, y: float, s: float, color: str, grosor: float = 1.6) -> None:
    """Geometría de los iconos de trazo, en una caja de 24 unidades centrada en (x, y)."""
    k = s / 24.0

    def P(*coords):
        return [x + (c - 12) * k if i % 2 == 0 else y + (c - 12) * k for i, c in enumerate(coords)]

    w = max(1, grosor * s / 16)
    op = dict(fill=color, width=w, capstyle="round", joinstyle="round")
    if nombre == "refrescar":
        cv.create_arc(*P(3, 3, 21, 21), start=40, extent=290, style="arc", outline=color, width=w)
        cv.create_line(*P(20, 3, 20, 9, 14, 9), **op)
    elif nombre == "grafico":
        cv.create_line(*P(3, 3, 3, 21, 21, 21), **op)
        cv.create_line(*P(7, 15, 11, 11, 14, 14, 19, 8), **op)
    elif nombre == "menu":
        for yy in (7, 12, 17):
            cv.create_line(*P(4, yy, 20, yy), **op)
    elif nombre == "cerrar":
        cv.create_line(*P(6, 6, 18, 18), **op)
        cv.create_line(*P(18, 6, 6, 18), **op)
    elif nombre == "clave":
        cv.create_oval(*P(3, 11, 11, 19), outline=color, width=w)
        cv.create_line(*P(10, 12, 20, 4), **op)
        cv.create_line(*P(17, 7, 20, 10), **op)
    elif nombre == "campana":
        cv.create_arc(*P(6, 3, 18, 15), start=0, extent=180, style="arc", outline=color, width=w)
        cv.create_line(*P(6, 9, 6, 16, 4, 18, 20, 18, 18, 16, 18, 9), **op)
        cv.create_line(*P(10, 21, 14, 21), **op)
    elif nombre == "reinicio":
        cv.create_arc(*P(3, 3, 21, 21), start=100, extent=290, style="arc", outline=color, width=w)
        cv.create_line(*P(3, 4, 3, 9, 8, 9), **op)
    elif nombre == "sonido":
        cv.create_line(*P(11, 5, 6, 9, 3, 9, 3, 15, 6, 15, 11, 19, 11, 5), **op)
        cv.create_arc(*P(11, 8, 19, 16), start=-60, extent=120, style="arc", outline=color, width=w)
    elif nombre == "idioma":
        cv.create_oval(*P(3, 3, 21, 21), outline=color, width=w)
        cv.create_oval(*P(8, 3, 16, 21), outline=color, width=w)
        cv.create_line(*P(3, 12, 21, 12), **op)
    elif nombre == "encendido":
        cv.create_arc(*P(4, 5, 20, 21), start=120, extent=300, style="arc", outline=color, width=w)
        cv.create_line(*P(12, 2, 12, 12), **op)
    elif nombre == "ojo":
        cv.create_oval(*P(2, 6, 22, 18), outline=color, width=w)
        cv.create_oval(*P(9, 9, 15, 15), outline=color, width=w)
    elif nombre == "reloj":
        cv.create_oval(*P(4, 6, 20, 22), outline=color, width=w)
        cv.create_line(*P(12, 14, 15, 11), **op)
        cv.create_line(*P(10, 2, 14, 2), **op)
    elif nombre == "aviso":
        cv.create_line(*P(12, 3, 22, 20, 2, 20, 12, 3), **op)
        cv.create_line(*P(12, 9, 12, 14), **op)
        cv.create_line(*P(12, 17, 12, 17.2), **op)
    elif nombre == "descarga":
        cv.create_line(*P(12, 3, 12, 15), **op)
        cv.create_line(*P(7, 10, 12, 15, 17, 10), **op)
        cv.create_line(*P(5, 21, 19, 21), **op)
    elif nombre == "volver":
        cv.create_line(*P(19, 12, 5, 12), **op)
        cv.create_line(*P(12, 19, 5, 12, 12, 5), **op)
    elif nombre == "mas":
        cv.create_line(*P(12, 5, 12, 19), **op)
        cv.create_line(*P(5, 12, 19, 12), **op)


class _Trazos:
    """Imita la parte del Canvas que usan los iconos y guarda los trazos como polilíneas."""

    def __init__(self):
        self.trazos = []        # (puntos, grosor)

    def create_line(self, *coords, width=1, **_kw):
        pts = list(zip(coords[0::2], coords[1::2]))
        self.trazos.append((pts, width))

    def create_arc(self, x0, y0, x1, y1, start=0, extent=90, width=1, **_kw):
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
        n = max(8, int(abs(extent) / 10))
        pts = [(cx + rx * math.cos(math.radians(start + extent * i / n)),
                cy - ry * math.sin(math.radians(start + extent * i / n))) for i in range(n + 1)]
        self.trazos.append((pts, width))

    def create_oval(self, x0, y0, x1, y1, width=1, **_kw):
        self.create_arc(x0, y0, x1, y1, start=0, extent=360, width=width)


_ICONOS_TK = {}


def foto_icono(maestro, nombre: str, s: int, color: str, fondo: str) -> tk.PhotoImage:
    """Icono rasterizado con antialias: cobertura por distancia a cada trazo.

    Los create_line/create_arc del Canvas de Windows salen sin suavizar y los
    iconos pequeños se ven dentados; así quedan limpios a cualquier escala.
    """
    clave = (nombre, s, color, fondo)
    if clave in _ICONOS_TK:
        return _ICONOS_TK[clave]
    rec = _Trazos()
    _trazar_icono(rec, nombre, s / 2, s / 2, s, color)
    segmentos = []
    for pts, w in rec.trazos:
        r = max(0.6, w / 2)
        if len(pts) == 1:
            pts = pts * 2
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            segmentos.append((ax, ay, bx, by, r))
    cr, cg, cb = hex_rgb(color)
    fr, fg, fb = hex_rgb(fondo)
    filas = []
    for y in range(s):
        py = y + 0.5
        fila = []
        for x in range(s):
            px = x + 0.5
            cob = 0.0
            for ax, ay, bx, by, r in segmentos:
                if px < min(ax, bx) - r - 1 or px > max(ax, bx) + r + 1 or py < min(ay, by) - r - 1 or py > max(ay, by) + r + 1:
                    continue
                dx, dy = bx - ax, by - ay
                ll = dx * dx + dy * dy
                t = 0.0 if ll == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / ll))
                d = math.hypot(px - ax - t * dx, py - ay - t * dy)
                cob = max(cob, min(1.0, max(0.0, r - d + 0.5)))
                if cob >= 1.0:
                    break
            fila.append("#%02x%02x%02x" % (round(fr + (cr - fr) * cob), round(fg + (cg - fg) * cob), round(fb + (cb - fb) * cob)))
        filas.append("{" + " ".join(fila) + "}")
    img = tk.PhotoImage(master=maestro, width=s, height=s)
    img.put(" ".join(filas))
    _ICONOS_TK[clave] = img
    return img


def dibujar_icono(cv: tk.Canvas, nombre: str, x: float, y: float, s: float, color: str, grosor: float = 1.6) -> None:
    """Coloca en el Canvas el icono suavizado, centrado en (x, y), fundido con su fondo."""
    img = foto_icono(cv, nombre, max(8, int(round(s))), color, cv["bg"])
    cv.create_image(x, y, image=img, tags="icono")
    cv._foto_icono = img
    cv._icono = (nombre, x, y, s, color)


def pintar_fondo(w, bg: str) -> None:
    """Cambia el fondo de un widget; si es un Canvas con icono, lo vuelve a fundir con el fondo nuevo."""
    w.configure(bg=bg)
    datos = getattr(w, "_icono", None)
    if datos:
        w.delete("icono")
        dibujar_icono(w, *datos)


def etiqueta_eje(ts: float, dias: float) -> str:
    d = datetime.fromtimestamp(ts)
    if dias <= 1:
        return d.strftime("%H:%M")
    if dias <= 7:
        return f"{dia_c(d)} {d.day}"
    if dias <= 180:
        return T("{n} {mes}", n=d.day, mes=mes_c(d))
    return f"{mes_c(d)} {str(d.year)[2:]}"


class App:
    def __init__(self, silencioso: bool):
        activar_conciencia_dpi()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(TITULO)
        self.e = Estilo(self.root)
        self.cfg = Config.cargar()
        poner_idioma(self.cfg.idioma)
        self.hist = Historial()

        # Estado de datos (solo se toca en el hilo de Tk).
        self.limites = []
        self.ultimo_ok = None
        self.tipo_error = None          # None | "clave" | "red"
        self.fallos = 0
        self.aviso_clave_enviado = False
        self.aviso_red_enviado = False
        self.accion_aviso = "panel"
        self._previo = {}               # clave -> (reinicio, pct) de la lectura anterior

        # Estado de la interfaz.
        self.vista = "principal"        # principal | menu | ayuda | acerca
        self.grafico = False
        self.ver_clave = False
        self.ver_umbrales = False
        self.clave_borrador = tk.StringVar(master=self.root)
        self.error_clave = ""
        self.validando = False
        self.serie = "sesiones"
        self.rango = 30
        self.grano = 5
        self.nota_csv = ""
        self._fotos = []
        self._imgs = {}                 # formas con antialias, se generan una vez
        self._foto_tarjeta = None
        self._pista = None
        self.form_umbral = tk.StringVar(master=self.root)
        self.form_color = None

        self.panel = tk.Toplevel(self.root)
        self.panel.withdraw()
        self.panel.overrideredirect(True)
        self.panel.attributes("-topmost", True)
        self.panel.configure(bg=C["borde"])
        self.panel.bind("<Escape>", lambda _e: self._esc())
        self.marco = tk.Frame(self.panel, bg=C["fondo"])
        self.marco.pack(padx=1, pady=1, fill="both", expand=True)

        self.tarjeta = tk.Toplevel(self.root)
        self.tarjeta.withdraw()
        self.tarjeta.overrideredirect(True)
        self.tarjeta.attributes("-topmost", True)
        self.tarjeta.configure(bg=C["borde"])

        self.cola = queue.Queue()
        self._despertar = threading.Event()
        self._vivo = True
        clave = self.cfg.clave
        self.api = ClaudeAPI(clave, self.cfg.org_id) if clave else None

        self.bandeja = None
        if ES_WINDOWS:
            try:
                self.bandeja = Bandeja(self.root, {
                    "alternar": self.alternar_panel,
                    "tarjeta": self.mostrar_tarjeta,
                    "ocultar_tarjeta": self.ocultar_tarjeta,
                    "clic_aviso": self._clic_aviso,
                    "panel_abierto": self.panel_visible,
                    ID_PANEL: self.alternar_panel,
                    ID_ACTUALIZAR: self.actualizar_ahora,
                    ID_AUTOSTART: lambda: autostart_poner(not autostart_activo()),
                    ID_ACERCA: self._acerca,
                    ID_SALIR: self.salir,
                })
            except OSError as exc:
                registrar(f"no se pudo crear el icono de la bandeja: {exc!r}")

        threading.Thread(target=self._trabajador, daemon=True, name="lecturas").start()
        self.root.after(200, self._leer_cola)
        self._pintar_icono()
        if not silencioso or not self.api or self.bandeja is None:
            self.root.after(100, self.mostrar_panel)

    # ------------------------------------------------------------------ #
    # Lecturas en segundo plano
    # ------------------------------------------------------------------ #
    def _trabajador(self) -> None:
        while self._vivo:
            api = self.api
            espera = self.cfg.refresco
            if api:
                try:
                    limites = api.leer()
                    self.cola.put(("ok", limites, api.org_id))
                except ErrorClave:
                    self.cola.put(("clave",))
                    espera = 300            # no insistir en balde
                except ErrorConexion as exc:
                    self.cola.put(("red", str(exc)))
                    espera = min(300, self.cfg.refresco * (2 ** min(self.fallos + 1, 4)))
                except Exception as exc:  # noqa: BLE001
                    registrar(f"error inesperado leyendo: {exc!r}")
                    self.cola.put(("red", type(exc).__name__))
            self._despertar.wait(espera)
            self._despertar.clear()

    def actualizar_ahora(self) -> None:
        self._despertar.set()

    def _leer_cola(self) -> None:
        try:
            while True:
                msg = self.cola.get_nowait()
                if msg[0] == "ok":
                    self._datos_nuevos(msg[1], msg[2])
                elif msg[0] == "clave":
                    self._error_clave_caducada()
                elif msg[0] == "red":
                    self._error_red(msg[1])
                elif msg[0] == "validada":
                    self._clave_validada(msg[1], msg[2])
                elif msg[0] == "invalida":
                    self.validando = False
                    self.error_clave = msg[1]
                    self.redibujar()
        except queue.Empty:
            pass
        if self._vivo:
            self.root.after(200, self._leer_cola)

    def _datos_nuevos(self, limites: list, org_id: str) -> None:
        self.limites = limites
        self.ultimo_ok = ahora()
        self.tipo_error = None
        self.fallos = 0
        self.aviso_clave_enviado = self.aviso_red_enviado = False
        try:
            self.hist.anotar(limites)
        except sqlite3.Error as exc:
            registrar(f"no se pudo anotar en el historial: {exc}")
        if org_id and org_id != self.cfg.org_id:
            self.cfg.org_id = org_id
            self.cfg.guardar()
        self._comprobar_avisos(limites)
        self._pintar_icono()
        if self.panel_visible() and self.vista == "principal":
            self.redibujar()

    def _error_clave_caducada(self) -> None:
        if self.tipo_error != "clave":
            registrar("clave rechazada por claude.ai")
        self.tipo_error = "clave"
        if not self.aviso_clave_enviado:
            self.aviso_clave_enviado = True
            self._avisar(T("SessionKey caducada"), T("Haz clic aquí para pegar una nueva y seguir viendo el uso."), GRIS, "clave")
        self._pintar_icono()
        if self.panel_visible() and self.vista == "principal":
            self.redibujar()

    def _error_red(self, detalle: str) -> None:
        self.fallos += 1
        self.tipo_error = "red"
        if self.fallos == 1:
            registrar(f"sin conexión: {detalle}")
        if self.fallos >= FALLOS_PARA_AVISO and not self.aviso_red_enviado:
            self.aviso_red_enviado = True
            desde = hora(self.ultimo_ok) if self.ultimo_ok else T("ahora")
            self._avisar(T("Sin conexión con claude.ai"),
                         T("Desde las {desde}. Se reintenta solo y se mantiene el último dato.", desde=desde), GRIS, "panel")
        self._pintar_icono()
        if self.panel_visible() and self.vista == "principal":
            self.redibujar()

    # ------------------------------------------------------------------ #
    # SessionKey
    # ------------------------------------------------------------------ #
    def validar_clave(self) -> None:
        clave = self.clave_borrador.get().strip()
        if not clave or self.validando:
            return
        if not formato_clave_valido(clave):
            self.error_clave = T("No es una SessionKey válida. Debe empezar por sk-ant-sid01- y copiarse entera, sin espacios.")
            self.redibujar()
            return
        self.validando = True
        self.error_clave = ""
        self.redibujar()

        def probar():
            api = ClaudeAPI(clave)
            try:
                self.cola.put(("validada", api, api.leer()))
            except ErrorClave:
                self.cola.put(("invalida", T("claude.ai ha rechazado la clave. Puede haber caducado: vuelve a copiarla.")))
            except ErrorConexion as exc:
                self.cola.put(("invalida", T("No se pudo comprobar la clave ({detalle}). Revisa la conexión.", detalle=T(str(exc)))))
            except Exception as exc:  # noqa: BLE001
                self.cola.put(("invalida", T("No se pudo comprobar la clave ({detalle}).", detalle=type(exc).__name__)))

        threading.Thread(target=probar, daemon=True, name="validacion").start()

    def _clave_validada(self, api: ClaudeAPI, limites: list) -> None:
        cifrada = cifrar_clave(api.clave)
        self.validando = False
        if not cifrada:
            self.error_clave = T("La clave es válida, pero no se pudo guardar cifrada en este equipo.")
            self.redibujar()
            return
        self.cfg.clave_cifrada = cifrada
        self.cfg.org_id = api.org_id
        self.cfg.guardar()
        self.api = api
        self.clave_borrador.set("")
        self.error_clave = ""
        self.ver_clave = False
        self.vista = "principal"
        registrar("clave nueva validada")
        self._datos_nuevos(limites, api.org_id)
        self.redibujar()

    # ------------------------------------------------------------------ #
    # Avisos: una vez por umbral y sesión, también tras reiniciar el programa
    # ------------------------------------------------------------------ #
    def _comprobar_avisos(self, limites: list) -> None:
        tonos = self.tonos()
        umbrales = [u for u in sorted(self.cfg.umbrales) if u[0] > 0]
        ultimo_umbral = umbrales[-1][0] if umbrales else 100
        cambio = False
        for l in limites:
            clave, pct, reinicio = l["clave"], l["pct"], l["reinicio"]
            if not reinicio:
                continue
            es_5h = clave == "five_hour"
            es_semana = clave in CLAVES_SEMANA
            permitido = self.cfg.notif_5h if es_5h else self.cfg.notif_semana
            nombre = T("de 5 h") if es_5h else (T("semanal") if es_semana else T("semanal de {modelo}", modelo=l["nombre"]))

            previo = self._previo.get(clave)
            if (previo and not misma_sesion(previo[0], reinicio) and previo[1] >= ultimo_umbral
                    and self.cfg.aviso_reinicio):
                self._avisar(T("Límite {nombre} disponible", nombre=nombre),
                             T("Se ha reiniciado a las {hora}. Vuelves a tener el 100 %.", hora=hora(previo[0])),
                             tonos[sorted(self.cfg.umbrales)[0][1]], "panel")
            self._previo[clave] = (reinicio, pct)

            candidatos = [v for v, _c in umbrales if pct >= v] + ([100] if pct >= 100 else [])
            nuevos = [v for v in candidatos
                      if not misma_sesion(leer_iso(self.cfg.avisados.get(f"{clave}|{v}")), reinicio)]
            if not nuevos:
                continue
            for v in nuevos:
                self.cfg.avisados[f"{clave}|{v}"] = reinicio.isoformat()
            cambio = True
            if not permitido:
                continue
            # Si se cruzan varios de golpe (por ejemplo, al arrancar) solo se avisa del más alto.
            v = max(nuevos)
            color = color_de(v, self.cfg.umbrales, tonos)
            if v >= 100:
                cuando = (T("hasta las {hora}", hora=hora(reinicio)) if es_5h
                          else T("hasta el {cuando}", cuando=cuando_reinicia(reinicio)))
                self._avisar(T("Límite {nombre} alcanzado", nombre=nombre),
                             T("No podrás usar Claude {cuando}, dentro de {falta}.", cuando=cuando, falta=falta(reinicio)),
                             color, "panel")
                continue
            if es_5h:
                titulo = T("Sesión de 5 h al {v} %", v=v)
                texto = T("Reinicia a las {hora}, en {falta}.", hora=hora(reinicio), falta=falta(reinicio))
                p = proyectar(pct, self._ritmo(), reinicio)
                if p["eta_100"]:
                    texto += T(" A este ritmo llegarás al 100 % a las {hora}.", hora=hora(p["eta_100"]))
            else:
                titulo = (T("Uso semanal al {v} %", v=v) if es_semana
                          else T("{modelo} (semanal) al {v} %", modelo=l["nombre"], v=v))
                texto = T("Reinicia el {cuando}, en {falta}.", cuando=cuando_reinicia(reinicio), falta=falta(reinicio))
            self._avisar(titulo, texto, color, "panel")
        if cambio:
            limite_antiguo = ahora() - timedelta(days=8)
            self.cfg.avisados = {k: v for k, v in self.cfg.avisados.items()
                                 if (leer_iso(v) or ahora()) > limite_antiguo}
            self.cfg.guardar()

    def _avisar(self, titulo: str, texto: str, color: str, accion: str) -> None:
        # Con el panel abierto ya lo estás viendo: no se envía nada.
        if self.panel_visible() or not self.bandeja:
            return
        self.accion_aviso = accion
        # En inglés el título puede empezar por el nombre del límite («weekly limit reached»).
        self.bandeja.avisar(titulo[:1].upper() + titulo[1:], texto, color, self.cfg.sonido)

    def _clic_aviso(self) -> None:
        if self.accion_aviso == "clave":
            self.vista, self.ver_clave = "menu", True
            self.mostrar_panel(conservar_vista=True)
        else:
            self.mostrar_panel()

    # ------------------------------------------------------------------ #
    # Utilidades de datos
    # ------------------------------------------------------------------ #
    def tonos(self, claro: bool = False) -> dict:
        paleta = PALETAS["accesible" if self.cfg.accesible else "normal"]
        return paleta["claro" if claro else "oscuro"]

    def nombre_color(self, c: str) -> str:
        return PALETAS["accesible" if self.cfg.accesible else "normal"]["nombres"][c]

    def color(self, pct: float) -> str:
        return color_de(pct, self.cfg.umbrales, self.tonos())

    def color_base(self) -> str:
        return self.tonos()[sorted(self.cfg.umbrales)[0][1]]

    def principal_limite(self):
        return next((l for l in self.limites if l["clave"] == "five_hour"), self.limites[0] if self.limites else None)

    def semanales(self) -> list:
        p = self.principal_limite()
        return [l for l in self.limites if l is not p]

    def puntos_sesion(self) -> list:
        l = self.principal_limite()
        if not l or not l["reinicio"]:
            return []
        fin = l["reinicio"].timestamp()
        filas = self.hist.serie(l["clave"], fin - ventana_limite(l["clave"]))
        return [(ts, pct) for ts, pct, r in filas if r is None or abs(r - fin) <= TOLERANCIA_SESION]

    def _ritmo(self):
        return ritmo_por_hora(self.puntos_sesion())

    def vivo(self) -> bool:
        return bool(self.limites) and self.tipo_error is None

    def _pintar_icono(self) -> None:
        if not self.bandeja:
            return
        p = self.principal_limite()
        if not self.api or (not self.limites and self.tipo_error is None):
            color, tip = AZUL, f"{TITULO} · {T('sin configurar') if not self.api else T('cargando…')}"
        elif self.tipo_error or not p:
            color = GRIS
            tip = f"{TITULO} · {T('sesión caducada') if self.tipo_error == 'clave' else T('sin conexión')}"
        else:
            color = color_de(p["pct"], self.cfg.umbrales, self.tonos(claro=barra_tareas_clara()))
            tip = T("Claude · {nombre} {pct} · reinicia {cuando}", nombre=p["nombre"], pct=pct_txt(p["pct"]),
                    cuando=cuando_reinicia(p["reinicio"]))
        self.bandeja.actualizar(color, tip)

    # ------------------------------------------------------------------ #
    # Panel: mostrar, ocultar, colocar
    # ------------------------------------------------------------------ #
    def panel_visible(self) -> bool:
        try:
            return self.panel.state() == "normal"
        except tk.TclError:
            return False

    def alternar_panel(self) -> None:
        if self.panel_visible():
            self.ocultar_panel()
        else:
            self.mostrar_panel()

    def mostrar_panel(self, conservar_vista: bool = False) -> None:
        self.ocultar_tarjeta()
        if not conservar_vista:
            self.vista = "principal"
        self.redibujar()
        self.panel.deiconify()
        self.panel.lift()
        redondear_esquinas(self.panel)
        self.panel.focus_force()

    def ocultar_panel(self) -> None:
        if self.bandeja is None:
            self.salir()
            return
        self.panel.withdraw()
        self.vista = "principal"

    def _esc(self) -> None:
        # Esc cierra primero lo que haya encima; con el panel limpio, lo oculta.
        if self.vista == "ayuda":
            self.vista = "menu"
        elif self.vista in ("menu", "acerca"):
            self.vista = "principal"
        else:
            self.ocultar_panel()
            return
        self.redibujar()

    def _colocar(self, ventana, ancla_x=None) -> None:
        ventana.update_idletasks()
        w, h = ventana.winfo_reqwidth(), ventana.winfo_reqheight()
        area = area_trabajo() or (0, 0, ventana.winfo_screenwidth(), ventana.winfo_screenheight())
        m = self.e.px(10)
        if ancla_x is None:
            x = area[2] - w - m
        else:
            x = min(max(area[0] + m, ancla_x - w // 2), area[2] - w - m)
        y = max(area[1] + m, area[3] - h - m)
        ventana.geometry(f"{w}x{h}+{x}+{y}")

    def redibujar(self) -> None:
        for hijo in self.marco.winfo_children():
            hijo.destroy()
        self._fotos = []
        self._pista = None
        if self.vista == "menu":
            self._vista_menu()
        elif self.vista == "ayuda":
            self._vista_ayuda()
        elif self.vista == "acerca":
            self._vista_acerca()
        else:
            self._cabecera()
            fila = tk.Frame(self.marco, bg=C["fondo"])
            fila.pack(fill="x")
            izquierda = tk.Frame(fila, bg=C["fondo"])
            izquierda.pack(side="left", fill="y")
            self._cuerpo(izquierda)
            if self.grafico and self.limites:
                tk.Frame(fila, bg=C["linea"], width=1).pack(side="left", fill="y")
                derecha = tk.Frame(fila, bg=C["fondo"])
                derecha.pack(side="left", fill="y")
                self._columna_sesion(derecha)
                self._historial(izquierda, derecha)
            if self.vivo():
                self._pie()
        # Ancho mínimo: todas las vistas miden como mínimo lo que el panel plegado.
        tk.Frame(self.marco, bg=self.marco["bg"], width=self.e.px(ANCHO_PANEL), height=1).pack()
        self._colocar(self.panel)

    # ------------------------------------------------------------------ #
    # Piezas reutilizables
    # ------------------------------------------------------------------ #
    def L(self, padre, texto, tam=12.0, color=None, peso="normal", bg=None, mono=False, **kw):
        kw.setdefault("anchor", "w")
        return tk.Label(padre, text=texto, font=self.e.f(tam, peso, mono), fg=color or C["texto"],
                        bg=bg or padre["bg"], justify="left", bd=0, **kw)

    def kicker(self, padre, texto, bg=None):
        return self.L(padre, texto.upper(), 10, C["acento_medio"], "bold", bg=bg)

    def boton(self, padre, texto, accion, icono=None, lleno=False):
        """Botón con borde de acento y el mismo hover que los de la cabecera."""
        bg = padre["bg"]
        fg = C["acento_claro"]
        marco = tk.Frame(padre, bg=C["acento"])
        dentro = tk.Frame(marco, bg=bg, cursor="hand2")
        dentro.pack(padx=1, pady=1, fill="both", expand=True)
        contenido = tk.Frame(dentro, bg=bg)
        contenido.pack(pady=self.e.px(6), padx=self.e.px(10), expand=lleno)
        piezas = [dentro, contenido]
        if icono:
            s = self.e.px(13)
            cv = tk.Canvas(contenido, width=s, height=s, bg=bg, highlightthickness=0, bd=0)
            dibujar_icono(cv, icono, s / 2, s / 2, s, fg)
            cv.pack(side="left", padx=(0, self.e.px(6)))
            piezas.append(cv)
        et = self.L(contenido, texto, 11.5, fg, "bold", bg=bg)
        et.pack(side="left")
        piezas.append(et)
        for p in piezas:
            p.bind("<Enter>", lambda _e: [pintar_fondo(x, C["banda"]) for x in piezas])
            p.bind("<Leave>", lambda _e: [pintar_fondo(x, bg) for x in piezas])
            p.bind("<Button-1>", lambda _e: accion())
        return marco

    def imagen(self, w, h, radio, relleno, borde, fondo, pomo=None):
        clave = (w, h, radio, relleno, borde, fondo, pomo)
        if clave not in self._imgs:
            self._imgs[clave] = foto_forma(self.root, w, h, radio, relleno, borde, fondo, pomo=pomo)
        return self._imgs[clave]

    def boton_pequeno(self, padre, texto, accion):
        """Renovar, Editar, Ver: mismo tamaño, esquinas redondeadas y el hover de la cabecera."""
        e = self.e
        bg = padre["bg"]
        w, h = e.px(78), e.px(26)
        normal = self.imagen(w, h, e.px(6), bg, C["acento"], bg)
        sobre = self.imagen(w, h, e.px(6), C["banda"], C["acento"], bg)
        et = tk.Label(padre, text=texto, image=normal, compound="center", font=e.f(11, "bold"),
                      fg=C["acento_claro"], bg=bg, bd=0, cursor="hand2")
        et.bind("<Enter>", lambda _e: et.configure(image=sobre))
        et.bind("<Leave>", lambda _e: et.configure(image=normal))
        et.bind("<Button-1>", lambda _e: accion())
        return et

    def interruptor(self, padre, activo: bool, accion):
        e = self.e
        bg = padre["bg"]
        w, h = e.px(34), e.px(20)
        pista = "#5D5294" if activo else C["borde"]
        pista_sobre = "#6B5FAA" if activo else "#4A4D59"
        normal = self.imagen(w, h, h / 2, pista, None, bg, pomo=(activo, C["texto"]))
        sobre = self.imagen(w, h, h / 2, pista_sobre, None, bg, pomo=(activo, C["texto"]))
        et = tk.Label(padre, image=normal, bg=bg, bd=0, cursor="hand2")
        et.bind("<Enter>", lambda _e: et.configure(image=sobre))
        et.bind("<Leave>", lambda _e: et.configure(image=normal))
        et.bind("<Button-1>", lambda _e: accion())
        return et

    def segmentado(self, padre, opciones, actual, accion, repartir=False):
        marco = tk.Frame(padre, bg=C["borde"])
        dentro = tk.Frame(marco, bg=padre["bg"])
        dentro.pack(padx=1, pady=1, fill="x")
        for i, (clave, texto) in enumerate(opciones):
            activo = clave == actual
            bg = C["banda_borde"] if activo else padre["bg"]
            fg = C["texto"] if activo else C["tenue"]
            et = tk.Label(dentro, text=texto, font=self.e.f(10.5, "bold"), bg=bg, fg=fg,
                          padx=self.e.px(7), pady=self.e.px(2), cursor="hand2")
            if repartir:
                # Sin columnas uniformes: con «2 años» como la más ancha, siete iguales no caben en la columna.
                et.grid(row=0, column=i, sticky="nsew")
                dentro.grid_columnconfigure(i, weight=1)
            else:
                et.pack(side="left")
            et.bind("<Enter>", lambda _e, w=et: w.configure(bg=C["banda"], fg=C["acento_claro"]))
            et.bind("<Leave>", lambda _e, w=et, b=bg, f=fg: w.configure(bg=b, fg=f))
            et.bind("<Button-1>", lambda _e, k=clave: accion(k))
        return marco

    def barra(self, padre, pct, color, ancho, alto=4, marca=None):
        extra = self.e.px(3) if marca is not None else 0
        a = self.e.px(alto)
        cv = tk.Canvas(padre, width=ancho, height=a + 2 * extra, bg=padre["bg"], highlightthickness=0, bd=0)
        cv.create_rectangle(0, extra, ancho, extra + a, fill=C["pista"], outline=C["pista"])
        lleno = max(0.0, min(1.0, pct / 100)) * ancho
        if lleno > 0:
            cv.create_rectangle(0, extra, lleno, extra + a, fill=color, outline=color)
        if marca is not None:
            x = max(1, min(ancho - 1, marca * ancho))
            cv.create_rectangle(x - 1, 0, x + 1, a + 2 * extra, fill=C["texto"], outline=C["texto"])
        return cv

    def logo(self, padre, lado, color):
        foto = foto_logo(self.root, self.e.px(lado), color, padre["bg"])
        self._fotos.append(foto)
        return tk.Label(padre, image=foto, bg=padre["bg"], bd=0)

    def separador(self, padre, margen=16):
        tk.Frame(padre, bg=C["linea"], height=1).pack(fill="x", padx=self.e.px(margen))

    def leyenda_ideal(self, padre, texto):
        f = tk.Frame(padre, bg=padre["bg"])
        tk.Frame(f, bg=C["texto"], width=2, height=self.e.px(9)).pack(side="left", padx=(0, self.e.px(5)))
        self.L(f, texto, 11, C["tenue"]).pack(side="left")
        return f

    # ------------------------------------------------------------------ #
    # Cabecera
    # ------------------------------------------------------------------ #
    def _cabecera(self) -> None:
        e = self.e
        cab = tk.Frame(self.marco, bg=C["fondo"])
        cab.pack(fill="x")
        dentro = tk.Frame(cab, bg=C["fondo"])
        dentro.pack(fill="x", padx=e.px(14), pady=(e.px(12), e.px(11)))
        self.logo(dentro, 24, AZUL).pack(side="left", padx=(0, e.px(10)))
        textos = tk.Frame(dentro, bg=C["fondo"])
        textos.pack(side="left", fill="x", expand=True)
        self.L(textos, "CLAUDE USAGE", 12.5, C["texto"], "bold").pack(anchor="w")
        sub, color_sub = self._subtitulo()
        self.L(textos, sub, 11.5, color_sub).pack(anchor="w")

        grupo = tk.Frame(dentro, bg=C["borde"])
        grupo.pack(side="right")
        fila = tk.Frame(grupo, bg=C["fondo"])
        fila.pack(padx=1, pady=1)
        grafico_activo = self.grafico and self.vista == "principal"
        botones = [("refrescar", T("ACTUALIZAR"), self.actualizar_ahora, False),
                   ("grafico", T("PLEGAR GRÁFICO") if grafico_activo else T("VER EVOLUCIÓN"), self._alternar_grafico, grafico_activo),
                   ("menu", T("MENÚ"), self._abrir_menu, False),
                   ("cerrar", T("CERRAR"), self.ocultar_panel, False)]
        for i, (icono, pista, accion, activo) in enumerate(botones):
            if i:
                tk.Frame(fila, bg=C["borde"], width=1).pack(side="left", fill="y")
            self._boton_cabecera(fila, icono, pista, accion, activo, cab)
        tk.Frame(self.marco, bg=C["linea"], height=1).pack(fill="x")

    def _boton_cabecera(self, padre, icono, pista, accion, activo, cab):
        e = self.e
        w, h = e.px(28), e.px(26)
        bg = C["banda"] if activo else C["fondo"]
        fg = C["acento_claro"] if activo else C["texto_2"]
        cv = tk.Canvas(padre, width=w, height=h, bg=bg, highlightthickness=0, bd=0, cursor="hand2")
        dibujar_icono(cv, icono, w / 2, h / 2, e.px(14), fg)

        def entrar(_e):
            cv.configure(bg=C["banda"])
            cv.delete("all")
            dibujar_icono(cv, icono, w / 2, h / 2, e.px(14), C["acento_claro"])
            if self._pista is None:
                self._pista = tk.Label(cab, font=e.f(9, "bold"), bg=C["borde"], fg=C["texto"], padx=6, pady=3)
            self._pista.configure(text=pista)
            self._pista.place(relx=1.0, x=-e.px(14), y=e.px(42), anchor="ne")
            self._pista.lift()

        def salir(_e):
            cv.configure(bg=bg)
            cv.delete("all")
            dibujar_icono(cv, icono, w / 2, h / 2, e.px(14), fg)
            if self._pista is not None:
                self._pista.place_forget()

        cv.bind("<Enter>", entrar)
        cv.bind("<Leave>", salir)
        cv.bind("<Button-1>", lambda _e: accion())
        cv.pack(side="left")

    def _subtitulo(self):
        if self.validando:
            return T("Validando…"), C["tenue"]
        if not self.api:
            return T("Sin configurar"), C["tenue"]
        cada = f"{self.cfg.refresco} s" if self.cfg.refresco < 60 else f"{self.cfg.refresco // 60} min"
        if self.tipo_error == "clave":
            return T("Caducada · dato {hora}", hora=hora(self.ultimo_ok)), self.tonos()["red"]
        if self.tipo_error == "red":
            return T("Sin conexión · dato {hora}", hora=hora(self.ultimo_ok)), self.tonos()["red"]
        if not self.limites:
            return T("Cargando…"), C["tenue"]
        return T("{hora} · cada {cada}", hora=hora(self.ultimo_ok), cada=cada), C["tenue"]

    def _alternar_grafico(self) -> None:
        self.grafico = not (self.grafico and self.vista == "principal")
        self.vista = "principal"
        self.redibujar()

    def _abrir_menu(self) -> None:
        self.grafico = False
        self.vista = "menu"
        self.redibujar()

    # ------------------------------------------------------------------ #
    # Cuerpo principal
    # ------------------------------------------------------------------ #
    def _cuerpo(self, padre) -> None:
        e = self.e
        if not self.api:
            self._primer_arranque(padre)
            return
        if self.tipo_error:
            self._aviso_error(padre)
        if not self.limites:
            caja = tk.Frame(padre, bg=C["fondo"])
            caja.pack(fill="x", padx=e.px(16), pady=e.px(18))
            self.L(caja, T("Sin datos todavía.") if self.tipo_error else T("Consultando claude.ai…"), 11.5, C["tenue"]).pack(anchor="w")
            return
        vivo = self.vivo()
        p = self.principal_limite()
        color = self.color(p["pct"]) if vivo else C["texto_2"]
        color_barra = self.color(p["pct"]) if vivo else GRIS
        ancho = e.px(ANCHO_PANEL - 32)

        bloque = tk.Frame(padre, bg=C["fondo"])
        bloque.pack(fill="x", padx=e.px(16), pady=(e.px(14), e.px(12)))
        self.kicker(bloque, T("Sesión · 5 h") if p["clave"] == "five_hour" else p["nombre"]).pack(anchor="w")
        fila = tk.Frame(bloque, bg=C["fondo"])
        fila.pack(fill="x", pady=(e.px(6), 0))
        cifra = tk.Frame(fila, bg=C["fondo"])
        cifra.pack(side="left", anchor="s")
        self.L(cifra, f"{round(p['pct'])}", 44, color, "bold").pack(side="left", anchor="s")
        self.L(cifra, "%", 18, C["tenue"], "bold").pack(side="left", anchor="s", pady=(0, e.px(7)))
        derecha = tk.Frame(fila, bg=C["fondo"])
        derecha.pack(side="right", anchor="s", pady=(0, e.px(6)))
        self.L(derecha, T("reinicia a las {hora}", hora=hora(p["reinicio"])), 12.5, C["texto"], "bold").pack(anchor="e")
        self.L(derecha, T("en {falta}", falta=falta(p["reinicio"])), 11, C["tenue"]).pack(anchor="e")

        ideal = fraccion_transcurrida(p["reinicio"], ventana_limite(p["clave"]))
        self.barra(bloque, p["pct"], color_barra, ancho, alto=6, marca=ideal).pack(anchor="w", pady=(e.px(8), 0))
        pie = tk.Frame(bloque, bg=C["fondo"])
        pie.pack(fill="x", pady=(e.px(5), 0))
        self.leyenda_ideal(pie, T("ritmo ideal ahora {n} %", n=round(ideal * 100))).pack(side="left")
        desvio = round(p["pct"] - ideal * 100)
        texto = T("en ritmo") if desvio == 0 else (
            T("{signo}{n} pts por encima", signo="+", n=desvio) if desvio > 0
            else T("{signo}{n} pts por debajo", signo="−", n=-desvio))
        self.L(pie, texto, 11, C["texto"] if desvio > 5 else C["tenue"], "bold" if desvio > 5 else "normal").pack(side="right")

        otros = self.semanales()
        if otros:
            self.separador(padre)
            sem = tk.Frame(padre, bg=C["fondo"])
            sem.pack(fill="x", padx=e.px(16), pady=(e.px(11), e.px(14)))
            cab = tk.Frame(sem, bg=C["fondo"])
            cab.pack(fill="x")
            self.kicker(cab, T("Semanales")).pack(side="left")
            r = otros[0]["reinicio"]
            self.L(cab, T("{cuando} · en {falta}", cuando=cuando_reinicia(r), falta=falta(r)), 11, C["tenue"]).pack(side="right")
            ideal_s = fraccion_transcurrida(r, VENTANA_SEMANA)
            self.leyenda_ideal(sem, T("ritmo ideal ahora {n} %", n=round(ideal_s * 100))).pack(anchor="w", pady=(e.px(2), e.px(6)))
            tabla = tk.Frame(sem, bg=C["fondo"])
            tabla.pack(fill="x")
            tabla.grid_columnconfigure(1, weight=1)
            ancho_b = ancho - e.px(70 + 48 + 24)
            for i, l in enumerate(otros):
                self.L(tabla, l["nombre"], 12.5, C["texto"], "bold").grid(row=i, column=0, sticky="w", pady=e.px(3))
                marca = fraccion_transcurrida(l["reinicio"], ventana_limite(l["clave"]))
                self.barra(tabla, l["pct"], self.color(l["pct"]) if vivo else GRIS, ancho_b, marca=marca).grid(
                    row=i, column=1, sticky="w", padx=e.px(12))
                self.L(tabla, pct_txt(l["pct"]), 12.5, C["texto"], "bold", anchor="e", width=5).grid(row=i, column=2, sticky="e")

    def _aviso_error(self, padre) -> None:
        e = self.e
        caja_b = tk.Frame(padre, bg=C["borde"])
        caja_b.pack(fill="x", padx=e.px(12), pady=(e.px(12), 0))
        caja = tk.Frame(caja_b, bg=C["pista"])
        caja.pack(fill="x", padx=1, pady=1)
        s = e.px(16)
        cv = tk.Canvas(caja, width=s, height=s, bg=C["pista"], highlightthickness=0)
        dibujar_icono(cv, "clave" if self.tipo_error == "clave" else "aviso", s / 2, s / 2, s, self.tonos()["red"])
        cv.pack(side="left", anchor="n", padx=(e.px(11), e.px(10)), pady=e.px(10))
        textos = tk.Frame(caja, bg=C["pista"])
        textos.pack(side="left", fill="x", expand=True, pady=e.px(9))
        if self.tipo_error == "clave":
            t, x, b, accion = (T("La SessionKey ha caducado"),
                               T("Los datos son de las {hora}. Pega una nueva para seguir.", hora=hora(self.ultimo_ok)),
                               T("Renovar"), self._ir_a_clave)
        else:
            t, x, b, accion = (T("No se puede conectar con claude.ai"),
                               T("{n} intentos fallidos. Se reintenta solo.", n=self.fallos),
                               T("Reintentar"), self.actualizar_ahora)
        self.L(textos, t, 12.5, C["texto"], "bold").pack(anchor="w")
        self.L(textos, x, 11.5, C["suave"], wraplength=e.px(190)).pack(anchor="w")
        self.boton_pequeno(caja, b, accion).pack(side="right", padx=e.px(10))

    def _ir_a_clave(self) -> None:
        self.vista, self.ver_clave, self.grafico = "menu", True, False
        self.redibujar()

    def _primer_arranque(self, padre) -> None:
        e = self.e
        caja = tk.Frame(padre, bg=C["fondo"])
        caja.pack(fill="x", padx=e.px(16), pady=(e.px(18), e.px(16)))
        self.L(caja, T("Conecta tu cuenta de Claude"), 17, C["texto"], "bold").pack(anchor="w")
        self.L(caja, T("El widget lee tu uso con la SessionKey de tu sesión en claude.ai."), 12.5, C["suave"],
               wraplength=e.px(310)).pack(anchor="w", pady=(e.px(4), e.px(12)))
        self._lista_pasos(caja, 12)
        self._campo_clave(caja, T("Conectar"))
        self.L(caja, T("Se guarda cifrada con DPAPI solo para tu usuario de Windows. No la compartas."), 11, C["tenue"],
               wraplength=e.px(310)).pack(anchor="w", pady=(e.px(8), 0))

    def _lista_pasos(self, padre, tam) -> None:
        e = self.e
        for n, (texto, codigo) in enumerate(PASOS_SESSIONKEY, start=1):
            f = tk.Frame(padre, bg=padre["bg"])
            f.pack(fill="x", pady=(0, e.px(8)))
            s = e.px(16)
            cv = tk.Canvas(f, width=s, height=s, bg=padre["bg"], highlightthickness=0)
            cv.create_oval(1, 1, s - 1, s - 1, outline="#5D5294")
            cv.create_text(s / 2, s / 2, text=str(n), fill=C["acento_claro"], font=e.f(9, "bold"))
            cv.pack(side="left", anchor="n", padx=(0, e.px(9)), pady=(e.px(1), 0))
            col = tk.Frame(f, bg=padre["bg"])
            col.pack(side="left", fill="x", expand=True)
            self.L(col, T(texto), tam, C["texto_2"], wraplength=e.px(270)).pack(anchor="w")
            if codigo:
                self.L(col, f" {T(codigo)} ", 10.5, C["acento_medio"], bg=C["hundido"], mono=True).pack(anchor="w", pady=(e.px(3), 0))

    def _campo_clave(self, padre, texto_boton) -> None:
        e = self.e
        fila = tk.Frame(padre, bg=padre["bg"])
        fila.pack(fill="x")
        borde = tk.Frame(fila, bg=C["borde"])
        borde.pack(side="left", fill="x", expand=True, padx=(0, e.px(6)))
        entrada = tk.Entry(borde, textvariable=self.clave_borrador, show="•", font=e.f(11.5, mono=True),
                           bg=C["hundido"], fg=C["texto"], insertbackground=C["texto"], relief="flat", bd=e.px(5))
        entrada.pack(fill="x", padx=1, pady=1)
        entrada.bind("<Return>", lambda _e: self.validar_clave())
        entrada.bind("<FocusIn>", lambda _e: borde.configure(bg=C["acento"]))
        entrada.bind("<FocusOut>", lambda _e: borde.configure(bg=C["borde"]))
        entrada.bind("<Key>", lambda ev: self._limpiar_error_clave() if ev.keysym != "Return" else None, add="+")
        self.boton(fila, T("Validando…") if self.validando else texto_boton, self.validar_clave).pack(side="right")
        if self.error_clave:
            self.L(padre, self.error_clave, 11, self.tonos()["red"], wraplength=e.px(290)).pack(anchor="w", pady=(e.px(6), 0))
        self.root.after(50, lambda: entrada.winfo_exists() and entrada.focus_set())

    def _limpiar_error_clave(self) -> None:
        if self.error_clave:
            self.error_clave = ""
            self.root.after_idle(self.redibujar)

    def _pie(self) -> None:
        e = self.e
        p = self.principal_limite()
        ritmo = self._ritmo()
        pr = proyectar(p["pct"], ritmo, p["reinicio"])
        pie = tk.Frame(self.marco, bg=C["fondo_pie"])
        pie.pack(fill="x")
        tk.Frame(pie, bg=C["linea"], height=1).pack(fill="x")
        dentro = tk.Frame(pie, bg=C["fondo_pie"])
        dentro.pack(fill="x", padx=e.px(16), pady=(e.px(11), e.px(12)))
        agota = pr["eta_100"] is not None
        s = e.px(8)
        cv = tk.Canvas(dentro, width=s, height=s, bg=C["fondo_pie"], highlightthickness=0)
        c = self.color(p["pct"]) if agota else self.color_base()
        cv.create_oval(0, 0, s, s, fill=c, outline=c)
        cv.pack(side="left", anchor="n", padx=(0, e.px(9)), pady=(e.px(5), 0))
        col = tk.Frame(dentro, bg=C["fondo_pie"])
        col.pack(side="left", fill="x")
        if agota:
            titulo = T("A este ritmo, 100 % a las {hora}", hora=hora(pr["eta_100"]))
            detalle = T("{falta} antes del reinicio · ritmo +{n} %/h", falta=falta(p["reinicio"], pr["eta_100"]), n=round(ritmo))
        elif pr["sobra"] is not None:
            titulo = T("A este ritmo llegas al reinicio con {n} % sin usar", n=pr["sobra"])
            detalle = T("Ritmo +{n} %/h · reinicio a las {hora}", n=round(ritmo), hora=hora(p["reinicio"]))
        else:
            titulo, detalle = T("Consumo estable"), T("Reinicio a las {hora}", hora=hora(p["reinicio"]))
        self.L(col, titulo, 13, C["texto"], "bold").pack(anchor="w")
        self.L(col, detalle, 11.5, C["tenue"]).pack(anchor="w")

    # ------------------------------------------------------------------ #
    # Columna: evolución de la sesión y consumo por minutos
    # ------------------------------------------------------------------ #
    def _columna_sesion(self, padre) -> None:
        e = self.e
        p = self.principal_limite()
        col = tk.Frame(padre, bg=C["fondo"])
        col.pack(padx=e.px(14), pady=e.px(12))
        vivo = self.vivo()
        color = self.color(p["pct"]) if vivo else GRIS
        ventana = ventana_limite(p["clave"])
        fin = p["reinicio"].timestamp() if p["reinicio"] else time.time()
        inicio = fin - ventana
        puntos = self.puntos_sesion()

        cab = tk.Frame(col, bg=C["fondo"])
        cab.pack(fill="x")
        self.kicker(cab, T("Evolución de la sesión")).pack(side="left")
        self.L(cab, f"{hora_ts(inicio)} – {hora_ts(fin)}", 11, C["tenue"]).pack(side="right")

        W, H = e.px(294), e.px(170)
        cv = tk.Canvas(col, width=W, height=H, bg=C["fondo"], highlightthickness=0)
        cv.pack(pady=(e.px(8), 0))
        x0, x1, y0, y1 = e.px(30), W - e.px(4), e.px(10), H - e.px(20)

        def X(t):
            return x0 + (t - inicio) / ventana * (x1 - x0)

        def Y(v):
            return y1 - min(v, 100) / 100 * (y1 - y0)

        for v in (25, 50, 75, 100):
            cv.create_line(x0, Y(v), x1, Y(v), fill=C["linea"])
        for v in (0, 25, 50, 75, 100):
            cv.create_line(x0 - e.px(4), Y(v), x0, Y(v), fill=C["gris_barra"])
            cv.create_text(x0 - e.px(7), Y(v), text=porcentaje(v), anchor="e", fill=C["tenue"], font=e.f(9.5))
        for v, c in sorted(self.cfg.umbrales):
            if v > 0:
                cv.create_line(x0, Y(v), x1, Y(v), fill=self.tonos()[c] if vivo else GRIS, dash=(3, 3))
        cv.create_line(x0, y0, x0, y1, fill=C["gris_barra"])
        cv.create_line(x0, y1, x1, y1, fill=C["gris_barra"])
        cv.create_line(X(inicio), Y(0), X(fin), Y(100), fill=C["muy_tenue"], dash=(3, 3))
        pasos = 5 if ventana <= 86400 else 7
        for i in range(pasos + 1):
            t = inicio + i * ventana / pasos
            cv.create_line(X(t), y1, X(t), y1 + e.px(4), fill=C["gris_barra"])
            texto = hora_ts(t) if ventana <= 86400 else etiqueta_eje(t, 7)
            cv.create_text(X(t), H - e.px(6), text=texto, fill=C["tenue"], font=e.f(9))
        if puntos:
            coords = [(X(t), Y(v)) for t, v in puntos]
            if len(coords) > 1:
                poli = [(coords[0][0], y1)] + coords + [(coords[-1][0], y1)]
                cv.create_polygon(*[c for xy in poli for c in xy], fill=mezclar(color, C["fondo"], 0.14), outline="")
                cv.create_line(*[c for xy in coords for c in xy], fill=color, width=e.px(2), joinstyle="round")
            ax, ay = coords[-1]
            pr = proyectar(p["pct"], self._ritmo(), p["reinicio"])
            if pr["eta_100"]:
                cv.create_line(ax, ay, X(pr["eta_100"].timestamp()), Y(100), fill=color, dash=(2, 3), width=e.px(1.5))
            elif pr["sobra"] is not None:
                cv.create_line(ax, ay, X(fin), Y(100 - pr["sobra"]), fill=color, dash=(2, 3), width=e.px(1.5))
            r = e.px(3.5)
            cv.create_oval(ax - r, ay - r, ax + r, ay + r, fill=C["fondo"], outline=color, width=e.px(2))

        ley = tk.Frame(col, bg=C["fondo"])
        ley.pack(fill="x", pady=(e.px(6), 0))
        for texto, c, estilo in ((T("Uso real"), color, None), (T("Ritmo ideal"), C["muy_tenue"], (3, 3)),
                                 (T("Proyección"), color, (2, 3))):
            f = tk.Frame(ley, bg=C["fondo"])
            f.pack(side="left", padx=(0, e.px(12)))
            m = tk.Canvas(f, width=e.px(12), height=e.px(6), bg=C["fondo"], highlightthickness=0)
            m.create_line(0, e.px(3), e.px(12), e.px(3), fill=c, width=e.px(1.5), dash=estilo)
            m.pack(side="left", padx=(0, e.px(5)))
            self.L(f, texto, 10.5, C["suave"]).pack(side="left")

        self._consumo_minutos(col, puntos, inicio, fin, vivo)

    def _consumo_minutos(self, col, puntos, inicio, fin, vivo) -> None:
        e = self.e
        g = self.grano
        cab = tk.Frame(col, bg=C["fondo"])
        cab.pack(fill="x", pady=(e.px(14), 0))
        self.kicker(cab, T("Consumo por minutos")).pack(side="left")
        self.segmentado(cab, [(1, "1 min"), (5, "5 min"), (10, "10 min")], g, self._cambiar_grano).pack(side="right")

        transcurrido = max(60.0, min(fin, time.time()) - inicio)
        n = max(1, math.ceil(transcurrido / 60 / g))
        bins = [0.0] * n
        for (_t0, v0), (t1, v1) in zip(puntos, puntos[1:]):
            i = int((t1 - inicio) / 60 // g)
            if 0 <= i < n:
                bins[i] += max(0.0, v1 - v0)
        ventana = fin - inicio
        # Ritmo ideal: el que gasta el 100 % justo al reinicio. Cada tramo se compara con él.
        ideal_min = 100 / (ventana / 60)
        tonos = self.tonos()

        def ratio(i):
            minutos = min(g, transcurrido / 60 - i * g)
            return bins[i] / (ideal_min * max(0.5, minutos))

        def color_ratio(i):
            if not vivo:
                return GRIS
            r = ratio(i)
            return C["gris_barra"] if r < 1 else tonos["green"] if r < 1.5 else tonos["yellow"] if r < 2.5 else tonos["red"]

        lectura = tk.Frame(col, bg=C["fondo"], height=e.px(20))
        lectura.pack(fill="x", pady=(e.px(8), 0))
        lectura.pack_propagate(False)
        l_rango = self.L(lectura, "", 12.5, C["texto"], "bold", width=11)
        l_rango.pack(side="left")
        l_delta = self.L(lectura, "", 12.5, C["texto"], "bold", width=7)
        l_delta.pack(side="left")
        l_nota = self.L(lectura, "", 11, C["tenue"])
        l_nota.pack(side="right")
        mayor = max(range(n), key=lambda i: bins[i])

        def mostrar(i, fija=False):
            t0 = inicio + i * g * 60
            l_rango.configure(text=f"{hora_ts(t0)}–{hora_ts(min(t0 + g * 60, inicio + transcurrido))}")
            v = bins[i]
            l_delta.configure(text=porcentaje(0) if v < 0.05 else "+" + porcentaje(decimal_txt(v) if v < 10 else round(v)))
            l_nota.configure(text=T("mayor pico · {r}× el ideal", r=decimal_txt(ratio(i))) if fija
                             else T("{r}× el ritmo ideal", r=decimal_txt(ratio(i))))

        mostrar(mayor, True)

        W, H = e.px(294), e.px(62)
        cv = tk.Canvas(col, width=W, height=H, bg=C["fondo"], highlightthickness=0)
        cv.pack(pady=(e.px(4), 0))
        x0, x1, base = e.px(30), W - e.px(4), H - e.px(12)
        cv.create_line(x0, base, x1, base, fill=C["gris_barra"])
        cv.create_line(x0, e.px(6), x0, base, fill=C["gris_barra"])
        maximo = max(bins) or 1
        cv.create_text(x0 - e.px(6), e.px(8), text=decimal_txt(maximo) if maximo < 10 else str(round(maximo)),
                       anchor="e", fill=C["tenue"], font=e.f(9))
        cv.create_text(x0 - e.px(6), base, text="0", anchor="e", fill=C["tenue"], font=e.f(9))
        ancho_bin = (x1 - x0) * (g * 60) / ventana
        hueco = 0.4 if g == 1 else 1
        rects = []
        for i, v in enumerate(bins):
            h = (v / maximo) * (base - e.px(8)) if v > 0.02 else 0
            bx = x0 + i * ancho_bin
            rects.append(cv.create_rectangle(bx + hueco / 2, base - h, bx + max(0.6, ancho_bin - hueco), base,
                                             fill=color_ratio(i), outline=""))
        pasos = 5 if ventana <= 86400 else 7
        for k in range(pasos + 1):
            t = inicio + k * ventana / pasos
            cv.create_text(x0 + (t - inicio) / ventana * (x1 - x0), H - e.px(3),
                           text=hora_ts(t) if ventana <= 86400 else etiqueta_eje(t, 7), fill=C["muy_tenue"], font=e.f(8.5))
        estado = {"i": None}

        def mover(ev):
            i = int((ev.x - x0) // ancho_bin) if ancho_bin else -1
            if not 0 <= i < n or i == estado["i"]:
                return
            if estado["i"] is not None:
                cv.itemconfigure(rects[estado["i"]], fill=color_ratio(estado["i"]))
            estado["i"] = i
            cv.itemconfigure(rects[i], fill=C["texto"])
            mostrar(i)

        def salir(_ev):
            if estado["i"] is not None:
                cv.itemconfigure(rects[estado["i"]], fill=color_ratio(estado["i"]))
            estado["i"] = None
            mostrar(mayor, True)

        cv.bind("<Motion>", mover)
        cv.bind("<Leave>", salir)

        ley = tk.Frame(col, bg=C["fondo"])
        ley.pack(fill="x", pady=(e.px(6), 0))
        for texto, c in ((T("Bajo el ideal"), C["gris_barra"]), (T("Parejo"), tonos["green"]),
                         (T("Algo más"), tonos["yellow"]), (T("Pico"), tonos["red"])):
            f = tk.Frame(ley, bg=C["fondo"])
            f.pack(side="left", padx=(0, e.px(8)))
            tk.Frame(f, bg=c, width=e.px(8), height=e.px(8)).pack(side="left", padx=(0, e.px(4)))
            self.L(f, texto, 10, C["suave"]).pack(side="left")
        self.L(col, T("Ritmo ideal {pct} cada {g} min (100 % en {h} h)", pct=porcentaje(decimal_txt(ideal_min * g)), g=g,
                      h=round(ventana / 3600)), 10.5, C["muy_tenue"]).pack(anchor="w", pady=(e.px(4), 0))

    def _cambiar_grano(self, g) -> None:
        self.grano = g
        self.redibujar()

    # ------------------------------------------------------------------ #
    # Historial
    # ------------------------------------------------------------------ #
    def _historial(self, padre, derecha) -> None:
        """Vista de evolución: el gráfico va bajo los semanales y la lista de sesiones
        en la columna derecha, bajo el consumo por minutos, para que las dos midan parecido."""
        e = self.e
        self.separador(padre)
        col = tk.Frame(padre, bg=C["fondo"])
        col.pack(fill="x", padx=e.px(16), pady=(e.px(11), e.px(14)))
        cab = tk.Frame(col, bg=C["fondo"])
        cab.pack(fill="x", pady=(0, e.px(8)))
        self.kicker(cab, T("Historial")).pack(side="left")
        self.segmentado(cab, [("sesiones", T("Sesiones")), ("semana", T("Uso semanal"))], self.serie,
                        self._cambiar_serie).pack(side="right")
        rangos = [(1, "24 h"), (7, "7 d"), (30, "30 d"), (90, T("3 m")), (180, T("6 m")), (365, T("1 año")), (730, T("2 años"))]
        self.segmentado(col, rangos, self.rango, self._cambiar_rango, repartir=True).pack(fill="x")

        es_semana = self.serie == "semana"
        clave = "five_hour" if not es_semana else next(
            (l["clave"] for l in self.limites if l["clave"] in CLAVES_SEMANA), "seven_day")
        t1 = time.time()
        t0 = t1 - self.rango * 86400
        # Solo sesiones cerradas: la actual ya se ve en el panel.
        tramos = [g for g in self.hist.tramos(clave, t0) if g["reinicio"] and g["reinicio"] < t1]
        puntos = [pt for g in tramos for pt in g["puntos"]]
        cierres = [(g["fin"], g["cierre"], g) for g in tramos]
        media = round(sum(c[1] for c in cierres) / len(cierres)) if cierres else 0
        color_linea = self.color(media) if cierres else C["muy_tenue"]

        titular = tk.Frame(col, bg=C["fondo"], height=e.px(54))
        titular.pack(fill="x", pady=(e.px(12), 0))
        titular.pack_propagate(False)
        fila = tk.Frame(titular, bg=C["fondo"])
        fila.pack(fill="x")
        l_valor = self.L(fila, "—", 28, C["texto"], "bold")
        l_valor.pack(side="left")
        cambio = round(cierres[-1][1] - cierres[0][1]) if len(cierres) > 1 else 0
        self.L(fila, T("{signo}{n} pts en {rango}", signo="+" if cambio >= 0 else "−", n=abs(cambio),
                       rango=dict(rangos)[self.rango]), 12,
               C["acento_claro"], "bold").pack(side="left", padx=e.px(8), anchor="s", pady=(0, e.px(5)))
        fila2 = tk.Frame(titular, bg=C["fondo"])
        fila2.pack(fill="x")
        l_fecha = self.L(fila2, "", 11, C["tenue"])
        l_fecha.pack(side="left")
        self.L(fila2, T("media {n} %", n=media) if cierres else "", 11, C["tenue"]).pack(side="right")

        def rotulo(ts, v):
            l_valor.configure(text=pct_txt(v))
            d = datetime.fromtimestamp(ts, timezone.utc)
            l_fecha.configure(text=T("Semana a {fecha}", fecha=fecha_corta(d, minuscula=True)) if es_semana else fecha_corta(d))

        if cierres:
            rotulo(cierres[-1][0], cierres[-1][1])
        else:
            l_fecha.configure(text=T("Todavía no hay sesiones cerradas en este periodo."))

        W, H = e.px(ANCHO_PANEL - 32), e.px(110)
        cv = tk.Canvas(col, width=W, height=H, bg=C["fondo"], highlightthickness=0, cursor="crosshair")
        cv.pack(pady=(e.px(6), 0))
        x0, x1, y0, y1 = e.px(34), W - e.px(4), e.px(12), H - e.px(10)

        def X(t):
            return x0 + (t - t0) / (t1 - t0) * (x1 - x0)

        def Y(v):
            return y1 - min(v, 100) / 100 * (y1 - y0)

        for v in (50, 100):
            cv.create_line(x0, Y(v), x1, Y(v), fill=C["linea"])
        cv.create_line(x0, y0, x0, y1, fill=C["gris_barra"])
        cv.create_line(x0, y1, x1, y1, fill=C["gris_barra"])
        for v in (0, 50, 100):
            cv.create_text(x0 - e.px(7), Y(v), text=porcentaje(v), anchor="e", fill=C["tenue"], font=e.f(9.5))
        if len(puntos) > 1:
            coords = [(X(t), Y(v)) for t, v in puntos]
            poli = [(coords[0][0], y1)] + coords + [(coords[-1][0], y1)]
            cv.create_polygon(*[c for xy in poli for c in xy], fill=mezclar(color_linea, C["fondo"], 0.12), outline="")
            cv.create_line(*[c for xy in coords for c in xy], fill=color_linea, width=e.px(1.5), joinstyle="round")
        cursor = [cv.create_line(0, y0, 0, y1, fill=C["tenue"], dash=(2, 3), state="hidden"),
                  cv.create_oval(0, 0, 0, 0, fill=C["fondo"], outline=color_linea, width=e.px(2), state="hidden")]

        def marcar(ts, v):
            x, y, r = X(ts), Y(v), e.px(3.5)
            cv.coords(cursor[0], x, y0, x, y1)
            cv.coords(cursor[1], x - r, y - r, x + r, y + r)
            for it in cursor:
                cv.itemconfigure(it, state="normal")
            rotulo(ts, v)

        def mover(ev):
            if not puntos:
                return
            t = t0 + (ev.x - x0) / (x1 - x0) * (t1 - t0)
            marcar(*min(puntos, key=lambda pt: abs(pt[0] - t)))

        def salir(_ev):
            for it in cursor:
                cv.itemconfigure(it, state="hidden")
            if cierres:
                rotulo(cierres[-1][0], cierres[-1][1])

        cv.bind("<Motion>", mover)
        cv.bind("<Leave>", salir)

        eje = tk.Frame(col, bg=C["fondo"])
        eje.pack(fill="x", padx=(e.px(26), 0))
        for i in range(4):
            self.L(eje, etiqueta_eje(t0 + (t1 - t0) * i / 3, self.rango), 9.5, C["tenue"]).pack(
                side="left", expand=True, anchor="w" if i == 0 else "e" if i == 3 else "center")

        self.separador(derecha, margen=14)
        lista = tk.Frame(derecha, bg=C["fondo"])
        lista.pack(fill="x", padx=e.px(14), pady=(e.px(11), e.px(14)))
        cab2 = tk.Frame(lista, bg=C["fondo"])
        cab2.pack(fill="x", pady=(0, e.px(4)))
        self.kicker(cab2, T("Semanas anteriores") if es_semana else T("Sesiones anteriores")).pack(side="left")
        self.L(cab2, T("uso al cierre"), 11, C["tenue"]).pack(side="right")
        ventana = VENTANA_SEMANA if es_semana else VENTANA_5H
        for ts, v, g in reversed(cierres[-4:]):
            ini = datetime.fromtimestamp(g["reinicio"] - ventana, timezone.utc)
            local = ini.astimezone()
            texto = T("Semana del {n} {mes}", n=local.day, mes=mes_c(local)) if es_semana else fecha_corta(ini)
            f = tk.Frame(lista, bg=C["fondo"], cursor="hand2")
            f.pack(fill="x")
            a = self.L(f, texto, 12, C["texto"])
            a.pack(side="left", pady=e.px(5), padx=e.px(4))
            nota = self.L(f, T("llegó al límite") if v >= 100 else "", 10.5, C["tenue"])
            nota.pack(side="left")
            pc = self.L(f, pct_txt(v), 12, C["texto"], "bold")
            pc.pack(side="right", padx=e.px(4))
            b = self.barra(f, v, self.color(v), e.px(70))
            b.pack(side="right", padx=e.px(10))
            piezas = (f, a, nota, pc, b)
            for w in piezas:
                w.bind("<Enter>", lambda _e, ps=piezas: [x.configure(bg=C["pista"]) for x in ps])
                w.bind("<Leave>", lambda _e, ps=piezas: [x.configure(bg=C["fondo"]) for x in ps])
                w.bind("<Button-1>", lambda _e, t=ts, vv=v: marcar(t, vv))

        pie = tk.Frame(lista, bg=C["fondo"])
        pie.pack(fill="x", pady=(e.px(8), 0))
        exportar = self.L(pie, T("Exportar CSV"), 11, C["acento_claro"], "bold", cursor="hand2")
        exportar.pack(side="right")
        exportar.bind("<Button-1>", lambda _e: self._exportar())
        exportar.bind("<Enter>", lambda _e: exportar.configure(bg=C["banda"]))
        exportar.bind("<Leave>", lambda _e: exportar.configure(bg=C["fondo"]))
        if self.nota_csv:
            self.L(lista, self.nota_csv, 10.5, self.tonos()["green"]).pack(anchor="e", pady=(e.px(4), 0))

    def _cambiar_serie(self, s) -> None:
        self.serie = s
        self.redibujar()

    def _cambiar_rango(self, r) -> None:
        self.rango = r
        self.redibujar()

    def _exportar(self) -> None:
        carpeta = Path.home() / "Downloads"
        if not carpeta.exists():
            carpeta = Path.home()
        destino = carpeta / f"claude_usage_{datetime.now():%Y%m%d}.csv"
        if self.hist.exportar_csv(destino):
            self.nota_csv = T("Guardado en {carpeta} · {archivo}", carpeta=carpeta.name, archivo=destino.name)
        else:
            self.nota_csv = T("No se pudo exportar el historial.")
        self.redibujar()

        def borrar():
            self.nota_csv = ""
            if self.vista == "principal" and self.grafico and self.panel_visible():
                self.redibujar()

        self.root.after(5000, borrar)

    # ------------------------------------------------------------------ #
    # Menú
    # ------------------------------------------------------------------ #
    def _banda_menu(self) -> None:
        e = self.e
        banda = tk.Frame(self.marco, bg=C["banda"])
        banda.pack(fill="x")
        dentro = tk.Frame(banda, bg=C["banda"])
        dentro.pack(fill="x", padx=e.px(14), pady=e.px(12))
        self.logo(dentro, 22, AZUL).pack(side="left", padx=(0, e.px(10)))
        self.L(dentro, "CLAUDE USAGE", 12.5, C["texto"], "bold").pack(side="left")
        s = e.px(26)
        cv = tk.Canvas(dentro, width=s, height=s, bg=C["banda"], highlightthickness=0, cursor="hand2")
        dibujar_icono(cv, "cerrar", s / 2, s / 2, e.px(14), C["texto"])
        cv.pack(side="right")
        cv.bind("<Enter>", lambda _e: pintar_fondo(cv, C["banda_borde"]))
        cv.bind("<Leave>", lambda _e: pintar_fondo(cv, C["banda"]))
        cv.bind("<Button-1>", lambda _e: self._volver_principal())
        tk.Frame(self.marco, bg=C["banda_borde"], height=1).pack(fill="x")

    def _volver_principal(self) -> None:
        self.vista = "principal"
        self.redibujar()

    def _grupo(self, padre, titulo) -> None:
        self.kicker(padre, titulo, bg=C["superficie"]).pack(anchor="w", padx=self.e.px(16), pady=(self.e.px(12), self.e.px(4)))

    def _fila(self, padre, icono, titulo, nota="", color_icono=None, color_nota=None):
        e = self.e
        f = tk.Frame(padre, bg=C["superficie"])
        f.pack(fill="x", padx=e.px(16), pady=e.px(3))
        s = e.px(26)
        cv = tk.Canvas(f, width=s, height=s, bg=C["fondo"], highlightthickness=1, highlightbackground=C["borde"])
        dibujar_icono(cv, icono, s / 2, s / 2, e.px(15), color_icono or C["suave"])
        cv.pack(side="left", padx=(0, e.px(11)))
        textos = tk.Frame(f, bg=C["superficie"])
        textos.pack(side="left", fill="x", expand=True)
        self.L(textos, titulo, 12.5, C["texto"], "bold").pack(anchor="w")
        if nota:
            self.L(textos, nota, 10.5, color_nota or C["tenue"]).pack(anchor="w")
        return f

    def _vista_menu(self) -> None:
        e = self.e
        self._banda_menu()
        cuerpo = tk.Frame(self.marco, bg=C["superficie"])
        cuerpo.pack(fill="both")
        rojo = self.tonos()["red"]

        self._grupo(cuerpo, T("Conexión"))
        caducada = self.tipo_error == "clave"
        nota = T("Sin configurar") if not self.api else (T("Caducada") if caducada else T("Válida · cifrada con DPAPI"))
        f = self._fila(cuerpo, "clave", "SessionKey", nota, rojo if caducada else C["acento_medio"], rojo if caducada else None)
        self.boton_pequeno(f, T("Cerrar") if self.ver_clave else T("Renovar"), self._alternar_clave).pack(side="right")
        if self.ver_clave:
            caja_b = tk.Frame(cuerpo, bg=C["borde"])
            caja_b.pack(fill="x", padx=e.px(16), pady=(e.px(2), e.px(6)))
            caja = tk.Frame(caja_b, bg=C["fondo"])
            caja.pack(fill="x", padx=1, pady=1)
            dentro = tk.Frame(caja, bg=C["fondo"])
            dentro.pack(fill="x", padx=e.px(9), pady=e.px(9))
            self._campo_clave(dentro, T("Validar"))
            enlaces = tk.Frame(dentro, bg=C["fondo"])
            enlaces.pack(fill="x", pady=(e.px(8), 0))
            ayuda = self.L(enlaces, T("¿Cómo consigo la SessionKey?"), 11, C["acento_claro"], "bold", cursor="hand2")
            ayuda.pack(side="left")
            ayuda.bind("<Button-1>", lambda _e: self._ir_ayuda())
            ayuda.bind("<Enter>", lambda _e: ayuda.configure(bg=C["banda"]))
            ayuda.bind("<Leave>", lambda _e: ayuda.configure(bg=C["fondo"]))
            borrar = self.L(enlaces, T("Borrar campo"), 11, C["suave"], "bold", cursor="hand2")
            borrar.pack(side="right")
            borrar.bind("<Button-1>", lambda _e: (self.clave_borrador.set(""), self._limpiar_error_clave()))
            borrar.bind("<Enter>", lambda _e: borrar.configure(bg=C["pista"], fg=C["texto"]))
            borrar.bind("<Leave>", lambda _e: borrar.configure(bg=C["fondo"], fg=C["suave"]))

        self._grupo(cuerpo, T("Avisos"))
        f = self._fila(cuerpo, "campana", T("Umbrales y color del icono"), color_icono=C["acento_medio"])
        self.boton_pequeno(f, T("Cerrar") if self.ver_umbrales else T("Editar"), self._alternar_umbrales).pack(side="right")
        if self.ver_umbrales:
            self._tabla_umbrales(cuerpo)

        self._grupo(cuerpo, T("Notificaciones"))
        for icono, titulo, attr in (("campana", T("Umbrales de la sesión (5 h)"), "notif_5h"),
                                    ("campana", T("Umbrales semanales"), "notif_semana"),
                                    ("reinicio", T("Avisar cuando se reinicie"), "aviso_reinicio"),
                                    ("sonido", T("Sonido"), "sonido")):
            f = self._fila(cuerpo, icono, titulo)
            self.interruptor(f, getattr(self.cfg, attr), lambda a=attr: self._alternar_pref(a)).pack(side="right")

        self._grupo(cuerpo, T("Preferencias"))
        f = self._fila(cuerpo, "encendido", T("Iniciar con Windows"))
        self.interruptor(f, autostart_activo(), self._alternar_autostart).pack(side="right")
        f = self._fila(cuerpo, "ojo", T("Paleta accesible"))
        self.interruptor(f, self.cfg.accesible, lambda: self._alternar_pref("accesible")).pack(side="right")
        f = self._fila(cuerpo, "reloj", T("Refresco"))
        self.segmentado(f, [(v, f"{v} s" if v < 60 else f"{v // 60} min") for v in REFRESCOS],
                        self.cfg.refresco, self._cambiar_refresco).pack(side="right")
        # Cada idioma con su propio nombre, para encontrarlo aunque el panel esté en el otro.
        f = self._fila(cuerpo, "idioma", T("Idioma"))
        self.segmentado(f, [("auto", "Auto"), ("es", "Español"), ("en", "English")],
                        self.cfg.idioma, self._cambiar_idioma).pack(side="right")

        tk.Frame(cuerpo, bg=C["linea"], height=1).pack(fill="x", padx=e.px(16), pady=(e.px(10), 0))
        pie = tk.Frame(cuerpo, bg=C["superficie"])
        pie.pack(fill="x", padx=e.px(16), pady=(e.px(9), e.px(12)))
        self.boton(pie, T("Volver"), self._volver_principal, icono="volver", lleno=True).pack(fill="x")

    def _tabla_umbrales(self, cuerpo) -> None:
        e = self.e
        tonos = self.tonos()
        caja_b = tk.Frame(cuerpo, bg=C["borde"])
        caja_b.pack(fill="x", padx=e.px(16), pady=(e.px(2), e.px(6)))
        caja = tk.Frame(caja_b, bg=C["fondo"])
        caja.pack(fill="x", padx=1, pady=1)
        tramos = sorted(self.cfg.umbrales)
        opciones_spin = dict(from_=1, to=99, width=3, font=e.f(11.5, "bold"), bg=C["hundido"], fg=C["texto"],
                             buttonbackground=C["pista"], insertbackground=C["texto"], relief="flat", justify="right",
                             highlightthickness=1, highlightbackground=C["borde"], highlightcolor=C["acento"])
        for v, c in tramos:
            f = tk.Frame(caja, bg=C["fondo"])
            f.pack(fill="x", padx=e.px(8), pady=e.px(4))
            self.L(f, T("Desde"), 11.5, C["tenue"], width=6).pack(side="left")
            if v == 0:
                self.L(f, "0", 11.5, C["tenue"], "bold", width=4, anchor="e").pack(side="left")
            else:
                var = tk.StringVar(master=self.root, value=str(v))
                sp = tk.Spinbox(f, textvariable=var, **opciones_spin)
                sp.pack(side="left")
                confirmar = lambda _e=None, viejo=v, var=var: self._cambiar_valor_umbral(viejo, var.get())  # noqa: E731
                sp.bind("<Return>", confirmar)
                sp.bind("<FocusOut>", confirmar)
                sp.configure(command=confirmar)
            self.L(f, "%", 11.5, C["tenue"]).pack(side="left", padx=(e.px(4), 0))
            if v != 0:
                q = e.px(20)
                cv = tk.Canvas(f, width=q, height=q, bg=C["fondo"], highlightthickness=0, cursor="hand2")
                dibujar_icono(cv, "cerrar", q / 2, q / 2, e.px(12), C["tenue"])
                cv.pack(side="right")
                cv.bind("<Button-1>", lambda _e, vv=v: self._quitar_umbral(vv))
                cv.bind("<Enter>", lambda _e, w=cv: pintar_fondo(w, C["borde"]))
                cv.bind("<Leave>", lambda _e, w=cv: pintar_fondo(w, C["fondo"]))
            else:
                tk.Frame(f, bg=C["fondo"], width=e.px(20), height=1).pack(side="right")
            muestras = tk.Frame(f, bg=C["fondo"])
            muestras.pack(side="right", padx=e.px(6))
            for color in ORDEN_COLORES:
                self._muestra(muestras, tonos[color], color == c,
                              lambda col=color, vv=v: self._color_umbral(vv, col)).pack(side="left", padx=e.px(2))
        if len(tramos) < MAX_TRAMOS:
            tk.Frame(caja, bg=C["linea"], height=1).pack(fill="x")
            f = tk.Frame(caja, bg=C["fondo_pie"])
            f.pack(fill="x")
            dentro = tk.Frame(f, bg=C["fondo_pie"])
            dentro.pack(fill="x", padx=e.px(8), pady=e.px(7))
            sp = tk.Spinbox(dentro, textvariable=self.form_umbral, **opciones_spin)
            sp.pack(side="left")
            sp.bind("<Return>", lambda _e: self._anadir_umbral())
            self.L(dentro, "%", 11.5, C["tenue"]).pack(side="left", padx=(e.px(4), e.px(8)))
            usados = {c for _v, c in tramos}
            libres = [c for c in ORDEN_COLORES if c not in usados]
            if self.form_color not in libres:
                self.form_color = libres[0] if libres else None
            for color in libres:
                self._muestra(dentro, tonos[color], color == self.form_color,
                              lambda col=color: self._elegir_color_form(col)).pack(side="left", padx=e.px(2))
            s = e.px(24)
            mas = tk.Canvas(dentro, width=s, height=s, bg=C["fondo_pie"], highlightthickness=1,
                            highlightbackground=C["acento"], cursor="hand2")
            dibujar_icono(mas, "mas", s / 2, s / 2, e.px(13), C["acento_claro"])
            mas.pack(side="right")
            mas.bind("<Button-1>", lambda _e: self._anadir_umbral())
            mas.bind("<Enter>", lambda _e: pintar_fondo(mas, C["banda"]))
            mas.bind("<Leave>", lambda _e: pintar_fondo(mas, C["fondo_pie"]))

    def _muestra(self, padre, color, elegido, accion):
        s = self.e.px(19)
        cv = tk.Canvas(padre, width=s, height=s, bg=padre["bg"], highlightthickness=0, cursor="hand2")
        m = self.e.px(2)

        def pintar(sobre=False):
            cv.delete("all")
            d = 0 if sobre else m
            cv.create_rectangle(d + 1, d + 1, s - d - 1, s - d - 1, fill=color,
                                outline=C["texto"] if elegido else color, width=self.e.px(1.5) if elegido else 1)

        pintar()
        cv.bind("<Enter>", lambda _e: pintar(True))
        cv.bind("<Leave>", lambda _e: pintar(False))
        cv.bind("<Button-1>", lambda _e: accion())
        return cv

    def _guardar_umbrales(self, tramos) -> None:
        self.cfg.umbrales = normalizar_umbrales(tramos)
        self.cfg.guardar()
        self._pintar_icono()
        self.redibujar()

    def _cambiar_valor_umbral(self, viejo: int, texto: str) -> None:
        try:
            nuevo = int(texto)
        except ValueError:
            return
        if nuevo == viejo or not 1 <= nuevo <= 99 or any(v == nuevo for v, _c in self.cfg.umbrales):
            return
        self._guardar_umbrales([[nuevo if v == viejo else v, c] for v, c in self.cfg.umbrales])

    def _color_umbral(self, valor: int, color: str) -> None:
        # Cada color se usa una vez: elegir uno ocupado intercambia los dos tramos.
        actual = next(c for v, c in self.cfg.umbrales if v == valor)
        self._guardar_umbrales([[v, color if v == valor else (actual if c == color else c)] for v, c in self.cfg.umbrales])

    def _quitar_umbral(self, valor: int) -> None:
        self._guardar_umbrales([u for u in self.cfg.umbrales if u[0] != valor])

    def _elegir_color_form(self, color) -> None:
        self.form_color = color
        self.redibujar()

    def _anadir_umbral(self) -> None:
        try:
            v = int(self.form_umbral.get())
        except ValueError:
            return
        if not 1 <= v <= 99 or any(u[0] == v for u in self.cfg.umbrales) or not self.form_color:
            return
        self.form_umbral.set("")
        self._guardar_umbrales(self.cfg.umbrales + [[v, self.form_color]])

    def _alternar_clave(self) -> None:
        self.ver_clave = not self.ver_clave
        self.error_clave = ""
        self.redibujar()

    def _alternar_umbrales(self) -> None:
        self.ver_umbrales = not self.ver_umbrales
        self.redibujar()

    def _alternar_pref(self, attr: str) -> None:
        setattr(self.cfg, attr, not getattr(self.cfg, attr))
        self.cfg.guardar()
        if attr == "accesible":
            self._pintar_icono()
        self.redibujar()

    def _alternar_autostart(self) -> None:
        autostart_poner(not autostart_activo())
        self.redibujar()

    def _cambiar_refresco(self, v) -> None:
        self.cfg.refresco = v
        self.cfg.guardar()
        self.redibujar()

    def _cambiar_idioma(self, v) -> None:
        self.cfg.idioma = v
        self.cfg.guardar()
        poner_idioma(v)
        for l in self.limites:
            l["nombre"] = nombre_limite(l["clave"])
        self._pintar_icono()
        self.redibujar()

    def _ir_ayuda(self) -> None:
        self.vista = "ayuda"
        self.redibujar()

    def _volver_menu(self) -> None:
        self.vista = "menu"
        self.redibujar()

    def _vista_ayuda(self) -> None:
        e = self.e
        self._banda_menu()
        cuerpo = tk.Frame(self.marco, bg=C["superficie"])
        cuerpo.pack(fill="both")
        dentro = tk.Frame(cuerpo, bg=C["superficie"])
        dentro.pack(fill="x", padx=e.px(16), pady=(e.px(14), e.px(4)))
        self.L(dentro, T("Cómo conseguir la SessionKey"), 15, C["texto"], "bold").pack(anchor="w", pady=(0, e.px(12)))
        self._lista_pasos(dentro, 11.5)
        pie = tk.Frame(cuerpo, bg=C["superficie"])
        pie.pack(fill="x", padx=e.px(16), pady=(e.px(4), e.px(14)))
        self.boton(pie, T("Volver"), self._volver_menu, icono="volver", lleno=True).pack(fill="x")

    # ------------------------------------------------------------------ #
    # Tarjeta al pasar el ratón por el icono
    # ------------------------------------------------------------------ #
    def mostrar_tarjeta(self, x=None) -> None:
        if self.panel_visible():
            return
        e = self.e
        for hijo in self.tarjeta.winfo_children():
            hijo.destroy()
        marco = tk.Frame(self.tarjeta, bg=C["superficie"])
        marco.pack(padx=1, pady=1)
        vivo = self.vivo()
        p = self.principal_limite()
        cab = tk.Frame(marco, bg=C["superficie"])
        cab.pack(fill="x", padx=e.px(11), pady=(e.px(9), e.px(8)))
        color_logo = AZUL if not self.api or not self.limites else (self.color(p["pct"]) if vivo else GRIS)
        self._foto_tarjeta = foto_logo(self.root, e.px(16), color_logo, C["superficie"])
        tk.Label(cab, image=self._foto_tarjeta, bg=C["superficie"]).pack(side="left", padx=(0, e.px(8)))
        self.L(cab, "CLAUDE USAGE", 11, C["texto"], "bold").pack(side="left")
        self.L(cab, hora(self.ultimo_ok) if self.ultimo_ok else "", 10.5, C["tenue"]).pack(side="right", padx=(e.px(16), 0))
        if self.limites:
            filas = tk.Frame(marco, bg=C["superficie"])
            filas.pack(fill="x", padx=e.px(12), pady=(0, e.px(10)))
            claro = C["texto"] if vivo else C["tenue"]
            py = e.px(3)
            for i, l in enumerate(self.limites):
                self.L(filas, l["nombre"], 11.5, claro, "bold").grid(row=i, column=0, sticky="w", pady=py)
                self.barra(filas, l["pct"], self.color(l["pct"]) if vivo else GRIS, e.px(110)).grid(
                    row=i, column=1, padx=(e.px(12), e.px(12)), pady=py)
                self.L(filas, pct_txt(l["pct"]), 11.5, claro, "bold", anchor="e").grid(row=i, column=2, sticky="e", pady=py)
                self.L(filas, cuando_reinicia(l["reinicio"], corto=True), 10.5, C["tenue"], anchor="e").grid(
                    row=i, column=3, sticky="e", padx=(e.px(14), 0), pady=py)
        pie = tk.Frame(marco, bg=C["fondo"])
        pie.pack(fill="x")
        tk.Frame(pie, bg=C["linea"], height=1).pack(fill="x")
        dentro = tk.Frame(pie, bg=C["fondo"])
        dentro.pack(fill="x", padx=e.px(11), pady=(e.px(7), e.px(8)))
        if not self.api:
            texto, punto = T("Clic para conectar tu cuenta"), C["acento"]
        elif self.tipo_error == "clave":
            texto, punto = T("Sesión caducada · clic para renovar"), self.tonos()["red"]
        elif self.tipo_error == "red":
            texto, punto = T("Sin conexión · reintentando"), self.tonos()["red"]
        elif not self.limites:
            texto, punto = T("Cargando…"), AZUL
        else:
            pr = proyectar(p["pct"], self._ritmo(), p["reinicio"])
            if pr["eta_100"]:
                texto, punto = T("A este ritmo, 100 % a las {hora}", hora=hora(pr["eta_100"])), self.color(p["pct"])
            elif pr["sobra"] is not None:
                texto, punto = T("A este ritmo, {n} % sin usar al reinicio", n=pr["sobra"]), self.color_base()
            else:
                texto, punto = T("Consumo estable · reinicia a las {hora}", hora=hora(p["reinicio"])), self.color_base()
        s = e.px(7)
        cv = tk.Canvas(dentro, width=s, height=s, bg=C["fondo"], highlightthickness=0)
        cv.create_oval(0, 0, s, s, fill=punto, outline=punto)
        cv.pack(side="left", padx=(0, e.px(7)))
        self.L(dentro, texto, 11, C["texto_2"]).pack(side="left")
        self._colocar(self.tarjeta, ancla_x=x)
        self.tarjeta.deiconify()
        self.tarjeta.lift()
        redondear_esquinas(self.tarjeta)

    def ocultar_tarjeta(self) -> None:
        try:
            self.tarjeta.withdraw()
        except tk.TclError:
            pass

    # ------------------------------------------------------------------ #
    # Varios
    # ------------------------------------------------------------------ #
    def _acerca(self) -> None:
        # Vista del propio panel. Un MessageBox nativo abierto desde el menú de la bandeja
        # cerraba el programa al aceptarlo.
        self.vista = "acerca"
        self.mostrar_panel(conservar_vista=True)

    def _vista_acerca(self) -> None:
        e = self.e
        self._banda_menu()
        cuerpo = tk.Frame(self.marco, bg=C["superficie"])
        cuerpo.pack(fill="both")
        d = tk.Frame(cuerpo, bg=C["superficie"])
        d.pack(fill="x", padx=e.px(16), pady=(e.px(14), e.px(4)))
        self.L(d, f"Claude Usage {VERSION}", 15, C["texto"], "bold").pack(anchor="w")
        self.L(d, T("Uso de los límites de Claude en la bandeja de Windows."), 12, C["texto_2"],
               wraplength=e.px(300)).pack(anchor="w", pady=(e.px(4), e.px(10)))
        self.L(d, T("Usa la interfaz interna de claude.ai: puede dejar de funcionar si Claude la cambia. "
                    "Claude es una marca de Anthropic; esta herramienta no es oficial."), 11, C["tenue"],
               wraplength=e.px(300)).pack(anchor="w")
        self.kicker(d, T("Datos"), bg=C["superficie"]).pack(anchor="w", pady=(e.px(12), e.px(4)))
        self.L(d, f" {carpeta_config()} ", 10.5, C["acento_medio"], bg=C["hundido"], mono=True,
               wraplength=e.px(300)).pack(anchor="w")
        pie = tk.Frame(cuerpo, bg=C["superficie"])
        pie.pack(fill="x", padx=e.px(16), pady=(e.px(14), e.px(14)))
        self.boton(pie, T("Volver"), self._volver_principal, icono="volver", lleno=True).pack(fill="x")

    def salir(self) -> None:
        self._vivo = False
        self._despertar.set()
        if self.bandeja:
            self.bandeja.cerrar()
        registrar("salida a petición del usuario")
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def ejecutar(self) -> None:
        self.root.mainloop()


def main() -> None:
    silencioso = "--silent" in sys.argv
    if not es_unica_instancia():
        return
    registrar(f"arranque {VERSION} ({'silencioso' if silencioso else 'con panel'})")
    App(silencioso).ejecutar()


if __name__ == "__main__":
    main()
