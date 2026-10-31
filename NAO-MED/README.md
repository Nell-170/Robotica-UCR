# NAO-MED

Robot NAO que recuerda tomar la medicina. Cuando el cronograma indica un
medicamento, el robot suena una alarma, identifica los cubos de medicina,
busca a la persona, la guía hasta los cubos y le **señala** el que le toca.

Proyecto del curso CI-0160 Robótica (UCR). Público meta: personas adultas
mayores y cuidadores. Rama `Alternative-pipeline`: **el robot no agarra el
cubo**, solo lo señala (el agarre del pipeline anterior no está implementado
en esta rama).

## Estado del proyecto

- Funciona en el **simulador (Webots)** y en el **robot físico (NAO V6)**,
  pero con diferencias importantes entre ambos (ver "Limitaciones").
- Las pruebas fueron exploratorias y manuales; **no hay pruebas automatizadas**.

## Pipeline (sin agarrar el cubo)

La secuencia es determinista y la dispara `src/main.py`:

1. Alarma sonora y luces.
2. Barrido de la cabeza e **identificación de los cubos** (izquierda,
   centro o derecha, según el orden en que aparecen).
3. Dice en voz alta qué cubos vio, por ejemplo: "Veo el cubo paracetamol,
   el cubo clonacepam y el cubo ibuprofeno".
4. Gira para buscar a una persona. Si **no ve un rostro**, dice que no ve
   a nadie y no camina. Si lo ve, camina 1 m hacia ella y le dice qué
   medicamento toca.
5. Gira para volver hacia los cubos y camina de regreso.
6. Se alinea con el cubo del medicamento (paso lateral si está a la
   izquierda o a la derecha; el del centro no se mueve).
7. Levanta el brazo, señala el cubo y dice "Es este, el del centro /
   de la izquierda / de la derecha". Apaga las luces.

Si un giro no se puede verificar, el robot cancela el paso siguiente en vez
de seguir a ciegas (búsqueda de rostro o regreso).

En el NAO real, el barrido de la cabeza y las capturas se repiten dos
veces para aumentar la oportunidad de ver los tres cubos. Por eso la
identificación tarda un poco más; usa la cámara inferior, adecuada para
los cubos cercanos.

## Arquitectura

```
src/main.py  (punto de entrada)
 ├─ robot_connector.py       detecta el NAO real (192.168.1.140:9559) o abre Webots
 ├─ schedule.py              lee data/cronograma.csv
 ├─ medication_scheduler.py  compara día/hora del sistema con el cronograma
 └─ nao_controller.py        notificar_medicamento(): secuencia completa
     ├─ robot real:  ALProxy (NAOqi) + reconocimiento.py + deteccion_cubo.py
     └─ simulador:   socket TCP 127.0.0.1:9000  ->  controlador de Webots
                      webots/controllers/nao_med_controller/nao_med_controller.py
```

| Módulo | Función |
|--------|---------|
| `src/main.py` | Conecta con el robot, carga el cronograma y monitorea la hora. |
| `src/robot_connector.py` | Revisa por socket si el NAO real responde; si no, lanza Webots con `nao_med.wbt`. |
| `src/schedule.py` | Carga el CSV (columnas `medicamento,dia,hora`). |
| `src/medication_scheduler.py` | Detecta el medicamento pendiente y llama a la notificación. |
| `src/nao_controller.py` | Secuencia del robot real; en el simulador solo envía el comando. |
| `src/deteccion_cubo.py` | Identificación de cubos por HSV con OpenCV (cámara del NAO real). |
| `src/reconocimiento.py` | Detección de presencia de rostro con `ALFaceDetection` (NAO real). |
| `src/naoqi_mock.py` | Mock de NAOqi para probar la lógica sin SDK; **no mueve el robot**. |
| `src/prueba.py` | Prueba de conexión al NAO o al simulador. |
| `webots/controllers/nao_med_controller/` | Controlador del simulador: recibe `NOTIFICAR:<medicamento>` por socket y ejecuta la secuencia con movimientos `.motion`. |
| `webots/motions/` | Movimientos usados por el simulador (caminar, giros, pasos laterales, levantarse). |
| `webots/worlds/nao_med.wbt` | Mundo del simulador (NAO H25 V5.0, mesa, cubos, imagen de rostro). |

