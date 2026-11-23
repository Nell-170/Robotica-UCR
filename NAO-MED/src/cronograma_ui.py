# -*- coding: utf-8 -*-
"""
Interfaz web local para editar el cronograma de medicamentos de NAO-Med.

Se ejecuta con Python 3 y solo usa la biblioteca estandar (sin Flask ni
dependencias nuevas). Abre una pagina en el navegador con dos vistas:

  - Semana: la semana completa en una rejilla de 7 dias por 24 horas,
    con una casilla por hora. Clic en una casilla vacia agrega una
    entrada en ese dia y hora; clic en una entrada la edita.
  - Lista: todas las entradas en una tabla, ordenadas por dia y hora.

Permite agregar, modificar y eliminar entradas y trabajar sobre dos
destinos intercambiables desde la propia pagina:

  - Este equipo: edita un CSV local (por defecto data/cronograma.csv).
  - NAO por SSH: lee y escribe el CSV dentro del robot, por defecto
    /home/nao/NAO-MED/data/cronograma.csv, usando el cliente ssh del
    sistema (autenticacion por clave o ssh-agent, sin contrasenas).

En modo SSH la interfaz muestra ademas la hora del robot, porque el
monitor de medicacion compara el cronograma con el reloj interno del NAO
y no con el de la PC. La vista semanal resalta el dia y la hora del
destino activo.

Cada cambio reescribe el CSV completo conservando las columnas
medicamento,dia,hora, en UTF-8 y con saltos de linea CRLF (compatibles
con Excel en Windows).

Uso:
    py -3 src/cronograma_ui.py
    py -3 src/cronograma_ui.py --port 9000 --no-browser
    py -3 src/cronograma_ui.py --csv otra/ruta/cronograma.csv
    py -3 src/cronograma_ui.py --ssh 192.168.1.140
    py -3 src/cronograma_ui.py --ssh 192.168.1.140 --ssh-user nao \\
        --ssh-ruta /home/nao/NAO-MED/data/cronograma.csv
"""
from __future__ import print_function

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DEFAULT_CSV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "cronograma.csv",
)

# Ruta del cronograma dentro del NAO.
RUTA_NAO = "/home/nao/NAO-MED/data/cronograma.csv"

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
_RE_HOST = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,252})$")
_RE_USUARIO = re.compile(r"^[A-Za-z0-9._-]{1,32}$")
# Rutas remotas: solo caracteres seguros, porque ssh entrega el comando a
# un shell en el robot. Sin espacios, comillas ni metacaracteres.
_RE_RUTA_REMOTA = re.compile(r"^/[A-Za-z0-9._/-]*$")

_ESCRITURA = threading.Lock()


class ApiError(Exception):
    """Error de validacion que se devuelve al navegador como HTTP 400."""


class BackendError(Exception):
    """Fallo al hablar con el destino (SSH o disco); se devuelve como 502."""


# ---------------------------------------------------------------------------
# CSV: texto <-> entradas
# ---------------------------------------------------------------------------

def parsear_csv(texto):
    """Convierte el contenido del CSV en una lista de dicts sin normalizar.

    Las filas incompletas o con valores raros se conservan tal cual para
    que la interfaz las muestre y el usuario decida que hacer con ellas;
    nunca se descartan en silencio.
    """
    if not texto:
        return []
    entradas = []
    lector = csv.DictReader(io.StringIO(texto))
    for fila in lector:
        medicamento = (fila.get("medicamento") or "").strip()
        dia = (fila.get("dia") or "").strip()
        hora = (fila.get("hora") or "").strip()
        if not (medicamento or dia or hora):
            continue
        entradas.append({"medicamento": medicamento, "dia": dia, "hora": hora})
    return entradas


def serializar_csv(entradas, salto="\r\n"):
    """Devuelve el CSV completo como texto, sin BOM."""
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator=salto)
    escritor.writerow(COLUMNAS)
    for entrada in entradas:
        escritor.writerow([entrada["medicamento"], entrada["dia"], entrada["hora"]])
    return salida.getvalue()


def salto_de(texto):
    """Conserva el fin de linea que ya usa el archivo (CRLF o LF)."""
    return "\r\n" if "\r\n" in (texto or "") else "\n"


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


# ---------------------------------------------------------------------------
# Destinos: archivo local o NAO por SSH
# ---------------------------------------------------------------------------

