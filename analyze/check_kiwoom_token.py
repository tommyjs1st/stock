"""
키움 토큰 상태 확인 및 재발급 스크립트

실행:
  python check_kiwoom_token.py
"""
import json
import os
import requests
import yaml
from datetime import datetime

TOKEN_FILE = "kiwoom_token.json"

with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

kiwoom_config = config.get('kiwoom', {})
BASE_URL   = kiwoom_config.get('base_url', 'https://api.kiwoom.com')
APP_KEY    = kiwoom_config.get('app_key', '')
APP_SECRET = kiwoom_config.get('app_secret', '')

print("=" * 60)
print("키움 토큰 상태 확인")
print("=" * 60)

# ── 1. 저장된 토큰 파일 확인 ─────────────────────────────────
print(f"\n[1] 저장된 토큰 파일: {TOKEN_FILE}")
if os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, 'r', encoding='utf-8') as f:
        token_data = json.load(f)

    print(f"   파일 존재: ✅")
    print(f"   저장된 키 목록: {list(token_data.keys())}")

    expire_str = token_data.get('access_token_token_expired', '')
    requested_at = token_data.get('requested_at', 0)
    token_val = token_data.get('access_token', '')

    print(f"   access_token  : {token_val[:20]}...{token_val[-10:] if token_val else ''}")
    print(f"   만료시각       : {expire_str}")
    print(f"   발급시각(epoch): {requested_at} → {datetime.fromtimestamp(requested_at) if requested_at else 'N/A'}")

    if expire_str:
        try:
            expire_dt = datetime.strptime(expire_str, '%Y-%m-%d %H:%M:%S')
            now = datetime.now()
            diff = expire_dt - now
            if diff.total_seconds() > 0:
                print(f"   토큰 상태     : ✅ 유효 (잔여 {diff})")
            else:
                print(f"   토큰 상태     : ❌ 만료됨 ({abs(diff.total_seconds()/3600):.1f}시간 전)")
        except Exception as e:
            print(f"   만료시각 파싱 오류: {e}")
    else:
        print(f"   만료시각 없음 → 파일 포맷 문제 가능성")
else:
    print(f"   파일 없음: ❌")

# ── 2. 강제 신규 토큰 발급 ───────────────────────────────────
print(f"\n[2] 신규 토큰 강제 발급")
resp = requests.post(
    f"{BASE_URL}/oauth2/token",
    headers={"Content-Type": "application/json; charset=UTF-8"},
    json={
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "secretkey": APP_SECRET
    },
    timeout=15
)

print(f"   HTTP 상태: {resp.status_code}")
if resp.status_code == 200:
    data = resp.json()
    new_token = data.get('token', '')
    expires_dt = data.get('expires_dt', '')  # "20260227102638" 형식
    print(f"   신규 토큰: {new_token[:20]}...{new_token[-10:]}")
    print(f"   만료일시 (원본): {expires_dt}")

    # 파일 저장 포맷 확인 (kiwoom_api_client.py의 save_token 로직과 동일하게)
    if expires_dt:
        try:
            expire_datetime = datetime.strptime(expires_dt, '%Y%m%d%H%M%S')
            print(f"   만료일시 (변환): {expire_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        except Exception as e:
            print(f"   ⚠️ 만료일시 변환 오류: {e}")
            print(f"      → expires_dt 형식이 예상과 다를 수 있음")
            print(f"      → 전체 응답: {data}")

    print(f"\n[3] 신규 토큰으로 ka10080 분봉 API 테스트")
    test_resp = requests.post(
        f"{BASE_URL}/api/dostk/chart",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {new_token}",
            "api-id": "ka10080",
        },
        json={
            "stk_cd": "000660",
            "tic_scope": "1",
            "upd_stkpc_tp": "1"
        },
        timeout=15
    )
    print(f"   HTTP 상태: {test_resp.status_code}")
    test_data = test_resp.json()
    rc = test_data.get('return_code', -1)
    print(f"   return_code: {rc}")
    print(f"   return_msg : {test_data.get('return_msg', '')}")
    if rc == 0:
        records = test_data.get('stk_min_pole_chart_qry', [])
        print(f"   ✅ 분봉 데이터: {len(records)}건")
    else:
        print(f"   ❌ 분봉 API 실패")

else:
    print(f"   ❌ 토큰 발급 실패: {resp.text[:300]}")

print("\n" + "=" * 60)
print("확인 완료")
print("=" * 60)
