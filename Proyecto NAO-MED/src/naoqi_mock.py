# -*- coding: utf-8 -*-
"""
Mock de naoqi para testing sin el SDK real.

En el lab, cuando tengan el SDK oficial de NAOqi 2.8.7.4 instalado,
reemplacen los imports de 'naoqi_mock' por 'naoqi' en nao_controller.py
"""
import time


class ALProxy(object):
    """Mock de ALProxy que simula las acciones del NAO."""
    
    def __init__(self, service_name, ip, port):
        self.service_name = service_name
        self.ip = ip
        self.port = port
        print("[MOCK] ALProxy('{}', '{}', {})".format(service_name, ip, port))
    
    def loadFile(self, path):
        """Mock de loadFile para ALAudioPlayer."""
        print("[MOCK] loadFile('{}')".format(path))
        return 1  # ID ficticio
    
    def play(self, sound_id):
        """Mock de play para ALAudioPlayer."""
        print("[MOCK] play({}) - reproduciendo sonido...".format(sound_id))
        time.sleep(2)  # Simula 2 segundos de sonido
    
    def fadeRGB(self, led_name, color, duration):
        """Mock de fadeRGB para ALLeds."""
        print("[MOCK] fadeRGB('{}', 0x{:06X}, {})".format(led_name, color, duration))
    
    def wakeUp(self):
        """Mock de wakeUp para ALMotion."""
        print("[MOCK] wakeUp()")
    
    def goToPosture(self, posture, speed):
        """Mock de goToPosture para ALRobotPosture."""
        print("[MOCK] goToPosture('{}', {})".format(posture, speed))
    
    def moveTo(self, x, y, theta):
        """Mock de moveTo para ALMotion."""
        print("[MOCK] moveTo({}, {}, {}) - caminando...".format(x, y, theta))
        time.sleep(3)  # Simula 3 segundos de caminata
    
    def say(self, text):
        """Mock de say para ALTextToSpeech."""
        print("[MOCK] say('{}')".format(text))
