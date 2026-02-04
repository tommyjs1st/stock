#!/bin/bash
pkill -f "/Volumes/SSD/RESTAPI/venv311/bin/python3 /Volumes/SSD/RESTAPI/trading_system/main.py"
cd /Volumes/SSD/RESTAPI/trading_system/monitoring
/Volumes/SSD/RESTAPI/venv311/bin/python3 /Volumes/SSD/RESTAPI/trading_system/monitoring/monitoring_server.py &
cd /Volumes/SSD/RESTAPI/trading_system
/Volumes/SSD/RESTAPI/venv311/bin/python3 /Volumes/SSD/RESTAPI/trading_system/main.py  