Simulador y robot real **no comparten implementación** de las acciones:
la caminata, los giros, el paso lateral y la detección de rostro
(clasificador Haar de OpenCV en Webots, `ALFaceDetection` en el NAO real)
se programaron por separado.

### Los cubos y su medicamento

| Cubo | Medicamento | Como lo ve la camara |
|------|-------------|----------------------|
| Blanco con logo negro | paracetamol | semilla oscura pequena (el logo) rodeada de claro |
| Negro con logo claro | ibuprofeno | mancha oscura grande cuyo entorno es mayormente oscuro |
| Cubo de rubik (6 cm) | clonacepam | stickers azul muy saturado |

La identificacion es por la estructura del cubo, no por el color del
fondo: la semilla es el cubo mismo (su logo, su cuerpo o sus stickers).
Funciona sobre piso blanco, que era un requisito del laboratorio.

## Instalación de dependencias

Se usan **dos entornos separados**. Los comandos siguientes se ejecutan desde
`NAO-MED/`, en una terminal de Windows. No instalar ambos archivos de
requirements en el mismo entorno ni actualizar el entorno del laboratorio
sin conservar primero su configuración.

| Entorno | Python comprobado localmente | Archivo | Versiones fijadas |
|---------|------------------------------|---------|-------------------|
| Robot físico (computadora de control) | 2.7.18, 64 bits | `requirements-robot.txt` | NumPy 1.16.6, OpenCV 4.2.0.32 |
| Controlador de Webots | 3.13.2 | `requirements-webots.txt` | NumPy 2.2.4, OpenCV 4.11.0.86 |

Estas versiones se obtuvieron del entorno instalado y se comprobaron sus
imports. No equivalen a una validación física ni a una prueba de instalación
desde cero. Para otras versiones de Python o plataformas hay que comprobar
la disponibilidad de paquetes binarios y la compatibilidad.

### Robot físico: Python 2.7

```bat
py -2.7 -m pip install -r requirements-robot.txt
py -2.7 -c "import numpy, cv2; from naoqi import ALProxy; print(numpy.__version__, cv2.__version__)"
```

El SDK oficial de NAOqi **no se instala con pip**. Obtenerlo del laboratorio
o del proveedor y configurar su ruta en `PYTHONPATH` para ese intérprete.
Debe ser compatible con la versión de NAOqi del robot, Python 2.7 y la
arquitectura del sistema. El archivo anterior mencionaba NAOqi 2.8.7.4;
confirmar la versión efectiva del robot antes de elegir el SDK.

Python 2.7 está fuera de soporte: mantener este entorno legado separado.
No actualizar pip indiscriminadamente: pip 20.3.4 es la última versión
compatible con Python 2.7. Si el SDK no se puede importar, el programa puede
usar `naoqi_mock.py`; ese mock sirve para pruebas de lógica, **no controla el
robot ni sustituye a Webots**. La comprobación anterior importa el SDK real
sin enviar comandos al robot.

### Simulador: Python 3 y Webots

Instalar Webots R2025a por separado. Para preparar un entorno Python aislado:

```bat
py -3.13 -m venv .venv-webots
.venv-webots\Scripts\python.exe -m pip install -r requirements-webots.txt
.venv-webots\Scripts\python.exe -c "import numpy, cv2; print(numpy.__version__, cv2.__version__)"
```

Configurar en Webots la ruta absoluta de
`.venv-webots\Scripts\python.exe` como comando de Python del controlador.
Instalar paquetes en otro intérprete no los hace disponibles automáticamente
en Webots. El módulo `controller` (con `Motion` y `Supervisor`) lo proporciona
Webots; **no instalar un paquete homónimo con pip**. No se necesita el SDK
NAOqi para mover el robot simulado: el proceso externo envía comandos por
socket y el controlador dentro de Webots los ejecuta.

