# 분봉 데이터 수집 - 관심종목 설정 가이드

## 개요

`minute_collector.py`는 **보유종목**과 **관심종목**의 분봉 데이터를 자동으로 수집합니다.

## 📋 수집 대상

### 1. 보유종목 (자동)
- 키움증권 API를 통해 자동으로 보유종목을 조회
- 별도 설정 불필요

### 2. 관심종목 (수동 설정)
- `config.yaml`에서 직접 지정
- 보유하지 않은 종목도 분봉 데이터 수집 가능
- 분석용, 모니터링용으로 활용

## ⚙️ config.yaml 설정 방법

### 기본 설정 구조

`config.yaml` 파일에 다음 섹션을 추가하세요:

```yaml
# =============================================================================
# 분봉 데이터 수집 설정
# =============================================================================
minute_collection:
  # 관심종목 리스트 (보유종목 외에 추가로 수집할 종목)
  watchlist:
    - "005930"  # 삼성전자
    - "000660"  # SK하이닉스
    - "035720"  # 카카오
    - "005380"  # 현대차
    - "051910"  # LG화학
    # 필요한 종목을 계속 추가하세요

  # 분봉 수집 개수 (기본값)
  default_minute_count: 120  # 120분 = 2시간

  # 관심종목 수집 활성화
  collect_watchlist: true  # true: 관심종목 수집, false: 보유종목만 수집
```

### 설정 항목 설명

| 항목 | 설명 | 기본값 |
|------|------|--------|
| `watchlist` | 관심종목 코드 리스트 | `[]` (빈 배열) |
| `default_minute_count` | 기본 분봉 수집 개수 | `120` (2시간) |
| `collect_watchlist` | 관심종목 수집 활성화 여부 | `true` |

## 📝 관심종목 추가 방법

### 1. 개별 추가

```yaml
watchlist:
  - "005930"  # 삼성전자
  - "000660"  # SK하이닉스
```

### 2. 카테고리별 정리 (주석 활용)

```yaml
watchlist:
  # 반도체
  - "005930"  # 삼성전자
  - "000660"  # SK하이닉스

  # 자동차
  - "005380"  # 현대차
  - "000270"  # 기아

  # IT/플랫폼
  - "035720"  # 카카오
  - "035420"  # NAVER
```

### 3. 주의사항

- ✅ 종목코드는 **6자리 숫자** (예: `"005930"`)
- ✅ 반드시 **따옴표**로 감싸기 (예: `"005930"`)
- ✅ 각 항목 앞에 **하이픈(`-`)** 필수
- ❌ 공백이나 빈 줄이 있으면 안 됨

**올바른 예시:**
```yaml
watchlist:
  - "005930"
  - "000660"
```

**잘못된 예시:**
```yaml
watchlist:
  - 005930      # 따옴표 없음 ❌
  - "05930"     # 5자리 ❌
  - 005930      # 하이픈 없음 ❌
```

## 🚀 실행 방법

### 1. 기본 실행 (보유종목 + 관심종목)

```bash
python minute_collector.py
```

**동작:**
- 키움 API로 보유종목 조회
- config.yaml의 관심종목 추가
- 합쳐진 종목들의 분봉 데이터 수집 (기본 120분봉)

### 2. 분봉 개수 지정

```bash
# 60분봉 (1시간)
python minute_collector.py --count 60

# 240분봉 (4시간)
python minute_collector.py --count 240
```

### 3. 테스트 모드 (1종목만)

```bash
python minute_collector.py --test
```

### 4. 특정 종목만 수집

```bash
# 삼성전자만
python minute_collector.py --codes 005930

# 여러 종목
python minute_collector.py --codes 005930 000660 035720
```

**참고:** `--codes` 옵션 사용 시 보유종목과 관심종목은 무시됩니다.

### 5. 확인 프롬프트 건너뛰기

```bash
python minute_collector.py -y
```

## 📊 수집 결과 확인

### 전체 현황 확인

```bash
python check_collection_status.py --minute
```

### 특정 종목 확인

```bash
# 삼성전자
python check_collection_status.py --stock 005930

# SK하이닉스
python check_collection_status.py --stock 000660
```

## 💡 활용 예시

### 시나리오 1: 보유종목만 수집

