"""
키움증권 API 엔드포인트 테스트
다양한 엔드포인트를 시도해서 올바른 경로 찾기
"""
import requests
import json
import yaml

# config.yaml에서 설정 로드
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

kiwoom_config = config.get('kiwoom', {})
base_url = kiwoom_config.get('base_url', 'https://api.kiwoom.com')

# 토큰 발급
print("토큰 발급 중...")
token_response = requests.post(
    f"{base_url}/oauth2/token",
    headers={"Content-Type": "application/json; charset=UTF-8"},
    json={
        "grant_type": "client_credentials",
        "appkey": kiwoom_config.get('app_key'),
        "secretkey": kiwoom_config.get('app_secret')
    }
)

if token_response.status_code == 200:
    token_data = token_response.json()
    token = token_data.get('token')
    print(f"✅ 토큰 발급 성공: {token[:20]}...{token[-20:]}\n")
else:
    print(f"❌ 토큰 발급 실패: {token_response.text}")
    exit(1)

# 계좌 정보
account_no = "6349-6548"
parts = account_no.split('-')
cano = parts[0]
acnt_prdt_cd = parts[1]

# 테스트할 엔드포인트 목록
test_endpoints = [
    # 패턴 1: 한투 스타일
    {
        "name": "계좌잔고 (한투 스타일 1)",
        "url": f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance",
        "method": "GET",
        "tr_id": "TTTC8434R",
        "params": {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "N",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
    },
    # 패턴 2: 키움 스타일 추측
    {
        "name": "계좌잔고 (키움 스타일 1)",
        "url": f"{base_url}/api/domestic-stock/v1/trading/inquire-balance",
        "method": "GET",
        "tr_id": "TTTC8434R",
        "params": {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd
        }
    },
    {
        "name": "계좌잔고 (키움 스타일 2)",
        "url": f"{base_url}/api/account/balance",
        "method": "GET",
        "tr_id": None,
        "params": {
            "account_no": account_no
        }
    },
    {
        "name": "계좌잔고 (키움 스타일 3)",
        "url": f"{base_url}/api/v1/account/balance",
        "method": "GET",
        "tr_id": None,
        "params": {
            "cano": cano,
            "acnt_prdt_cd": acnt_prdt_cd
        }
    }
]

print("=" * 80)
print("API 엔드포인트 테스트")
print("=" * 80)

for endpoint in test_endpoints:
    print(f"\n📍 테스트: {endpoint['name']}")
    print(f"   URL: {endpoint['url']}")

    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}"
    }

    if endpoint.get('tr_id'):
        headers['tr_id'] = endpoint['tr_id']

    try:
        if endpoint['method'] == 'GET':
            response = requests.get(
                endpoint['url'],
                headers=headers,
                params=endpoint.get('params'),
                timeout=10
            )
        else:
            response = requests.post(
                endpoint['url'],
                headers=headers,
                json=endpoint.get('params'),
                timeout=10
            )

        print(f"   상태: {response.status_code}")

        if response.status_code == 200:
            print(f"   ✅ 성공!")
            print(f"   응답: {response.text[:300]}")

            # 성공한 엔드포인트는 상세 출력
            try:
                data = response.json()
                print(f"\n   📄 전체 응답:")
                print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
            except:
                pass
        else:
            print(f"   ❌ 실패: {response.text[:200]}")

    except Exception as e:
        print(f"   ❌ 예외: {e}")

print("\n" + "=" * 80)
