# -*- coding: utf-8 -*-
"""
Verificador de cronograma: revisa si en este momento (dia/hora del
sistema) corresponde suministrar algun medicamento del cronograma.
"""
import time
from datetime import datetime

from schedule import cargar_cronograma, DEFAULT_CSV_PATH

# Cada cuantos segundos se revisa el cronograma
INTERVALO_REVISION_SEGUNDOS = 20


def _coincide_ahora(entrada, ahora):
    """True si 'ahora' cae dentro del mismo dia/hora/minuto de la entrada."""
    return (
        ahora.weekday() == entrada["dia"]
        and ahora.hour == entrada["hora"]
        and ahora.minute == entrada["minuto"]
    )


def buscar_medicamento_pendiente(cronograma, ahora=None):
    """
    Retorna la primera entrada del cronograma que coincide con el
    dia/hora/minuto actual, o None si no hay ninguna pendiente.
    """
    ahora = ahora or datetime.now()
    for entrada in cronograma:
        if _coincide_ahora(entrada, ahora):
            return entrada
    return None


def ejecutar_monitor(accion_notificar, csv_path=DEFAULT_CSV_PATH,
                      intervalo=INTERVALO_REVISION_SEGUNDOS):
    """
    Bucle infinito que revisa el cronograma periodicamente y llama a
    'accion_notificar(medicamento)' cuando corresponde suministrar uno.

    Evita repetir la misma notificacion varias veces durante el mismo
    minuto (ya que se revisa cada pocos segundos).
    """
    cronograma = cargar_cronograma(csv_path)
    print("Cronograma cargado ({} medicamento(s)).".format(len(cronograma)))

    ultima_notificacion = None  # (medicamento, dia, hora, minuto)

    print("Monitor de medicacion iniciado. Presiona Ctrl+C para detener.")
    try:
        while True:
            ahora = datetime.now()
            pendiente = buscar_medicamento_pendiente(cronograma, ahora)

            if pendiente is not None:
                clave = (pendiente["medicamento"], pendiente["dia"],
                          pendiente["hora"], pendiente["minuto"])
                if clave != ultima_notificacion:
                    accion_notificar(pendiente["medicamento"])
                    ultima_notificacion = clave
            else:
                ultima_notificacion = None

            time.sleep(intervalo)
    except KeyboardInterrupt:
        print("\nMonitor de medicacion detenido.")


if __name__ == "__main__":
    def _imprimir_notificacion(medicamento):
        print("[NOTIFICACION] Es hora de: {}".format(medicamento))

    ejecutar_monitor(_imprimir_notificacion)