`requirements.txt` incluye `requirements-webots.txt`: es el acceso
predeterminado para simulación, no un archivo común a ambos entornos.

**Instalación existente:** `runtime.ini` añade `webots/libs` al `PYTHONPATH`
del controlador. Esa carpeta contiene una copia local de OpenCV; se comprobó
la versión 4.11.0.86, coincidente con el nuevo archivo. Puede tener prioridad
sobre lo instalado en el entorno virtual. Para diagnosticar qué copia carga
un intérprete, consultar `cv2.__file__` y `cv2.__version__` con esa misma
configuración. No borrar la carpeta ni mezclar binarios de distintas versiones
de Python sin verificar su compatibilidad.

`run.bat setup` conserva el mecanismo anterior: instala solo OpenCV en
`webots/libs` usando el comando `python` y no instala NumPy. Para entornos
nuevos, usar los comandos de requirements anteriores. Los comandos
`run.bat start`, `test` y `schedule` usan Python 2.7 para el proceso externo;
el controlador de Webots sigue ejecutándose con su Python 3 independiente.

## Cómo correr

Todos los comandos se ejecutan desde `NAO-MED/`. `run.bat` busca Python 2.7
(variable `NAOMED_PYTHON27`, `C:\Python27-NAOMed`, `C:\Python27` o
`%LOCALAPPDATA%\Programs\Python\Python27`).

| Comando | Qué hace |
|---------|----------|
| `run.bat start` | Monitor completo: detecta el NAO real o abre Webots y espera la hora del cronograma. |
| `run.bat test` | Dispara una notificación de inmediato (medicamento `Paracetamol`), sin esperar el cronograma. |
| `run.bat schedule` | Muestra el cronograma cargado. |
| `run.bat setup` | Instala OpenCV en `webots/libs` (solo simulador). |

Equivalente sin `run.bat`: `py -2.7 src/main.py`.

**Robot real:** conectar la computadora a la misma red del NAO (IP y puerto
en `src/robot_connector.py`), colocar los cubos (ver abajo) y correr
`run.bat test`.

**Simulador:** abrir `webots/worlds/nao_med.wbt` en Webots R2025a y,
con el mundo cargado, correr `run.bat test`. Si Webots no está abierto,
`robot_connector.py` intenta lanzarlo. El controlador solo se recarga al
reiniciar o reabrir el mundo.

Con diagnóstico (impresión de medidas por candidato y fotogramas anotados
en `data/debug/`), activar la bandera de diagnóstico que se pasa hasta
`identificar_cubos`.

### Cronograma

`data/cronograma.csv` se puede editar con Excel o similar:

```
medicamento,dia,hora
Paracetamol,Domingo,17:50
```

Los nombres de medicamento deben coincidir con los de los cubos
(paracetamol, ibuprofeno, clonacepam, sin importar mayúsculas). El día y la
hora se comparan con el reloj del sistema, que debe estar en hora.

### Parámetros que se ajustan en el código

| Parámetro | Dónde | Valor actual |
|-----------|-------|--------------|
| Distancia de caminata hacia la persona | `nao_controller.py`: `DISTANCIA_CAMINATA_METROS` | 1.0 m |
| Paso lateral (robot real) | `nao_controller.py`: `DISTANCIA_PASO_LATERAL_METROS` | 0.10 m |
| Paso lateral (Webots) | movimientos `SideStepLeft/Right.motion` | 0.25 m aprox. |
| Ajuste del rumbo de regreso (robot real) | `nao_controller.py`: `AJUSTE_RUMBO_REGRESO_RADIANES` | 45° (calibrado a mano) |
| Tolerancia e intentos de corrección de giro | `nao_controller.py` | 3° y 3 intentos |
| Color de las luces | `nao_controller.py`: `COLOR_LUCES_NOTIFICACION` | `0x00A2FF` |
| Puerto del controlador de Webots | `nao_med_controller.py`: `PUERTO_ESCUCHA` | 9000 |

Estos valores son empíricos: se obtuvieron probando, no se validaron
formalmente.

