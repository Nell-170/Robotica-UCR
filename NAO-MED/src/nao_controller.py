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
import math
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
# Desplazamiento lateral para alinearse con el cubo izquierdo/derecho.
DISTANCIA_PASO_LATERAL_METROS = 0.10
TOLERANCIA_GIRO_RADIANES = math.radians(3.0)
INTENTOS_CORRECCION_GIRO = 3
AJUSTE_RUMBO_REGRESO_RADIANES = math.radians(45.0)

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
# El brazo entero se levanta y se estira (pitch bien negativo = por
# encima de la horizontal, codo casi sin doblar) para que se vea como
# un senalamiento claro con todo el brazo, no solo la mano.
ANGULOS_BRAZO_SENALAR = {
    "RShoulderPitch": -0.5,
    "RShoulderRoll": -0.05,
    "RElbowYaw": 0.0,
    "RElbowRoll": 0.05,
    "RWristYaw": 0.0,
}
ANGULOS_BRAZO_SENALAR_IZQUIERDA = {
    "RShoulderPitch": -0.5,
    "RShoulderRoll": 0.3,
    "RElbowYaw": -1.0,
    "RElbowRoll": 0.05,
    "RWristYaw": 0.0,
}
ANGULOS_BRAZO_SENALAR_DERECHA = {
    "RShoulderPitch": -0.5,
    "RShoulderRoll": -0.3,
    "RElbowYaw": 0.0,
    "RElbowRoll": 0.05,
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


def _leer_rumbos(motion):
    """Lee la pose de ALMotion basada en sensores y en comandos."""
    try:
        pose_sensores = [float(valor) for valor in motion.getRobotPosition(True)]
        pose_comandos = [float(valor) for valor in motion.getRobotPosition(False)]
        rumbo_sensores = pose_sensores[2]
        rumbo_comandos = pose_comandos[2]
        diferencia = (rumbo_sensores - rumbo_comandos + math.pi) % (2.0 * math.pi) - math.pi
        print("[ODOMETRIA] sensores=True pose={} rumbo={:.1f} grados".format(
            ["{:.3f}".format(valor) for valor in pose_sensores],
            math.degrees(rumbo_sensores)))
        print("[ODOMETRIA] sensores=False pose={} rumbo={:.1f} grados".format(
            ["{:.3f}".format(valor) for valor in pose_comandos],
            math.degrees(rumbo_comandos)))
        print("[ODOMETRIA] Diferencia angular True-False: {:.1f} grados".format(
            math.degrees(diferencia)))
        return rumbo_sensores
    except Exception as e:
        print("Aviso: no se pudieron leer/comparar las poses de ALMotion ({}).".format(e))
        return None


def _leer_rumbo(ip, puerto):
    """Lee el rumbo del robot y registra ambas fuentes de ALMotion."""
    try:
        return _leer_rumbos(ALProxy("ALMotion", ip, puerto))
    except Exception as e:
        print("Aviso: no se pudo crear ALMotion para leer la odometria ({}).".format(e))
        return None


def _diferencia_angular(angulo_objetivo, angulo_actual):
    """Diferencia angular firmada mas corta, en el rango [-pi, pi]."""
    return (angulo_objetivo - angulo_actual + math.pi) % (2.0 * math.pi) - math.pi


def _girar_grados(ip, puerto, grados):
    """Solicita solo un giro relativo en grados, sin consultar la odometria."""
    try:
        motion = ALProxy("ALMotion", ip, puerto)
        angulo = math.radians(float(grados))
        print("[NAO-MED] Giro relativo solicitado: {:.1f} grados.".format(grados))
        motion.moveTo(0.0, 0.0, angulo)
        return True
    except Exception as e:
        print("Aviso: no se pudo ejecutar el giro relativo ({}).".format(e))
        return False


def _girar_hacia_rumbo(ip, puerto, rumbo_objetivo, sentido=None):
    """Alcanza un rumbo usando un sentido fijo y corrigiendo con la odometria."""
    try:
        motion = ALProxy("ALMotion", ip, puerto)
        rumbo_inicial = _leer_rumbos(motion)
        if rumbo_inicial is None:
            return False
        rumbo_objetivo = float(rumbo_objetivo) % (2.0 * math.pi)
        error_inicial = _diferencia_angular(rumbo_objetivo, rumbo_inicial)
        if sentido is None:
            sentido = 1 if error_inicial > 0.0 else -1
        elif sentido not in (-1, 1):
            print("Aviso: sentido de giro invalido: {}.".format(sentido))
            return False
        distancia = ((rumbo_objetivo - rumbo_inicial) % (2.0 * math.pi)
                     if sentido > 0 else
                     -((rumbo_inicial - rumbo_objetivo) % (2.0 * math.pi)))
        print("[NAO-MED] Giro por odometria: inicio {:.1f}, objetivo {:.1f}, "
              "comando inicial {:.1f} grados (sentido {}).".format(
                  rumbo_inicial, rumbo_objetivo, math.degrees(distancia),
                  "positivo" if sentido > 0 else "negativo"))

        restante = distancia
        rumbo_anterior = rumbo_inicial
        max_tramos = INTENTOS_CORRECCION_GIRO + 4
        for intento in range(max_tramos + 1):
            if abs(restante) <= TOLERANCIA_GIRO_RADIANES:
                print("[NAO-MED] Rumbo alcanzado en el sentido solicitado.")
                return True
            if sentido * restante < -TOLERANCIA_GIRO_RADIANES:
                print("[NAO-MED] Se sobrepaso el objetivo; se detiene para no invertir el giro.")
                return False
            if intento == max_tramos:
                break
            tramo = sentido * min(abs(restante), math.radians(90.0))
            print("[NAO-MED] Giro/correccion {}: comando {:.1f} grados.".format(
                intento + 1, math.degrees(tramo)))
            motion.moveTo(0.0, 0.0, tramo)
            rumbo_actual = _leer_rumbos(motion)
            if rumbo_actual is None:
                return False
            avance = _diferencia_angular(rumbo_actual, rumbo_anterior)
            if sentido * avance < -TOLERANCIA_GIRO_RADIANES:
                print("[NAO-MED] La odometria indica movimiento en sentido contrario; "
                      "se detiene la correccion.")
                return False
            restante -= avance
            rumbo_anterior = rumbo_actual

        print("[NAO-MED] Giro no completado en el sentido solicitado; "
              "restan {:.1f} grados.".format(math.degrees(restante)))
        return False
    except Exception as e:
        print("Aviso: no se pudo completar/verificar el giro por odometria ({}).".format(e))
        return False


def _caminar_lateral(ip, puerto, izquierda, distancia=DISTANCIA_PASO_LATERAL_METROS):
    """Paso lateral del NAO (y positivo = izquierda del robot) para
    alinearse con el cubo; el robot queda mirando hacia la mesa."""
    lado = "izquierda" if izquierda else "derecha"
    print("[NAO-MED] Caminando {} metros hacia la {}...".format(distancia, lado))
    try:
        motion = ALProxy("ALMotion", ip, puerto)
        motion.moveTo(0.0, distancia if izquierda else -distancia, 0.0)
    except Exception as e:
        print("Aviso: no se pudo dar el paso lateral ({}).".format(e))


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


def _senalar_medicamento(ip, puerto, medicamentos, medicamento, alineado=False):
    """Levanta el brazo senalando el cubo del medicamento y lo anuncia.
    Con alineado=True el robot ya se coloco frente al cubo, asi que el
    brazo apunta al frente en vez de hacia un lado."""
    posicion = posicion_cubo(medicamentos, medicamento)
    gesto = _GESTOS_SENALAR.get(posicion)
    if gesto:
        angulos, frase = gesto
        if alineado:
            angulos = ANGULOS_BRAZO_SENALAR
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

        # Guardar el rumbo de la mesa y fijar el sentido de giro hacia la persona.
        rumbo_mesa = _leer_rumbo(ip, puerto)
        if rumbo_mesa is None:
            print("[NAO-MED] Se cancela la busqueda de rostro porque no se pudo leer el rumbo.")
            _apagar_luces(ip, puerto)
            return
        rumbo_persona = rumbo_mesa + math.pi
        error_hacia_persona = _diferencia_angular(rumbo_persona, rumbo_mesa)
        sentido_giro = 1 if error_hacia_persona > 0.0 else -1
        if not _girar_hacia_rumbo(ip, puerto, rumbo_persona, sentido_giro):
            print("[NAO-MED] Se cancela la busqueda de rostro porque el giro no se verifico.")
            _apagar_luces(ip, puerto)
            return

        # La deteccion de rostro es la que activa el movimiento:
        # solo camina y notifica si ve a alguien frente al robot.
        hay_persona = reconocer_rostro(ip, puerto)
        if hay_persona:
            print("[NAO-MED] Persona detectada: el robot camina y notifica.")
            _caminar_hacia_frente(ip, puerto)
            _decir_frase(ip, puerto, medicamento)
            _decir(ip, puerto, FRASE_ROSTRO_DETECTADO)
            # Sesgo empirico a la izquierda para compensar el desvio observado
            # a la derecha al regresar a la mesa.
            rumbo_regreso = rumbo_mesa + AJUSTE_RUMBO_REGRESO_RADIANES
            if _girar_hacia_rumbo(ip, puerto, rumbo_regreso, sentido_giro):
                time.sleep(3)
                _girar_hacia_rumbo(ip, puerto, rumbo_mesa, sentido_giro)
                time.sleep(3)
                _girar_grados(ip, puerto, -6)
                _caminar_hacia_frente(ip, puerto)
                # Pausa larga para que el robot termine de caminar y asentarse
                # antes de senalar: sin esto, el gesto y la frase ocurren
                # encimados con el final de la caminata.
                time.sleep(7)
                # Alinearse con el cubo: 25 cm a un lado (el del centro no se mueve).
                posicion = posicion_cubo(medicamentos, medicamento)
                if posicion == "izquierda":
                    _caminar_lateral(ip, puerto, True)
                elif posicion == "derecha":
                    _caminar_lateral(ip, puerto, False)
                time.sleep(2)
                _senalar_medicamento(ip, puerto, medicamentos, medicamento, alineado=True)
            else:
                print("[NAO-MED] No se camina hacia la mesa: el giro de regreso no se verifico.")
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
