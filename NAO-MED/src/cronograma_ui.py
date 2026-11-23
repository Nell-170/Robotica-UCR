# -*- coding: utf-8 -*-
"""
Interfaz web local para editar data/cronograma.csv de NAO-Med.

Se ejecuta con Python 3 y solo usa la biblioteca estandar (sin Flask ni
dependencias nuevas). Abre una pagina en el navegador con dos vistas:

  - Semana: la semana completa en una rejilla de 7 dias por 24 horas,
    con una casilla por hora. Clic en una casilla vacia agrega una
    entrada en ese dia y hora; clic en una entrada la edita.
  - Lista: todas las entradas en una tabla, ordenadas por dia y hora.

Permite agregar, modificar y eliminar entradas. Cada cambio reescribe el
CSV completo conservando las columnas medicamento,dia,hora, en UTF-8 y
con saltos de linea CRLF (compatibles con Excel en Windows).

Uso:
    py -3 src/cronograma_ui.py
    py -3 src/cronograma_ui.py --port 9000 --no-browser
    py -3 src/cronograma_ui.py --csv otra/ruta/cronograma.csv
"""
from __future__ import print_function

import argparse
import csv
import json
import os
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DEFAULT_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "cronograma.csv",
)

COLUMNAS = ["medicamento", "dia", "hora"]

DIAS = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]

# Medicamentos de los cubos del proyecto (ver README). La interfaz los
# ofrece como sugerencia, pero acepta cualquier nombre.
MEDICAMENTOS = ["Paracetamol", "Ibuprofeno", "Clonacepam"]

_ALIAS_DIAS = {
    "lunes": "Lunes",
    "martes": "Martes",
    "miercoles": "Miercoles",
    "miércoles": "Miercoles",
    "jueves": "Jueves",
    "viernes": "Viernes",
    "sabado": "Sabado",
    "sábado": "Sabado",
    "domingo": "Domingo",
}

_RE_HORA = re.compile(r"^(\d{1,2})\s*:\s*(\d{1,2})$")

_ESCRITURA = threading.Lock()


class ApiError(Exception):
    """Error de validacion que se devuelve al navegador como HTTP 400."""


def leer_entradas(csv_path):
    """Lee el CSV y retorna las filas como dicts de texto sin normalizar.

    Las filas incompletas o con valores raros se conservan tal cual para
    que la interfaz las muestre y el usuario decida que hacer con ellas;
    nunca se descartan en silencio.
    """
    if not os.path.exists(csv_path):
        return []

    with open(csv_path, "r", newline="", encoding="utf-8-sig") as archivo:
        lector = csv.DictReader(archivo)
        entradas = []
        for fila in lector:
            medicamento = (fila.get("medicamento") or "").strip()
            dia = (fila.get("dia") or "").strip()
            hora = (fila.get("hora") or "").strip()
            if not (medicamento or dia or hora):
                continue
            entradas.append({"medicamento": medicamento, "dia": dia, "hora": hora})
        return entradas


def escribir_entradas(csv_path, entradas):
    """Reescribe el CSV completo de forma atomica (archivo temporal + replace)."""
    carpeta = os.path.dirname(os.path.abspath(csv_path))
    if carpeta and not os.path.isdir(carpeta):
        os.makedirs(carpeta)

    temporal = csv_path + ".tmp"
    with open(temporal, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo, lineterminator="\r\n")
        escritor.writerow(COLUMNAS)
        for entrada in entradas:
            escritor.writerow([entrada["medicamento"], entrada["dia"], entrada["hora"]])
    os.replace(temporal, csv_path)


def normalizar_hora(texto):
    """Acepta '8:00', '08:00' o '8:0' y retorna 'HH:MM'."""
    coincidencia = _RE_HORA.match((texto or "").strip())
    if not coincidencia:
        raise ApiError("La hora debe tener el formato HH:MM (por ejemplo 08:30).")
    hora, minuto = int(coincidencia.group(1)), int(coincidencia.group(2))
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        raise ApiError("La hora esta fuera de rango: use 00:00 a 23:59.")
    return "{:02d}:{:02d}".format(hora, minuto)


def normalizar_entrada(datos):
    """Valida y normaliza una entrada recibida del navegador."""
    if not isinstance(datos, dict):
        raise ApiError("Datos invalidos.")

    medicamento = " ".join(str(datos.get("medicamento") or "").split())
    if not medicamento:
        raise ApiError("Escriba el nombre del medicamento.")
    if len(medicamento) > 60:
        raise ApiError("El nombre del medicamento es demasiado largo (maximo 60).")

    dia = _ALIAS_DIAS.get(str(datos.get("dia") or "").strip().lower())
    if not dia:
        raise ApiError("Elija un dia de la semana valido.")

    return {
        "medicamento": medicamento,
        "dia": dia,
        "hora": normalizar_hora(datos.get("hora")),
    }


