#!/bin/bash
# 포트폴리오 모니터링 앱 실행 스크립트

cd "$(dirname "$0")"

# 비밀번호 설정 (변경하세요!)
export APP_PASSWORD="portfolio2026"

echo "🚀 포트폴리오 모니터링 앱 시작..."
echo "📱 브라우저에서 http://localhost:8501 접속"
echo "🔐 비밀번호: $APP_PASSWORD"
echo ""

streamlit run portfolio_monitor_app.py