class BackendLocal(object):
    """Cronograma en un archivo de este equipo."""

    modo = "local"

    def __init__(self, ruta):
        self.ruta = os.path.abspath(ruta)

    def leer(self):
        if not os.path.exists(self.ruta):
            return ""
        with open(self.ruta, "r", newline="", encoding="utf-8-sig") as archivo:
            return archivo.read()

    def escribir(self, texto):
        carpeta = os.path.dirname(self.ruta)
        if carpeta and not os.path.isdir(carpeta):
            os.makedirs(carpeta)
        temporal = self.ruta + ".tmp"
        with open(temporal, "w", newline="", encoding="utf-8") as archivo:
            archivo.write(texto)
        os.replace(temporal, self.ruta)

    def reloj(self):
        ahora = datetime.now()
        return {
            "hora": ahora.strftime("%H:%M"),
            "dia": ahora.weekday(),
            "fecha": ahora.strftime("%Y-%m-%d %H:%M:%S"),
            "fuente": "PC",
            "desfase": 0,
        }

    def cerrar(self):
        pass

    def describir(self):
        return {
            "modo": "local",
            "archivo": self.ruta,
            "ruta": self.ruta,
            "host": "",
            "usuario": "",
            "puerto": 0,
            "identidad": "",
            "autenticacion": "",
        }


def _mensaje_ssh(detalle, host, usuario, puerto=22, contrasena=False):
    """Traduce los errores mas comunes de ssh a una frase util."""
    bajo = detalle.lower()
    if "permission denied" in bajo or "authentication failed" in bajo:
        if contrasena:
            return (
                "SSH rechazo el usuario o la contrasena de {}@{}.\n"
                "Revise la contrasena del NAO y vuelva a intentarlo.".format(usuario, host)
            )
        return (
            "SSH rechazo la autenticacion para {}@{}.\n"
            "Escriba la contrasena del NAO o configure una clave "
            "(ssh-copy-id {}@{}).".format(usuario, host, usuario, host)
        )
    if "host key verification failed" in bajo:
        return (
            "La clave del host {} no es de confianza. Conectese una vez a mano "
            "(ssh {}@{}) y acepte la huella.".format(host, usuario, host)
        )
    if ("connection refused" in bajo or "no valid connections" in bajo
            or "unable to connect" in bajo):
        return "El NAO rechazo la conexion en {}:{}. Verifique que sshd este activo.".format(
            host, puerto)
    if "no route to host" in bajo or "timed out" in bajo:
        return "No se pudo llegar a {}. Revise la red y la IP del NAO.".format(host)
    if "could not resolve hostname" in bajo or "name or service not known" in bajo:
        return "No se pudo resolver el nombre '{}'.".format(host)
    return detalle or "No se pudo ejecutar el comando en {}:{}.".format(host, puerto)


