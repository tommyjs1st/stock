"""
키움 REST API 주식분봉차트 (ka10080) 테스트 v2

목적:
  - ka10080 API 동작 확인
  - 응답 필드명 및 구조 파악
  - NXT 시간외(15:30~20:00) 데이터 포함 여부 확인
  - 페이징(연속조회) 동작 확인

실행:
  python test_kiwoom_minute.py
  python test_kiwoom_minute.py --code 000660   # 종목 지정
  python test_kiwoom_minute.py --tic 3         # 3분봉 테스트
"""
import requests
import json
import yaml
import argparse
from datetime import datetime

# ─────────────────────────────────────────────
# 설정 로드
# ─────────────────────────────────────────────
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

kiwoom_config = config.get('kiwoom', {})
BASE_URL   = kiwoom_config.get('base_url', 'https://api.kiwoom.com')
APP_KEY    = kiwoom_config.get('app_key', '')
APP_SECRET = kiwoom_config.get('app_secret', '')

# ─────────────────────────────────────────────
# 인수 파싱
# ─────────────────────────────────────────────
parser = argparse.ArgumentParser(description='키움 분봉 API 테스트')
parser.add_argument('--code', default='005930', help='종목코드 (기본: 005930 삼성전자)')
parser.add_argument('--tic',  default='1',      help='분봉 단위 (기본: 1분봉)')
args = parser.parse_args()

STOCK_CODE = args.code
TIC_SCOPE  = args.tic

print("=" * 70)
print(f"  키움 REST API 주식분봉차트 (ka10080) 테스트 v2")
print(f"  실행시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  종목코드: {STOCK_CODE}  /  분봉단위: {TIC_SCOPE}분봉")
print("=" * 70)


# ─────────────────────────────────────────────
# STEP 1. 토큰 발급
# ─────────────────────────────────────────────
print("\n[STEP 1] 토큰 발급")
print("-" * 50)

token_response = requests.post(
    f"{BASE_URL}/oauth2/token",
    headers={"Content-Type": "application/json; charset=UTF-8"},
    json={
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "secretkey": APP_SECRET
    },
    timeout=15
)

if token_response.status_code != 200:
    print(f"❌ 토큰 발급 실패 (HTTP {token_response.status_code})")
    print(f"   응답: {token_response.text[:300]}")
    exit(1)

token_data = token_response.json()
TOKEN = token_data.get('token')

if not TOKEN:
    print(f"❌ 토큰 없음. 응답 키: {list(token_data.keys())}")
    exit(1)

print(f"✅ 토큰 발급 성공: {TOKEN[:20]}...{TOKEN[-10:]}")


# ─────────────────────────────────────────────
# 공통 헤더
# ─────────────────────────────────────────────
def make_headers(api_id: str, cont_yn: str = "N", next_key: str = "") -> dict:
    h = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {TOKEN}",
        "api-id": api_id,
    }
    if cont_yn == "Y":
        h["cont-yn"] = cont_yn
        h["next-key"] = next_key
    return h


# ─────────────────────────────────────────────
# STEP 2. 1차 분봉 조회
# ─────────────────────────────────────────────
print(f"\n[STEP 2] 분봉 1차 조회 (종목: {STOCK_CODE}, {TIC_SCOPE}분봉)")
print("-" * 50)

url = f"{BASE_URL}/api/dostk/chart"

params_1st = {
    "stk_cd":       STOCK_CODE,   # 종목코드
    "tic_scope":    TIC_SCOPE,    # 분봉 단위 (1, 3, 5, 10, 15, 30, 60)
    "upd_stkpc_tp": "1"           # 수정주가구분: 0=미적용, 1=적용 (필수값)
}

print(f"요청 파라미터: {json.dumps(params_1st, ensure_ascii=False)}")

resp_1st = requests.post(
    url,
    headers=make_headers("ka10080"),
    json=params_1st,
    timeout=15
)

print(f"HTTP 상태: {resp_1st.status_code}")

if resp_1st.status_code != 200:
    print(f"❌ API 호출 실패")
    print(f"   응답: {resp_1st.text[:500]}")
    exit(1)

data_1st = resp_1st.json()

# ─────────────────────────────────────────────
# 응답 구조 분석
# ─────────────────────────────────────────────
print("\n▶ 응답 최상위 키:")
for k, v in data_1st.items():
    if isinstance(v, list):
        print(f"   [{k}] → list, {len(v)}건")
    elif isinstance(v, dict):
        print(f"   [{k}] → dict, 키: {list(v.keys())}")
    else:
        print(f"   [{k}] → {repr(v)}")

return_code = data_1st.get('return_code', 'N/A')
return_msg  = data_1st.get('return_msg', '')
print(f"\n▶ return_code: {return_code}")
print(f"▶ return_msg : {return_msg}")

