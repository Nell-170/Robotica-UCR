#!/usr/bin/env pybricks-micropython
from pybricks.hubs import EV3Brick
from pybricks.ev3devices import ColorSensor
from pybricks.parameters import Port
from pybricks.tools import wait

ev3 = EV3Brick()

eye_right = ColorSensor(Port.S1)
eye_left = ColorSensor(Port.S4)

while True:
    gris_izq = eye_left.reflection()
    gris_der = eye_right.reflection()

    ev3.screen.clear()
    ev3.screen.print("Izq S4: " + str(gris_izq))
    ev3.screen.print("Der S1: " + str(gris_der))

    wait(200)
