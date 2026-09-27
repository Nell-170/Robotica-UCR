"""
Prueba de conexión a NAO - Real o Simulador
"""
import sys
from pathlib import Path

# Importar el conector de robot
sys.path.insert(0, str(Path(__file__).parent))
from robot_connector import main as connect_robot

try:
    from naoqi import ALProxy
except ImportError:
    print("⚠️  naoqi no está instalado. Usando simulador...")
    ALProxy = None

def main():
    # Detecta NAO o abre simulador
    config = connect_robot()
    
    if ALProxy is None:
        print("⚠️  No se puede usar ALProxy sin naoqi instalado.")
        print("   Pero el simulador Webots está abierto.")
        print("   Puedes conectarte manualmente o instalar naoqi.")
        return
    
    # Conecta al robot (real o simulador)
    try:
        tts = ALProxy("ALTextToSpeech", config["ip"], config["port"])
        tts.say("Python also works")
        print("✅ Mensaje enviado al robot")
    except Exception as e:
        print(f"❌ Error al conectar: {e}")
        print(f"   Tipo: {config['type']}")
        print(f"   IP: {config['ip']}")

if __name__ == "__main__":
    main()