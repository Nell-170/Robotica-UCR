# -*- coding: utf-8 -*-
"""
Calibracion del piso por homografia para el NAO real.

La homografia es una transformada de perspectiva que traduce un pixel de
la imagen de la camara inferior a una posicion sobre el piso: distancia
al frente y desplazamiento lateral, en metros, medidos desde la base del
robot. Se calibra con 4 puntos del piso de distancia conocida: se anotan
los pixeles donde aparecen en la imagen y las coordenadas reales.

La matriz se guarda en un archivo JSON (data/calibracion_piso.json) para
no tener que recalibrar cada vez que se ejecuta el programa.

La calibracion vale solo para una inclinacion fija de la cabeza
(HeadPitch = INCLINACION_CALIBRACION): al mover la cabeza cambia la
perspectiva y la correspondencia pixel-piso deja de ser valida.

Requiere OpenCV y numpy. Si no estan, las funciones retornan None sin
romper el flujo.
"""
import os
import json

try:
    import cv2
    import numpy as np
    OPENCV_DISPONIBLE = True
except ImportError:
    OPENCV_DISPONIBLE = False

RUTA_CALIBRACION = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "calibracion_piso.json"
))

# Inclinacion de la cabeza (radianes, HeadPitch) con la que se calibra.
# Debe coincidir con INCLINACION_ACERCAMIENTO de agarre_cubo.py.
INCLINACION_CALIBRACION = 0.4


def calcular_homografia(puntos_pixel, puntos_piso):
    """Matriz 3x3 que traduce pixeles a metros sobre el piso, o None sin OpenCV."""
    if not OPENCV_DISPONIBLE:
        return None
    pixel = np.array(puntos_pixel, dtype=np.float32)
    piso = np.array(puntos_piso, dtype=np.float32)
    return cv2.getPerspectiveTransform(pixel, piso)


def pixel_a_piso(matriz, x_pixel, y_pixel):
    """(adelante_m, lateral_m) del punto en pixeles, o None si no se puede."""
    if matriz is None:
        return None
    vector = np.array([x_pixel, y_pixel, 1.0], dtype=np.float64)
    resultado = np.dot(matriz, vector)
    w = resultado[2]
    if abs(w) < 1e-6:
        return None
    return float(resultado[0] / w), float(resultado[1] / w)


def guardar_calibracion(matriz, inclinacion=INCLINACION_CALIBRACION):
    """Guarda la matriz y la inclinacion en RUTA_CALIBRACION. True si guardo."""
    try:
        directorio = os.path.dirname(RUTA_CALIBRACION)
        if not os.path.isdir(directorio):
            os.makedirs(directorio)
        datos = {
            "matriz": [[float(valor) for valor in fila] for fila in matriz],
            "inclinacion": float(inclinacion),
        }
        with open(RUTA_CALIBRACION, "w") as archivo:
            json.dump(datos, archivo)
        return True
    except Exception as e:
        print("Aviso: no se pudo guardar la calibracion ({}).".format(e))
        return False


def cargar_calibracion():
    """(matriz, inclinacion) desde RUTA_CALIBRACION, o (None, None) si falla."""
    if not OPENCV_DISPONIBLE:
        return None, None
    try:
        with open(RUTA_CALIBRACION, "r") as archivo:
            datos = json.load(archivo)
        matriz = np.array(datos["matriz"], dtype=np.float32)
        inclinacion = float(datos["inclinacion"])
        return matriz, inclinacion
    except Exception:
        return None, None


def calibrar_desde_consola():
    """Pide por consola los 4 puntos del piso y guarda la homografia."""
    if not OPENCV_DISPONIBLE:
        print("OpenCV/numpy no disponibles: no se puede calibrar.")
        return
    print("Calibracion del piso por homografia.")
    print("Configuracion tipica: un cuadrado de 0.4 m de lado centrado a 0.5 m")
    print("del robot, es decir los puntos (0.3, 0.2), (0.3, -0.2), (0.7, 0.2),")
    print("(0.7, -0.2) en (adelante, lateral).")
    puntos_pixel = []
    puntos_piso = []
    for i in range(1, 5):
        print("Punto {}:".format(i))
        x = float(raw_input("  Pixel x: "))
        y = float(raw_input("  Pixel y: "))
        adelante = float(raw_input("  Metros al frente: "))
        lateral = float(raw_input("  Metros a la izquierda (negativo = derecha): "))
        puntos_pixel.append((x, y))
        puntos_piso.append((adelante, lateral))
    matriz = calcular_homografia(puntos_pixel, puntos_piso)
    if matriz is None:
        print("No se pudo calcular la homografia.")
        return
    if guardar_calibracion(matriz):
        print("Calibracion guardada en {}.".format(RUTA_CALIBRACION))
    print("Matriz de homografia:")
    print(matriz)
    print("Recuerda: la calibracion solo vale con la cabeza en HeadPitch = {:.2f} rad.".format(INCLINACION_CALIBRACION))


if __name__ == "__main__":
    calibrar_desde_consola()
