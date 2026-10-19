# -*- coding: utf-8 -*-
"""Identificacion de los cubos de medicina en el NAO real.

Pipeline alternativo: no se agarra el cubo. El robot barre la cabeza
(HeadPitch), mira por la camara inferior e identifica que cubos tiene
en frente por su estructura:

    paracetamol: mancha oscura pequena (el logo) rodeada de claro.
    ibuprofeno:  mancha oscura grande cuyo entorno es mayormente oscuro.
    clonacepam:  stickers azul muy saturado (el cubo de rubik).

La semilla es el cubo mismo, no el fondo, asi el piso blanco del
laboratorio no participa. Los umbrales se midieron sobre fotogramas de
la camara del NAO en Webots; en el robot real hay que recalibrarlos
corriendo el modo diagnostico y mirando las lineas [CUBO-DEBUG] y los
fotogramas de data/debug/.
"""
import os
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

# Diagnostico: aca se guardan fotogramas de la camara con los candidatos
# marcados, para afinar los umbrales con evidencia y no a ciegas.
RUTA_DEBUG = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "debug"
))

# Inclinaciones de la cabeza (radianes, HeadPitch: negativo = arriba,
# positivo = abajo; rango NAO -0.67 a 0.51).
INCLINACIONES_CABEZA = (0.0, 0.35, 0.5, -0.3, -0.6)
SEGUNDOS_POR_INCLINACION = 2.0
PAUSA_CABEZA_SEGUNDOS = 0.8

# Camara inferior: es la que ve la mesa con los cubos de cerca.
CAMARA_INFERIOR = 1
RESOLUCION_QVGA = 1
ESPACIO_BGR = 13
FPS_CAMARA = 10


def _cubos_en_frame(bgr, etiqueta_debug=None):
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
    # V~133 y el cuerpo negro V~70-90. En el NAO real pueden variar:
    # recalibrar con el modo diagnostico.
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


def identificar_cubos(ip, puerto, diagnostico=False):
    """Barre la cabeza, identifica los cubos en frente y devuelve los
    medicamentos vistos, ordenados de izquierda a derecha en la imagen.

    Con diagnostico=True imprime, por cada candidato, sus medidas y
    guarda un fotograma anotado en data/debug/ para afinar umbrales.
    """
    if not OPENCV_DISPONIBLE:
        print("[CUBO] OpenCV/numpy no disponibles: identificacion de cubos omitida.")
        return []

    try:
        video = ALProxy("ALVideoDevice", ip, puerto)
        suscripcion = video.subscribeCamera(
            "NaoMed_Cubos", CAMARA_INFERIOR, RESOLUCION_QVGA, ESPACIO_BGR, FPS_CAMARA
        )
    except Exception as e:
        print("Aviso: no se pudo abrir la camara ({}).".format(e))
        return []

    try:
        motion = ALProxy("ALMotion", ip, puerto)
        motion.setStiffnesses("Head", 1.0)
    except Exception as e:
        print("Aviso: no se pudo controlar la cabeza ({}).".format(e))
        motion = None

    vistos = {}
    try:
        for inclinacion in INCLINACIONES_CABEZA:
            if motion:
                try:
                    motion.setAngles("HeadPitch", inclinacion, 0.2)
                except Exception as e:
                    print("Aviso: no se pudo mover la cabeza ({}).".format(e))
                time.sleep(PAUSA_CABEZA_SEGUNDOS)
            inicio = time.time()
            por_medicamento = {}
            primer_frame = True
            while time.time() - inicio < SEGUNDOS_POR_INCLINACION:
                try:
                    frame = video.getImageRemote(suscripcion)
                    if frame:
                        ancho, alto, capas = frame[0], frame[1], frame[2]
                        bgr = np.frombuffer(bytes(frame[6]), dtype=np.uint8).reshape((alto, ancho, capas))
                        etiqueta = None
                        if diagnostico and primer_frame:
                            etiqueta = "pitch{:+.1f}".format(inclinacion)
                            primer_frame = False
                        for medicamento, cx in _cubos_en_frame(bgr, etiqueta):
                            por_medicamento.setdefault(medicamento, []).append(cx)
                except Exception as e:
                    print("Aviso: error en identificacion de cubos ({}).".format(e))
                    break
                time.sleep(0.1)
            for medicamento, xs in por_medicamento.items():
                if len(xs) >= 3 and medicamento not in vistos:
                    vistos[medicamento] = sum(xs) / float(len(xs))
    finally:
        try:
            video.unsubscribe(suscripcion)
        except Exception:
            pass
        if motion:
            try:
                motion.setAngles("HeadPitch", 0.0, 0.2)
            except Exception:
                pass

    ordenados = sorted(vistos.items(), key=lambda par: par[1])
    return [medicamento for medicamento, _ in ordenados]


def posicion_cubo(medicamentos, medicamento):
    """Posicion del cubo del medicamento dado (izquierda/centro/derecha),
    segun su orden de izquierda a derecha en la mesa.

    Solo se reconoce cuando se identificaron exactamente tres cubos (el
    acomodo habitual). Por ahora solo se actua sobre el caso "centro"; la
    senalizacion de izquierda y derecha queda pendiente.
    """
    if medicamento not in medicamentos or len(medicamentos) != 3:
        return None
    return ("izquierda", "centro", "derecha")[medicamentos.index(medicamento)]


def frase_cubos(medicamentos):
    """Frase hablada con los cubos identificados."""
    if not medicamentos:
        return "No veo ningun cubo"
    if len(medicamentos) == 1:
        return "Veo el cubo " + medicamentos[0]
    if len(medicamentos) == 2:
        return "Veo el cubo {} y el cubo {}".format(medicamentos[0], medicamentos[1])
    return "Veo el cubo {}, el cubo {} y el cubo {}".format(*medicamentos)
