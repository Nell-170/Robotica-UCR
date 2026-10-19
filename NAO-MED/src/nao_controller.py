# -*- coding: utf-8 -*-
"""
Controlador de acciones del NAO para NAO-Med.

Secuencia al detectar que es hora de un medicamento:
    1. Sonido de alarma (~2 segundos)
    2. Luces LED de los ojos encendidas
    3. Deteccion del cubo (solo informa) y reconocimiento de rostro: espera a ver a alguien frente al robot
    4. Solo si detecta a una persona, camina en linea recta hacia el
       frente y dice la frase de notificacion del medicamento
    5. Si no detecta a nadie, el robot NO camina: solo dice que no ve
       a nadie y pide que se acerque

La deteccion de rostro vive en reconocimiento.py, que usa el modulo de
vision que NAOqi ya trae integrado (ALFaceDetection). Es la que activa
el movimiento: la caminata y el mensaje solo ocurren si hay alguien
frente al robot.
"""
import time
import socket

try:
    from naoqi import ALProxy
except ImportError:
    print("[WARN] naoqi no disponible, usando mock para testing")
    from naoqi_mock import ALProxy

from reconocimiento import reconocer_rostro
from deteccion_cubo import identificar_cubos, frase_cubos, posicion_cubo

# Distancia (en metros) que camina el NAO en linea recta hacia el frente
DISTANCIA_CAMINATA_METROS = 1.0

# Duracion de la alarma sonora, en segundos
DURACION_ALARMA_SEGUNDOS = 2

# Color de las luces de los ojos al notificar (RGB en hexadecimal)
COLOR_LUCES_NOTIFICACION = 0x00A2FF  # azul, para llamar la atencion

# Frases que dice el NAO segun el resultado de la deteccion de rostro
FRASE_ROSTRO_DETECTADO = "Sigueme, te mostrare en donde esta."
FRASE_ROSTRO_NO_DETECTADO = "No veo a nadie, por favor acercate."

# Frases y poses del brazo al senalar el cubo, segun su posicion.
FRASE_CUBO_CENTRO = "Es este, el del centro"
FRASE_CUBO_IZQUIERDA = "Es este, el de la izquierda"
FRASE_CUBO_DERECHA = "Es este, el de la derecha"
ANGULOS_BRAZO_SENALAR = {
    "RShoulderPitch": 0.0,
    "RShoulderRoll": -0.05,
    "RElbowYaw": 0.0,
    "RElbowRoll": 0.03,
    "RWristYaw": 0.0,
}
ANGULOS_BRAZO_SENALAR_IZQUIERDA = {
    "RShoulderPitch": 0.0,
    "RShoulderRoll": 0.3,
    "RElbowYaw": -1.0,
    "RElbowRoll": 0.03,
    "RWristYaw": 0.0,
}
ANGULOS_BRAZO_SENALAR_DERECHA = {
    "RShoulderPitch": 0.0,
    "RShoulderRoll": -0.3,
    "RElbowYaw": 0.0,
    "RElbowRoll": 0.03,
    "RWristYaw": 0.0,
}
ANGULOS_BRAZO_REPOSO = {
    "RShoulderPitch": 1.5497,
    "RShoulderRoll": -0.1334,
    "RElbowYaw": 1.1894,
    "RElbowRoll": 0.6317,
    "RWristYaw": -0.0323,
}


def _reproducir_alarma(ip, puerto):
    """Reproduce un sonido de alarma corto usando ALAudioPlayer."""
    try:
        audio_player = ALProxy("ALAudioPlayer", ip, puerto)
        sonido_id = audio_player.loadFile(
            "/opt/aldebaran/share/naoqi/wav/random_waiting.wav"
        )
        audio_player.play(sonido_id)
        time.sleep(DURACION_ALARMA_SEGUNDOS)
    except Exception as e:
        print("Aviso: no se pudo reproducir la alarma ({}).".format(e))


