#!/usr/bin/env pybricks-micropython
from pybricks.hubs import EV3Brick
from pybricks.ev3devices import Motor, ColorSensor, UltrasonicSensor
from pybricks.parameters import Button, Port
from pybricks.tools import wait, StopWatch

ev3 = EV3Brick()

left = Motor(Port.C)
right = Motor(Port.B)
eye_right = ColorSensor(Port.S1)
eye_left = ColorSensor(Port.S4)
opponent_sensor = UltrasonicSensor(Port.S2)

ATTACK_SPEED = 1000
BACK_SPEED = 800
TURN_SPEED = 600
SEARCH_SPEED = 350
EDGE_REFLECTION = 12 # Cambiar en la pelea
OPPONENT_DISTANCE = 1000


def drive(left_speed, right_speed):
    left.run(left_speed)
    right.run(right_speed)


def edge_left():
    return eye_left.reflection() <= EDGE_REFLECTION


def edge_right():
    return eye_right.reflection() <= EDGE_REFLECTION


def escape(l_hit, r_hit):
    timer = StopWatch()
    while timer.time() < 700 and (edge_left() or edge_right()):
        drive(-BACK_SPEED, -BACK_SPEED)
        wait(10)

    drive(0, 0)
    if l_hit and not r_hit:
        turn_left, turn_right, turn_time = TURN_SPEED, -TURN_SPEED, 300
    elif r_hit and not l_hit:
        turn_left, turn_right, turn_time = -TURN_SPEED, TURN_SPEED, 300
    else:
        turn_left, turn_right, turn_time = TURN_SPEED, -TURN_SPEED, 500

    timer.reset()
    while timer.time() < turn_time and not (edge_left() or edge_right()):
        drive(turn_left, turn_right)
        wait(10)
    drive(0, 0)


def search_for_opponent():
    drive(SEARCH_SPEED, -SEARCH_SPEED)


ev3.speaker.beep()
while Button.CENTER not in ev3.buttons.pressed():
    wait(10)

while True:
    l_hit = edge_left()
    r_hit = edge_right()

    if l_hit or r_hit:
        escape(l_hit, r_hit)
        continue

    distance = opponent_sensor.distance()
    if 0 < distance <= OPPONENT_DISTANCE:
        drive(ATTACK_SPEED, ATTACK_SPEED)
    else:
        search_for_opponent()
    wait(10)
