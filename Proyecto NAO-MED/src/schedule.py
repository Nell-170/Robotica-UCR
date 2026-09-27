# -*- coding: utf-8 -*-
"""
Lectura del cronograma semanal de medicacion de NAO-Med.

El cronograma vive en un archivo CSV (data/cronograma.csv) que un
cuidador sin experiencia tecnica puede editar directamente con
Excel, Google Sheets o LibreOffice Calc.

Columnas esperadas en el CSV: medicamento, dia, hora
Ejemplo:
    medicamento,dia,hora
    Paracetamol,Lunes,16:00
"""
import csv
import os

DEFAULT_CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cronograma.csv")

DIAS_SEMANA = {
    "lunes": 0,
    "martes": 1,
    "miercoles": 2,
    "miércoles": 2,
    "jueves": 3,
    "viernes": 4,
    "sabado": 5,
    "sábado": 5,
    "domingo": 6,
}


def _parsear_hora(texto_hora):
    """Convierte 'HH:MM' en (hora, minuto) como enteros."""
    partes = texto_hora.strip().split(":")
    if len(partes) != 2:
        raise ValueError("Formato de hora invalido: '{}' (usar HH:MM)".format(texto_hora))
    hora, minuto = int(partes[0]), int(partes[1])
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        raise ValueError("Hora fuera de rango: '{}'".format(texto_hora))
    return hora, minuto


def cargar_cronograma(csv_path=DEFAULT_CSV_PATH):
    """
    Lee el CSV de cronograma y retorna una lista de dicts:
    [{"medicamento": "Paracetamol", "dia": 0, "hora": 16, "minuto": 0}, ...]

    "dia" queda en formato datetime.weekday() (0=Lunes ... 6=Domingo).
    """
    if not os.path.exists(csv_path):
        raise IOError(
            "No se encontro el cronograma en: {}\n"
            "Crea el archivo con columnas: medicamento,dia,hora".format(csv_path)
        )

    entradas = []
    # En Python 2.7 se abre en "rb", en Python 3 en "r" (texto).
    # Intentamos primero con "r" (Python 3), si falla usamos "rb" (Python 2.7).
    try:
        f = open(csv_path, "r")
    except TypeError:
        f = open(csv_path, "rb")
    
    try:
        lector = csv.DictReader(f)
        for fila_num, fila in enumerate(lector, start=2):
            medicamento = (fila.get("medicamento") or "").strip()
            dia_texto = (fila.get("dia") or "").strip().lower()
            hora_texto = (fila.get("hora") or "").strip()

            if not medicamento or not dia_texto or not hora_texto:
                print("Aviso: fila {} del cronograma incompleta, se omite.".format(fila_num))
                continue

            if dia_texto not in DIAS_SEMANA:
                print(
                    "Aviso: fila {} tiene un dia invalido "
                    "'{}', se omite. Dias validos: {}".format(fila_num, dia_texto, list(DIAS_SEMANA))
                )
                continue

            try:
                hora, minuto = _parsear_hora(hora_texto)
            except ValueError as e:
                print("Aviso: fila {} - {}, se omite.".format(fila_num, e))
                continue

            entradas.append({
                "medicamento": medicamento,
                "dia": DIAS_SEMANA[dia_texto],
                "hora": hora,
                "minuto": minuto,
            })
    finally:
        f.close()

    return entradas


if __name__ == "__main__":
    for entrada in cargar_cronograma():
        print(entrada)