if return_code != 0:
    print(f"\n❌ API 오류 응답. 전체 응답:")
    print(json.dumps(data_1st, ensure_ascii=False, indent=2))
    exit(1)

# 연속조회 키 확인 (헤더 또는 본문 모두 확인)
resp_cont_yn  = resp_1st.headers.get('cont-yn',  data_1st.get('cont_yn',  'N/A'))
resp_next_key = resp_1st.headers.get('next-key', data_1st.get('next_key', ''))
print(f"\n▶ 응답 헤더 cont-yn : {resp_1st.headers.get('cont-yn', '없음')}")
print(f"▶ 응답 헤더 next-key: {repr(resp_1st.headers.get('next-key', '없음'))}")
print(f"▶ 응답 본문 cont_yn : {data_1st.get('cont_yn', '없음')}")
print(f"▶ 응답 본문 next_key: {repr(data_1st.get('next_key', '없음'))}")

# ─────────────────────────────────────────────
# 데이터 리스트 키 자동 탐색
# ─────────────────────────────────────────────
data_key = None
for k, v in data_1st.items():
    if isinstance(v, list) and len(v) > 0:
        data_key = k
        break

if data_key is None:
    print("\n⚠️ 리스트 형태의 데이터 키를 찾지 못했습니다.")
    print("전체 응답:")
    print(json.dumps(data_1st, ensure_ascii=False, indent=2)[:3000])
    exit(1)

records_1st = data_1st[data_key]
print(f"\n▶ 데이터 키: '{data_key}', 건수: {len(records_1st)}")

# ─────────────────────────────────────────────
# 첫/마지막 레코드 필드 구조 출력
# ─────────────────────────────────────────────
if records_1st:
    print("\n▶ 첫 번째 레코드 (최신 데이터) 전체 필드:")
    first = records_1st[0]
    for k, v in first.items():
        print(f"   {k:35s} = {repr(v)}")

    if len(records_1st) > 1:
        print("\n▶ 마지막 레코드 (가장 오래된 데이터):")
        last = records_1st[-1]
        for k, v in last.items():
            print(f"   {k:35s} = {repr(v)}")


# ─────────────────────────────────────────────
# STEP 3. 시간 범위 분석 (NXT 포함 여부)
# ─────────────────────────────────────────────
print(f"\n[STEP 3] 시간 범위 분석")
print("-" * 50)

# 시간 관련 필드 자동 탐색
time_fields = []
if records_1st:
    for k in records_1st[0].keys():
        kl = k.lower()
        if any(kw in kl for kw in ['time', 'hour', 'tm', 'dt', 'date', 'cntg', 'cntr']):
            time_fields.append(k)

print(f"▶ 시간 관련 필드 후보: {time_fields}")

# 모든 시간값 수집
all_times = []
for r in records_1st:
    for tf in time_fields:
        val = str(r.get(tf, '')).strip()
        if val and len(val) >= 4:
            all_times.append(val)
            break

if all_times:
    print(f"▶ 수집된 시간값 샘플 (앞 5개): {all_times[:5]}")
    print(f"▶ 수집된 시간값 샘플 (뒤 5개): {all_times[-5:]}")

    def extract_time_part(t):
        """다양한 형식에서 HHMMSS 추출"""
        t = t.replace(' ', '').replace(':', '').replace('-', '')
        if len(t) >= 14:
            return t[8:14]   # YYYYMMDDHHMMSS
        elif len(t) >= 12:
            return t[6:12]
        elif len(t) >= 6:
            return t[-6:]
        elif len(t) == 4:
            return t + '00'
        return t

    time_parts = [extract_time_part(t) for t in all_times if t]
    valid_times = [t for t in time_parts if t.isdigit()]

    after_1530 = [t for t in valid_times if t >= '153000']
    after_1800 = [t for t in valid_times if t >= '180000']
    after_2000 = [t for t in valid_times if t >= '200000']

    print(f"\n▶ 정규장 마감(15:30) 이후 데이터: {len(after_1530)}건")
    if after_1530:
        print(f"   시간 예시: {sorted(set(after_1530))[:10]}")
        print(f"   ✅ NXT 시간외 데이터 포함!")

    print(f"▶ 18:00 이후 데이터           : {len(after_1800)}건")
    if after_1800:
        print(f"   시간 예시: {sorted(set(after_1800))[:10]}")

    print(f"▶ 20:00 이후 데이터           : {len(after_2000)}건")
    if after_2000:
        print(f"   시간 예시: {sorted(set(after_2000))[:10]}")
        print(f"   ✅ NXT 저녁 거래 데이터 포함!")

    if not after_1530:
        print(f"\n   ℹ️  현재 {datetime.now().strftime('%H:%M')} - 정규장 중 또는 NXT 미지원일 수 있음")
        print(f"      NXT 확인은 15:30 이후 재실행 권장")
