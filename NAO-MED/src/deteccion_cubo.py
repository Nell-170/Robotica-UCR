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

# Inclinaciones de la cabeza (radianes, HeadPitch: negativo = arriba,
# positivo = abajo; rango NAO -0.67 a 0.51). El robot barre estas
# posiciones hasta encontrar el cubo, asi no tiene que estar a la altura
# de sus ojos.
INCLINACIONES_CABEZA = (0.0, 0.35, 0.5, -0.3, -0.6)
SEGUNDOS_POR_INCLINACION = 2.0
PAUSA_CABEZA_SEGUNDOS = 0.8
COINCIDENCIAS_MINIMAS = 8
VISTAS_FORMA_MINIMAS = 2

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


def ubicar_cubo_por_forma(imagen):
    """True si hay una mancha clara casi cuadrada con negro dentro (el cubo)."""
    hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
    claro = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 130)).astype(np.uint8)
    oscuro = hsv[:, :, 2] < 70
    claro = cv2.morphologyEx(claro, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, _, stats, _ = cv2.connectedComponentsWithStats(claro)
    h, w = imagen.shape[:2]
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < 30 or bw > w * 0.5 or bh > h * 0.5 or not 0.6 < bw / float(bh) < 1.6:
            continue
        if (y + bh / 2.0) / h > 0.8 or area / float(bw * bh) < 0.5:
            continue
        if not 0.04 <= oscuro[y:y + bh, x:x + bw].mean() <= 0.5:
            continue
        return True
    return False


def detectar_cubo(ip, puerto):
    """Retorna True si ve el cubo en la camara del NAO moviendo la cabeza arriba y abajo."""
    if not OPENCV_DISPONIBLE:
        print("[CUBO] OpenCV/numpy no disponibles: deteccion del cubo omitida.")
        return False

    orb = cv2.ORB_create(nfeatures=1200)
    referencias = _cargar_referencias(orb)

    try:
        video = ALProxy("ALVideoDevice", ip, puerto)
        suscripcion = video.subscribeCamera(
            "NaoMed_Cubo", CAMARA_SUPERIOR, RESOLUCION_QVGA, ESPACIO_BGR, FPS_CAMARA
        )
    except Exception as e:
        print("Aviso: no se pudo abrir la camara ({}).".format(e))
        return False

    try:
        motion = ALProxy("ALMotion", ip, puerto)
        motion.setStiffnesses("Head", 1.0)
    except Exception as e:
        print("Aviso: no se pudo controlar la cabeza ({}).".format(e))
        motion = None

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    mejor_global = 0
    encontrado = False
    metodo = None
    try:
        for inclinacion in INCLINACIONES_CABEZA:
            if motion:
                try:
                    motion.setAngles("HeadPitch", inclinacion, 0.2)
                except Exception as e:
                    print("Aviso: no se pudo mover la cabeza ({}).".format(e))
                time.sleep(PAUSA_CABEZA_SEGUNDOS)
            vistas_forma = 0
            inicio = time.time()
            while time.time() - inicio < SEGUNDOS_POR_INCLINACION:
                try:
                    frame = video.getImageRemote(suscripcion)
                    if frame:
                        ancho, alto, capas = frame[0], frame[1], frame[2]
                        imagen = np.frombuffer(bytes(frame[6]), dtype=np.uint8).reshape((alto, ancho, capas))
                        if ubicar_cubo_por_forma(imagen):
                            vistas_forma += 1
                            if vistas_forma >= VISTAS_FORMA_MINIMAS:
                                encontrado = True
                                metodo = "forma"
                                break
                        elif referencias:
                            gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
                            _, desc = orb.detectAndCompute(gris, None)
                            if desc is not None:
                                for ref in referencias:
                                    pares = matcher.knnMatch(ref, desc, k=2)
                                    buenas = [p[0] for p in pares
                                              if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
                                    mejor_global = max(mejor_global, len(buenas))
                            if mejor_global >= COINCIDENCIAS_MINIMAS:
                                encontrado = True
                                metodo = "ORB"
                                break
                except Exception as e:
                    print("Aviso: error en deteccion del cubo ({}).".format(e))
                    break
                time.sleep(0.1)
            if encontrado:
                break
    finally:
        try:
            video.unsubscribe(suscripcion)
        except Exception:
            pass
        if motion:
            try:
                motion.setAngles("HeadPitch", 0.0, 0.2)
            except Exception:
                pass

    if encontrado:
        if metodo == "forma":
            print("[CUBO] Cubo detectado por forma.")
        else:
            print("[CUBO] Cubo detectado por ORB ({} coincidencias).".format(mejor_global))
    else:
        print("[CUBO] No se detecto el cubo (mejor coincidencia: {}).".format(mejor_global))
    return encontrado
