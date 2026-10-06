# -*- coding: utf-8 -*-
"""
Calibracion del plano por homografia para el NAO real.

La homografia es una transformada de perspectiva que traduce un pixel de
la imagen de la camara inferior a una posicion DENTRO DE UN PLANO: la
superficie donde esta el cubo (mesa o suelo). Devuelve la distancia al
frente y el desplazamiento lateral, en metros, medidos desde la base del
robot. Se calibra con 4 puntos del plano de distancia conocida: se anotan
los pixeles donde aparecen en la imagen y las coordenadas reales.

Hay que calibrar sobre la superficie donde estara el cubo: si el cubo
esta sobre una mesa, los 4 puntos deben estar sobre esa mesa; si esta en
el suelo, sobre el suelo.

La matriz se guarda en un archivo JSON (data/calibracion_plano.json) para
no tener que recalibrar cada vez que se ejecuta el programa.

La calibracion vale solo para una inclinacion fija de la cabeza
(HeadPitch = INCLINACION_CALIBRACION): al mover la cabeza cambia la
perspectiva y la correspondencia pixel-plano deja de ser valida.

Requiere OpenCV y numpy. Si no estan, las funciones retornan None sin
romper el flujo.
"""
import os
import json
import sys
import time

try:
    from naoqi import ALProxy
except ImportError:
    from naoqi_mock import ALProxy

try:
    import cv2
    import numpy as np
    OPENCV_DISPONIBLE = True
except ImportError:
    OPENCV_DISPONIBLE = False

RUTA_CALIBRACION = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "calibracion_plano.json"
))

# Inclinacion de la cabeza (radianes, HeadPitch) con la que se calibra.
# Debe coincidir con INCLINACION_ACERCAMIENTO de agarre_cubo.py.
INCLINACION_CALIBRACION = 0.4

# Camara inferior del NAO (ALVideoDevice): camara 1, QVGA, BGR, 10 FPS.
CAMARA_INFERIOR = 1
RESOLUCION_QVGA = 1
ESPACIO_BGR = 13
FPS_CAMARA = 10

# IP y puerto por defecto del NAO (los mismos que usa robot_connector).
try:
    from robot_connector import NAO_IP as IP_DEFECTO, NAO_PORT as PUERTO_DEFECTO
except Exception:
    IP_DEFECTO = "127.0.0.1"
    PUERTO_DEFECTO = 9559


def calcular_homografia(puntos_pixel, puntos_plano):
    """Matriz 3x3 que traduce pixeles a metros sobre el plano, o None sin OpenCV."""
    if not OPENCV_DISPONIBLE:
        return None
    pixel = np.array(puntos_pixel, dtype=np.float32)
    plano = np.array(puntos_plano, dtype=np.float32)
    return cv2.getPerspectiveTransform(pixel, plano)


def pixel_a_plano(matriz, x_pixel, y_pixel):
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
    """Pide por consola los 4 puntos del plano y guarda la homografia."""
    if not OPENCV_DISPONIBLE:
        print("OpenCV/numpy no disponibles: no se puede calibrar.")
        return
    print("Calibracion del plano por homografia.")
    print("Configuracion tipica: un cuadrado de 0.4 m de lado centrado a 0.5 m")
    print("del robot, es decir los puntos (0.3, 0.2), (0.3, -0.2), (0.7, 0.2),")
    print("(0.7, -0.2) en (adelante, lateral).")
    print("Los 4 puntos deben estar sobre la superficie donde estara el cubo")
    print("(mesa o suelo).")
    puntos_pixel = []
    puntos_plano = []
    for i in range(1, 5):
        print("Punto {}:".format(i))
        x = float(raw_input("  Pixel x: "))
        y = float(raw_input("  Pixel y: "))
        adelante = float(raw_input("  Metros al frente: "))
        lateral = float(raw_input("  Metros a la izquierda (negativo = derecha): "))
        puntos_pixel.append((x, y))
        puntos_plano.append((adelante, lateral))
    matriz = calcular_homografia(puntos_pixel, puntos_plano)
    if matriz is None:
        print("No se pudo calcular la homografia.")
        return
    if guardar_calibracion(matriz):
        print("Calibracion guardada en {}.".format(RUTA_CALIBRACION))
    print("Matriz de homografia:")
    print(matriz)
    print("Recuerda: la calibracion solo vale con la cabeza en HeadPitch = {:.2f} rad.".format(INCLINACION_CALIBRACION))