def _encender_luces(ip, puerto):
    """Enciende las luces LED de los ojos con un color llamativo."""
    try:
        leds = ALProxy("ALLeds", ip, puerto)
        leds.fadeRGB("FaceLeds", COLOR_LUCES_NOTIFICACION, 0.5)
    except Exception as e:
        print("Aviso: no se pudieron encender las luces ({}).".format(e))


def _apagar_luces(ip, puerto):
    """Regresa las luces de los ojos a su color normal (blanco)."""
    try:
        leds = ALProxy("ALLeds", ip, puerto)
        leds.fadeRGB("FaceLeds", 0xFFFFFF, 0.5)
    except Exception as e:
        print("Aviso: no se pudieron restaurar las luces ({}).".format(e))


def _caminar_hacia_frente(ip, puerto, distancia=DISTANCIA_CAMINATA_METROS):
    """Hace que el NAO camine en linea recta hacia el frente."""
    try:
        motion = ALProxy("ALMotion", ip, puerto)
        posture = ALProxy("ALRobotPosture", ip, puerto)

        motion.wakeUp()
        posture.goToPosture("StandInit", 0.5)
        motion.moveTo(distancia, 0.0, 0.0)
    except Exception as e:
        print("Aviso: no se pudo mover el robot ({}).".format(e))


def _girar_180(ip, puerto):
    """Hace que el NAO gire 180 grados sobre si mismo (a la izquierda)."""
    try:
        motion = ALProxy("ALMotion", ip, puerto)
        motion.moveTo(0.0, 0.0, 3.14159)
    except Exception as e:
        print("Aviso: no se pudo girar el robot ({}).".format(e))


def _mover_brazo(ip, puerto, angulos):
    """Lleva el brazo derecho a la pose dada (diccionario articulacion -> radianes)."""
    try:
        motion = ALProxy("ALMotion", ip, puerto)
        motion.setStiffnesses("RArm", 1.0)
        motion.angleInterpolationWithSpeed(list(angulos.keys()), list(angulos.values()), 0.3)
    except Exception as e:
        print("Aviso: no se pudo mover el brazo ({}).".format(e))


_GESTOS_SENALAR = {
    "centro": (ANGULOS_BRAZO_SENALAR, FRASE_CUBO_CENTRO),
    "izquierda": (ANGULOS_BRAZO_SENALAR_IZQUIERDA, FRASE_CUBO_IZQUIERDA),
    "derecha": (ANGULOS_BRAZO_SENALAR_DERECHA, FRASE_CUBO_DERECHA),
}


def _senalar_medicamento(ip, puerto, medicamentos, medicamento):
    """Levanta el brazo senalando el cubo del medicamento, en la
    direccion que corresponda (centro/izquierda/derecha), y lo anuncia."""
    posicion = posicion_cubo(medicamentos, medicamento)
    gesto = _GESTOS_SENALAR.get(posicion)
    if gesto:
        angulos, frase = gesto
        print("[NAO-MED] El cubo del {} esta a la/en el {}: senalando.".format(medicamento, posicion))
        _mover_brazo(ip, puerto, angulos)
        _decir(ip, puerto, frase)
        _mover_brazo(ip, puerto, ANGULOS_BRAZO_REPOSO)
    else:
        print("[NAO-MED] No se pudo determinar la posicion del cubo del {}.".format(medicamento))


def _decir(ip, puerto, texto):
    """Hace que el NAO diga 'texto' usando ALTextToSpeech."""
    try:
        tts = ALProxy("ALTextToSpeech", ip, puerto)
        tts.say(texto)
    except Exception as e:
        print("Aviso: no se pudo hablar ({}).".format(e))


def _decir_frase(ip, puerto, medicamento):
    """Dice la frase de notificacion del medicamento."""
    _decir(ip, puerto, "Te toca tu medicina, por favor tomate el {}".format(medicamento))


