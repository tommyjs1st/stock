"""
키움 API 패턴 테스트
확인된 패턴을 바탕으로 다양한 api-id 테스트
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
    print(f"✅ 토큰 발급 성공\n")
else:
    print(f"❌ 토큰 발급 실패: {token_response.text}")
    exit(1)

# 계좌 정보
account_no = "6349-6548"
parts = account_no.split('-')

# 테스트할 API ID 목록
test_apis = [
    # 확인된 API
    {
        "name": "일별잔고수익률 (확인됨)",
        "url": f"{base_url}/api/dostk/acnt",
        "api_id": "ka01690",
        "params": {}
    },
    # 추측되는 계좌 관련 API들
    {
        "name": "보유종목조회 (추측 1)",
        "url": f"{base_url}/api/dostk/acnt",
        "api_id": "ka01671",
        "params": {}
    },
    {
        "name": "보유종목조회 (추측 2)",
        "url": f"{base_url}/api/dostk/acnt",
        "api_id": "ka01672",
        "params": {}
    },
    {
        "name": "계좌잔고조회 (추측 1)",
        "url": f"{base_url}/api/dostk/acnt",
        "api_id": "ka01670",
        "params": {}
    },
    # 추측되는 시세 관련 API들
    {
        "name": "현재가조회 (추측 1)",
        "url": f"{base_url}/api/dostk/quot",
        "api_id": "ks01010",
        "params": {"stk_cd": "005930"}
    },
    {
        "name": "현재가조회 (추측 2)",
        "url": f"{base_url}/api/dostk/quot",
        "api_id": "ks01100",
        "params": {"stk_cd": "005930"}
    }
]

print("=" * 80)
print("키움 API 패턴 테스트")
print("=" * 80)

for test_api in test_apis:
    print(f"\n📍 {test_api['name']}")
    print(f"   URL: {test_api['url']}")
    print(f"   API-ID: {test_api['api_id']}")

    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "authorization": f"Bearer {token}",
        "api-id": test_api['api_id']
    }

    try:
        response = requests.post(
            test_api['url'],
            headers=headers,
            json=test_api['params'],
            timeout=10
        )

        print(f"   상태: {response.status_code}")

        if response.status_code == 200:
            print(f"   ✅ 성공!")
            try:
                data = response.json()
                print(f"   응답: {json.dumps(data, indent=2, ensure_ascii=False)[:500]}")
            except:
                print(f"   응답: {response.text[:300]}")
        else:
            error_text = response.text[:300]
            print(f"   ❌ 실패: {error_text}")

            # 에러 메시지에서 힌트 찾기
            if "api-id" in error_text.lower() or "api_id" in error_text.lower():
                print(f"   💡 api-id 관련 오류")

    except Exception as e:
        print(f"   ❌ 예외: {e}")

print("\n" + "=" * 80)
print("💡 성공한 API가 있다면 해당 api-id를 사용하세요")
print("💡 모두 실패했다면 API 문서에서 정확한 api-id를 확인해주세요")
print("=" * 80)
