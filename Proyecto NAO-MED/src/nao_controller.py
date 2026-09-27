# -*- coding: utf-8 -*-
"""
Controlador de acciones del NAO para NAO-Med.

Secuencia al detectar que es hora de un medicamento:
    1. Sonido de alarma (~2 segundos)
    2. Luces LED de los ojos encendidas
    3. Camina en linea recta hacia el frente (distancia fija, sin
       deteccion de persona todavia)
    4. Dice la frase de notificacion del medicamento

Nota: por ahora el robot no detecta a la persona, solo avanza una
distancia fija asumiendo que esta enfrente. La deteccion real de
rostro es un incremento de dificultad futuro.
"""
import time

from naoqi import ALProxy

# Distancia (en metros) que camina el NAO en linea recta hacia el frente
DISTANCIA_CAMINATA_METROS = 1.0

# Duracion de la alarma sonora, en segundos
DURACION_ALARMA_SEGUNDOS = 2

# Color de las luces de los ojos al notificar (RGB en hexadecimal)
COLOR_LUCES_NOTIFICACION = 0x00A2FF  # azul, para llamar la atencion


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


def _decir_frase(ip, puerto, medicamento):
    """Dice la frase de notificacion del medicamento."""
    try:
        tts = ALProxy("ALTextToSpeech", ip, puerto)
        tts.say("Te toca tu medicina, por favor tomate el {}".format(medicamento))
    except Exception as e:
        print("Aviso: no se pudo hablar ({}).".format(e))


def notificar_medicamento(config, medicamento):
    """
    Ejecuta la secuencia completa de notificacion en el NAO:
    alarma -> luces -> caminar -> hablar.

    'config' es el dict retornado por robot_connector (ip, port, type).
    """
    ip, puerto = config["ip"], config["port"]

    print("Notificando medicamento '{}' via {}...".format(medicamento, config['description']))

    _reproducir_alarma(ip, puerto)
    _encender_luces(ip, puerto)
    _caminar_hacia_frente(ip, puerto)
    _decir_frase(ip, puerto, medicamento)
    _apagar_luces(ip, puerto)

    print("Notificacion completada.")