def notificar_medicamento(config, medicamento, diagnostico=False):
    """
    Ejecuta la secuencia completa de notificacion en el NAO:
    alarma -> luces -> cubos -> rostro -> caminar -> hablar.

    'config' es el dict retornado por robot_connector (ip, port, type).
    Con diagnostico=True el controlador imprime medidas de cada cubo y
    guarda fotogramas anotados en data/debug/ (solo simulador).

    Si es simulador (Webots), usa webots_controller.
    Si es robot real, usa NAOqi (ALProxy).
    """
    ip, puerto = config["ip"], config["port"]
    robot_type = config["type"]

    print("Notificando medicamento '{}' via {}...".format(medicamento, config['description']))

    if robot_type == "simulator":
        # Usar controlador de Webots
        _notificar_webots(medicamento, diagnostico)
    else:
        # Usar NAOqi para robot real
        _reproducir_alarma(ip, puerto)
        _encender_luces(ip, puerto)

        # Pipeline alternativo: no se agarra el cubo. Lo primero es
        # identificar que cubos hay en frente y decirlo.
        medicamentos = identificar_cubos(ip, puerto, diagnostico=diagnostico)
        if medicamentos:
            print("[NAO-MED] Cubos identificados: {}".format(", ".join(medicamentos)))
        else:
            print("[NAO-MED] No se identifico ningun cubo.")
        _decir(ip, puerto, frase_cubos(medicamentos))

        # La deteccion de rostro es la que activa el movimiento:
        # solo camina y notifica si ve a alguien frente al robot.
        hay_persona = reconocer_rostro(ip, puerto)
        if hay_persona:
            print("[NAO-MED] Persona detectada: el robot camina y notifica.")
            _caminar_hacia_frente(ip, puerto)
            _decir_frase(ip, puerto, medicamento)
            _decir(ip, puerto, FRASE_ROSTRO_DETECTADO)
            # Guiar a la persona hacia la mesa: girar y caminar un metro de regreso.
            _girar_180(ip, puerto)
            _caminar_hacia_frente(ip, puerto)
            # Ya de vuelta frente a la mesa: senalar el cubo correcto.
            _senalar_medicamento(ip, puerto, medicamentos, medicamento)
        else:
            print("[NAO-MED] No se detecto a nadie: el robot no camina.")
            _decir(ip, puerto, FRASE_ROSTRO_NO_DETECTADO)

        _apagar_luces(ip, puerto)

    print("Notificacion completada.")


def _notificar_webots(medicamento, diagnostico=False):
    """
    Comunica con el controlador de Webots para ejecutar la notificacion.
    
    El controlador de Webots corre dentro del simulador y recibe comandos
    via socket desde este proceso externo. Webots puede tardar varios
    segundos en abrir, cargar el mundo y arrancar el controlador, asi
    que reintentamos la conexion durante un rato antes de rendirnos.
    """
    intentos_conexion = 15
    espera_entre_intentos = 2  # segundos
    # La secuencia real en el controlador de Webots: ~2s de alarma + caminata
    # con el archivo Forwards50.motion (~6.8s por cada 0.5m, 2 ciclos para 1m
    # = ~13.6s). Total real ~15.6s; usamos ~25s (1.6x) de margen.
    timeout_respuesta = 25

    sock = None
    for intento in range(1, intentos_conexion + 1):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect(("127.0.0.1", 9000))
            break
        except Exception as e:
            sock = None
            if intento == 1:
                print("[WEBOTS] Esperando a que el controlador este listo...")
            if intento == intentos_conexion:
                print("Aviso: no se pudo conectar al controlador de Webots ({}).".format(e))
                print("Asegurate de que Webots este abierto con nao_med.wbt cargado.")
            else:
                time.sleep(espera_entre_intentos)

    if sock is None:
        return

    try:
        comando = "NOTIFICAR:{}|DIAG={}".format(medicamento, 1 if diagnostico else 0)
        sock.send(comando.encode("utf-8"))

        sock.settimeout(timeout_respuesta)
        respuesta = sock.recv(1024).decode("utf-8")
        print("[WEBOTS] Respuesta: {}".format(respuesta))
    except Exception as e:
        print("Aviso: no se recibio respuesta del controlador de Webots ({}).".format(e))
    finally:
        sock.close()
