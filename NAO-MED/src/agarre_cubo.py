# -*- coding: utf-8 -*-
"""
Agarre del cubo (la "medicina") para el NAO real.

Misma logica que el controlador de Webots: sigue el cubo con la camara
superior, camina hacia el en pasos cortos, se detiene cuando el sonar
marca DISTANCIA_SONAR_AGARRE, cierra ambos brazos de a poco hasta notar
contacto (el brazo no llega al angulo ordenado) y lo levanta.

El cubo se reconoce por su aspecto (mancha clara casi cuadrada con negro
dentro), sin depender del color del fondo.

Requiere OpenCV y numpy. Si no estan, retorna False sin romper el flujo.
"""
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

from calibracion_piso import cargar_calibracion, pixel_a_piso

CAMARA_INFERIOR = 1
RESOLUCION_QVGA = 1
ESPACIO_BGR = 13
FPS_CAMARA = 10

INCLINACION_ACERCAMIENTO = 0.4
INCLINACIONES_BUSQUEDA = (0.4, 0.2, 0.0, 0.5)
MAX_PASOS_ACERCAMIENTO = 12
MAX_PASOS_SIN_SONAR = 3  # maximo de pasos sin lectura del sonar
LARGO_PASO_METROS = 0.08
BANDA_CENTRADO = 0.12
PASO_LATERAL_METROS = 0.05
ANCHO_CUBO_AGARRE = 0.20

DISTANCIA_SONAR_AGARRE = 0.35
DISTANCIA_AGARRE_METROS = 0.35  # distancia al frente para considerar el cubo al alcance
SONAR_SIN_ECO = 2.0
CLAVES_SONAR = ("Device/SubDeviceList/US/Left/Sensor/Value",
                "Device/SubDeviceList/US/Right/Sensor/Value")

POSE_ABIERTA = {"ShoulderPitch": 0.95, "ShoulderRoll": 0.30, "ElbowYaw": 0.0, "ElbowRoll": -0.30}
PASO_CIERRE = 0.04
ROLL_CIERRE_MAX = -0.28
UMBRAL_CONTACTO = 0.03
APRIETE_EXTRA = 0.06
PITCH_LEVANTADO = 0.0
INTENTOS_AGARRE = 3
VELOCIDAD_BRAZOS = 0.15

NOMBRES_BRAZOS = ["LShoulderPitch", "LShoulderRoll", "LElbowYaw", "LElbowRoll",
                  "RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll"]


