# Claude Usage

Uso de los límites de Claude en el área de notificación de Windows: sesión de
5 h, semana y límites por modelo (Opus, Sonnet…), con proyección, historial y
avisos al cruzar cada umbral. En español e inglés.

Un solo archivo Python, sin dependencias: tkinter para el panel y ctypes
contra la API de Windows para el icono de bandeja, los avisos y el cifrado de
la clave.

## Descarga

`ClaudeUsage.exe` está en [Releases](../../releases/latest). No hace falta
instalar Python: se ejecuta, se pega la SessionKey de claude.ai y queda en la
bandeja.

## Qué hace

- **Icono de bandeja** teñido con el color del tramo de uso. Azul mientras no
  hay cuenta o carga; gris sin conexión o con la clave caducada.
- **Al pasar el ratón**: tarjeta con todos los límites, sus barras y la
  proyección.
- **Clic izquierdo**: abre y cierra el panel. Se cierra también con Esc o con
  la X; el programa sigue en la bandeja.
- **Clic derecho**: menú nativo — Abrir panel, Actualizar ahora, Iniciar con
  Windows, Acerca de, Salir.
- **Panel**: sesión de 5 h con ritmo ideal, límites semanales, proyección.
  Botón de gráfico: evolución de la sesión y consumo por minutos (1, 5 o
  10 min) coloreado frente al ritmo ideal, y el historial: el gráfico debajo
  de los semanales y la lista de sesiones debajo del consumo por minutos.
- **Historial** de 24 h a 2 años: sesiones o uso semanal, con cursor y las
  cuatro últimas sesiones o semanas. Exportación a CSV.
- **Avisos** de Windows al cruzar cada umbral, una sola vez por sesión (se
  recuerda aunque se reinicie el programa). Sesión y semana se activan por
  separado; también el aviso de reinicio y el sonido.
- **Umbrales** configurables: hasta 4 tramos, uno por color. Por defecto
  verde desde 0 %, amarillo 50 %, naranja 70 %, rojo 85 %.
- **Paleta accesible** para daltonismo, aplicada a toda la aplicación.
- **Idiomas**: español e inglés. Por defecto sigue el idioma de Windows
  (español también con Windows en catalán, gallego o euskera; inglés en el
  resto); se cambia en Menú › Preferencias › Idioma.

## Uso

Requiere Python 3.10+ con tcl/tk.

```
pythonw ClaudeUsage.pyw            abre el panel
pythonw ClaudeUsage.pyw --silent   solo bandeja
```

`EJECUTAR.bat` hace lo mismo y avisa si falta Python.

## Reparto al equipo

`CONSTRUIR_EXE.bat` genera `dist\ClaudeUsage.exe`. El logo va dentro del
ejecutable. Cada persona lo ejecuta en su equipo y pega **su propia**
SessionKey: nunca se comparte ni se deja en una carpeta común.

## Datos

En `%LOCALAPPDATA%\ClaudeUsage`, por usuario:

| Archivo | Contenido |
| --- | --- |
| `config.json` | Preferencias, avisos enviados y la SessionKey cifrada con DPAPI. |
| `historial.db` | Lecturas de los últimos 730 días (SQLite). |
| `diagnostico.log` | Cambios de estado, sin datos sensibles. |

## Documentación

- `docs/LEEME.txt` — manual completo, técnico.
- `docs/LEEME-EQUIPO.txt` — guía breve para quien solo lo usa.
- `diseno/panel-visual.dc.html` — maqueta del diseño.

Claude y sus marcas pertenecen a Anthropic. Herramienta no oficial: usa la
interfaz interna de claude.ai y puede dejar de funcionar si Claude la cambia.
