# NAO-MED

NAO que recuerda tomar la medicina: identifica los cubos de medicina,
anuncia lo que ve y avisa a la persona.

## Pipeline alternativo (sin agarrar el cubo)

El robot no agarra nada. La secuencia es determinista:

1. Alarma sonora y luces.
2. Barrido de la cabeza y **identificacion de los cubos** en frente.
3. Dice en voz alta que cubos vio, por ejemplo: "Veo el cubo
   paracetamol, el cubo clonacepam y el cubo ibuprofeno".
4. Busca a una persona: si la ve, camina hacia ella y le repite que
   medicamento toca.

En el NAO real, el barrido de la cabeza y las capturas se repiten dos
veces para aumentar la oportunidad de ver los tres cubos. Por eso la
identificacion tarda un poco mas; usa la camara inferior, adecuada para
los cubos cercanos.

### Los cubos y su medicamento

| Cubo | Medicamento | Como lo ve la camara |
|------|-------------|----------------------|
| Blanco con logo negro | paracetamol | semilla oscura pequena (el logo) rodeada de claro |
| Negro con logo claro | ibuprofeno | mancha oscura grande cuyo entorno es mayormente oscuro |
| Cubo de rubik (6 cm) | clonacepam | stickers azul muy saturado |

La identificacion es por la estructura del cubo, no por el color del
fondo: la semilla es el cubo mismo (su logo, su cuerpo o sus stickers).
Funciona sobre piso blanco, que era un requisito del laboratorio.

## Como correr

```
py -2.7 src/main.py
```

Con diagnostico (impresiones de medidas por candidato y fotogramas
anotados en data/debug/), activar la bandera de diagnostico que se
pasa hasta identificar_cubos.

En el simulador, con Webots abierto con nao_med.wbt:

```
run.bat test
```

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

## Estructura

```
src/               programa principal y modulos del NAO real (Python 2.7)
webots/            mundo y controlador del simulador (Python 3)
data/cronograma.csv  horario de medicamentos
data/debug/        fotogramas de diagnostico (ignorado por git)
data/CALIBRACION.md  calibracion del plano por homografia (pipeline viejo de agarre)
```