```yaml
minute_collection:
  watchlist: []
  collect_watchlist: false  # 비활성화
```

### 시나리오 2: 관심종목만 수집 (보유종목 제외)

키움 API 없이 관심종목만 수집하려면:

```bash
python minute_collector.py --codes 005930 000660 035720
```

### 시나리오 3: 보유종목 + 관심종목 (권장)

```yaml
minute_collection:
  watchlist:
    - "005930"  # 삼성전자
    - "000660"  # SK하이닉스
    - "035720"  # 카카오
  collect_watchlist: true
```

```bash
python minute_collector.py
```

**결과:** 보유종목 3개 + 관심종목 5개 = 총 8개 종목 수집 (중복 제거)

### 시나리오 4: 자동화 (cron)

```bash
# 매 시간마다 분봉 수집
0 * * * 1-5 cd /Users/jsshin/RESTAPI/analyze && python minute_collector.py -y >> logs/minute_cron.log 2>&1
```

## 🔍 로그 확인

수집 로그는 `logs/minute_collector_YYYYMMDD.log`에 저장됩니다.

```bash
# 오늘 로그 확인
tail -f logs/minute_collector_$(date +%Y%m%d).log

# 관심종목 추가 확인
grep "관심종목" logs/minute_collector_$(date +%Y%m%d).log
```

**예시 로그:**
```
2026-02-09 21:14:21 [INFO] 관심종목 5개 설정됨
2026-02-09 21:14:21 [INFO] 보유종목 3개 조회 완료
2026-02-09 21:14:21 [INFO] 관심종목 5개 추가 완료 (중복 0개 제외)
2026-02-09 21:14:21 [INFO] 총 8개 종목 수집 대상
```

## 🛠️ 문제 해결

### 관심종목이 수집되지 않는 경우

1. **config.yaml 확인**
   ```bash
   grep -A 10 "minute_collection:" config.yaml
   ```

2. **관심종목 활성화 확인**
   ```yaml
   collect_watchlist: true  # false이면 수집 안 됨
   ```

3. **종목코드 형식 확인**
   - 6자리 숫자
   - 따옴표로 감싸기
   - 하이픈(`-`) 붙이기

### 중복 종목 처리

보유종목과 관심종목이 겹치는 경우, **자동으로 중복 제거**됩니다.

**예시:**
- 보유종목: `["005930", "000660", "035720"]`
- 관심종목: `["005930", "005380"]`
- **실제 수집**: `["005930", "000660", "035720", "005380"]` (총 4개)

### 로그에서 확인

```
관심종목 2개 추가 완료 (중복 1개 제외)
```

## 📌 추천 설정

### 일반 투자자

```yaml
minute_collection:
  watchlist:
    - "005930"  # 삼성전자
    - "000660"  # SK하이닉스
    - "035720"  # 카카오
    - "035420"  # NAVER
    - "005380"  # 현대차
  default_minute_count: 120
  collect_watchlist: true
```

### 단타 트레이더

```yaml
minute_collection:
  watchlist:
    # 변동성이 큰 종목
    - "005930"  # 삼성전자
    - "000660"  # SK하이닉스
    - "373220"  # LG에너지솔루션
    - "207940"  # 삼성바이오로직스
  default_minute_count: 240  # 4시간 (장 시작부터)
  collect_watchlist: true
```

### 장기 투자자 (모니터링용)

```yaml
minute_collection:
  watchlist:
    # 주요 우량주
    - "005930"  # 삼성전자
    - "000660"  # SK하이닉스
    - "005380"  # 현대차
    - "051910"  # LG화학
    - "035420"  # NAVER
    - "035720"  # 카카오
  default_minute_count: 60   # 1시간만
  collect_watchlist: true
```

## 🎯 요약

1. **설정 파일**: `config.yaml`의 `minute_collection` 섹션 편집
2. **종목 추가**: `watchlist`에 6자리 종목코드 입력 (따옴표 필수)
3. **실행**: `python minute_collector.py`
4. **확인**: `python check_collection_status.py --minute`

**간단 예시:**
```yaml
minute_collection:
  watchlist:
    - "005930"
    - "000660"
  collect_watchlist: true
```

이제 보유종목과 관심종목 모두의 분봉 데이터를 자동으로 수집할 수 있습니다! 🚀
