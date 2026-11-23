# -*- coding: utf-8 -*-
"""
Reloj del NAO: obtiene la hora del robot en vez de la de la PC.

ALSystem no expone la fecha/hora (en NAOqi 2.8 solo tiene timezone() y
setTimezone()), asi que se intenta, en orden:

  1. ALSystem.date(), si esa version de NAOqi del robot lo trae.
  2. La zona horaria del robot (ALSystem.timezone()) aplicada a la hora
     UTC: el reloj del NAO se sincroniza por NTP, de modo que
     UTC + zona del robot es su hora local. Requiere pytz.
  3. La hora de la PC, avisando una sola vez.

Si el robot deja de responder, el monitor sigue con la hora de la PC para
no detener el aviso de medicacion.
"""
from datetime import datetime

try:
    from naoqi import ALProxy
except ImportError:
    from naoqi_mock import ALProxy

SERVICIO_RELOJ = "ALSystem"


def _a_datetime(valores):
    """Convierte [anio, mes, dia, hora, minuto, segundo, ...] a datetime."""
    anio, mes, dia, hora, minuto, segundo = [int(v) for v in valores[:6]]
    return datetime(anio, mes, dia, hora, minuto, segundo)


def _hora_por_zona(zona):
    """Hora local del robot: hora UTC de la PC + zona horaria del NAO."""
    import pytz
    tz = pytz.timezone(zona)
    return datetime.now(pytz.utc).astimezone(tz).replace(tzinfo=None)


def _leer_hora(proxy, metodo=None):
    """
    Retorna (datetime, metodo). Con metodo=None prueba date() y, si el
    robot no lo tiene, la zona horaria.
    """
    if metodo in (None, "date"):
        try:
            return _a_datetime(proxy.date()), "date"
        except Exception:
            if metodo == "date":
                raise
    zona = proxy.timezone()
    return _hora_por_zona(zona), "zona horaria {}".format(zona)


def crear_reloj_robot(ip, puerto):
    """
    Retorna una funcion sin argumentos que devuelve la hora del NAO.

    Reutiliza el proxy ALSystem y el metodo que funciono entre lecturas.
    Si una lectura falla, cae al reloj de la PC (avisando una sola vez)
    y reintenta el robot en la siguiente revision.
    """
    estado = {"proxy": None, "metodo": None, "avisado": False}

    def _avisar(error):
        if not estado["avisado"]:
            print("[WARN] No se pudo leer la hora del NAO ({});".format(error))
            print("       se usa la hora de la PC mientras tanto.")
            estado["avisado"] = True

    def _reloj():
        try:
            if estado["proxy"] is None:
                estado["proxy"] = ALProxy(SERVICIO_RELOJ, ip, puerto)
            ahora, metodo = _leer_hora(estado["proxy"], estado["metodo"])
        except Exception as e:
            estado["proxy"] = None
            estado["metodo"] = None
            _avisar(e)
            return datetime.now()
        if metodo != estado["metodo"]:
            estado["metodo"] = metodo
            print("[OK] Hora del NAO leida por {}.".format(metodo))
        return ahora

    return _reloj


def leer_hora_robot(ip, puerto):
    """
    Retorna (datetime, metodo) con la hora del NAO, o (None, None) si no
    se pudo leer.
    """
    try:
        proxy = ALProxy(SERVICIO_RELOJ, ip, puerto)
        return _leer_hora(proxy)
    except Exception as e:
        print("[WARN] No se pudo leer la hora del NAO ({}).".format(e))
        return None, None


if __name__ == "__main__":
    from robot_connector import NAO_IP, NAO_PORT

    print("PC : {}".format(datetime.now()))
    hora, metodo = leer_hora_robot(NAO_IP, NAO_PORT)
    if hora is None:
        print("NAO: no disponible")
    else:
        print("NAO: {}  ({})".format(hora, metodo))
        print("Diferencia con la PC: {}".format(hora - datetime.now()))
