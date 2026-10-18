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

# Inclinaciones de cabeza (rad) que barre el robot buscando el cubo.
INCLINACIONES_CABEZA = (0.0, 0.35, 0.5, -0.3, -0.6)
SEGUNDOS_POR_INCLINACION = 2.0

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

# Diagnostico: aca se guardan fotogramas de la camara con los candidatos
# marcados, para afinar los umbrales con evidencia y no a ciegas.
RUTA_DEBUG = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "..", "..", "data", "debug"
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

    def _frame_bgr(self):
        """Imagen actual de la camara en BGR, o None si no hay camara."""
        if not self.camera or not OPENCV_DISPONIBLE:
            return None
        image_data = self.camera.getImage()
        if not image_data:
            return None
        width = self.camera.getWidth()
        height = self.camera.getHeight()
        rgba = np.frombuffer(image_data, dtype=np.uint8).reshape((height, width, 4))
        return rgba[:, :, [2, 1, 0]]

    def _cubos_en_frame(self, bgr, etiqueta_debug=None):
        """Clasifica los cubos del frame por su estructura, no por el fondo.

        La semilla es una mancha oscura compacta (el logo del cubo blanco,
        el cuerpo del cubo negro) o azul (los stickers del rubik). Cada
        semilla se clasifica por lo que hay en su entorno inmediato, asi el
        color del fondo (puerta blanca, piso claro) no participa.
        """
        hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
        h, w = hsv.shape[:2]
        saturacion = hsv[:, :, 1]
        valor = hsv[:, :, 2]
        tono = hsv[:, :, 0]
        # Umbrales medidos sobre fotogramas reales de la camara del Nao en
        # Webots (data/debug/): esa camara desvia a azul toda la escena, la
        # madera se ve con H~108 y S~98, la cara blanca del cubo rinde
        # V~133 y el cuerpo negro V~70-90.
        clara = ((saturacion < 80) & (valor > 115)).astype(np.uint8)
        oscura = (valor < 90).astype(np.uint8)
        # Azul solo si esta muy saturado: la mesa (S~98) y la pared quedan
        # fuera; los stickers del rubik miden S~169.
        azul = ((tono >= 100) & (tono <= 135) & (saturacion > 120) & (valor > 60)).astype(np.uint8)

        nucleo = np.ones((3, 3), np.uint8)
        hallados = {}  # medicamento -> x del hallazgo mas a la izquierda
        anotada = bgr.copy() if etiqueta_debug else None

        def _entorno(x, y, ancho, alto):
            """Recuadro de la mancha con un margen de 2 pixeles."""
            return (max(x - 2, 0), max(y - 2, 0),
                    min(x + ancho + 2, w), min(y + alto + 2, h))

        # Semillas oscuras:
        # - pequena (el logo, 8-130 px, caja hasta 16x16) rodeada de claro:
        #   el paracetamol.
        # - grande (200-700 px) y mayormente oscura sin azul alrededor: el
        #   cuerpo del ibuprofeno.
        # El cuerpo oscuro del rubik (area ~350) queda excluido porque su
        # entorno tiene stickers azules.
        n, _, stats, _ = cv2.connectedComponentsWithStats(
            cv2.morphologyEx(oscura, cv2.MORPH_CLOSE, nucleo))
        for i in range(1, n):
            x, y, ancho, alto, area = stats[i]
            if area < 8 or area > 700 or ancho > w * 0.5 or alto > h * 0.5:
                continue
            if not 0.5 < ancho / float(alto) < 2.0:
                continue
            if (y + alto / 2.0) > 0.85 * h:
                continue
            x0, y0, x1, y1 = _entorno(x, y, ancho, alto)
            trozo = np.s_[y0:y1, x0:x1]
            clara_ent = clara[trozo].mean()
            oscura_ent = oscura[trozo].mean()
            azul_ent = azul[trozo].mean()
            medicamento = None
            if area <= 130 and ancho <= 18 and alto <= 18 and clara_ent >= 0.25 and azul_ent < 0.12:
                medicamento = "paracetamol"
            elif area > 200 and oscura_ent >= 0.40 and azul_ent < 0.12:
                medicamento = "ibuprofeno"
            if etiqueta_debug:
                print("[CUBO-DEBUG] {} oscuro: area={} caja={}x{} clara={:.2f} oscura={:.2f} azul={:.2f} -> {}".format(
                    etiqueta_debug, area, ancho, alto, clara_ent, oscura_ent, azul_ent,
                    medicamento or "descartado"))
                cv2.rectangle(anotada, (x0, y0), (x1, y1), (0, 0, 255), 1)
            if medicamento is None:
                continue
            cx = x + ancho / 2.0
            if medicamento not in hallados or cx < hallados[medicamento]:
                hallados[medicamento] = cx

        # Semillas azules: los stickers del rubik (clonacepam). Se exige que
        # el entorno tambien tenga azul (la cara 3x3 entera) y que la mancha
        # sea chica: el piso, que esta camara tambien ve azulado, forma una
        # banda de todo el ancho y queda excluida por tamano.
        n, _, stats, _ = cv2.connectedComponentsWithStats(
            cv2.morphologyEx(azul, cv2.MORPH_CLOSE, nucleo))
        for i in range(1, n):
            x, y, ancho, alto, area = stats[i]
            if area < 8 or ancho > 40 or alto > 40:
                continue
            # Proporcion relajada: los stickers pueden verse como una fila
            # (19x5 en la imagen real). La banda del piso queda excluida por
            # el tope de ancho de arriba.
            if not 0.25 < ancho / float(alto) < 4.0:
                continue
            if (y + alto / 2.0) > 0.85 * h:
                continue
            x0, y0, x1, y1 = _entorno(x, y, ancho, alto)
            fraccion_azul = azul[y0:y1, x0:x1].mean()
            if etiqueta_debug:
                print("[CUBO-DEBUG] {} azul: area={} caja={}x{} azul={:.2f} -> {}".format(
                    etiqueta_debug, area, ancho, alto, fraccion_azul,
                    "clonacepam" if fraccion_azul >= 0.20 else "descartado"))
                cv2.rectangle(anotada, (x0, y0), (x1, y1), (0, 255, 255), 1)
            if fraccion_azul < 0.20:
                continue
            cx = x + ancho / 2.0
            if "clonacepam" not in hallados or cx < hallados["clonacepam"]:
                hallados["clonacepam"] = cx

        if etiqueta_debug and anotada is not None:
            if not os.path.isdir(RUTA_DEBUG):
                os.makedirs(RUTA_DEBUG)
            ruta_imagen = os.path.join(RUTA_DEBUG, "frame_{}.png".format(etiqueta_debug))
            cv2.imwrite(ruta_imagen, anotada)
            print("[CUBO-DEBUG] Fotograma guardado: {}".format(ruta_imagen))

        return sorted(hallados.items(), key=lambda par: par[1])

    def identificar_cubos(self, diagnostico=False):
        """Barre la cabeza, identifica los cubos en frente y devuelve los
        medicamentos vistos, ordenados de izquierda a derecha en la imagen.

        Con diagnostico=True imprime, por cada candidato, sus medidas y
        guarda un fotograma anotado en data/debug/ para afinar umbrales.
        """
        if not self.camera or not OPENCV_DISPONIBLE:
            print("[WEBOTS] Identificacion de cubos no disponible (sin camara u OpenCV)")
            return []

        vistos = {}
        for inclinacion in INCLINACIONES_CABEZA:
            self._inclinar_cabeza(inclinacion)
            inicio = time.time()
            por_medicamento = {}
            primer_frame = True
            while time.time() - inicio < SEGUNDOS_POR_INCLINACION:
                bgr = self._frame_bgr()
                if bgr is not None:
                    etiqueta = None
                    if diagnostico and primer_frame:
                        etiqueta = "pitch{:+.1f}".format(inclinacion)
                        primer_frame = False
                    for medicamento, cx in self._cubos_en_frame(bgr, etiqueta):
                        por_medicamento.setdefault(medicamento, []).append(cx)
                if self.robot.step(self.timestep) == -1:
                    break
            for medicamento, xs in por_medicamento.items():
                if len(xs) >= 3 and medicamento not in vistos:
                    vistos[medicamento] = sum(xs) / float(len(xs))
            if len(vistos) == 3:
                break

        self._inclinar_cabeza(0.0)
        ordenados = sorted(vistos.items(), key=lambda par: par[1])
        return [medicamento for medicamento, _ in ordenados]

    def identificar_cubos_con_diagnostico(self):
        """Igual a identificar_cubos, pero con impresiones y fotogramas de
        diagnostico. Usar solo para calibrar umbrales."""
        return self.identificar_cubos(diagnostico=True)

    def _frase_cubos(self, medicamentos):
        """Frase hablada con los cubos identificados."""
        if not medicamentos:
            return "No veo ningun cubo"
        if len(medicamentos) == 1:
            return "Veo el cubo " + medicamentos[0]
        if len(medicamentos) == 2:
            return "Veo el cubo {} y el cubo {}".format(medicamentos[0], medicamentos[1])
        return "Veo el cubo {}, el cubo {} y el cubo {}".format(*medicamentos)

    def ejecutar_notificacion(self, medicamento):
        print("[WEBOTS] === NOTIFICACION DE MEDICAMENTO ===")
        print("[WEBOTS] Medicamento: {}".format(medicamento))

        self.reproducir_alarma(2)
        self.encender_luces()

        # Pipeline alternativo: no se agarra el cubo. Lo primero es
        # identificar que cubos hay en frente y decirlo.
        medicamentos = self.identificar_cubos()
        if medicamentos:
            print("[WEBOTS] Cubos identificados: {}".format(", ".join(medicamentos)))
        else:
            print("[WEBOTS] No se identifico ningun cubo.")
        self.decir(self._frase_cubos(medicamentos))

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
