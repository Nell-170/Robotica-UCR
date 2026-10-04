# -*- coding: utf-8 -*-
"""
Deteccion del cubo (la "medicina") para el NAO real.

Misma logica que el controlador de Webots: coincidencias ORB entre los
frames de la camara del NAO (ALVideoDevice) y las tres imagenes de
referencia en data/cubo_referencias. Solo informa si lo ve o no; el
flujo de notificacion continua igual en ambos casos.

Requiere OpenCV y numpy en el Python que corre main.py. Con Python 2.7
la ultima version disponible es opencv-python==4.2.0.32. Si no estan
instalados, la deteccion se omite (retorna False) sin romper el flujo.
"""
import os
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

RUTA_REFERENCIAS_CUBO = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "cubo_referencias"
))

TIMEOUT_CUBO_SEGUNDOS = 8.0
COINCIDENCIAS_MINIMAS = 8

CAMARA_SUPERIOR = 0
RESOLUCION_QVGA = 1
ESPACIO_BGR = 13
FPS_CAMARA = 10


def _cargar_referencias(orb):
    descriptores = []
    for nombre in ("cubo.jpg", "cubo2.jpg", "cubo3.jpg"):
        ruta = os.path.join(RUTA_REFERENCIAS_CUBO, nombre)
        referencia = cv2.imread(ruta, cv2.IMREAD_GRAYSCALE)
        if referencia is None:
            print("Aviso: no se pudo cargar referencia del cubo: {}".format(ruta))
            continue
        _, desc = orb.detectAndCompute(referencia, None)
        if desc is not None:
            descriptores.append(desc)
    return descriptores


def detectar_cubo(ip, puerto, timeout=TIMEOUT_CUBO_SEGUNDOS):
    """Retorna True si ve el cubo en la camara del NAO dentro de 'timeout' s."""
    if not OPENCV_DISPONIBLE:
        print("[CUBO] OpenCV/numpy no disponibles: deteccion del cubo omitida.")
        return False

    orb = cv2.ORB_create(nfeatures=1200)
    referencias = _cargar_referencias(orb)
    if not referencias:
        print("[CUBO] Sin imagenes de referencia: deteccion del cubo omitida.")
        return False

    try:
        video = ALProxy("ALVideoDevice", ip, puerto)
        suscripcion = video.subscribeCamera(
            "NaoMed_Cubo", CAMARA_SUPERIOR, RESOLUCION_QVGA, ESPACIO_BGR, FPS_CAMARA
        )
    except Exception as e:
        print("Aviso: no se pudo abrir la camara ({}).".format(e))
        return False

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    mejor_global = 0
    try:
        inicio = time.time()
        while time.time() - inicio < timeout:
            try:
                frame = video.getImageRemote(suscripcion)
                if frame:
                    ancho, alto, capas = frame[0], frame[1], frame[2]
                    imagen = np.frombuffer(bytes(frame[6]), dtype=np.uint8).reshape((alto, ancho, capas))
                    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
                    _, desc = orb.detectAndCompute(gris, None)
                    if desc is not None:
                        for ref in referencias:
                            pares = matcher.knnMatch(ref, desc, k=2)
                            buenas = [p[0] for p in pares
                                      if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
                            mejor_global = max(mejor_global, len(buenas))
                    if mejor_global >= COINCIDENCIAS_MINIMAS:
                        print("[CUBO] Cubo detectado ({} coincidencias).".format(mejor_global))
                        return True
            except Exception as e:
                print("Aviso: error en deteccion del cubo ({}).".format(e))
                return False
            time.sleep(0.1)
    finally:
        try:
            video.unsubscribe(suscripcion)
        except Exception:
            pass

    print("[CUBO] No se detecto el cubo en {} s (mejor coincidencia: {}).".format(
        timeout, mejor_global))
    return False
