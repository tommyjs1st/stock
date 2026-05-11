#!/bin/bash
# backfill_snapshot.sh
# 사용법: bash backfill_snapshot.sh

ANALYZE_DIR="/Users/jsshin/RESTAPI/analyze"
PYTHON="/Volumes/SSD/RESTAPI/venv311/bin/python3"

cd "$ANALYZE_DIR"

START="2025-01-01"
END=$(date +%Y-%m-%d)

current="$START"

while [[ "$current" < "$END" || "$current" == "$END" ]]; do
    # 주말 스킵 (1=월 ~ 7=일, 6=토, 7=일)
    dow=$(date -d "$current" +%u 2>/dev/null || date -j -f "%Y-%m-%d" "$current" +%u)
    
    if [[ "$dow" -lt 6 ]]; then
        date_fmt=$(echo "$current" | tr -d '-')  # YYYYMMDD 형식
        echo "▶ $current 처리 중..."
        $PYTHON save_daily_snapshot.py --date "$date_fmt"
        
        if [[ $? -ne 0 ]]; then
            echo "❌ $current 실패 - 계속 진행합니다."
        fi
        
        sleep 1  # API 부하 방지
    else
        echo "⏭️  $current 주말 스킵"
    fi
    
    # 다음 날짜로 (macOS/Linux 호환)
    current=$(date -d "$current + 1 day" +%Y-%m-%d 2>/dev/null || \
              date -j -v+1d -f "%Y-%m-%d" "$current" +%Y-%m-%d)
done

echo "✅ 백필 완료"
