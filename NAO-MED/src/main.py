# -*- coding: utf-8 -*-
"""
Punto de entrada de NAO-Med.

Flujo:
    1. Detecta si el NAO real esta disponible en la red; si no, abre
       el simulador Webots (robot_connector.py).
    2. Carga el cronograma semanal de medicamentos (schedule.py).
    3. Monitorea continuamente el dia/hora del reloj del NAO real (o el
       de la PC en el simulador) (medication_scheduler.py).
    4. Cuando corresponde un medicamento, ejecuta la secuencia en el
       NAO: alarma, luces, caminar y hablar (nao_controller.py).
"""
from datetime import datetime

from robot_connector import main as conectar_robot
from medication_scheduler import ejecutar_monitor
from nao_controller import notificar_medicamento
from reloj import crear_reloj_robot


def main():
    config = conectar_robot()

    # Con robot real el cronograma se compara contra el reloj interno del
    # NAO (ALSystem); en el simulador no hay reloj de robot, se usa la PC.
    if config.get("type") == "real":
        reloj = crear_reloj_robot(config["ip"], config["port"])
    else:
        reloj = datetime.now

    def _notificar(medicamento):
        notificar_medicamento(config, medicamento, diagnostico=False)

    ejecutar_monitor(_notificar, reloj=reloj)


if __name__ == "__main__":
    main()



