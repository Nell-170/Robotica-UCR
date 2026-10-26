#!/usr/bin/env pybricks-micropython
from pybricks.hubs import EV3Brick
from pybricks.ev3devices import Motor, UltrasonicSensor, ColorSensor
from pybricks.parameters import Port
from pybricks.tools import wait, StopWatch

ev3 = EV3Brick()

left      = Motor(Port.C)
right     = Motor(Port.B)
eye_right = ColorSensor(Port.S1)
eye_left  = ColorSensor(Port.S4)
eyes      = UltrasonicSensor(Port.S2)

# Tuning
SEARCH_SPEED = 400
ATTACK_SPEED = 1000
BACK_SPEED   = 800
TURN_SPEED   = 600
DETECT_DIST  = 500
EDGE_LIGHT   = 50

def drive(l, r):
    left.run(l)
    right.run(r)

def edge_left():
    return eye_left.reflection() > EDGE_LIGHT

def edge_right():
    return eye_right.reflection() > EDGE_LIGHT

def escape(l_hit, r_hit):
    drive(-BACK_SPEED, -BACK_SPEED)
    wait(300)
    if l_hit and not r_hit:
        drive(TURN_SPEED, -TURN_SPEED)     # edge on left -> turn right
        wait(300)
    elif r_hit and not l_hit:
        drive(-TURN_SPEED, TURN_SPEED)     # edge on right -> turn left
        wait(300)
    else:
        drive(TURN_SPEED, -TURN_SPEED)     # both -> half turn
        wait(500)

# Start button + 5 second rule
ev3.speaker.beep()
while not ev3.buttons.pressed():
    wait(10)
while ev3.buttons.pressed():
    wait(10)
wait(5000)

direction = 1
spin_timer = StopWatch()

while True:
    l_hit = edge_left()
    r_hit = edge_right()

    # 1. Edge safety
    if l_hit or r_hit:
        escape(l_hit, r_hit)
        continue

    # 2. Opponent seen -> charge
    if eyes.distance() < DETECT_DIST:
        drive(ATTACK_SPEED, ATTACK_SPEED)

    # 3. Search by spinning, switching direction every 2 s
    else:
        if spin_timer.time() > 2000:
            direction *= -1
            spin_timer.reset()
        drive(SEARCH_SPEED * direction, -SEARCH_SPEED * direction)

    wait(10)