#!/bin/bash

# 급락 매수 전략 실행 스크립트

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 드라이런 모드 체크
if [ "$1" == "--dry-run" ] || [ "$1" == "--test" ]; then
    MODE="드라이런 (테스트)"
    DRY_RUN_FLAG="--dry-run"
else
    MODE="실전"
    DRY_RUN_FLAG=""
fi

echo "🚀 급락 매수 전략 시작 ($MODE)..."
echo "📁 작업 디렉토리: $SCRIPT_DIR"
echo "⏰ 시작 시간: $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# Python 가상환경 활성화 (필요한 경우)
# source venv/bin/activate

# 프로그램 실행
python3 sharp_decline_trader.py $DRY_RUN_FLAG

EXIT_CODE=$?

echo "=========================================="
echo "⏰ 종료 시간: $(date '+%Y-%m-%d %H:%M:%S')"
echo "📊 종료 코드: $EXIT_CODE"

exit $EXIT_CODE
