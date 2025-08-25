#!/bin/bash
cd /Volumes/SSD/RESTAPI
source /Volumes/SSD/RESTAPI/venv311/bin/activate
pkill -f "/Volumes/SSD/RESTAPI/venv311/bin/python3 /Volumes/SSD/RESTAPI/trading_system/main.py"
cd /Volumes/SSD/RESTAPI/trading_system
/Volumes/SSD/RESTAPI/venv311/bin/python3 /Volumes/SSD/RESTAPI/trading_system/main.py
cd /Volumes/SSD/RESTAPI/trading_system/monitoring
/Volumes/SSD/RESTAPI/venv311/bin/python3 /Volumes/SSD/RESTAPI/trading_system/monitoring/monitoring_server.py
