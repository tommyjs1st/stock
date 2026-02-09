# 급락 매수 전략 (Sharp Decline Trading)

## 📋 전략 개요

- **대상**: 코스피 시가총액 상위 200개 종목 (제외 목록 제외)
- **매수 시간**: 9:00 ~ 9:30
- **매수 조건**: 전일 종가 대비 15% 이상 하락 → 시장가 매수
- **매도 시간**: 오후 3시 (15:00) → 시장가 전량 매도
- **안전장치**: 당일 급락매수한 종목만 매도 (다른 보유 종목 안전)

## 🚀 빠른 시작 (zsh 사용자)

### 1단계: alias 설정 (최초 1회만)

```bash
cd /Users/jsshin/RESTAPI/trading_system
./setup_alias.sh
source ~/.zshrc
```

### 2단계: 전일 종가 수집

```bash
전일종가수집
```

### 3단계: 테스트 실행

```bash
# 설정 확인
급락설정확인

# 드라이런 모드 테스트 (실제 주문 없음)
급락테스트
```

### 4단계: 실전 실행

```bash
# 월요일 오전 8:50~8:55에 실행
급락매수
```

## 📝 사용 가능한 명령어

| 명령어 | 설명 | 실제 명령어 |
|--------|------|------------|
| `급락테스트` | 드라이런 모드 (시뮬레이션) | `python3 sharp_decline_trader.py --dry-run` |
| `급락매수` | 실전 모드 (실제 주문) | `python3 sharp_decline_trader.py` |
| `급락설정확인` | 설정 및 DB 확인 | `python3 test_sharp_decline.py` |
| `전일종가수집` | 전일 종가 데이터 수집 | `python daily_collector.py --daily` |

## 🔧 수동 실행 방법 (alias 없이)

```bash
# 1. 전일 종가 수집
cd /Users/jsshin/RESTAPI/analyze
python daily_collector.py --daily

# 2. 설정 확인
cd /Users/jsshin/RESTAPI/trading_system
python3 test_sharp_decline.py

# 3. 드라이런 테스트
python3 sharp_decline_trader.py --dry-run

# 4. 실전 실행
python3 sharp_decline_trader.py
```

## 📊 실행 흐름

```
08:50  프로그램 시작
       ↓
       코스피 상위 200개 조회
       전일 종가 DB에서 로드
       ↓
09:00  급락 모니터링 시작 (30초마다)
~      15% 이상 하락 종목 발견
09:30  → 시장가 매수
       → purchased_stocks_YYYYMMDD.json 저장
       ↓
15:00  급락매수한 종목만 시장가 매도
       → 파일 삭제
       ↓
       프로그램 종료
```

## ⚠️ 안전장치

### ✅ 당일 급락매수 종목만 매도
- `purchased_stocks` 딕셔너리로 추적
- `strategy: 'sharp_decline'` 태그 추가
- 다른 전략 보유 종목은 절대 매도 안함

### ✅ 프로그램 재시작 안전
- 매수 즉시 파일 저장
- 재시작 시 자동 로드
- 오후 3시에 정확히 매도

### ✅ 계좌 확인
- 매도 전 계좌에 실제로 있는지 확인
- 없으면 스킵

## 📁 생성 파일

- `purchased_stocks_20260208.json` - 당일 급락매수 종목 목록
- `stock_names.json` - 종목명 캐시
- `exclude_stocks.json` - 제외 종목 목록 (수동 편집 가능)

## 🔧 설정 변경

### 제외 종목 추가

`exclude_stocks.json` 파일 수정:

```json
[
  "005930",
  "000660",
  "035720"
]
```

### 하락률 변경

`sharp_decline_trader.py` 파일 수정:

```python
self.decline_threshold = 0.15  # 15% → 원하는 비율로 변경
```

### 매수/매도 시간 변경

```python
self.buy_time_start = (9, 0)   # 9:00
self.buy_time_end = (9, 30)    # 9:30
self.sell_time = (15, 0)       # 15:00
```

## 🔔 Discord 알림

프로그램 실행 중 다음 상황에서 Discord 알림이 전송됩니다:

- 🚀 프로그램 시작
- 🔥 급락 감지
- ✅ 매수 완료
- ✅ 매도 완료
- ❌ 오류 발생

## 🧪 테스트 모드

### 드라이런 모드 특징
- ✅ 실제 주문 없이 시뮬레이션만
- ✅ 모든 로직 실행 (급락 감지, 시간 체크 등)
- ✅ 로그에 `🧪 [드라이런]` 표시
- ✅ Discord 알림 주황색으로 전송
- ✅ 파일 저장/로드 테스트

## 📝 로그 확인

```bash
# 실시간 로그 보기
tail -f logs/sharp_decline_trader_*.log

# 최근 로그 확인
ls -lt logs/sharp_decline_trader_*.log | head -1
```

## 💡 팁

1. **매일 전일 종가 수집 필수**
   ```bash
   전일종가수집  # 매일 실행
   ```

2. **드라이런으로 먼저 테스트**
   ```bash
   급락테스트  # 월요일 아침에 먼저 테스트
   ```

3. **로그 모니터링**
   ```bash
   tail -f logs/sharp_decline_trader_*.log
   ```

4. **제외 종목 관리**
   - 삼성전자, SK하이닉스 등 대형주는 제외 권장
   - 변동성 큰 종목 위주로 매매

## 📞 문제 해결

### DB 연결 오류
```bash
brew services list | grep mysql
brew services start mysql
```

### 전일 종가 데이터 없음
```bash
전일종가수집
```

### 모듈 import 오류
```bash
cd /Users/jsshin/RESTAPI/trading_system
python3 -c "import sys; sys.path.insert(0, '.'); from utils.logger import setup_logger"
```

---

**준비 완료!** 월요일 아침에 `급락테스트`로 먼저 확인해보세요! 🚀
