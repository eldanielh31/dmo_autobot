# DMO Autobot

Bot de farmeo para DMO en Windows. Detecta la barra de vida del objetivo en la
ventana del juego y automatiza la seleccion, el ataque y el giro de la camara.

## Requisitos

- Windows 10 u 11.
- Python 3.10 o superior, disponible como `python3` en PATH.
- DMO abierto en una ventana cuyo titulo contenga `Client Version`.

## Instalacion y ejecucion

1. Descarga o clona este repositorio.
2. Abre una terminal en la carpeta del proyecto.
3. Abre DMO y entra al juego.
4. Ejecuta `python3 bot.py`.

Si faltan dependencias, `bot.py` las instala desde `requirements.txt` para el
Python que ejecutó el comando; la primera ejecución requiere conexión a
Internet. También puedes usar `ejecutar_bot.bat` para ejecutarlo dentro de un
entorno virtual.

## Flujo de farmeo

1. Busca un enemigo con **TAB**.
2. Si no encuentra una barra de vida, vuelve a intentar y gira la camara para
   ampliar la busqueda.
3. Cuando detecta el banner y una barra roja con vida, detiene el giro y ataca
   con **1**.
4. Sigue atacando mientras haya rojo en la barra. Si el banner desaparece,
   vuelve a buscar de inmediato. Si el banner permanece pero la barra esta
   vacia, da un golpe final y vuelve a buscar tras una confirmacion breve.

El texto “Seleccionar objetivo” no participa en las decisiones de combate:
solo el banner y la barra roja determinan si se ataca o se busca. La logica de
transiciones esta separada en `combat.py`; vision, controles, configuracion y
anti-macro viven respectivamente en `target_detection.py`, `game_input.py`,
`config.py` y `antimacro.py`.

## Controles

- **Ctrl+Alt+P** o **Ctrl+Shift+P**: pausar o reanudar desde cualquier ventana.
- **Ctrl+Shift+Q**: detener el bot. La terminal permanece abierta.

La ventana `DMO Farm Bot` muestra el estado detectado y la zona que se analiza.
Al pausar, el bot libera el boton derecho del raton si estaba girando la camara.
El bot evita enviar `Esc` durante el combate porque esa tecla puede abrir el
menu. Si el menu se abre manualmente, confirma el panel en tres capturas
consecutivas antes de pausar las entradas, y suelta el boton derecho hasta que
lo cierres manualmente; despues reanuda.
Si detecta el aviso anti-macro, bloquea las entradas del juego, muestra una
sirena local repetida y guarda una captura del momento en `debug/`. La sirena
se detiene cuando el aviso lleva 0.35 segundos sin detectarse; el bot espera
tres segundos antes de reanudar la búsqueda. Resuelve el aviso manualmente.
Si se dispone de una captura de la cabecera, guardala como
`antimacro_header.png` junto a `bot.py` para habilitar la deteccion por
plantilla; sin ella se ubica el dialogo por su barra amarilla y OCR. Al iniciar,
el programa crea `.env` si no existe. Para recibir la captura actual por
Telegram, completa
`TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`; `.env` está excluido de Git. La
captura se guarda localmente y se envía de forma asíncrona.
La detección anti-macro usa la barra amarilla para ubicar el encabezado del
diálogo en cualquier parte de la ventana y lo reconoce con el OCR integrado de
Windows; no depende de una posición fija. Sus bindings se instalan desde
`requirements.txt`, sin necesidad de instalar Tesseract. El OCR depende de que
Windows tenga disponible un idioma compatible en sus paquetes de reconocimiento.
El título de la ventana del juego aparece en los logs y en el banner de alerta.

## Ajustes

Para mover los recuadros de deteccion, edita en `config.py` `TARGET_FRAME_ROI` y
`HP_BAR_ROI`. Ambos usan la forma `(x1, y1, x2, y2)` con valores entre `0.0` y
`1.0`, relativos al area cliente del juego (no a la ventana de vista previa):

- `TARGET_FRAME_ROI`: recuadro exterior del panel superior del objetivo; se usa
  para detectar si hay un objetivo seleccionado.
- `HP_BAR_ROI`: recuadro interior sobre la barra roja; se usa para medir su vida.

Subir `x1` o `x2` mueve los bordes horizontales hacia la derecha; subir `y1` o
`y2` los mueve hacia abajo. Por ejemplo, aumentar ambos valores `y` desplaza el
recuadro hacia abajo. Si cambias la resolucion o la interfaz, ajusta ambos
recuadros mirando las cajas dibujadas en `DMO Farm Bot`. El umbral
`TARGET_FRAME_MIN_BRIGHTNESS` y `MIN_HP_RED_PIXELS` en `config.py` controlan la
deteccion del marco y el rojo de la barra. El rojo disperso se descarta para
evitar que elementos de la escena o artefactos se confundan con vida; la barra
debe tener una distribucion compacta de pixeles rojos. Se considera vacia si
no quedan pixeles rojos fiables.

## Dependencias

Las librerias de terceros estan listadas en `requirements.txt`. Las demas
dependencias usadas por el programa pertenecen a la biblioteca estandar de
Python o a Windows.

---

**Daniel Brenes Gomez**
