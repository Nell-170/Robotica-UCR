# -*- coding: utf-8 -*-
"""Identificacion de los cubos de medicina en el NAO real.

Pipeline alternativo: no se agarra el cubo. El robot mira con sus DOS
camaras a la vez (la superior ve lo lejano, la inferior lo cercano),
barre la cabeza en horizontal (HeadYaw) e identifica que cubos tiene en
frente por su estructura:

    paracetamol: mancha oscura pequena (el logo) rodeada de claro.
    ibuprofeno:  mancha oscura grande cuyo entorno es mayormente oscuro.
    clonacepam:  stickers azul muy saturado (el cubo de rubik).

La semilla es el cubo mismo, no el fondo, asi el piso blanco del
laboratorio no participa. Los umbrales se midieron sobre fotogramas de
la camara del NAO en Webots; en el robot real hay que recalibrarlos
corriendo el modo diagnostico y mirando las lineas [CUBO-DEBUG] y los
fotogramas de data/debug/.

Como la cabeza gira, la x en pixeles de un cubo cambia de un fotograma
a otro. Por eso cada deteccion se convierte a un angulo respecto al
robot (azimut) y los cubos se ordenan por ese angulo, no por pixeles.
"""
import math
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

# Barrido horizontal de la cabeza (radianes, HeadYaw: positivo = izquierda
# del robot; rango NAO -2.08 a 2.08). Con ~56 grados de campo horizontal
# por camara, +-0.5 rad cubre unos 115 grados frente al robot.
GIROS_CABEZA = (0.5, 0.0, -0.5)
# Giros para seguir un cubo mientras se camina hacia el: primero al
# frente, que es donde deberia estar, y solo si no esta, a los lados.
GIROS_SEGUIMIENTO = (0.0, 0.5, -0.5)
# Inclinacion fija (HeadPitch): con las dos camaras ya no hace falta el
# barrido vertical; la superior cubre el horizonte y la inferior el piso
# cercano.
INCLINACION_CABEZA = 0.0
PASADAS_BARRIDO = 2
SEGUNDOS_POR_POSICION = 2.0
PAUSA_CABEZA_SEGUNDOS = 0.8
# Detecciones minimas de un medicamento para darlo por visto.
DETECCIONES_MINIMAS = 3

# Camaras del NAO (indices de ALVideoDevice).
CAMARA_SUPERIOR = 0
CAMARA_INFERIOR = 1
CAMARAS = (CAMARA_SUPERIOR, CAMARA_INFERIOR)
NOMBRE_CAMARA = {CAMARA_SUPERIOR: "sup", CAMARA_INFERIOR: "inf"}
# Cadena de ALMotion de cada camara, para leer su orientacion real.
CADENA_CAMARA = {CAMARA_SUPERIOR: "CameraTop", CAMARA_INFERIOR: "CameraBottom"}
# Inclinacion de montaje de cada camara respecto a la cabeza (grados,
# positivo = hacia abajo). Solo se usa si ALMotion no da la orientacion.
INCLINACION_MONTAJE_GRADOS = {CAMARA_SUPERIOR: 1.2, CAMARA_INFERIOR: 39.7}

# Resolucion: 1 = QVGA (320x240), 2 = VGA (640x480). Los umbrales de
# tamano estan medidos en QVGA y se escalan solos con el ancho del
# fotograma, asi que basta con cambiar esta constante.
RESOLUCION = 1
ESPACIO_BGR = 13
FPS_CAMARA = 10

# Campo de vision de las camaras del NAO V6 (OV5640), en grados.
FOV_HORIZONTAL_GRADOS = 56.3
FOV_VERTICAL_GRADOS = 43.7

# En la camara superior se descartan candidatos que queden por encima de
# este angulo bajo el horizonte (grados): los cubos estan en el piso, lo
# que se ve arriba del horizonte (paredes, muebles, gente) no es un cubo.
MARGEN_HORIZONTE_GRADOS = 0.0

# Espacio de coordenadas FRAME_ROBOT de ALMotion.
FRAME_ROBOT = 2


