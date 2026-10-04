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
import numpy as np

from controller import Robot, Motion

try:
    import cv2
    OPENCV_DISPONIBLE = True
except ImportError:
    OPENCV_DISPONIBLE = False

PUERTO_ESCUCHA = 9000

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
        self.motion_caminar = None
        if os.path.exists(RUTA_MOTION_CAMINAR):
            self.motion_caminar = Motion(RUTA_MOTION_CAMINAR)
        else:
            print("[WEBOTS] Aviso: no se encontro el archivo de movimiento {}".format(RUTA_MOTION_CAMINAR))

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
            self.motion_caminar.play()
            while not self.motion_caminar.isOver():
                if self.robot.step(self.timestep) == -1:
                    return

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

    def detectar_cubo(self, timeout=8.0):
        """Busca el cubo en la cámara usando coincidencias ORB."""
        if not self.camera or not self.cubo_orb or not self.cubo_descriptores:
            print("[WEBOTS] Detector del cubo no disponible")
            return False

        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        inicio = time.time()
        mejor_global = 0
        frames_recibidos = 0
        while time.time() - inicio < timeout:
            image_data = self.camera.getImage()
            if image_data:
                try:
                    frames_recibidos += 1
                    width = self.camera.getWidth()
                    height = self.camera.getHeight()
                    rgba = np.frombuffer(image_data, dtype=np.uint8).reshape((height, width, 4))
                    image_bgr = rgba[:, :, [2, 1, 0]]
                    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
                    _, descriptores = self.cubo_orb.detectAndCompute(gray, None)

                    mejor = 0
                    if descriptores is not None:
                        for referencia in self.cubo_descriptores:
                            pares = matcher.knnMatch(referencia, descriptores, k=2)
                            buenas = [par[0] for par in pares
                                      if len(par) == 2 and par[0].distance < 0.75 * par[1].distance]
                            mejor = max(mejor, len(buenas))

                    mejor_global = max(mejor_global, mejor)

                    if mejor >= 8:
                        print("[WEBOTS] Cubo detectado ({} coincidencias)".format(mejor))
                        return True
                except Exception as e:
                    print("[WEBOTS] Error en deteccion del cubo: {}".format(e))

            if self.robot.step(self.timestep) == -1:
                return False

        print("[WEBOTS] No se detecto el cubo en {} segundos (mejor coincidencia: {})".format(
            timeout, mejor_global))
        print("[WEBOTS] Frames recibidos: {}".format(frames_recibidos))
        return False

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
            self.caminar_hacia_frente(1.0)
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