## Colocacion de los cubos

Para probar con el **NAO real**, coloca los cubos sobre una caja y situalos
a unos **40 cm del robot**. Esta colocacion es para el robot fisico; no
cambia la configuracion del simulador descrita abajo.

En el **simulador**, los cubos van en el piso, en una fila frente al
robot, vistos por la camara inferior (la del pecho, inclinada ~40 grados
hacia abajo).

| Parametro | Valor recomendado |
|-----------|-------------------|
| Distancia del robot a la fila | 0.6 a 0.8 m |
| Separacion entre cubos | 20 a 25 cm |

Razones, medidas con la camara del simulador (QVGA, 320x240):

- A 0.6 m un cubo de 5 cm proyecta ~25 pixeles y la imagen cubre
  ~0.66 m de ancho: los tres cubos entran juntos en el mismo frame.
- A menos de ~0.3 m el cubo se sale del encuadre cuando la cabeza
  mira abajo (HeadPitch 0.5).
- Con esa separacion las manchas de los cubos no se tocan entre si y
  cada uno queda bien identificado.

El cubo de rubik mira al robot con su cara azul: el clasificador
reconoce los stickers azules. Girarlo no rompe la deteccion del
ibuprofeno ni del paracetamol, pero si deja de ver azul, no se
identifica el clonacepam.

## Diagnostico y calibracion de umbrales

La camara real del NAO y la del simulador desvian los colores (la
escena se ve azulada: madera con H~108 y S~98). Los umbrales del
clasificador se midieron sobre fotogramas de Webots y hay que
recalibrarlos en cada lugar nuevo:

1. Activar el modo diagnostico (ver "Como correr").
2. Correr una notificacion con los cubos ya colocados.
3. Leer las lineas `[CUBO-DEBUG]` de la consola: area, tamano de caja
   y fracciones de claro/oscuro/azul por candidato.
4. Mirar los fotogramas anotados en `data/debug/` (no se confirman en
   git).
5. Ajustar los umbrales de las mascaras (`clara`, `oscura`, `azul`) en
   `src/deteccion_cubo.py` (NAO real) o
   `webots/controllers/nao_med_controller/nao_med_controller.py`
   (simulador).

Referencia de los umbrales que funcionaron en Webots:
`oscura: V<90`, `clara: S<80 y V>115`, `azul: H 100-135, S>120, V>60`.

## Limitaciones conocidas

- **Giros en el robot real:** la odometría puede reportar giros que no
  ocurrieron. Por eso se usan giros deterministas con un ajuste de rumbo
  calibrado a mano; en las pruebas funcionó solo en una minoría de los
  intentos (~30 %).
- **Distancias:** con las distancias entre cámara y cubos del simulador,
  el robot físico no logra completar el pipeline; en el laboratorio se
  usan distancias mucho menores (cubos a ~40 cm).
- **Desvío al avanzar:** al seguir el rostro, el robot puede desviarse a
  un lado y arrastrar el error al resto de la secuencia (abierto).
- **Caídas:** el controlador de Webots detecta si el NAO se cayó y se
  levanta; el robot real **no** tiene detección ni recuperación de caídas.
- **Versiones distintas:** el simulador usa un NAO H25 V5.0 y el robot
  físico es un NAO V6.
- **Umbrales HSV** calibrados sobre fotogramas de Webots; hay que
  recalibrarlos en cada lugar nuevo (ver sección anterior).
- No implementado respecto a la propuesta original: agarre del cubo,
  autenticación, base de datos y confirmación por voz.

## Estructura de carpetas

```
src/                 programa principal y módulos del NAO real (Python 2.7)
webots/              mundo, controlador, movimientos y libs del simulador (Python 3)
data/cronograma.csv  horario de medicamentos
data/imagenes/       texturas del mundo (rostro de prueba, caras del cubo de rubik)
data/cubo_referencias/ fotos de referencia de los cubos
data/debug/          fotogramas de diagnóstico (ignorado por git)
run.bat              comandos de ejecución
requirements*.txt    dependencias por entorno
```
