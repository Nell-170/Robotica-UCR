# -*- coding: utf-8 -*-
"""
Controlador de NAO para Webots (NAO-Med).

Corre DENTRO del simulador Webots (asignado como "controller" del
nodo Nao en el mundo nao_med.wbt). Escucha comandos por socket desde
el proceso externo (main.py -> nao_controller.py) y mueve/hace hablar
al NAO simulado en consecuencia.
"""
import os
import tempfile
import socket
import time
import numpy as np

from controller import Robot, Motion

try:
    import cv2
    OPENCV_DISPONIBLE = True
except ImportError:
    OPENCV_DISPONIBLE = False

PUERTO_ESCUCHA = 9000

# Si NAOMED_LOG apunta a un archivo, todo lo que se imprime tambien se guarda ahi.
_RUTA_LOG = os.environ.get("NAOMED_LOG")
if _RUTA_LOG:
    import builtins
    _print_original = builtins.print

    def print(*args, **kwargs):
        _print_original(*args, **kwargs)
        with open(_RUTA_LOG, "a") as f:
            _print_original(*args, file=f)

# Inclinaciones de cabeza (rad) que barre el robot buscando el cubo.
INCLINACIONES_CABEZA = (0.0, 0.35, 0.5, -0.3, -0.6)
SEGUNDOS_POR_INCLINACION = 2.0

# Acercamiento al cubo guiado por la camara (lazo cerrado).
INCLINACION_ACERCAMIENTO = 0.4
MAX_PASOS_ACERCAMIENTO = 12
MAX_PASOS_SIN_SONAR = 3  # maximo de pasos sin lectura del sonar
# Distancia (m) maxima al obstaculo del sonar para considerar el agarre.
DISTANCIA_SONAR_AGARRE = 0.35
SONAR_SIN_ECO = 2.0
# Cierre de brazos: avance de ShoulderRoll por paso y diferencia (rad) entre
# lo ordenado y lo medido que se toma como contacto con el cubo.
PASO_CIERRE = 0.04
UMBRAL_CONTACTO = 0.03
INTENTOS_AGARRE = 3

# Poses de brazos (rad). Hombro pitch positivo = brazo hacia abajo.
# Izquierdo; el derecho usa los mismos valores con roll/yaw espejados.
POSE_ABIERTA = {"ShoulderPitch": 0.95, "ShoulderRoll": 0.30, "ElbowYaw": 0.0, "ElbowRoll": -0.30}
ROLL_CIERRE_MAX = -0.28
APRIETE_EXTRA = 0.06
PITCH_LEVANTADO = 0.0

# Se considera "cerca" de la persona cuando su rostro ocupa esta fraccion del ancho de imagen.
ROSTRO_CERCA = 0.30
MAX_PASOS_HACIA_PERSONA = 4

# Frases que dice el NAO segun el resultado de la deteccion de rostro
# (mismo texto que usa el robot fisico en nao_controller.py).
FRASE_ROSTRO_DETECTADO = "Te veo, que tengas un buen dia."
FRASE_ROSTRO_NO_DETECTADO = "No veo a nadie."

# El archivo .motion viene copiado dentro del proyecto (webots/motions/) para
# no depender de la ruta interna de instalacion de Webots en cada maquina.
RUTA_MOTION_CAMINAR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "motions", "Forwards50.motion"
)

RUTA_MOTION_PASO = os.path.join(os.path.dirname(RUTA_MOTION_CAMINAR), "Forwards.motion")
RUTA_MOTION_LADO_IZQ = os.path.join(os.path.dirname(RUTA_MOTION_CAMINAR), "SideStepLeft.motion")
RUTA_MOTION_LADO_DER = os.path.join(os.path.dirname(RUTA_MOTION_CAMINAR), "SideStepRight.motion")
BANDA_CENTRADO = 0.12
ANCHO_CUBO_AGARRE = 0.20

RUTA_REFERENCIAS_CUBO = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "data", "cubo_referencias"
))