def estado(csv_path):
    """Estado completo que consume la interfaz."""
    entradas = leer_entradas(csv_path)
    for indice, entrada in enumerate(entradas):
        entrada["id"] = indice
    return {
        "entradas": entradas,
        "dias": DIAS,
        "medicamentos": MEDICAMENTOS,
        "archivo": os.path.abspath(csv_path),
    }


def _indice_valido(indice, total):
    if not (0 <= indice < total):
        raise ApiError("La entrada ya no existe. Recargue la pagina.")


def agregar(csv_path, datos):
    entrada = normalizar_entrada(datos)
    with _ESCRITURA:
        entradas = leer_entradas(csv_path)
        entradas.append(entrada)
        escribir_entradas(csv_path, entradas)
    return estado(csv_path)


def modificar(csv_path, indice, datos):
    entrada = normalizar_entrada(datos)
    with _ESCRITURA:
        entradas = leer_entradas(csv_path)
        _indice_valido(indice, len(entradas))
        entradas[indice] = entrada
        escribir_entradas(csv_path, entradas)
    return estado(csv_path)


def eliminar(csv_path, indice):
    with _ESCRITURA:
        entradas = leer_entradas(csv_path)
        _indice_valido(indice, len(entradas))
        del entradas[indice]
        escribir_entradas(csv_path, entradas)
    return estado(csv_path)


def leer_pagina():
    """Lee la pagina HTML que acompana a este script."""
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cronograma_ui.html")
    with open(ruta, "r", encoding="utf-8") as archivo:
        return archivo.read()


class Handler(BaseHTTPRequestHandler):
    server_version = "CronogramaUI/1.0"
    csv_path = DEFAULT_CSV_PATH

    def log_message(self, formato, *args):
        pass

    def _enviar(self, codigo, cuerpo, tipo="application/json; charset=utf-8"):
        datos = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(datos)

    def _json(self, codigo, objeto):
        self._enviar(codigo, json.dumps(objeto, ensure_ascii=False))

    def _cuerpo(self):
        largo = int(self.headers.get("Content-Length") or 0)
        crudo = self.rfile.read(largo) if largo else b""
        if not crudo:
            return {}
        try:
            return json.loads(crudo.decode("utf-8"))
        except ValueError:
            raise ApiError("El cuerpo de la peticion no es JSON valido.")

    def _indice_de_ruta(self):
        ruta = urlparse(self.path).path.rstrip("/")
        partes = ruta.split("/")
        if len(partes) != 4 or partes[1] != "api" or partes[2] != "cronograma":
            raise ApiError("Ruta no valida.")
        try:
            return int(partes[3])
        except ValueError:
            raise ApiError("Identificador de entrada no valido.")

    def _manejar(self, accion):
        try:
            self._json(200, accion())
        except ApiError as error:
            self._json(400, {"error": str(error)})
        except Exception as error:  # noqa: BLE001 - se informa al navegador
            self._json(500, {"error": "Error del servidor: {}".format(error)})

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta in ("/", "/index.html"):
            self._enviar(200, leer_pagina(), "text/html; charset=utf-8")
        elif ruta == "/api/cronograma":
            self._manejar(lambda: estado(self.csv_path))
        else:
            self._json(404, {"error": "No encontrado."})

    def do_POST(self):
        self._manejar(lambda: agregar(self.csv_path, self._cuerpo()))

    def do_PUT(self):
        indice = self._indice_de_ruta()
        self._manejar(lambda: modificar(self.csv_path, indice, self._cuerpo()))

    def do_DELETE(self):
        indice = self._indice_de_ruta()
        self._manejar(lambda: eliminar(self.csv_path, indice))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Interfaz para editar el cronograma de NAO-Med.")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="Ruta del cronograma a editar.")
    parser.add_argument("--port", type=int, default=8765, help="Puerto local (por defecto 8765).")
    parser.add_argument("--no-browser", action="store_true", help="No abrir el navegador.")
    args = parser.parse_args(argv)

    csv_path = os.path.abspath(args.csv)
    Handler.csv_path = csv_path

    servidor = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = "http://127.0.0.1:{}/".format(args.port)

    print("Cronograma: {}".format(csv_path))
    print("Interfaz lista en {}".format(url))
    print("Presiona Ctrl+C para detenerla.")

    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nInterfaz detenida.")
    finally:
        servidor.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
