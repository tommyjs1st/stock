#!/bin/bash
cd /Volumes/SSD/RESTAPI
source /Volumes/SSD/RESTAPI/venv311/bin/activate
/Volumes/SSD/RESTAPI/venv311/bin/python3 /Volumes/SSD/RESTAPI/backtest.py
/Volumes/SSD/RESTAPI/venv311/bin/python3 /Volumes/SSD/RESTAPI/analyze_buying_stocks.py
