# -*- coding: utf-8 -*-
"""
Robot Connector - Detecta NAO real o abre simulador Webots
"""
import socket
import subprocess
import time
import sys
import os

# Forzar UTF-8 en la salida para que los emojis no rompan la consola de Windows
# (solo en Python 3.7+; en Python 2.7 no existe reconfigure)
if sys.version_info[0] >= 3 and hasattr(sys.stdout, 'reconfigure'):
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

# Configuración
NAO_IP = "192.168.1.140"
NAO_PORT = 9559
WEBOTS_TIMEOUT = 5  # segundos para intentar conectar

def check_nao_connection(ip, port, timeout=2):
    """
    Intenta conectarse al NAO en la IP especificada.
    Retorna True si está disponible, False si no.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except Exception as e:
        print("Error al verificar conexion: {}".format(e))
        return False

# Mundo de NAO-Med (incluye el controlador nao_med_controller ya asignado)
NAO_WORLD = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "webots", "worlds", "nao_med.wbt"
)

def find_webots_executable():
    """Busca el ejecutable de Webots en las ubicaciones comunes de Windows."""
    webots_paths = [
        r"C:\Program Files\Webots\msys64\mingw64\bin\webots.exe",
        r"C:\Program Files (x86)\Webots\msys64\mingw64\bin\webots.exe",
    ]
    for path in webots_paths:
        if os.path.exists(path):
            return path
    return None

def launch_webots_simulator(world_path=NAO_WORLD):
    """
    Lanza el simulador Webots con un mundo de NAO cargado.
    """
    webots_exe = find_webots_executable()

    if not webots_exe:
        print("❌ No se encontró Webots instalado.")
        print("Descárgalo desde: https://www.cyberbotics.com/")
        return False

    print("🤖 Abriendo simulador Webots con NAO...")
    try:
        args = [webots_exe]
        if world_path and os.path.exists(world_path):
            args.append(world_path)
        else:
            print("[WARN] Mundo no encontrado ({}), se abre Webots vacio.".format(world_path))

        subprocess.Popen(args)
        print("[OK] Simulador iniciado. Espera a que cargue...")
        time.sleep(5)  # Espera a que Webots se abra
        return True
    except Exception as e:
        print("[ERROR] Error al abrir Webots: {}".format(e))
        return False

def get_robot_connection(use_simulator=False):
    """
    Retorna la configuración para conectarse al robot.
    Si use_simulator=True, usa localhost (simulador).
    Si use_simulator=False, usa la IP del NAO real.
    """
    if use_simulator:
        return {
            "ip": "127.0.0.1",
            "port": 9559,
            "type": "simulator",
            "description": "Simulador Webots"
        }
    else:
        return {
            "ip": NAO_IP,
            "port": NAO_PORT,
            "type": "real",
            "description": "NAO Real ({})".format(NAO_IP)
        }

def main():
    """
    Flujo principal: detecta NAO o abre simulador
    """
    print("=" * 50)
    print("🔍 Buscando NAO Poseidón en la red...")
    print("=" * 50)
    
    # Intenta conectar al NAO real
    if check_nao_connection(NAO_IP, NAO_PORT):
        print("[OK] NAO detectado en {}".format(NAO_IP))
        config = get_robot_connection(use_simulator=False)
    else:
        print("[ERROR] NAO no detectado en {}".format(NAO_IP))
        print("[INFO] Abriendo simulador Webots...")
        
        if launch_webots_simulator():
            config = get_robot_connection(use_simulator=True)
        else:
            print("[ERROR] No se pudo abrir el simulador.")
            sys.exit(1)
    
    print("\n" + "=" * 50)
    print("[INFO] Conectando a: {}".format(config['description']))
    print("   IP: {}".format(config['ip']))
    print("   Puerto: {}".format(config['port']))
    print("=" * 50 + "\n")
    
    return config

if __name__ == "__main__":
    config = main()
    # El script retorna la configuración para que otros módulos la usen
