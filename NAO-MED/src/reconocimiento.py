# -*- coding: utf-8 -*-
"""
Reconocimiento de rostros para NAO-Med.

NAO ya trae de fabrica el modulo de vision necesario para esto (ALFace
Detection); este archivo solo se encarga de consultarlo y traducir el
resultado a un simple True/False para el resto del programa
(nao_controller.py).

Se suscribe el modulo y se sondea ALMemory (clave "FaceDetected")
durante un tiempo maximo, reportando si aparecio algun rostro.
http://doc.aldebaran.com/2-8/naoqi/peopleperception/alfacedetection.html

Si el modulo de NAOqi no esta disponible (por ejemplo, corriendo con
el mock) se degrada a un resultado simulado en vez de lanzar una
excepcion, para no romper el flujo de notificacion.
"""
import time

try:
    from naoqi import ALProxy
except ImportError:
    from naoqi_mock import ALProxy

# Cuanto tiempo (segundos) se espera, como maximo, a que aparezca un
# rostro frente a la camara antes de darlo por no encontrado.
TIMEOUT_RECONOCIMIENTO_SEGUNDOS = 8.0

# Cada cuanto se sondea ALMemory mientras se espera (segundos).
INTERVALO_SONDEO_SEGUNDOS = 0.3


def reconocer_rostro(ip, puerto, timeout=TIMEOUT_RECONOCIMIENTO_SEGUNDOS):
    """
    Intenta detectar un rostro frente al NAO usando ALFaceDetection.

    Retorna True si detecto al menos un rostro dentro de 'timeout'
    segundos, False si no detecto ninguno o si el modulo no esta
    disponible.
    """
    try:
        deteccion = ALProxy("ALFaceDetection", ip, puerto)
        memoria = ALProxy("ALMemory", ip, puerto)
    except Exception as e:
        print("Aviso: no se pudo iniciar la deteccion de rostros ({}).".format(e))
        return False

    suscripcion = "NaoMed_FaceDetection"
    try:
        deteccion.subscribe(suscripcion)
    except Exception as e:
        print("Aviso: no se pudo suscribir la deteccion de rostros ({}).".format(e))
        return False

    encontrado = False
    try:
        inicio = time.time()
        while time.time() - inicio < timeout:
            datos = memoria.getData("FaceDetected")
            # ALMemory retorna [] cuando no hay rostro, y una lista con
            # info (marcas de tiempo, forma, extra info) cuando si.
            if datos and isinstance(datos, list) and len(datos) > 1 and datos[1]:
                encontrado = True
                break
            time.sleep(INTERVALO_SONDEO_SEGUNDOS)
    finally:
        try:
            deteccion.unsubscribe(suscripcion)
        except Exception:
            pass

    if encontrado:
        print("[RECONOCIMIENTO] Rostro detectado.")
    else:
        print("[RECONOCIMIENTO] No se detecto ningun rostro en {} segundos.".format(timeout))

    return encontrado
