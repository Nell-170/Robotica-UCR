# -*- coding: utf-8 -*-
"""
Controlador de NAO para Webots (NAO-Med).

Corre DENTRO del simulador Webots (asignado como "controller" del
nodo Nao en el mundo nao_med.wbt). Escucha comandos por socket desde
el proceso externo (main.py -> nao_controller.py) y mueve/hace hablar
al NAO simulado en consecuencia.
"""
import os
import socket
import time
import logging
import numpy as np

from controller import Supervisor, Motion

try:
    import cv2
    OPENCV_DISPONIBLE = True
except ImportError:
    OPENCV_DISPONIBLE = False

PUERTO_ESCUCHA = 9000

# Inclinaciones de cabeza (rad) que barre el robot buscando el cubo.
INCLINACIONES_CABEZA = (0.0, 0.35, 0.5, -0.3, -0.6)
SEGUNDOS_POR_INCLINACION = 2.0
# Separacion horizontal entre el cuerpo y el cubo para la postura de agarre.
# Las manos alcanzan el cubo por delante del cuerpo.
DISTANCIA_AGARRE_METROS = 0.20
TIEMPO_MAXIMO_ACERCAMIENTO = 60.0
# Velocidades angulares durante el agarre (rad/s).
VELOCIDAD_BRAZOS_AGARRE = 0.30
VELOCIDAD_DEDOS_AGARRE = 0.25

logging.basicConfig(
    filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), "ejecucion.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

# Frases que dice el NAO segun el resultado de la deteccion de rostro
# (mismo texto que usa el robot fisico en nao_controller.py).
FRASE_ROSTRO_DETECTADO = "Te veo, que tengas un buen dia."
FRASE_ROSTRO_NO_DETECTADO = "No veo a nadie, por favor acercate."

# El archivo .motion viene copiado dentro del proyecto (webots/motions/) para
# no depender de la ruta interna de instalacion de Webots en cada maquina.
RUTA_MOTION_CAMINAR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "motions", "Forwards50.motion"
)
RUTA_MOTION_RETROCEDER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "motions", "Backwards.motion"
)

RUTA_REFERENCIAS_CUBO = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "data", "cubo_referencias"
))


