#!/bin/bash
cd /Users/jsshin/RESTAPI
source /Users/jsshin/RESTAPI/venv311/bin/activate
/Users/jsshin/RESTAPI/venv311/bin/python3 /Users/jsshin/RESTAPI/analyze_buying_stocks_jhj.py >>/Users/jsshin/cron.log 2>&1
