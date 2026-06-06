#!/bin/bash

# run locAware for vehicle detection at virtual loops algorithm
pkill -f mrpSpat
sleep 1s

# run bsmSimu for RSU simulation sending BSM messages along a trajectory
pkill -f msgFwd.py
sleep 3s