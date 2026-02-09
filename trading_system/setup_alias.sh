#!/bin/zsh

# 급락 매수 전략 alias 설정 스크립트 (zsh용)

TRADING_DIR="/Users/jsshin/RESTAPI/trading_system"
ANALYZE_DIR="/Users/jsshin/RESTAPI/analyze"

echo "🔧 급락 매수 전략 alias 설정 중..."

# .zshrc에 alias 추가
ZSHRC="$HOME/.zshrc"

# 백업
if [ -f "$ZSHRC" ]; then
    cp "$ZSHRC" "$ZSHRC.backup.$(date +%Y%m%d_%H%M%S)"
    echo "✅ .zshrc 백업 완료"
fi

# 기존 alias 제거 (있으면)
sed -i.bak '/# 급락 매수 전략 alias/,/# 급락 매수 전략 끝/d' "$ZSHRC" 2>/dev/null

# 새로운 alias 추가
cat >> "$ZSHRC" << 'EOF'

# 급락 매수 전략 alias
alias 급락매수="cd /Users/jsshin/RESTAPI/trading_system && python3 sharp_decline_trader.py"
alias 급락테스트="cd /Users/jsshin/RESTAPI/trading_system && python3 sharp_decline_trader.py --dry-run"
alias 급락설정확인="cd /Users/jsshin/RESTAPI/trading_system && python3 test_sharp_decline.py"
alias 전일종가수집="cd /Users/jsshin/RESTAPI/analyze && python daily_collector.py --daily"
# 급락 매수 전략 끝
EOF

echo "✅ .zshrc에 alias 추가 완료"
echo ""
echo "사용 가능한 명령어:"
echo "  급락테스트      - 드라이런 모드로 테스트"
echo "  급락매수        - 실전 모드로 실행"
echo "  급락설정확인    - 설정 및 DB 확인"
echo "  전일종가수집    - 전일 종가 데이터 수집"
echo ""
echo "⚠️  alias를 사용하려면 터미널을 재시작하거나 다음 명령어 실행:"
echo "  source ~/.zshrc"
