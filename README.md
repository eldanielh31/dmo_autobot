# DMO Autobot

Bot de farmeo para DMO en Windows. Detecta la barra de vida del objetivo en la
ventana del juego y automatiza la seleccion, el ataque y el giro de la camara.

## Requisitos

- Windows 10 u 11.
- Python 3.10 o superior, disponible como `python` en PATH.
- DMO abierto en una ventana cuyo titulo contenga `Client Version`.

## Instalacion y ejecucion

1. Descarga o clona este repositorio.
2. Abre DMO y entra al juego.
3. Ejecuta `ejecutar_bot.bat`.

El archivo crea un entorno virtual local `.venv`, instala las dependencias de
`requirements.txt` y ejecuta `bot.py`. La primera ejecucion requiere conexion a
Internet para descargar las librerias.

## Controles

- **Ctrl+Shift+P**: pausar o reanudar desde cualquier ventana.
- **Ctrl+Shift+Q**: detener el bot. La terminal permanece abierta.
- **Q** o **Esc**: detenerlo desde la ventana de vista previa.

La ventana `DMO Farm Bot` muestra el estado detectado y la zona que se analiza.
Al pausar, el bot libera el boton derecho del raton si estaba girando la camara.
Si `Esc` abre el menu del juego, el bot lo detecta, lo cierra y espera a
confirmar que desaparecio antes de volver a mover la camara o pulsar otras teclas.

## Ajustes

Si la resolucion o la interfaz del juego difieren, revisa en `bot.py` los
valores `TARGET_FRAME_ROI`, `HP_BAR_ROI`, `TARGET_FRAME_MIN_BRIGHTNESS` y
`MIN_HP_RED_PIXELS`. Los ROI son coordenadas relativas al area cliente del juego.

## Dependencias

Las librerias de terceros estan listadas en `requirements.txt`. Las demas
dependencias usadas por el programa pertenecen a la biblioteca estandar de
Python o a Windows.

---

**Daniel Brenes Gomez**
