# Calibracion del plano (homografia) para el NAO real

La homografia traduce un pixel de la camara del NAO a una posicion sobre
la superficie donde esta el cubo: metros al frente y metros a los lados.
Esa superficie puede ser una mesa o el piso; el procedimiento es el mismo,
solo cambia donde se pegan las marcas.

La calibracion se guarda en `data/calibracion_plano.json` y se hace una
sola vez. Despues el robot la usa para saber a que distancia esta el cubo
sin depender del sonar.

## Antes de empezar

- El robot encendido y en la red, con su IP a mano.
- Cinta de papel o marcador para las 4 marcas.
- Cinta metrica.
- El cubo puesto donde va a estar durante la demostracion.

## Paso 1: poner las marcas

Pega 4 marcas sobre la superficie, formando un rectangulo alrededor del
cubo. Las 4 esquinas son los puntos de calibracion.

- Que el cubo quede adentro del rectangulo.
- Que las 4 esquinas se vean desde la camara del robot (si el cubo tapa
  una, muevela hacia afuera).
- Un rectangulo de unos 40 x 30 cm suele funcionar bien.

## Paso 2: medir el rectangulo

Con la cinta metrica, anota para cada esquina:

- Metros al frente, medidos desde la base del robot.
- Metros a la izquierda (si esta a la derecha, el numero es negativo).

Ejemplo de un rectangulo de 40 x 30 cm centrado a 50 cm del robot:

| Esquina | Al frente (m) | A la izquierda (m) |
|---------|---------------|--------------------|
| 1       | 0.3           | 0.2                |
| 2       | 0.3           | -0.2               |
| 3       | 0.7           | 0.2                |
| 4       | 0.7           | -0.2               |

## Paso 3: tomar la foto

```
cd NAO-MED
py -2.7 src/calibracion_plano.py --foto
```

Si el robot tiene otra IP:

```
py -2.7 src/calibracion_plano.py --foto --ip 192.168.1.140
```

El robot mueve la cabeza a la inclinacion de calibracion y guarda la foto
en `data/calibracion_vista.png`.

## Paso 4: leer los pixeles

Abre `data/calibracion_vista.png` en un visor de imagenes y anota la
coordenada (x, y) de cada una de las 4 esquinas. El origen (0, 0) es la
esquina superior izquierda de la imagen.

## Paso 5: guardar la calibracion

```
py -2.7 src/calibracion_plano.py
```

Te pide, para cada punto, el pixel x, el pixel y, los metros al frente y
los metros a la izquierda. Al terminar guarda la matriz en
`data/calibracion_plano.json`.

## Paso 6: verificar

```
py -2.7 src/calibracion_plano.py --verificar
```

Toma una foto nueva, detecta el cubo y calcula su distancia. Compara el
resultado con la distancia real medida con la cinta metrica. Si se
parecen, la calibracion quedo bien.

## Cosas que rompen la calibracion

- Mover la cabeza: la calibracion vale solo con HeadPitch = 0.4 rad, que
  es la inclinacion que usa el agarre.
- Mover la mesa o el robot de sitio.
- Cambiar la resolucion de la camara.

Si cambia algo de eso, hay que recalibrar.