class NAOMedController(object):
    def __init__(self):
        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())

        # Nombres reales de los dispositivos del modelo Nao de Webots
        # (verificados contra Nao.proto; no son los mismos nombres que usa
        # NAOqi en el robot real).
        self.leds = {
            "left_eye": self._get_device_seguro("Face/Led/Left"),
            "right_eye": self._get_device_seguro("Face/Led/Right"),
        }
        self.cabeza = self._get_device_seguro("HeadPitch")
        self.brazos = {}
        for lado in ("L", "R"):
            for junta in ("ShoulderPitch", "ShoulderRoll", "ElbowYaw", "ElbowRoll"):
                self.brazos[lado + junta] = self._get_device_seguro(lado + junta)
        for nombre, motor in self.brazos.items():
            if motor:
                sensor = motor.getPositionSensor()
                if sensor:
                    sensor.enable(self.timestep)
        self.sonares = [self._get_device_seguro("Sonar/Left"), self._get_device_seguro("Sonar/Right")]
        for sonar in self.sonares:
            if sonar:
                sonar.enable(self.timestep)
        self.motion_paso = Motion(RUTA_MOTION_PASO) if os.path.exists(RUTA_MOTION_PASO) else None
        self.motion_lado_izq = Motion(RUTA_MOTION_LADO_IZQ) if os.path.exists(RUTA_MOTION_LADO_IZQ) else None
        self.motion_lado_der = Motion(RUTA_MOTION_LADO_DER) if os.path.exists(RUTA_MOTION_LADO_DER) else None
        self.rostro_ancho_rel = None
        self.motion_caminar = None
        if os.path.exists(RUTA_MOTION_CAMINAR):
            self.motion_caminar = Motion(RUTA_MOTION_CAMINAR)
        else:
            print("[WEBOTS] Aviso: no se encontro el archivo de movimiento {}".format(RUTA_MOTION_CAMINAR))

        # Camara del Nao (rostros y cubo)
        self.camera = self._get_device_seguro("CameraTop")
        if self.camera:
            self.camera.enable(self.timestep)
        self.cubo_ancho = 0.0
        self.camara_baja = self._get_device_seguro("CameraBottom")
        if self.camara_baja:
            self.camara_baja.enable(self.timestep)

        # Cascade classifier para deteccion de rostros (OpenCV)
        self.face_cascade = None
        if OPENCV_DISPONIBLE:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.face_cascade = cv2.CascadeClassifier(cascade_path)
            if self.face_cascade.empty():
                print("[WEBOTS] Aviso: no se pudo cargar el cascade classifier de rostros")
                self.face_cascade = None
        else:
            print("[WEBOTS] Aviso: OpenCV no disponible, deteccion de rostros deshabilitada")

        # Detector del cubo: usa las tres vistas de referencia.
        self.cubo_orb = None
        self.cubo_descriptores = []
        if OPENCV_DISPONIBLE:
            self.cubo_orb = cv2.ORB_create(nfeatures=1200)
            for nombre in ("cubo.jpg", "cubo2.jpg", "cubo3.jpg"):
                ruta = os.path.join(RUTA_REFERENCIAS_CUBO, nombre)
                referencia = cv2.imread(ruta, cv2.IMREAD_GRAYSCALE)
                if referencia is None:
                    print("[WEBOTS] Aviso: no se pudo cargar referencia del cubo: {}".format(ruta))
                    continue
                _, descriptores = self.cubo_orb.detectAndCompute(referencia, None)
                if descriptores is not None:
                    self.cubo_descriptores.append(descriptores)
            print("[WEBOTS] Referencias del cubo cargadas: {}".format(
                len(self.cubo_descriptores)))

        # El Nao de Webots no tiene un dispositivo de audio/TTS: no existe
        # forma de que "hable" con sonido dentro del simulador, asi que la
        # frase solo se imprime en la consola de Webots.

        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", PUERTO_ESCUCHA))
        self.server.listen(1)
        self.server.settimeout(0.0)  # no bloqueante

        print("[WEBOTS] Controlador NAO-Med escuchando en puerto {}".format(PUERTO_ESCUCHA))

    def _get_device_seguro(self, nombre):
        try:
            return self.robot.getDevice(nombre)
        except Exception:
            print("[WEBOTS] Aviso: dispositivo '{}' no disponible en este modelo.".format(nombre))
            return None

    def encender_luces(self, color=0x00A2FF):
        for led in self.leds.values():
            if led:
                led.set(color)
        print("[WEBOTS] Luces encendidas: 0x{:06X}".format(color))

    def apagar_luces(self):
        for led in self.leds.values():
            if led:
                led.set(0xFFFFFF)
        print("[WEBOTS] Luces apagadas")

    def reproducir_alarma(self, duracion=2):
        print("[WEBOTS] ALARMA SONORA ({} segundos)".format(duracion))
        self._esperar(duracion)

    def caminar_hacia_frente(self, distancia=1.0):
        # El Nao de Webots no tiene un metodo "moveTo(distancia)" como NAOqi;
        # caminar se logra reproduciendo un archivo .motion (Forwards50.motion,
        # ~50cm por ciclo) sobre los motores de las piernas. Para aproximar
        # la distancia pedida, se reproduce el ciclo las veces necesarias.
        print("[WEBOTS] Caminando {} metros hacia el frente...".format(distancia))
        if not self.motion_caminar:
            print("[WEBOTS] Aviso: no hay movimiento de caminata cargado, se omite.")
            self._esperar(3)
            return

        ciclos = max(int(round(distancia / 0.5)), 1)
        for _ in range(ciclos):
            self._reproducir(self.motion_caminar)

    def decir(self, texto):
        # El Nao de Webots no incluye un dispositivo de audio/TTS: no hay
        # forma de simular la voz con sonido, solo se muestra el texto.
        print("[WEBOTS] Diciendo: {}".format(texto))

    def decir_frase(self, medicamento):
        self.decir("Por favor tomate tu medicina: {}".format(medicamento))

    def detectar_rostro(self, timeout=8.0):
        # Intenta detectar un rostro usando la camara del Nao y OpenCV.
        # Si OpenCV no esta disponible, simula el resultado.
        # Timeout: espera hasta 'timeout' segundos a que aparezca un rostro.
        if not self.camera or not self.face_cascade or not OPENCV_DISPONIBLE:
            print("[WEBOTS] Rostro detectado (simulado, sin camara/OpenCV)")
            return True
        
        inicio = time.time()
        while time.time() - inicio < timeout:
            # Captura frame de la camara
            image_data = self.camera.getImage()
            if not image_data:
                self.robot.step(self.timestep)
                continue
            
            try:
                # Convierte el formato de Webots a numpy array (RGBA -> BGR para OpenCV)
                width = self.camera.getWidth()
                height = self.camera.getHeight()
                image_array = np.frombuffer(image_data, dtype=np.uint8).reshape((height, width, 4))
                # Convierte RGBA a BGR (OpenCV espera BGR)
                image_bgr = image_array[:, :, [2, 1, 0]]
                
                # Convierte a escala de grises para la deteccion
                gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
                
                # Detecta rostros
                faces = self.face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
                
                if len(faces) > 0:
                    print("[WEBOTS] Rostro detectado (real, {} rostro(s) encontrado(s))".format(len(faces)))
                    self.rostro_ancho_rel = max(f[2] for f in faces) / float(width)
                    return True
            except Exception as e:
                print("[WEBOTS] Error en deteccion de rostro: {}".format(e))
                return True
            
            # Avanza la simulacion un paso
            self.robot.step(self.timestep)
        
        print("[WEBOTS] No se detecto ningun rostro en {} segundos".format(timeout))
        return False

    def _inclinar_cabeza(self, angulo):
        """Mueve la cabeza (HeadPitch) y deja pasar unos pasos de simulacion."""
        if self.cabeza:
            self.cabeza.setPosition(angulo)
            self._esperar(0.8)

    def detectar_cubo(self):
        """Busca el cubo barriendo la cabeza arriba y abajo (ORB)."""
        if not self.camera or not self.cubo_orb or not self.cubo_descriptores:
            print("[WEBOTS] Detector del cubo no disponible")
            return False

        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        mejor_global = 0
        encontrado = False
        for inclinacion in INCLINACIONES_CABEZA:
            self._inclinar_cabeza(inclinacion)
            inicio = time.time()
            while time.time() - inicio < SEGUNDOS_POR_INCLINACION:
                image_data = self.camera.getImage()
                if image_data:
                    try:
                        width = self.camera.getWidth()
                        height = self.camera.getHeight()
                        rgba = np.frombuffer(image_data, dtype=np.uint8).reshape((height, width, 4))
                        gray = cv2.cvtColor(rgba[:, :, [2, 1, 0]], cv2.COLOR_BGR2GRAY)
                        puntos, descriptores = self.cubo_orb.detectAndCompute(gray, None)
                        if descriptores is not None:
                            for referencia in self.cubo_descriptores:
                                pares = matcher.knnMatch(referencia, descriptores, k=2)
                                buenas = [par[0] for par in pares
                                          if len(par) == 2 and par[0].distance < 0.75 * par[1].distance]
                                mejor_global = max(mejor_global, len(buenas))
                        if mejor_global >= 8:
                            encontrado = True
                            break
                    except Exception as e:
                        print("[WEBOTS] Error en deteccion del cubo: {}".format(e))
                if self.robot.step(self.timestep) == -1:
                    return False
            if encontrado:
                break

        self._inclinar_cabeza(0.0)
        if encontrado:
            print("[WEBOTS] Cubo detectado ({} coincidencias, inclinacion de cabeza {} rad)".format(
                mejor_global, inclinacion))
        else:
            print("[WEBOTS] No se detecto el cubo (mejor coincidencia: {})".format(mejor_global))
        return encontrado

    def _ubicar_cubo(self):
        """Un cuadro de camara: devuelve (x, y) relativos (0..1) del cubo, o None.
        Busca una mancha clara poco saturada, casi cuadrada, con negro dentro
        (logo y esquinas del cubo), sin depender del fondo, y deja su ancho relativo en self.cubo_ancho."""
        image_data = self.camera.getImage()
        if not image_data:
            return None
        w = self.camera.getWidth()
        h = self.camera.getHeight()
        rgba = np.frombuffer(image_data, dtype=np.uint8).reshape((h, w, 4))
        hsv = cv2.cvtColor(np.ascontiguousarray(rgba[:, :, :3]), cv2.COLOR_BGR2HSV)
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

    def _ubicar_cubo_estable(self, intentos=15):
        for _ in range(intentos):
            ubic = self._ubicar_cubo()
            if ubic:
                return ubic
            if self.robot.step(self.timestep) == -1:
                return None
        return None

    def _reproducir(self, motion):
        """Reproduce un .motion completo: isOver() puede dar True antes de empezar,
        asi que se espera tambien la duracion total del movimiento."""
        motion.play()
        fin = self.robot.getTime() + motion.getDuration() / 1000.0
        while self.robot.getTime() < fin or not motion.isOver():
            if self.robot.step(self.timestep) == -1:
                return

    def _dar_paso(self):
        """Un paso corto hacia adelante (Forwards.motion, ~2.6 s)."""
        if not self.motion_paso:
            self._esperar(2)
            return
        t0 = self.robot.getTime()
        self._reproducir(self.motion_paso)
        print("[WEBOTS] Paso dado: duro {:.2f} s de simulacion".format(self.robot.getTime() - t0))

    def _centrar_cubo(self):
        """Si el cubo no esta centrado en la imagen, da un paso lateral hacia el."""
        ubic = self._ubicar_cubo_estable(5)
        if not ubic:
            print("[WEBOTS] Cubo fuera de vista, avanzo recto.")
            return
        x = ubic[0]
        print("[WEBOTS] Cubo en x={:.2f}".format(x))
        if x < 0.5 - BANDA_CENTRADO and self.motion_lado_izq:
            print("[WEBOTS] Paso lateral a la izquierda.")
            self._reproducir(self.motion_lado_izq)
        elif x > 0.5 + BANDA_CENTRADO and self.motion_lado_der:
            print("[WEBOTS] Paso lateral a la derecha.")
            self._reproducir(self.motion_lado_der)

    def _ver_cubo_o_buscar(self, numero):
        """Guarda una captura y comprueba que el cubo siga en la imagen; si no,
        prueba otras inclinaciones de cabeza. Deja la cabeza donde lo vio."""
        for inclinacion in (INCLINACION_ACERCAMIENTO, 0.2, 0.0, 0.6):
            self._inclinar_cabeza(inclinacion)
            ubic = self._ubicar_cubo_estable(8)
            if ubic:
                ruta = os.path.join(tempfile.gettempdir(), "naomed_paso{}.png".format(numero))
                self.camera.saveImage(ruta, 90)
                if self.camara_baja:
                    self.camara_baja.saveImage(ruta.replace("paso", "bajo"), 90)
                print("[WEBOTS] Cubo visto en x={:.2f} y={:.2f} (cabeza {}), captura {}".format(
                    ubic[0], ubic[1], inclinacion, ruta))
                return True
        return False

    def _distancia_sonar(self):
        """Menor distancia (m) que ven los sonares, o None si no hay lectura."""
        lecturas = [s.getValue() for s in self.sonares
                    if s and 0.0 < s.getValue() < SONAR_SIN_ECO]
        return min(lecturas) if lecturas else None

    def _esperar_brazos_quietos(self, maximo=2.0):
        """Espera a que los brazos dejen de moverse (o se agote el tiempo)."""
        previo = None
        fin = self.robot.getTime() + maximo
        while self.robot.getTime() < fin:
            actual = (self._medido("LShoulderRoll"), self._medido("RShoulderRoll"))
            if previo and None not in actual and \
                    all(abs(a - b) < 0.002 for a, b in zip(actual, previo)):
                return
            previo = actual
            for _ in range(8):
                if self.robot.step(self.timestep) == -1:
                    return

    def _medido(self, clave):
        motor = self.brazos.get(clave)
        sensor = motor.getPositionSensor() if motor else None
        return sensor.getValue() if sensor else None

    def _poner_brazos(self, pitch, roll, codo=-0.30):
        """Ordena la misma pose a ambos brazos (derecho espejado)."""
        for lado, signo in (("L", 1), ("R", -1)):
            ordenes = {"ShoulderPitch": pitch, "ShoulderRoll": signo * roll,
                       "ElbowYaw": 0.0, "ElbowRoll": signo * codo}
            for junta, valor in ordenes.items():
                motor = self.brazos.get(lado + junta)
                if motor:
                    motor.setPosition(valor)

    def _cerrar_hasta_contacto(self):
        """Cierra los brazos de a poco; devuelve el roll ordenado al detectar
        contacto en ambas manos (el brazo no llega a donde se le ordena), o None."""
        roll = POSE_ABIERTA["ShoulderRoll"]
        while roll > ROLL_CIERRE_MAX:
            roll -= PASO_CIERRE
            self._poner_brazos(POSE_ABIERTA["ShoulderPitch"], roll)
            self._esperar_brazos_quietos()
            izq = self._medido("LShoulderRoll")
            der = self._medido("RShoulderRoll")
            if izq is None or der is None:
                print("[WEBOTS] Sin sensores de posicion en los brazos.")
                return None
            retraso_izq = izq - roll
            retraso_der = -der - roll
            if retraso_izq > UMBRAL_CONTACTO and retraso_der > UMBRAL_CONTACTO:
                print("[WEBOTS] Contacto en ambas manos (roll ordenado {:.2f}, medido {:.2f}/{:.2f})".format(
                    roll, izq, -der))
                return roll
        return None

    def acercarse_y_agarrar(self):
        """Sigue el cubo con la camara hasta tenerlo al alcance, lo aprieta con
        ambas manos (verificando contacto) y lo levanta. True si lo tiene."""
        self._poner_brazos(POSE_ABIERTA["ShoulderPitch"], POSE_ABIERTA["ShoulderRoll"])
        self._inclinar_cabeza(INCLINACION_ACERCAMIENTO)
        pasos = 0
        for intento in range(INTENTOS_AGARRE):
            al_alcance = False
            pasos_sin_sonar = 0
            while True:
                if not self._ver_cubo_o_buscar(pasos):
                    print("[WEBOTS] Perdi el cubo de vista: no sigo caminando.")
                    break
                print("[WEBOTS] Ancho del cubo: {:.2f} (meta {:.2f})".format(
                    self.cubo_ancho, ANCHO_CUBO_AGARRE))
                sonar = self._distancia_sonar()
                print("[WEBOTS] Sonar: {}".format("sin lectura" if sonar is None else "{:.2f} m".format(sonar)))
                if sonar is not None and sonar <= DISTANCIA_SONAR_AGARRE:
                    print("[WEBOTS] Obstaculo a {:.2f} m: me detengo.".format(sonar))
                    if self.cubo_ancho >= ANCHO_CUBO_AGARRE:
                        al_alcance = True
                    else:
                        print("[WEBOTS] El sonar detecta algo cerca, pero el cubo aun no parece al alcance.")
                    break
                if sonar is None:
                    if self.cubo_ancho >= ANCHO_CUBO_AGARRE:
                        print("[WEBOTS] El cubo ya se ve al alcance (ancho {:.2f}): me detengo.".format(self.cubo_ancho))
                        al_alcance = True
                        break
                    if pasos_sin_sonar >= MAX_PASOS_SIN_SONAR:
                        print("[WEBOTS] Sin lectura del sonar tras {} pasos: me detengo por seguridad.".format(pasos_sin_sonar))
                        break
                if pasos >= MAX_PASOS_ACERCAMIENTO:
                    break
                self._centrar_cubo()
                self._dar_paso()
                pasos += 1
                if sonar is None:
                    pasos_sin_sonar += 1
            if not al_alcance:
                print("[WEBOTS] No confirme que el cubo este al alcance: cancelo el agarre.")
                break
            print("[WEBOTS] Intento de agarre {}...".format(intento + 1))
            roll = self._cerrar_hasta_contacto()
            if roll is not None:
                self._poner_brazos(POSE_ABIERTA["ShoulderPitch"], roll - APRIETE_EXTRA)
                self._esperar(0.8)
                print("[WEBOTS] Levantando el cubo...")
                self._poner_brazos(PITCH_LEVANTADO, roll - APRIETE_EXTRA)
                self._esperar(2.0)
                self._inclinar_cabeza(0.0)
                return True
            print("[WEBOTS] Sin contacto: abro los brazos y reintento sin avanzar.")
            self._poner_brazos(POSE_ABIERTA["ShoulderPitch"], POSE_ABIERTA["ShoulderRoll"])
            self._esperar(1.0)
        print("[WEBOTS] No pude agarrar el cubo.")
        self._inclinar_cabeza(0.0)
        return False

    def acercarse_a_persona(self):
        """Busca a la persona; si esta lejos camina hacia ella. True si la encontro."""
        for _ in range(MAX_PASOS_HACIA_PERSONA + 1):
            self.rostro_ancho_rel = None
            if not self.detectar_rostro(timeout=4.0):
                return False
            if self.rostro_ancho_rel is None or self.rostro_ancho_rel >= ROSTRO_CERCA:
                return True
            print("[WEBOTS] Persona lejos (rostro {:.0%} del ancho): me acerco.".format(self.rostro_ancho_rel))
            self.caminar_hacia_frente(0.5)
        return True

    def ejecutar_notificacion(self, medicamento):
        print("[WEBOTS] === NOTIFICACION DE MEDICAMENTO ===")
        print("[WEBOTS] Medicamento: {}".format(medicamento))

        self.reproducir_alarma(2)
        self.encender_luces()

        # El cubo representa la medicina: solo se informa si se encontro,
        # y el flujo continua igual en ambos casos.
        cubo_visto = self.detectar_cubo()
        if cubo_visto:
            print("[WEBOTS] Cubo detectado.")
            self.decir("Cubo detectado")
        else:
            print("[WEBOTS] Cubo no detectado.")
            self.decir("Cubo no detectado")

        # Primero toma el cubo; luego busca a la persona y se le acerca.
        if cubo_visto:
            self.acercarse_y_agarrar()
        else:
            print("[WEBOTS] Sin cubo: no hay nada que agarrar.")

        if self.acercarse_a_persona():
            print("[WEBOTS] Persona detectada: el robot se acerca y notifica.")
            self.decir_frase(medicamento)
        else:
            print("[WEBOTS] No se detecto a nadie: el robot no camina.")
            self.decir(FRASE_ROSTRO_NO_DETECTADO)

        self.apagar_luces()

        print("[WEBOTS] === NOTIFICACION COMPLETADA ===")

    def _esperar(self, segundos):
        """Espera 'segundos' avanzando la simulacion paso a paso."""
        pasos = int((segundos * 1000) / self.timestep)
        for _ in range(max(pasos, 1)):
            if self.robot.step(self.timestep) == -1:
                break

    def _atender_conexiones(self):
        """Revisa si hay una conexion entrante y procesa el comando."""
        try:
            conn, _ = self.server.accept()
        except socket.error:
            return  # no hay conexiones pendientes

        conn.settimeout(2)
        try:
            data = conn.recv(1024)
            comando = data.decode("utf-8").strip()
            if comando.startswith("NOTIFICAR:"):
                medicamento = comando.split(":", 1)[1]
                self.ejecutar_notificacion(medicamento)
                conn.send("OK".encode("utf-8"))
            else:
                conn.send("COMANDO_DESCONOCIDO".encode("utf-8"))
        except Exception as e:
            print("[WEBOTS] Error atendiendo conexion: {}".format(e))
        finally:
            conn.close()

    def run(self):
        print("[WEBOTS] Controlador corriendo. Esperando comandos...")
        while self.robot.step(self.timestep) != -1:
            self._atender_conexiones()


if __name__ == "__main__":
    controller = NAOMedController()
    controller.run()
