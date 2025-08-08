#!/bin/bash
cd /Volumes/SSD/RESTAPI
source /Volumes/SSD/RESTAPI/venv311/bin/activate
pkill -f "/Volumes/SSD/RESTAPI/autotrader.py"
/Volumes/SSD/RESTAPI/venv311/bin/python3 /Volumes/SSD/RESTAPI/autotrader.py