class _Agarre(object):
    def __init__(self, ip, puerto):
        self.motion = ALProxy("ALMotion", ip, puerto)
        self.memoria = ALProxy("ALMemory", ip, puerto)
        self.video = ALProxy("ALVideoDevice", ip, puerto)
        self.suscripcion = self.video.subscribeCamera(
            "NaoMed_Agarre", CAMARA_INFERIOR, RESOLUCION_QVGA, ESPACIO_BGR, FPS_CAMARA)
        self.cubo_ancho = 0.0
        self.matriz_piso, self.inclinacion_piso = cargar_calibracion()
        if self.matriz_piso is None:
            print("[CUBO] Sin calibracion del piso: se usara el sonar para la distancia.")
        else:
            print("[CUBO] Calibracion del piso cargada (HeadPitch {:.2f}).".format(self.inclinacion_piso))
        self.motion.setStiffnesses("Head", 1.0)
        self.motion.setStiffnesses("LArm", 1.0)
        self.motion.setStiffnesses("RArm", 1.0)

    def cerrar(self):
        try:
            self.video.unsubscribe(self.suscripcion)
        except Exception:
            pass

    def _inclinar_cabeza(self, angulo):
        self.motion.setAngles("HeadPitch", angulo, 0.2)
        time.sleep(0.8)

    def _ubicar_cubo(self):
        """(x, y) relativos (0..1) del cubo, o None. Deja el ancho relativo en cubo_ancho."""
        frame = self.video.getImageRemote(self.suscripcion)
        if not frame:
            return None
        w, h, capas = frame[0], frame[1], frame[2]
        self.ancho_imagen = w
        self.alto_imagen = h
        imagen = np.frombuffer(frame[6], dtype=np.uint8).reshape((h, w, capas))
        hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
        claro = ((hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 130)).astype(np.uint8)
        oscuro = hsv[:, :, 2] < 70
        claro = cv2.morphologyEx(claro, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, _, stats, _ = cv2.connectedComponentsWithStats(claro)
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
                mejor = (area, (x + bw / 2.0) / w, (y + bh / 2.0) / h, bw / float(w))
        if not mejor:
            return None
        self.cubo_ancho = mejor[3]
        return mejor[1], mejor[2]

    def _ubicar_cubo_estable(self, intentos=8):
        for _ in range(intentos):
            ubic = self._ubicar_cubo()
            if ubic:
                return ubic
            time.sleep(0.1)
        return None

    def _ver_cubo_o_buscar(self):
        for inclinacion in INCLINACIONES_BUSQUEDA:
            self._inclinar_cabeza(inclinacion)
            ubic = self._ubicar_cubo_estable()
            if ubic:
                return ubic
        return None

    def _distancia_sonar(self):
        lecturas = []
        for clave in CLAVES_SONAR:
            try:
                valor = float(self.memoria.getData(clave))
            except Exception:
                continue
            if 0.0 < valor < SONAR_SIN_ECO:
                lecturas.append(valor)
        return min(lecturas) if lecturas else None

    def _distancia_por_homografia(self, ubic):
        """Distancia al frente en metros segun la calibracion del piso, o None."""
        if self.matriz_piso is None:
            return None
        x_pixel = ubic[0] * self.ancho_imagen
        y_pixel = ubic[1] * self.alto_imagen
        resultado = pixel_a_piso(self.matriz_piso, x_pixel, y_pixel)
        if resultado is None:
            return None
        return resultado[0]

    def _centrar_y_avanzar(self, x):
        lateral = 0.0
        if x < 0.5 - BANDA_CENTRADO:
            lateral = PASO_LATERAL_METROS
        elif x > 0.5 + BANDA_CENTRADO:
            lateral = -PASO_LATERAL_METROS
        self.motion.moveTo(LARGO_PASO_METROS, lateral, 0.0)

    def _poner_brazos(self, pitch, roll, codo=-0.30):
        angulos = [pitch, roll, 0.0, codo, pitch, -roll, 0.0, -codo]
        self.motion.setAngles(NOMBRES_BRAZOS, angulos, VELOCIDAD_BRAZOS)

    def _medido(self, nombre):
        return self.motion.getAngles(nombre, True)[0]

    def _esperar_brazos_quietos(self, maximo=2.0):
        previo = None
        fin = time.time() + maximo
        while time.time() < fin:
            actual = (self._medido("LShoulderRoll"), self._medido("RShoulderRoll"))
            if previo and all(abs(a - b) < 0.002 for a, b in zip(actual, previo)):
                return
            previo = actual
            time.sleep(0.15)

    def _cerrar_hasta_contacto(self):
        roll = POSE_ABIERTA["ShoulderRoll"]
        while roll > ROLL_CIERRE_MAX:
            roll -= PASO_CIERRE
            self._poner_brazos(POSE_ABIERTA["ShoulderPitch"], roll)
            self._esperar_brazos_quietos()
            retraso_izq = self._medido("LShoulderRoll") - roll
            retraso_der = -self._medido("RShoulderRoll") - roll
            if retraso_izq > UMBRAL_CONTACTO and retraso_der > UMBRAL_CONTACTO:
                print("[CUBO] Contacto en ambas manos (roll ordenado {:.2f}).".format(roll))
                return roll
        return None

    def acercarse_y_agarrar(self):
        self._poner_brazos(POSE_ABIERTA["ShoulderPitch"], POSE_ABIERTA["ShoulderRoll"])
        self._inclinar_cabeza(INCLINACION_ACERCAMIENTO)
        time.sleep(1.0)
        pasos = 0
        for intento in range(INTENTOS_AGARRE):
            al_alcance = False
            pasos_sin_sonar = 0
            while True:
                ubic = self._ver_cubo_o_buscar()
                if not ubic:
                    print("[CUBO] Perdi el cubo de vista: no sigo caminando.")
                    break
                distancia = self._distancia_por_homografia(ubic)
                sonar = self._distancia_sonar()
                if distancia is not None:
                    print("[CUBO] Ancho {:.2f} (meta {:.2f}), sonar {}, piso {:.2f} m".format(
                        self.cubo_ancho, ANCHO_CUBO_AGARRE,
                        "sin lectura" if sonar is None else "{:.2f} m".format(sonar), distancia))
                    if distancia <= DISTANCIA_AGARRE_METROS:
                        print("[CUBO] Cubo a {:.2f} m segun la calibracion: me detengo.".format(distancia))
                        al_alcance = True
                        break
                else:
                    print("[CUBO] Ancho {:.2f} (meta {:.2f}), sonar {}".format(
                        self.cubo_ancho, ANCHO_CUBO_AGARRE,
                        "sin lectura" if sonar is None else "{:.2f} m".format(sonar)))
                if sonar is not None and sonar <= DISTANCIA_SONAR_AGARRE:
                    print("[CUBO] Obstaculo a {:.2f} m: me detengo.".format(sonar))
                    if self.cubo_ancho >= ANCHO_CUBO_AGARRE:
                        al_alcance = True
                    else:
                        print("[CUBO] El sonar detecta algo cerca, pero el cubo aun no parece al alcance.")
                    break
                if distancia is None and sonar is None:
                    if self.cubo_ancho >= ANCHO_CUBO_AGARRE:
                        print("[CUBO] El cubo ya se ve al alcance (ancho {:.2f}): me detengo.".format(self.cubo_ancho))
                        al_alcance = True
                        break
                    if pasos_sin_sonar >= MAX_PASOS_SIN_SONAR:
                        print("[CUBO] Sin lectura del sonar tras {} pasos: me detengo por seguridad.".format(pasos_sin_sonar))
                        break
                if sonar is not None:
                    pasos_sin_sonar = 0
                if pasos >= MAX_PASOS_ACERCAMIENTO:
                    break
                self._centrar_y_avanzar(ubic[0])
                pasos += 1
                if sonar is None:
                    pasos_sin_sonar += 1
            if not al_alcance:
                print("[CUBO] No confirme que el cubo este al alcance: cancelo el agarre.")
                break
            print("[CUBO] Intento de agarre {}...".format(intento + 1))
            roll = self._cerrar_hasta_contacto()
            if roll is not None:
                self._poner_brazos(POSE_ABIERTA["ShoulderPitch"], roll - APRIETE_EXTRA)
                time.sleep(0.8)
                self._poner_brazos(PITCH_LEVANTADO, roll - APRIETE_EXTRA)
                time.sleep(2.0)
                self._inclinar_cabeza(0.0)
                return True
            print("[CUBO] Sin contacto: abro los brazos y reintento sin avanzar.")
            self._poner_brazos(POSE_ABIERTA["ShoulderPitch"], POSE_ABIERTA["ShoulderRoll"])
            time.sleep(1.0)
        self._inclinar_cabeza(0.0)
        return False


def agarrar_cubo(ip, puerto):
    """Camina hacia el cubo, lo agarra con ambas manos y lo levanta. True si lo tiene."""
    if not OPENCV_DISPONIBLE:
        print("[CUBO] OpenCV/numpy no disponibles: agarre omitido.")
        return False
    try:
        agarre = _Agarre(ip, puerto)
    except Exception as e:
        print("Aviso: no se pudo preparar el agarre ({}).".format(e))
        return False
    try:
        return agarre.acercarse_y_agarrar()
    except Exception as e:
        print("Aviso: error durante el agarre ({}).".format(e))
        return False
    finally:
        agarre.cerrar()