class BackendSsh(object):
    """Cronograma dentro del NAO, leido y escrito por ssh.

    Con contrasena usa paramiko (opcional, `pip install paramiko`), que
    permite autenticarse igual que `ssh nao@192.168.1.140` escribiendo la
    clave. Sin contrasena usa el cliente ssh del sistema con una clave o
    ssh-agent, sin pedir nada por consola.
    """

    modo = "ssh"

    def __init__(self, host, usuario, puerto, ruta, identidad="", clave=""):
        self.host = host
        self.usuario = usuario
        self.puerto = puerto
        self.ruta = ruta
        self.identidad = identidad
        self.clave = clave
        self._cliente = None
        self._lock = threading.Lock()

    # -- cliente ssh del sistema (clave o ssh-agent) ------------------------

    def _comando_ssh(self, comando):
        args = [
            "ssh",
            "-p", str(self.puerto),
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new",
        ]
        if self.identidad:
            args += ["-i", self.identidad]
        args += ["{}@{}".format(self.usuario, self.host), comando]
        return args

    def _ejecutar_ssh(self, comando, entrada=None):
        try:
            proceso = subprocess.run(
                self._comando_ssh(comando),
                input=entrada,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except FileNotFoundError:
            raise BackendError(
                "No se encontro el cliente 'ssh' en este equipo. "
                "Instale OpenSSH o use el modo local."
            )
        except subprocess.TimeoutExpired:
            raise BackendError("El NAO no respondio a tiempo ({}).".format(self.host))

        if proceso.returncode != 0:
            detalle = proceso.stderr.decode("utf-8", "replace").strip()
            if not detalle:
                detalle = "ssh termino con codigo {} sin mensaje".format(proceso.returncode)
            raise BackendError(_mensaje_ssh(detalle, self.host, self.usuario, self.puerto))
        return proceso.stdout.decode("utf-8", "replace")

    # -- paramiko (contrasena) ---------------------------------------------

    def _cerrar_paramiko(self):
        if self._cliente is not None:
            try:
                self._cliente.close()
            except Exception:
                pass
            self._cliente = None

    def _cliente_paramiko(self):
        if self._cliente is not None:
            transporte = self._cliente.get_transport()
            if transporte is not None and transporte.is_active():
                return self._cliente
            self._cerrar_paramiko()

        try:
            import paramiko
        except ImportError:
            raise BackendError(
                "Para conectarse con contrasena hace falta paramiko.\n"
                "Instalelo con: pip install paramiko\n"
                "Tambien puede usar una clave SSH y dejar la contrasena vacia."
            )

        cliente = paramiko.SSHClient()
        cliente.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            cliente.connect(
                hostname=self.host,
                port=self.puerto,
                username=self.usuario,
                password=self.clave,
                key_filename=self.identidad or None,
                timeout=8,
                banner_timeout=15,
                auth_timeout=15,
                allow_agent=False,
                look_for_keys=False,
            )
        except paramiko.AuthenticationException:
            raise BackendError(
                _mensaje_ssh("authentication failed", self.host, self.usuario,
                             self.puerto, True)
            )
        except Exception as error:
            raise BackendError(
                _mensaje_ssh(str(error), self.host, self.usuario, self.puerto, True)
            )
        self._cliente = cliente
        return cliente

    def _ejecutar_paramiko(self, comando, entrada=None):
        with self._lock:
            cliente = self._cliente_paramiko()
            try:
                stdin, stdout, stderr = cliente.exec_command(comando, timeout=30)
                if entrada:
                    stdin.write(entrada)
                    stdin.flush()
                stdin.channel.shutdown_write()
                salida = stdout.read()
                error = stderr.read().decode("utf-8", "replace").strip()
                codigo = stdout.channel.recv_exit_status()
            except Exception as fallo:
                self._cerrar_paramiko()
                raise BackendError(
                    _mensaje_ssh(str(fallo), self.host, self.usuario, self.puerto, True)
                )
        if codigo != 0:
            raise BackendError(
                _mensaje_ssh(error, self.host, self.usuario, self.puerto, True)
            )
        return salida.decode("utf-8", "replace")

    # -- interfaz comun -----------------------------------------------------

    def _ejecutar(self, comando, entrada=None):
        if self.clave:
            return self._ejecutar_paramiko(comando, entrada)
        return self._ejecutar_ssh(comando, entrada)

    def leer(self):
        # Si el archivo no existe todavia, se trata como cronograma vacio.
        comando = "if [ -f {r} ]; then cat {r}; fi".format(r=self.ruta)
        return self._ejecutar(comando)

    def escribir(self, texto):
        temporal = self.ruta + ".tmp"
        comando = "cat > {t} && mv {t} {r}".format(t=temporal, r=self.ruta)
        self._ejecutar(comando, entrada=texto.encode("utf-8"))

    def reloj(self):
        salida = self._ejecutar("date +%Y-%m-%dT%H:%M:%S%z").strip()
        try:
            robot = datetime.strptime(salida, "%Y-%m-%dT%H:%M:%S%z")
        except ValueError:
            raise BackendError("El NAO devolvio una fecha inesperada: '{}'.".format(salida))
        desfase = (robot - datetime.now().astimezone()).total_seconds()
        return {
            "hora": robot.strftime("%H:%M"),
            "dia": robot.weekday(),
            "fecha": robot.strftime("%Y-%m-%d %H:%M:%S"),
            "fuente": "NAO",
            "desfase": int(round(desfase)),
        }

    def cerrar(self):
        self._cerrar_paramiko()

    def describir(self):
        # La contrasena nunca sale de aqui: solo se informa como se autentica.
        return {
            "modo": "ssh",
            "archivo": "{}@{}:{}".format(self.usuario, self.host, self.ruta),
            "ruta": self.ruta,
            "host": self.host,
            "usuario": self.usuario,
            "puerto": self.puerto,
            "identidad": self.identidad,
            "autenticacion": "contrasena" if self.clave else "clave",
        }


def construir_backend(datos):
    """Crea el destino pedido por el navegador, validando cada campo."""
    if not isinstance(datos, dict):
        raise ApiError("Datos invalidos.")
    modo = str(datos.get("modo") or "local").strip().lower()
    if modo == "local":
        return BackendLocal(datos.get("ruta") or DEFAULT_CSV_PATH)
    if modo != "ssh":
        raise ApiError("Modo de conexion desconocido.")

    host = str(datos.get("host") or "").strip()
    if not _RE_HOST.match(host):
        raise ApiError("Escriba una IP o nombre de host valido para el NAO.")

    usuario = str(datos.get("usuario") or "nao").strip()
    if not _RE_USUARIO.match(usuario):
        raise ApiError("El usuario SSH solo admite letras, numeros, punto, guion y guion bajo.")

    try:
        puerto = int(datos.get("puerto") or 22)
    except (TypeError, ValueError):
        raise ApiError("El puerto SSH debe ser un numero.")
    if not (1 <= puerto <= 65535):
        raise ApiError("El puerto SSH esta fuera de rango.")

    ruta = str(datos.get("ruta") or RUTA_NAO).strip()
    if not _RE_RUTA_REMOTA.match(ruta) or ".." in ruta:
        raise ApiError("La ruta remota debe ser absoluta y sin espacios ni caracteres raros.")

    identidad = str(datos.get("identidad") or "").strip()
    if identidad:
        identidad = os.path.expanduser(identidad)
        if not os.path.isfile(identidad):
            raise ApiError("No se encontro el archivo de clave: {}".format(identidad))

    clave = datos.get("clave")
    clave = "" if clave is None else str(clave)
    if len(clave) > 256:
        raise ApiError("La contrasena es demasiado larga.")
    if "\x00" in clave or "\r" in clave or "\n" in clave:
        raise ApiError("La contrasena contiene caracteres no validos.")

    return BackendSsh(host, usuario, puerto, ruta, identidad, clave)


class Conexion(object):
    """Destino activo, protegido para que los hilos no lo pisen."""

    def __init__(self, backend):
        self._backend = backend
        self._lock = threading.Lock()

    def actual(self):
        with self._lock:
            return self._backend

    def cambiar(self, backend):
        with self._lock:
            anterior = self._backend
            self._backend = backend
        cerrar = getattr(anterior, "cerrar", None)
        if cerrar is not None:
            cerrar()


CONEXION = Conexion(BackendLocal(DEFAULT_CSV_PATH))

# La hora del robot se cachea unos segundos: cada lectura es un ssh.
_RELOJ_CACHE = {"clave": None, "valor": None, "momento": 0.0}
_RELOJ_SEGUNDOS = 10


def reloj_de(backend):
    clave = backend.describir()["archivo"]
    ahora = time.time()
    if (
        _RELOJ_CACHE["clave"] == clave
        and _RELOJ_CACHE["valor"] is not None
        and ahora - _RELOJ_CACHE["momento"] < _RELOJ_SEGUNDOS
    ):
        return _RELOJ_CACHE["valor"]
    valor = backend.reloj()
    _RELOJ_CACHE.update({"clave": clave, "valor": valor, "momento": ahora})
    return valor


def estado():
    """Estado completo que consume la interfaz."""
    backend = CONEXION.actual()
    entradas = parsear_csv(backend.leer())
    for indice, entrada in enumerate(entradas):
        entrada["id"] = indice
    return {
        "entradas": entradas,
        "dias": DIAS,
        "medicamentos": MEDICAMENTOS,
        "archivo": backend.describir()["archivo"],
        "conexion": backend.describir(),
        "reloj": reloj_de(backend),
    }


def _indice_valido(indice, total):
    if not (0 <= indice < total):
        raise ApiError("La entrada ya no existe. Recargue la pagina.")


def _mutar(cambio):
    """Lee, aplica el cambio y reescribe el CSV del destino activo."""
    backend = CONEXION.actual()
    with _ESCRITURA:
        texto = backend.leer()
        entradas = parsear_csv(texto)
        cambio(entradas)
        backend.escribir(serializar_csv(entradas, salto_de(texto)))
    return estado()


def agregar(datos):
    entrada = normalizar_entrada(datos)
    return _mutar(lambda entradas: entradas.append(entrada))


def modificar(indice, datos):
    entrada = normalizar_entrada(datos)

    def cambio(entradas):
        _indice_valido(indice, len(entradas))
        entradas[indice] = entrada

    return _mutar(cambio)


def eliminar(indice):
    def cambio(entradas):
        _indice_valido(indice, len(entradas))
        del entradas[indice]

    return _mutar(cambio)


def probar_conexion(datos):
    """Prueba un destino sin activarlo: lee el CSV y la hora."""
    backend = construir_backend(datos)
    try:
        entradas = parsear_csv(backend.leer())
        reloj = backend.reloj()
    finally:
        cerrar = getattr(backend, "cerrar", None)
        if cerrar is not None:
            cerrar()
    return {
        "ok": True,
        "archivo": backend.describir()["archivo"],
        "entradas": len(entradas),
        "reloj": reloj,
    }


def conectar(datos):
    """Activa un destino nuevo y devuelve el estado ya leido de el."""
    backend = construir_backend(datos)
    backend.leer()  # falla aqui si el destino no responde
    CONEXION.cambiar(backend)
    _RELOJ_CACHE.update({"clave": None, "valor": None, "momento": 0.0})
    return estado()


def leer_pagina():
    """Lee la pagina HTML que acompana a este script."""
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cronograma_ui.html")
    with open(ruta, "r", encoding="utf-8") as archivo:
        return archivo.read()


class Handler(BaseHTTPRequestHandler):
    server_version = "CronogramaUI/1.1"

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
        except BackendError as error:
            self._json(502, {"error": str(error)})
        except Exception as error:  # noqa: BLE001 - se informa al navegador
            self._json(500, {"error": "Error del servidor: {}".format(error)})

    def do_GET(self):
        ruta = urlparse(self.path).path
        if ruta in ("/", "/index.html"):
            self._enviar(200, leer_pagina(), "text/html; charset=utf-8")
        elif ruta == "/api/cronograma":
            self._manejar(estado)
        else:
            self._json(404, {"error": "No encontrado."})

    def do_POST(self):
        ruta = urlparse(self.path).path.rstrip("/")
        if ruta == "/api/cronograma":
            self._manejar(lambda: agregar(self._cuerpo()))
        elif ruta == "/api/conexion":
            self._manejar(lambda: conectar(self._cuerpo()))
        elif ruta == "/api/conexion/probar":
            self._manejar(lambda: probar_conexion(self._cuerpo()))
        else:
            self._json(404, {"error": "No encontrado."})

    def do_PUT(self):
        indice = self._indice_de_ruta()
        self._manejar(lambda: modificar(indice, self._cuerpo()))

    def do_DELETE(self):
        indice = self._indice_de_ruta()
        self._manejar(lambda: eliminar(indice))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Interfaz para editar el cronograma de NAO-Med.")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH, help="Ruta del cronograma local.")
    parser.add_argument("--port", type=int, default=8765, help="Puerto local (por defecto 8765).")
    parser.add_argument("--no-browser", action="store_true", help="No abrir el navegador.")
    parser.add_argument("--ssh", metavar="HOST", help="Arrancar conectado al NAO por SSH.")
    parser.add_argument("--ssh-user", default="nao", help="Usuario SSH del NAO (por defecto nao).")
    parser.add_argument("--ssh-port", type=int, default=22, help="Puerto SSH (por defecto 22).")
    parser.add_argument("--ssh-ruta", default=RUTA_NAO, help="Ruta del CSV dentro del NAO.")
    parser.add_argument("--ssh-identidad", default="", help="Archivo de clave privada SSH.")
    parser.add_argument(
        "--ssh-pedir-clave",
        action="store_true",
        help="Pedir la contrasena del NAO por consola (no queda en el historial).",
    )
    args = parser.parse_args(argv)

    if args.ssh:
        clave = ""
        if args.ssh_pedir_clave:
            import getpass

            if sys.stdin is not None and sys.stdin.isatty():
                clave = getpass.getpass("Contrasena de {}@{}: ".format(args.ssh_user, args.ssh))
            else:
                # Sin terminal (por ejemplo una tuberia) se lee una linea.
                clave = sys.stdin.readline().rstrip("\r\n")
        try:
            backend = construir_backend({
                "modo": "ssh",
                "host": args.ssh,
                "usuario": args.ssh_user,
                "puerto": args.ssh_port,
                "ruta": args.ssh_ruta,
                "identidad": args.ssh_identidad,
                "clave": clave,
            })
            backend.leer()
        except (ApiError, BackendError) as error:
            print("[ERROR] {}".format(error))
            return 1
        CONEXION.cambiar(backend)
    else:
        CONEXION.cambiar(BackendLocal(args.csv))

    servidor = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = "http://127.0.0.1:{}/".format(args.port)

    print("Cronograma: {}".format(CONEXION.actual().describir()["archivo"]))
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