else:
    print("⚠️ 시간 필드를 찾지 못했습니다.")
    if records_1st:
        print("   전체 첫 레코드:")
        print(json.dumps(records_1st[0], ensure_ascii=False, indent=2))


# ─────────────────────────────────────────────
# STEP 4. 연속조회 테스트
# ─────────────────────────────────────────────
print(f"\n[STEP 4] 연속조회 테스트")
print("-" * 50)

if resp_cont_yn == 'Y' and resp_next_key:
    print(f"✅ 연속조회 가능 → next-key: {repr(resp_next_key)}")

    params_2nd = {
        "stk_cd":       STOCK_CODE,
        "tic_scope":    TIC_SCOPE,
        "upd_stkpc_tp": "1",
    }

    resp_2nd = requests.post(
        url,
        headers=make_headers("ka10080", cont_yn="Y", next_key=resp_next_key),
        json=params_2nd,
        timeout=15
    )

    print(f"2차 HTTP 상태: {resp_2nd.status_code}")

    if resp_2nd.status_code == 200:
        data_2nd = resp_2nd.json()
        rc2 = data_2nd.get('return_code', 'N/A')
        print(f"2차 return_code: {rc2}")

        records_2nd = data_2nd.get(data_key, [])
        print(f"✅ 2차 조회 성공: {len(records_2nd)}건")

        cont_2nd  = resp_2nd.headers.get('cont-yn',  data_2nd.get('cont_yn',  'N/A'))
        nkey_2nd  = resp_2nd.headers.get('next-key', data_2nd.get('next_key', ''))
        print(f"   2차 cont-yn : {cont_2nd}")
        print(f"   2차 next-key: {repr(nkey_2nd)}")

        if records_2nd and time_fields:
            print(f"   2차 첫 레코드 시간:")
            for tf in time_fields:
                if tf in records_2nd[0]:
                    print(f"     {tf} = {records_2nd[0][tf]}")
            print(f"   2차 마지막 레코드 시간:")
            for tf in time_fields:
                if tf in records_2nd[-1]:
                    print(f"     {tf} = {records_2nd[-1][tf]}")
    else:
        print(f"❌ 2차 조회 실패: {resp_2nd.text[:300]}")
else:
    print(f"연속조회 없음 (cont-yn={resp_cont_yn})")
    # 응답 본문에서 연속조회 관련 키 추가 탐색
    nxt_candidates = {k: v for k, v in data_1st.items()
                      if any(x in k.lower() for x in ['next', 'cont', 'key', 'cursor', 'page'])}
    if nxt_candidates:
        print(f"  응답 본문 연속조회 관련 키: {nxt_candidates}")


# ─────────────────────────────────────────────
# STEP 5. DB 컬럼 매핑 가이드
# ─────────────────────────────────────────────
print(f"\n[STEP 5] DB 저장용 컬럼 매핑 가이드")
print("-" * 50)
print("현재 DB 포맷:")
print("  trade_datetime, open_price, high_price, low_price,")
print("  close_price, volume, trading_value")
print()

if records_1st:
    sample = records_1st[0]
    print("ka10080 응답 필드 매핑 후보 (★ 표시):")
    for k, v in sample.items():
        hint = ""
        kl = k.lower()
        if any(x in kl for x in ['open', 'oprc', 'strt', 'op']):
            hint = "← open_price 후보"
        elif any(x in kl for x in ['high', 'hgpr', 'hg']):
            hint = "← high_price 후보"
        elif any(x in kl for x in ['low', 'lwpr', 'lw']):
            hint = "← low_price 후보"
        elif any(x in kl for x in ['close', 'prpr', 'clpr', 'cur', 'prc', 'end']):
            hint = "← close_price 후보"
        elif any(x in kl for x in ['vol', 'qty']):
            hint = "← volume 후보"
        elif any(x in kl for x in ['amt', 'value', 'trad']):
            hint = "← trading_value 후보"
        elif any(x in kl for x in ['time', 'tm', 'hour', 'date', 'dt', 'cntg']):
            hint = "← trade_datetime 후보"

        marker = "  ★" if hint else "   "
        print(f"{marker} {k:35s} = {repr(str(v)):25s}  {hint}")

print("\n" + "=" * 70)
print("테스트 완료")
print("=" * 70)
print()
print("다음 단계:")
print("  1. ★ 표시 필드명 확인 → 컬럼 매핑 결정")
print("  2. NXT 데이터 포함 여부 확인 (없으면 15:30 이후 재실행)")
print("  3. 확인 후 kiwoom_api_client.py 및 minute_collector.py 수정 진행")
