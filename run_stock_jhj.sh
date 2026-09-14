#!/bin/bash
cd /Users/jsshin/RESTAPI/analyze
#/Users/jsshin/RESTAPI/venv311/bin/python \
#   /Users/jsshin/RESTAPI/analyze_buying_stocks_jhj.py >>/Users/jsshin/cron.log 2>&1
/Users/jsshin/RESTAPI/venv311/bin/python \
   /Users/jsshin/RESTAPI/analyze/run_score_ranking.py --universe 300 --top-n 30  >>/Users/jsshin/cron.log 2>&1
