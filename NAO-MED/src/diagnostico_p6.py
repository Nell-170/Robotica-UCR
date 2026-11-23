# -*- coding: utf-8 -*-
"""Prueba controlada de cubos y rostros en el NAO real para P6."""
import argparse
import sys
import time

try:
    from naoqi import ALProxy
except ImportError:
    print("Error: no se encuentra el SDK real de NAOqi en este Python.")
    sys.exit(1)

from deteccion_cubo import OPENCV_DISPONIBLE, identificar_cubos
from reconocimiento import reconocer_rostro
from robot_connector import NAO_IP, NAO_PORT, check_nao_connection


def main():
    parser = argparse.ArgumentParser(
        description="Prueba de deteccion P6 en el NAO real para una condicion de luz.")
    parser.add_argument(
        "iluminacion",
        choices=("4_luces", "2_luces", "0_luces"),
        help="Etiqueta de la iluminacion usada durante esta corrida.")
    args = parser.parse_args()

    if not OPENCV_DISPONIBLE:
        print("Error: OpenCV/numpy no estan disponibles en este Python.")
        return 1
    if not check_nao_connection(NAO_IP, NAO_PORT):
        print("Error: no se puede conectar al NAO en {}:{}.".format(NAO_IP, NAO_PORT))
        return 1

    marca_tiempo = time.strftime("%Y%m%d_%H%M%S")
    prefijo = "p6_{}_{}_".format(args.iluminacion, marca_tiempo)
    print("[P6] Condicion: {}.".format(args.iluminacion))
    print("[P6] Mantenga fijos los cubos y la posicion de la persona.")
    print("[P6] El robot solo barre la cabeza y detecta; no camina.")

    medicamentos = identificar_cubos(
        NAO_IP, NAO_PORT, diagnostico=True, prefijo_debug=prefijo)
    print("[P6] Cubos identificados: {}".format(
        ", ".join(medicamentos) if medicamentos else "ninguno"))

    rostro = reconocer_rostro(NAO_IP, NAO_PORT)
    print("[P6] Rostro detectado: {}".format("si" if rostro else "no"))
    print("[P6] Capturas anotadas guardadas en NAO-MED/data/debug/ con prefijo {}.".format(
        prefijo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