def _tomar_foto(ip, puerto, ruta):
    """Mueve la cabeza a la inclinacion de calibracion, toma una foto con la
    camara inferior y la guarda en ruta. Devuelve la imagen o None si fallo."""
    if not OPENCV_DISPONIBLE:
        print("OpenCV/numpy no disponibles: no se puede tomar la foto.")
        return None
    try:
        motion = ALProxy("ALMotion", ip, puerto)
        video = ALProxy("ALVideoDevice", ip, puerto)
        motion.setStiffnesses("Head", 1.0)
        motion.setAngles("HeadPitch", INCLINACION_CALIBRACION, 0.2)
        motion.setAngles("HeadYaw", 0.0, 0.2)
        time.sleep(1.0)
        suscripcion = video.subscribeCamera(
            "NaoMed_Calibracion", CAMARA_INFERIOR, RESOLUCION_QVGA, ESPACIO_BGR, FPS_CAMARA)
        try:
            frame = video.getImageRemote(suscripcion)
            if not frame:
                print("Aviso: no se obtuvo imagen de la camara inferior.")
                return None
            ancho, alto, capas = frame[0], frame[1], frame[2]
            imagen = np.frombuffer(frame[6], dtype=np.uint8).reshape((alto, ancho, capas))
            cv2.imwrite(ruta, imagen)
            return imagen
        finally:
            try:
                video.unsubscribe(suscripcion)
            except Exception:
                pass
    except Exception as e:
        print("Aviso: no se pudo tomar la foto ({}).".format(e))
        return None


def tomar_foto_calibracion(ip, puerto):
    """Guarda una foto de la camara inferior para leer los pixeles de las esquinas."""
    ruta = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "calibracion_vista.png"))
    imagen = _tomar_foto(ip, puerto, ruta)
    if imagen is None:
        print("No se pudo tomar la foto de calibracion.")
        return
    print("Foto guardada en {}.".format(ruta))
    print("Abre esa imagen y anota los pixeles de las 4 esquinas del plano")
    print("(la superficie donde estara el cubo), luego ejecuta este programa")
    print("sin argumentos para ingresarlos por consola.")


def _ubicar_cubo_en_imagen(imagen):
    """(x, y) relativos (0..1) del cubo en la imagen, o None si no lo ve."""
    hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
    claro = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 130)).astype(np.uint8)
    oscuro = hsv[:, :, 2] < 70
    claro = cv2.morphologyEx(claro, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(claro)
    h, w = imagen.shape[:2]
    mejor = None
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 30 or bw > w * 0.5 or bh > h * 0.5 or not 0.6 < bw / float(bh) < 1.6:
            continue
        if (y + bh / 2.0) / h > 0.8 or area / float(bw * bh) < 0.5:
            continue
        if not 0.04 <= oscuro[y:y + bh, x:x + bw].mean() <= 0.5:
            continue
        if mejor is None or area > mejor[0]:
            mejor = (area, (x + bw / 2.0) / w, (y + bh / 2.0) / h)
    if not mejor:
        return None
    return mejor[1], mejor[2]


def verificar_calibracion(ip, puerto):
    """Toma una foto, detecta el cubo y calcula su distancia con la homografia."""
    matriz, _ = cargar_calibracion()
    if matriz is None:
        print("No hay calibracion guardada: ejecuta primero la calibracion.")
        return
    ruta = os.path.normpath(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "data", "calibracion_verificacion.png"))
    imagen = _tomar_foto(ip, puerto, ruta)
    if imagen is None:
        print("No se pudo tomar la foto de verificacion.")
        return
    ubic = _ubicar_cubo_en_imagen(imagen)
    if ubic is None:
        print("No se detecto el cubo en la foto de verificacion.")
        return
    x_pixel = ubic[0] * imagen.shape[1]
    y_pixel = ubic[1] * imagen.shape[0]
    resultado = pixel_a_plano(matriz, x_pixel, y_pixel)
    if resultado is None:
        print("No se pudo calcular la distancia con la homografia.")
        return
    print("Cubo a {:.2f} m al frente, {:.2f} m lateral".format(resultado[0], resultado[1]))


def _parsear_argumentos(argv):
    """(modo, ip, puerto) desde sys.argv. Modo: consola, foto o verificar."""
    modo = "consola"
    ip = IP_DEFECTO
    puerto = PUERTO_DEFECTO
    i = 0
    while i < len(argv):
        if argv[i] == "--foto":
            modo = "foto"
        elif argv[i] == "--verificar":
            modo = "verificar"
        elif argv[i] == "--ip" and i + 1 < len(argv):
            ip = argv[i + 1]
            i += 1
        elif argv[i] == "--puerto" and i + 1 < len(argv):
            puerto = int(argv[i + 1])
            i += 1
        i += 1
    return modo, ip, puerto


if __name__ == "__main__":
    modo, ip, puerto = _parsear_argumentos(sys.argv[1:])
    if modo == "foto":
        tomar_foto_calibracion(ip, puerto)
    elif modo == "verificar":
        verificar_calibracion(ip, puerto)
    else:
        calibrar_desde_consola()
