# -*- coding: utf-8 -*-
"""
Punto de entrada de NAO-Med.

Flujo:
    1. Detecta si el NAO real esta disponible en la red; si no, abre
       el simulador Webots (robot_connector.py).
    2. Carga el cronograma semanal de medicamentos (schedule.py).
    3. Monitorea continuamente el dia/hora del sistema
       (medication_scheduler.py).
    4. Cuando corresponde un medicamento, ejecuta la secuencia en el
       NAO: alarma, luces, caminar y hablar (nao_controller.py).
"""
from robot_connector import main as conectar_robot
from medication_scheduler import ejecutar_monitor
from nao_controller import notificar_medicamento


def main():
    config = conectar_robot()

    def _notificar(medicamento):
        notificar_medicamento(config, medicamento)

    ejecutar_monitor(_notificar)


if __name__ == "__main__":
    main()