def _cubos_en_frame(bgr, etiqueta_debug=None, y_minimo=0):
    """Clasifica los cubos del frame por su estructura, no por el fondo.

    La semilla es una mancha oscura compacta (el logo del cubo blanco,
    el cuerpo del cubo negro) o azul (los stickers del rubik). Cada
    semilla se clasifica por lo que hay en su entorno inmediato, asi el
    color del fondo (puerta blanca, piso claro) no participa.

    Los candidatos cuyo centro queda por encima de la fila 'y_minimo'
    se descartan (filtro de horizonte de la camara superior).

    Devuelve [(medicamento, cx), ...] ordenado por cx.
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, w = hsv.shape[:2]
    # Los umbrales de tamano se midieron en QVGA (320 px de ancho).
    escala = w / 320.0
    escala_area = escala * escala
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

    lado_nucleo = max(3, int(round(3 * escala)) | 1)
    nucleo = np.ones((lado_nucleo, lado_nucleo), np.uint8)
    hallados = {}  # medicamento -> x del hallazgo mas a la izquierda
    anotada = bgr.copy() if etiqueta_debug else None
    if anotada is not None and y_minimo > 0:
        # Linea del horizonte: lo que queda arriba se descarta.
        cv2.line(anotada, (0, int(y_minimo)), (w - 1, int(y_minimo)), (255, 0, 255), 1)

    def _entorno(x, y, ancho, alto):
        """Recuadro de la mancha con un margen de 2 pixeles (en QVGA)."""
        m = int(round(2 * escala))
        return (max(x - m, 0), max(y - m, 0),
                min(x + ancho + m, w), min(y + alto + m, h))

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
        if area < 8 * escala_area or area > 700 * escala_area or ancho > w * 0.5 or alto > h * 0.5:
            continue
        if not 0.5 < ancho / float(alto) < 2.0:
            continue
        cy = y + alto / 2.0
        if cy > 0.85 * h or cy < y_minimo:
            continue
        x0, y0, x1, y1 = _entorno(x, y, ancho, alto)
        trozo = np.s_[y0:y1, x0:x1]
        clara_ent = clara[trozo].mean()
        oscura_ent = oscura[trozo].mean()
        azul_ent = azul[trozo].mean()
        medicamento = None
        if (area <= 130 * escala_area and ancho <= 18 * escala and alto <= 18 * escala
                and clara_ent >= 0.25 and azul_ent < 0.12):
            medicamento = "paracetamol"
        elif area > 200 * escala_area and oscura_ent >= 0.40 and azul_ent < 0.12:
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
        if area < 8 * escala_area or ancho > 40 * escala or alto > 40 * escala:
            continue
        # Proporcion relajada: los stickers pueden verse como una fila
        # (19x5 en la imagen real). La banda del piso queda excluida por
        # el tope de ancho de arriba.
        if not 0.25 < ancho / float(alto) < 4.0:
            continue
        cy = y + alto / 2.0
        if cy > 0.85 * h or cy < y_minimo:
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


# ---------------------------------------------------------------------------
# Geometria: de pixeles a angulos respecto al robot
# ---------------------------------------------------------------------------

def _distancia_focal(lado_pixeles, fov_grados):
    """Distancia focal en pixeles para un lado de imagen y su campo de vision."""
    return (lado_pixeles / 2.0) / math.tan(math.radians(fov_grados) / 2.0)


def _azimut_pixel(cx, ancho, yaw_camara):
    """Angulo horizontal (rad) del pixel respecto al frente del robot.

    Positivo = a la izquierda del robot, igual que HeadYaw. Un pixel a la
    izquierda del centro de la imagen esta mas a la izquierda del robot.
    """
    f = _distancia_focal(ancho, FOV_HORIZONTAL_GRADOS)
    return yaw_camara + math.atan((ancho / 2.0 - cx) / f)


def _fila_horizonte(alto, pitch_camara, margen_grados=MARGEN_HORIZONTE_GRADOS):
    """Fila de la imagen que esta 'margen_grados' bajo el horizonte.

    pitch_camara: inclinacion del eje optico (rad, positivo = abajo).
    Las filas por encima de la devuelta miran por encima del horizonte
    (o del margen). Se limita al rango [0, alto].
    """
    f = _distancia_focal(alto, FOV_VERTICAL_GRADOS)
    # Angulo bajo el eje optico que corresponde al margen pedido.
    angulo = math.radians(margen_grados) - pitch_camara
    # Si el horizonte cae muy por fuera del campo de vision, tan() se va
    # al infinito; se acota antes.
    limite = math.radians(89.0)
    angulo = max(-limite, min(limite, angulo))
    fila = alto / 2.0 + f * math.tan(angulo)
    return max(0.0, min(float(alto), fila))


def _orientacion_camara(motion, camara):
    """(yaw, pitch) en radianes del eje optico de la camara respecto al
    robot, con los sensores reales. Pitch positivo = hacia abajo.

    Primero se pide a ALMotion la posicion de la camara en FRAME_ROBOT
    (incluye la inclinacion del torso); si falla, se aproxima con los
    angulos de la cabeza mas la inclinacion de montaje de la camara.
    """
    if motion is None:
        return 0.0, math.radians(INCLINACION_MONTAJE_GRADOS[camara]) + INCLINACION_CABEZA
    try:
        posicion = motion.getPosition(CADENA_CAMARA[camara], FRAME_ROBOT, True)
        return float(posicion[5]), float(posicion[4])
    except Exception:
        pass
    try:
        yaw, pitch = motion.getAngles(["HeadYaw", "HeadPitch"], True)
    except Exception:
        yaw, pitch = 0.0, INCLINACION_CABEZA
    return float(yaw), float(pitch) + math.radians(INCLINACION_MONTAJE_GRADOS[camara])


# ---------------------------------------------------------------------------
# Camaras: suscripcion a las dos a la vez
# ---------------------------------------------------------------------------

def _abrir_camaras(video):
    """Se suscribe a las dos camaras.

    Primero intenta una sola suscripcion multi-camara (subscribeCameras /
    getImagesRemote); si la version de NAOqi no la soporta, abre dos
    suscripciones separadas. Devuelve (modo, suscripciones), con modo
    "multi" o "separadas", o (None, []) si no se pudo abrir ninguna.
    """
    n = len(CAMARAS)
    try:
        suscripcion = video.subscribeCameras(
            "NaoMed_Cubos", list(CAMARAS), [RESOLUCION] * n, [ESPACIO_BGR] * n, FPS_CAMARA)
        if suscripcion:
            return "multi", [suscripcion]
    except Exception as e:
        print("[CUBO] subscribeCameras no disponible ({}); se usan dos suscripciones.".format(e))

    suscripciones = []
    for camara in CAMARAS:
        try:
            suscripciones.append(video.subscribeCamera(
                "NaoMed_Cubos_{}".format(NOMBRE_CAMARA[camara]),
                camara, RESOLUCION, ESPACIO_BGR, FPS_CAMARA))
        except Exception as e:
            print("Aviso: no se pudo abrir la camara {} ({}).".format(NOMBRE_CAMARA[camara], e))
            suscripciones.append(None)
    if not any(suscripciones):
        return None, []
    return "separadas", suscripciones


def _cerrar_camaras(video, suscripciones):
    for suscripcion in suscripciones:
        if suscripcion:
            try:
                video.unsubscribe(suscripcion)
            except Exception:
                pass


def _imagen_a_bgr(imagen):
    """Convierte una imagen de ALVideoDevice (lista NAOqi) a arreglo BGR."""
    if not imagen:
        return None
    ancho, alto, capas = imagen[0], imagen[1], imagen[2]
    return np.frombuffer(bytes(imagen[6]), dtype=np.uint8).reshape((alto, ancho, capas))


def _leer_frames(video, modo, suscripciones):
    """Devuelve [(camara, bgr), ...] con el fotograma actual de cada camara."""
    frames = []
    if modo == "multi":
        imagenes = video.getImagesRemote(suscripciones[0]) or []
        for camara, imagen in zip(CAMARAS, imagenes):
            bgr = _imagen_a_bgr(imagen)
            if bgr is not None:
                frames.append((camara, bgr))
    else:
        for camara, suscripcion in zip(CAMARAS, suscripciones):
            if not suscripcion:
                continue
            bgr = _imagen_a_bgr(video.getImageRemote(suscripcion))
            if bgr is not None:
                frames.append((camara, bgr))
    return frames


# ---------------------------------------------------------------------------
# Identificacion
# ---------------------------------------------------------------------------

def _todos_vistos(vistos):
    """True si ya hay tres medicamentos con suficientes detecciones."""
    return sum(1 for angulos in vistos.values() if len(angulos) >= DETECCIONES_MINIMAS) >= 3


def _barrer(ip, puerto, giros, pasadas, terminado, diagnostico=False, prefijo_debug="",
            en_pixeles=False):
    """Mira con las dos camaras en cada giro de cabeza y acumula detecciones.

    giros:     posiciones de HeadYaw (rad) a recorrer, en orden.
    pasadas:   cuantas veces se recorre la lista de giros.
    terminado: funcion(vistos) -> bool; si devuelve True se deja de barrer.

    Devuelve {medicamento: [azimut (rad), ...]}, con el azimut respecto al
    frente del robot (positivo = izquierda). Con en_pixeles=True devuelve
    en cambio el desfase horizontal del cubo respecto al centro de la
    imagen, en pixeles de QVGA (positivo = a la derecha). Al terminar, la
    cabeza vuelve al frente.
    """
    if not OPENCV_DISPONIBLE:
        print("[CUBO] OpenCV/numpy no disponibles: identificacion de cubos omitida.")
        return {}

    try:
        video = ALProxy("ALVideoDevice", ip, puerto)
    except Exception as e:
        print("Aviso: no se pudo abrir ALVideoDevice ({}).".format(e))
        return {}
    modo, suscripciones = _abrir_camaras(video)
    if modo is None:
        return {}

    try:
        motion = ALProxy("ALMotion", ip, puerto)
        motion.setStiffnesses("Head", 1.0)
    except Exception as e:
        print("Aviso: no se pudo controlar la cabeza ({}).".format(e))
        motion = None

    vistos = {}  # medicamento -> [azimut (rad), ...]
    try:
        for pasada in range(1, pasadas + 1):
            for giro in giros:
                if motion:
                    try:
                        motion.setAngles(["HeadYaw", "HeadPitch"], [giro, INCLINACION_CABEZA], 0.2)
                    except Exception as e:
                        print("Aviso: no se pudo mover la cabeza ({}).".format(e))
                    time.sleep(PAUSA_CABEZA_SEGUNDOS)
                # La cabeza esta quieta durante la captura: se mide su
                # orientacion real una vez por posicion.
                orientacion = dict((camara, _orientacion_camara(motion, camara)) for camara in CAMARAS)
                inicio = time.time()
                por_medicamento = {}
                pendientes_debug = set(CAMARAS) if diagnostico else set()
                while time.time() - inicio < SEGUNDOS_POR_POSICION:
                    try:
                        frames = _leer_frames(video, modo, suscripciones)
                    except Exception as e:
                        print("Aviso: error en identificacion de cubos ({}).".format(e))
                        break
                    for camara, bgr in frames:
                        alto, ancho = bgr.shape[:2]
                        yaw_cam, pitch_cam = orientacion[camara]
                        y_minimo = 0
                        if camara == CAMARA_SUPERIOR:
                            y_minimo = _fila_horizonte(alto, pitch_cam)
                        etiqueta = None
                        if camara in pendientes_debug:
                            etiqueta = "{}{}-yaw{:+.1f}-barrido{}".format(
                                prefijo_debug, NOMBRE_CAMARA[camara], giro, pasada)
                            pendientes_debug.discard(camara)
                        for medicamento, cx in _cubos_en_frame(bgr, etiqueta, y_minimo):
                            if en_pixeles:
                                valor = (cx - ancho / 2.0) * 320.0 / ancho
                            else:
                                valor = _azimut_pixel(cx, ancho, yaw_cam)
                            por_medicamento.setdefault(medicamento, []).append(valor)
                    # Con lo acumulado hasta ahora puede que ya alcance.
                    parcial = dict((m, vistos.get(m, []) + a) for m, a in por_medicamento.items())
                    if terminado(dict(vistos, **parcial)):
                        break
                    time.sleep(0.1)
                for medicamento, angulos in por_medicamento.items():
                    vistos.setdefault(medicamento, []).extend(angulos)
                if diagnostico:
                    resumen = ", ".join(
                        "{}={} ({:+.0f} {})".format(
                            medicamento, len(angulos),
                            (sum(angulos) / len(angulos)) if en_pixeles
                            else math.degrees(sum(angulos) / len(angulos)),
                            "px" if en_pixeles else "grados")
                        for medicamento, angulos in sorted(por_medicamento.items())
                    ) or "ninguno"
                    print("[CUBO-DEBUG] {}barrido {} yaw{:+.1f} detecciones: {}".format(
                        prefijo_debug, pasada, giro, resumen))
                if terminado(vistos):
                    return vistos
    finally:
        _cerrar_camaras(video, suscripciones)
        if motion:
            try:
                motion.setAngles(["HeadYaw", "HeadPitch"], [0.0, 0.0], 0.2)
            except Exception:
                pass
    return vistos


def identificar_cubos(ip, puerto, diagnostico=False, prefijo_debug=""):
    """Mira con las dos camaras, barre la cabeza en horizontal, identifica
    los cubos en frente y devuelve los medicamentos vistos, ordenados de
    izquierda a derecha respecto al robot.

    Se detiene en cuanto ve los tres cubos. Con diagnostico=True imprime,
    por cada candidato, sus medidas y guarda un fotograma anotado por
    camara y posicion en data/debug/ para afinar umbrales. prefijo_debug
    permite separar las capturas de distintas condiciones.
    """
    vistos = _barrer(ip, puerto, GIROS_CABEZA, PASADAS_BARRIDO, _todos_vistos,
                     diagnostico, prefijo_debug)

    # Orden de izquierda a derecha = azimut de mayor a menor.
    ordenados = sorted(
        ((medicamento, sum(angulos) / float(len(angulos)))
         for medicamento, angulos in vistos.items() if len(angulos) >= DETECCIONES_MINIMAS),
        key=lambda par: par[1],
        reverse=True
    )
    if diagnostico:
        print("[CUBO-DEBUG] Resultado: {}".format(", ".join(
            "{} ({:+.0f} grados)".format(m, math.degrees(a)) for m, a in ordenados) or "ninguno"))
    return [medicamento for medicamento, _ in ordenados]


def azimut_cubo(ip, puerto, medicamento, diagnostico=False, prefijo_debug="seguimiento-"):
    """Angulo (rad) del cubo del medicamento respecto al frente del robot,
    positivo = a la izquierda, o None si no se vio.

    Pensado para corregir el rumbo mientras el robot camina hacia la mesa:
    mira primero al frente (donde deberia estar el cubo) y solo gira la
    cabeza a los lados si no lo encuentra. Termina en cuanto lo ve.
    """
    medicamento = medicamento.lower()

    def _visto(vistos):
        return len(vistos.get(medicamento, [])) >= DETECCIONES_MINIMAS

    vistos = _barrer(ip, puerto, GIROS_SEGUIMIENTO, 1, _visto, diagnostico, prefijo_debug)
    angulos = vistos.get(medicamento, [])
    if len(angulos) < DETECCIONES_MINIMAS:
        return None
    return sum(angulos) / float(len(angulos))


def desfase_pixeles_cubo(ip, puerto, medicamento, diagnostico=False, prefijo_debug="final-"):
    """Desfase horizontal (pixeles de QVGA) del cubo respecto al centro de
    la imagen, con la cabeza mirando al frente; positivo = a la derecha.
    None si no se ve al frente.

    Sirve para el ajuste fino final: centrar el cubo en la imagen no
    depende de que el campo de vision supuesto sea exacto.
    """
    medicamento = medicamento.lower()

    def _visto(vistos):
        return len(vistos.get(medicamento, [])) >= DETECCIONES_MINIMAS

    vistos = _barrer(ip, puerto, (0.0,), 1, _visto, diagnostico, prefijo_debug, en_pixeles=True)
    desfases = vistos.get(medicamento, [])
    if len(desfases) < DETECCIONES_MINIMAS:
        return None
    return sum(desfases) / float(len(desfases))


def posicion_cubo(medicamentos, medicamento):
    """Posicion del cubo del medicamento dado (izquierda/centro/derecha),
    segun su orden de izquierda a derecha en la mesa.

    Solo se determina cuando se identificaron exactamente tres cubos (el
    acomodo habitual); el controlador usa esta posicion para alinearse con
    los cubos de izquierda y derecha mediante un paso lateral.

    La comparacion no distingue mayusculas/minusculas: el cronograma
    guarda el medicamento como "Paracetamol" pero la identificacion del
    cubo siempre devuelve nombres en minuscula.
    """
    medicamentos_normalizados = [m.lower() for m in medicamentos]
    medicamento = medicamento.lower()
    if medicamento not in medicamentos_normalizados or len(medicamentos_normalizados) != 3:
        return None
    return ("izquierda", "centro", "derecha")[medicamentos_normalizados.index(medicamento)]


def frase_cubos(medicamentos):
    """Frase hablada con los cubos identificados."""
    if not medicamentos:
        return "No veo ningun cubo"
    if len(medicamentos) == 1:
        return "Veo el cubo " + medicamentos[0]
    if len(medicamentos) == 2:
        return "Veo el cubo {} y el cubo {}".format(medicamentos[0], medicamentos[1])
    return "Veo el cubo {}, el cubo {} y el cubo {}".format(*medicamentos)
