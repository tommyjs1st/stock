#!/bin/zsh
# 1. 작업 디렉토리 설정 (스크립트가 파일에 접근할 때의 기준 경로)
cd /Users/jsshin/RESTAPI/analyze

# 2. 가상 환경의 파이썬 인터프리터와 실행할 스크립트를 모두 절대 경로로 지정하여 실행
/Users/jsshin/RESTAPI/venv311/bin/python /Users/jsshin/RESTAPI/analyze/main.py  >> /Users/jsshin/cron.log 2>&1

