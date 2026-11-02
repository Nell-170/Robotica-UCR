#!/usr/bin/env pybricks-micropython
from pybricks.hubs import EV3Brick
from pybricks.ev3devices import UltrasonicSensor
from pybricks.parameters import Port
from pybricks.tools import wait

ev3 = EV3Brick()
opponent_sensor = UltrasonicSensor(Port.S2)

while True:
    ev3.screen.clear()
    ev3.screen.print("Distancia (mm):")
    ev3.screen.print(opponent_sensor.distance())
    wait(200)