class NAOMedController(object):
    def __init__(self):
        self.robot = Supervisor()
        self.timestep = int(self.robot.getBasicTimeStep())

        # Nombres reales de los dispositivos del modelo Nao de Webots
        # (verificados contra Nao.proto; no son los mismos nombres que usa
        # NAOqi en el robot real).
        self.leds = {
            "left_eye": self._get_device_seguro("Face/Led/Left"),
            "right_eye": self._get_device_seguro("Face/Led/Right"),
        }
        self.cabeza = self._get_device_seguro("HeadPitch")
        self.brazo_izquierdo = {
            nombre: self._get_device_seguro(nombre)
            for nombre in (
                "LShoulderPitch", "LShoulderRoll", "LElbowYaw",
                "LElbowRoll", "LWristYaw"
            )
        }
        self.brazo_derecho = {
            nombre: self._get_device_seguro(nombre)
            for nombre in (
                "RShoulderPitch", "RShoulderRoll", "RElbowYaw",
                "RElbowRoll", "RWristYaw"
            )
        }
        self.dedos_izquierdos = [
            self._get_device_seguro("LPhalanx{}".format(numero))
            for numero in range(1, 9)
        ]
        self.dedos_derechos = [
            self._get_device_seguro("RPhalanx{}".format(numero))
            for numero in range(1, 9)
        ]
        self.motion_caminar = None
        if os.path.exists(RUTA_MOTION_CAMINAR):
            self.motion_caminar = Motion(RUTA_MOTION_CAMINAR)
        else:
            print("[WEBOTS] Aviso: no se encontro el archivo de movimiento {}".format(RUTA_MOTION_CAMINAR))
        self.motion_retroceder = None
        if os.path.exists(RUTA_MOTION_RETROCEDER):
            self.motion_retroceder = Motion(RUTA_MOTION_RETROCEDER)
        else:
            print("[WEBOTS] Aviso: no se encontro el movimiento de retroceso {}".format(
                RUTA_MOTION_RETROCEDER))

        # Camara del Nao (rostros y cubo)
        self.camera = self._get_device_seguro("CameraTop")
        if self.camera:
            self.camera.enable(self.timestep)
        
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
            self.motion_caminar.setTime(0)
            self.motion_caminar.play()
            while not self.motion_caminar.isOver():
                if self.robot.step(self.timestep) == -1:
                    return

    def caminar_hacia_atras(self, distancia=0.5):
        """Retrocede usando el movimiento oficial Backwards de Webots."""
        print("[WEBOTS] Caminando {} metros hacia atras...".format(distancia))
        if not self.motion_retroceder:
            print("[WEBOTS] Aviso: no hay movimiento de retroceso cargado, se omite.")
            return

        ciclos = max(int(round(distancia / 0.5)), 1)
        for _ in range(ciclos):
            self.motion_retroceder.play()
            while not self.motion_retroceder.isOver():
                if self.robot.step(self.timestep) == -1:
                    return

    def acercarse_al_cubo(self):
        """Camina hasta dejar el cubo al alcance usando posiciones del simulador."""
        if self.motion_caminar is None or not self.motion_caminar.isValid():
            logging.error("No se pudo cargar Forwards50.motion")
            print("[WEBOTS] No se pudo cargar Forwards50.motion.")
            return False

        cubo = None
        if self.robot.getSupervisor():
            cubo = self.robot.getFromDef("CUBO")
            if cubo is None:
                # Un mundo guardado desde el editor puede conservar el nombre
                # del objeto sin conservar el DEF agregado al archivo.
                hijos = self.robot.getRoot().getField("children")
                for indice in range(hijos.getCount()):
                    nodo = hijos.getMFNode(indice)
                    nombre = nodo.getField("name")
                    if nombre is not None and nombre.getSFString() == "cubo":
                        cubo = nodo
                        break
        if cubo is None:
            logging.warning("Sin posicion del cubo: supervisor=%s; avance de dos ciclos sin agarre",
                            self.robot.getSupervisor())
            print("[WEBOTS] Sin posicion del cubo: avanzando dos ciclos. "
                  "Recarga nao_med.wbt para habilitar el agarre por distancia.")
            self.caminar_hacia_frente(1.0)
            return False

        inicio = self.robot.getTime()
        logging.info("Iniciando acercamiento al cubo por distancia")
        self.motion_caminar.setTime(0)
        self.motion_caminar.setLoop(True)
        self.motion_caminar.play()
        ultimo_registro = -1.0
        while self.robot.getTime() - inicio < TIEMPO_MAXIMO_ACERCAMIENTO:
            # Avanzar antes de consultar el estado de la animacion.
            if self.robot.step(self.timestep) == -1:
                self.motion_caminar.stop()
                self.motion_caminar.setLoop(False)
                return False
            posicion = self.robot.getSelf().getPosition()
            objetivo = cubo.getPosition()
            distancia = ((objetivo[0] - posicion[0]) ** 2
                         + (objetivo[1] - posicion[1]) ** 2) ** 0.5
            if self.robot.getTime() - ultimo_registro >= 1.0:
                logging.info("Acercamiento: distancia al cubo=%.3f m", distancia)
                ultimo_registro = self.robot.getTime()
            if distancia <= DISTANCIA_AGARRE_METROS:
                self.motion_caminar.stop()
                self.motion_caminar.setLoop(False)
                logging.info("Cubo al alcance: %.3f m; iniciando agarre", distancia)
                print("[WEBOTS] Cubo al alcance: {:.3f} m; iniciando agarre.".format(distancia))
                return True

        self.motion_caminar.stop()
        self.motion_caminar.setLoop(False)
        logging.warning("Tiempo limite de acercamiento; distancia final=%.3f m", distancia)
        print("[WEBOTS] No se llego al cubo dentro del tiempo limite; se omite el agarre.")
        return False

    def intentar_tomar_cubo(self):
        """Prepara ambas manos y las acerca al cubo para intentar tomarlo."""
        print("[WEBOTS] Intentando tomar el cubo...")

        # Limitar los motores hace mas lento el movimiento real; las pausas
        # permiten completar cada postura antes de iniciar la siguiente.
        for motor in list(self.brazo_izquierdo.values()) + list(self.brazo_derecho.values()):
            if motor:
                motor.setVelocity(min(VELOCIDAD_BRAZOS_AGARRE, motor.getMaxVelocity()))

        # En el modelo NAO de Webots, la posicion maxima deja los dedos
        # abiertos. Hazlo antes de mover los brazos.
        for dedo in self.dedos_izquierdos + self.dedos_derechos:
            if dedo:
                dedo.setVelocity(min(VELOCIDAD_DEDOS_AGARRE, dedo.getMaxVelocity()))
                dedo.setPosition(dedo.getMaxPosition())
        self._esperar(3.0)

        # Retira los brazos para evitar empujar el cubo.
        posiciones_retiro = {
            # Only move back enough to clear the approach; do not drop
            # the hands below the tabletop before bringing them inward.
            "LShoulderPitch": 0.75,
            "LShoulderRoll": 0.3,
            "LElbowYaw": -0.7,
            "LElbowRoll": -0.6,
            "LWristYaw": 0.0,
            "RShoulderPitch": 0.75,
            "RShoulderRoll": -0.3,
            "RElbowYaw": 0.7,
            "RElbowRoll": 0.6,
            "RWristYaw": 0.0,
        }
        for nombre, posicion in posiciones_retiro.items():
            grupo = self.brazo_izquierdo if nombre.startswith("L") else self.brazo_derecho
            motor = grupo[nombre]
            if motor:
                motor.setPosition(posicion)
        self._esperar(8.0)

        posiciones_izquierdas = {
            # Keep the hands above the tabletop while reaching inward.
            "LShoulderPitch": 0.7,
            "LShoulderRoll": -0.15,
            # Rotate the left hand around the cube: fingers to the side,
            # thumb toward the far side of the box.
            "LElbowYaw": -0.9,
            "LElbowRoll": -0.65,
            # Keep the fingers broadside to the cube face.
            "LWristYaw": -0.2,
        }
        posiciones_derechas = {
            "RShoulderPitch": 0.7,
            "RShoulderRoll": 0.15,
            # Mirror the same wrap-around pose on the right hand.
            "RElbowYaw": 0.9,
            "RElbowRoll": 0.65,
            "RWristYaw": 0.2,
        }
        for nombre, posicion in posiciones_izquierdas.items():
            motor = self.brazo_izquierdo[nombre]
            if motor:
                motor.setPosition(posicion)
        for nombre, posicion in posiciones_derechas.items():
            motor = self.brazo_derecho[nombre]
            if motor:
                motor.setPosition(posicion)
        self._esperar(3.0)

        # Close the fingers only part-way to hold the cube without crushing it.
        for dedo in self.dedos_izquierdos + self.dedos_derechos:
            if dedo:
                minimo = dedo.getMinPosition()
                maximo = dedo.getMaxPosition()
                dedo.setPosition(maximo + 0.35 * (minimo - maximo))
        self._esperar(2.5)
        print("[WEBOTS] Cubo sujetado suavemente.")

    def levantar_brazos_con_cubo(self):
        """Eleva los brazos despues del agarre, manteniendo las manos abiertas."""
        posiciones = {
            # Bring the arms slightly inward and keep them straighter while
            # lifting, so the open hands continue supporting the cube.
            "LShoulderPitch": 0.25,
            "LShoulderRoll": -0.2,
            "LElbowYaw": -0.8,
            "LElbowRoll": -0.3,
            "LWristYaw": 0.0,
            "RShoulderPitch": 0.25,
            "RShoulderRoll": 0.2,
            "RElbowYaw": 0.8,
            "RElbowRoll": 0.3,
            "RWristYaw": 0.0,
        }
        for nombre, posicion in posiciones.items():
            grupo = self.brazo_izquierdo if nombre.startswith("L") else self.brazo_derecho
            motor = grupo[nombre]
            if motor:
                motor.setPosition(posicion)
        # Give the motors time to reach the raised pose without jerking the cube.
        self._esperar(3.5)
        print("[WEBOTS] Brazos elevados con el cubo.")

    def decir(self, texto):
        # El Nao de Webots no incluye un dispositivo de audio/TTS: no hay
        # forma de simular la voz con sonido, solo se muestra el texto.
        print("[WEBOTS] Diciendo: {}".format(texto))

    def decir_frase(self, medicamento):
        self.decir("Te toca tu medicina, por favor tomate el {}".format(medicamento))

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
                        _, descriptores = self.cubo_orb.detectAndCompute(gray, None)
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

    def ejecutar_notificacion(self, medicamento):
        print("[WEBOTS] === NOTIFICACION DE MEDICAMENTO ===")
        print("[WEBOTS] Medicamento: {}".format(medicamento))

        self.reproducir_alarma(2)
        self.encender_luces()

        # El cubo representa la medicina: solo se informa si se encontro,
        # y el flujo continua igual en ambos casos.
        if self.detectar_cubo():
            print("[WEBOTS] Cubo detectado.")
            self.decir("Cubo detectado")
        else:
            print("[WEBOTS] Cubo no detectado.")
            self.decir("Cubo no detectado")

        # La deteccion de rostro es la que activa el movimiento:
        # solo camina y notifica si ve a alguien frente al robot.
        if self.detectar_rostro():
            print("[WEBOTS] Persona detectada: el robot camina y notifica.")
            if self.acercarse_al_cubo():
                self.intentar_tomar_cubo()
                self.levantar_brazos_con_cubo()
                self.caminar_hacia_atras(0.5)
            self.decir_frase(medicamento)
            self.decir(FRASE_ROSTRO_DETECTADO)
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
