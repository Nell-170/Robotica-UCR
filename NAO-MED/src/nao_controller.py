# -*- coding: utf-8 -*-
"""
Controlador de acciones del NAO para NAO-Med.

Secuencia al detectar que es hora de un medicamento:
    1. Sonido de alarma (~2 segundos)
    2. Luces LED de los ojos encendidas
    3. Reconocimiento de rostro: espera a ver a alguien frente al robot
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

# Distancia (en metros) que camina el NAO en linea recta hacia el frente
DISTANCIA_CAMINATA_METROS = 1.0

# Duracion de la alarma sonora, en segundos
DURACION_ALARMA_SEGUNDOS = 2

# Color de las luces de los ojos al notificar (RGB en hexadecimal)
COLOR_LUCES_NOTIFICACION = 0x00A2FF  # azul, para llamar la atencion

# Frases que dice el NAO segun el resultado de la deteccion de rostro
FRASE_ROSTRO_DETECTADO = "Te veo, que tengas un buen dia."
FRASE_ROSTRO_NO_DETECTADO = "No veo a nadie, por favor acercate."


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


def notificar_medicamento(config, medicamento):
    """
    Ejecuta la secuencia completa de notificacion en el NAO:
    alarma -> luces -> caminar -> hablar.

    'config' es el dict retornado por robot_connector (ip, port, type).
    
    Si es simulador (Webots), usa webots_controller.
    Si es robot real, usa NAOqi (ALProxy).
    """
    ip, puerto = config["ip"], config["port"]
    robot_type = config["type"]

    print("Notificando medicamento '{}' via {}...".format(medicamento, config['description']))

    if robot_type == "simulator":
        # Usar controlador de Webots
        _notificar_webots(medicamento)
    else:
        # Usar NAOqi para robot real
        _reproducir_alarma(ip, puerto)
        _encender_luces(ip, puerto)

        # La deteccion de rostro es la que activa el movimiento:
        # solo camina y notifica si ve a alguien frente al robot.
        hay_persona = reconocer_rostro(ip, puerto)
        if hay_persona:
            print("[NAO-MED] Persona detectada: el robot camina y notifica.")
            _caminar_hacia_frente(ip, puerto)
            _decir_frase(ip, puerto, medicamento)
            _decir(ip, puerto, FRASE_ROSTRO_DETECTADO)
        else:
            print("[NAO-MED] No se detecto a nadie: el robot no camina.")
            _decir(ip, puerto, FRASE_ROSTRO_NO_DETECTADO)

        _apagar_luces(ip, puerto)

    print("Notificacion completada.")


def _notificar_webots(medicamento):
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
        comando = "NOTIFICAR:{}".format(medicamento)
        sock.send(comando.encode("utf-8"))

        sock.settimeout(timeout_respuesta)
        respuesta = sock.recv(1024).decode("utf-8")
        print("[WEBOTS] Respuesta: {}".format(respuesta))
    except Exception as e:
        print("Aviso: no se recibio respuesta del controlador de Webots ({}).".format(e))
    finally:
        sock.close()
