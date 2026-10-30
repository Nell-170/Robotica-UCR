#!/usr/bin/env pybricks-micropython
from pybricks.hubs import EV3Brick
from pybricks.ev3devices import Motor, ColorSensor
from pybricks.parameters import Button, Port
from pybricks.tools import wait, StopWatch

ev3 = EV3Brick()

left      = Motor(Port.C)
right     = Motor(Port.B)
eye_right = ColorSensor(Port.S1)
eye_left  = ColorSensor(Port.S4)

# Tuning
ATTACK_SPEED = 1000
BACK_SPEED   = 800
TURN_SPEED   = 600
EDGE_LIGHT   = 50

def drive(l, r):
    left.run(l)
    right.run(r)

def edge_left():
    return eye_left.reflection() > EDGE_LIGHT

def edge_right():
    return eye_right.reflection() > EDGE_LIGHT

def escape(l_hit, r_hit):
    timer = StopWatch()
    while timer.time() < 700:
        if not edge_left() and not edge_right():
            break
        drive(-BACK_SPEED, -BACK_SPEED)
        wait(10)
    drive(0, 0)
    if edge_left() or edge_right():
        return

    if l_hit and not r_hit:
        turn_l, turn_r, turn_time = TURN_SPEED, -TURN_SPEED, 300
    elif r_hit and not l_hit:
        turn_l, turn_r, turn_time = -TURN_SPEED, TURN_SPEED, 300
    else:
        turn_l, turn_r, turn_time = TURN_SPEED, -TURN_SPEED, 500

    timer.reset()
    while timer.time() < turn_time:
        if edge_left() or edge_right():
            break
        drive(turn_l, turn_r)
        wait(10)
    drive(0, 0)

# Start when the central button is pressed.
ev3.speaker.beep()
while Button.CENTER not in ev3.buttons.pressed():
    wait(10)

while True:
    l_hit = edge_left()
    r_hit = edge_right()

    if l_hit or r_hit:
        escape(l_hit, r_hit)
        continue

    drive(ATTACK_SPEED, ATTACK_SPEED)
    wait(10)