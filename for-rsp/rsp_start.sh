#!/bin/bash

sleep 10s

# run mrp spat process for SPaT message generation
/home/calpath/mrp/spat/obj/mrpSpat -s /home/calpath/mrp/conf/spat.conf >/dev/null &
sleep 5s

# run message forwarding script
python3 /home/calpath/mrp/snmp/msgFwd.py > /dev/null 2>&1 &
sleep 5s

wait

