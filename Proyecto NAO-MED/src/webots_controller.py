# -*- coding: utf-8 -*-
"""
Controlador de NAO para Webots.

Este script corre DENTRO del simulador Webots y controla al NAO simulado.
Se comunica con el proceso externo (main.py) via TCP/sockets.

Para usar en Webots:
1. Copiar este archivo a: Proyecto NAO-MED/webots/controllers/nao_med_controller/
2. En Webots, asignar este script como controlador del robot NAO
3. Ejecutar main.py externamente (que se conectara al simulador)
"""
import socket
import time
import sys

try:
    from controller import Robot
except ImportError:
    print("[ERROR] Este script debe ejecutarse DENTRO de Webots, no externamente")
    sys.exit(1)


class NAOMedController(object):
    """Controlador del NAO para NAO-Med en Webots."""
    
    def __init__(self):
        self.robot = Robot()
        self.timestep = int(self.robot.getBasicTimeStep())
        
        # Obtener referencias a los dispositivos del NAO
        self.motion = self.robot.getDevice("Motion")
        self.posture = self.robot.getDevice("Posture")
        self.tts = self.robot.getDevice("TextToSpeech")
        self.leds = {
            "left_eye": self.robot.getDevice("LeftEyeLed"),
            "right_eye": self.robot.getDevice("RightEyeLed"),
        }
        
        print("[WEBOTS] NAO Med Controller iniciado")
    
    def encender_luces(self, color=0x00A2FF):
        """Enciende las luces de los ojos."""
        for led in self.leds.values():
            if led:
                led.set(color)
        print("[WEBOTS] Luces encendidas: 0x{:06X}".format(color))
    
    def apagar_luces(self):
        """Apaga las luces (blanco)."""
        for led in self.leds.values():
            if led:
                led.set(0xFFFFFF)
        print("[WEBOTS] Luces apagadas")
    
    def reproducir_alarma(self, duracion=2):
        """Simula una alarma (en Webots no hay sonido real, solo log)."""
        print("[WEBOTS] ALARMA SONORA ({} segundos)".format(duracion))
        time.sleep(duracion)
    
    def caminar_hacia_frente(self, distancia=1.0):
        """Hace que el NAO camine hacia el frente."""
        print("[WEBOTS] Caminando {} metros hacia el frente...".format(distancia))
        # En Webots, moveTo es simulado
        if self.motion:
            self.motion.moveTo(distancia, 0.0, 0.0)
        time.sleep(3)  # Simula tiempo de caminata
    
    def decir_frase(self, medicamento):
        """Hace que el NAO diga la frase del medicamento."""
        frase = "Te toca tu medicina, por favor tomate el {}".format(medicamento)
        print("[WEBOTS] Diciendo: {}".format(frase))
        if self.tts:
            self.tts.speak(frase)
    
    def ejecutar_notificacion(self, medicamento):
        """Ejecuta la secuencia completa de notificacion."""
        print("[WEBOTS] === NOTIFICACION DE MEDICAMENTO ===")
        print("[WEBOTS] Medicamento: {}".format(medicamento))
        
        self.reproducir_alarma(2)
        self.encender_luces()
        self.caminar_hacia_frente(1.0)
        self.decir_frase(medicamento)
        self.apagar_luces()
        
        print("[WEBOTS] === NOTIFICACION COMPLETADA ===")
    
    def run(self):
        """Bucle principal del controlador."""
        print("[WEBOTS] Controlador corriendo...")
        
        while self.robot.step(self.timestep) != -1:
            # El controlador espera comandos del proceso externo
            # Por ahora, solo mantiene el robot en pie
            pass


if __name__ == "__main__":
    controller = NAOMedController()
    controller.run()
