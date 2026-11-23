# -*- coding: utf-8 -*-
"""
Reloj del NAO: lee la hora del sistema del robot (ALSystem) en vez de la
de la PC, para que el cronograma se dispare con el reloj interno del NAO.

Si el robot no responde, se usa el reloj de la PC para no detener el
monitor de medicacion.
"""
from datetime import datetime

try:
    from naoqi import ALProxy
except ImportError:
    from naoqi_mock import ALProxy

SERVICIO_RELOJ = "ALSystem"


# Retorna un datetime con la hora del NAO, o None si no se pudo leer.
def leer_hora_robot(ip, puerto):
    try:
        valores = ALProxy(SERVICIO_RELOJ, ip, puerto).date()
        anio, mes, dia, hora, minuto, segundo = [int(v) for v in valores[:6]]
        return datetime(anio, mes, dia, hora, minuto, segundo)
    except Exception as e:
        print("[WARN] No se pudo leer la hora del NAO ({}).".format(e))
        return None


def crear_reloj_robot(ip, puerto):
    """
    Retorna una funcion sin argumentos que devuelve la hora del NAO.
    Reutiliza el proxy ALSystem entre lecturas y, si una lectura falla,
    cae al reloj de la PC (avisando una sola vez) para que el monitor
    siga revisando el cronograma.
    """
    estado = {"proxy": None, "avisado": False}

    def _reloj():
        try:
            if estado["proxy"] is None:
                estado["proxy"] = ALProxy(SERVICIO_RELOJ, ip, puerto)
            valores = estado["proxy"].date()
            anio, mes, dia, hora, minuto, segundo = [int(v) for v in valores[:6]]
            return datetime(anio, mes, dia, hora, minuto, segundo)
        except Exception as e:
            estado["proxy"] = None
            if not estado["avisado"]:
                print("[WARN] No se pudo leer la hora del NAO ({});".format(e))
                print("       se usa la hora de la PC mientras tanto.")
                estado["avisado"] = True
            return datetime.now()

    return _reloj


if __name__ == "__main__":
    from robot_connector import NAO_IP, NAO_PORT

    print("PC : {}".format(datetime.now()))
    print("NAO: {}".format(leer_hora_robot(NAO_IP, NAO_PORT)))
