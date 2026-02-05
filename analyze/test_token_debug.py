"""
토큰 발급 디버그 스크립트
"""
import requests
import json
import yaml

# config.yaml에서 설정 로드
with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

kiwoom_config = config.get('kiwoom', {})
app_key = kiwoom_config.get('app_key', '')
app_secret = kiwoom_config.get('app_secret', '')
base_url = kiwoom_config.get('base_url', 'https://api.kiwoom.com')

print("=" * 60)
print("토큰 발급 디버그")
print("=" * 60)
print(f"BASE_URL: {base_url}")
print(f"APP_KEY: {app_key[:15]}...{app_key[-15:]}")
print(f"APP_SECRET: {app_secret[:10]}...{app_secret[-10:]}")
print()

url = f"{base_url}/oauth2/token"
headers = {"Content-Type": "application/json; charset=UTF-8"}

# 여러 파라미터 조합 시도
data_variants = [
    {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecretkey": app_secret
    },
    {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "secretkey": app_secret
    },
    {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    },
    {
        "grant_type": "client_credentials",
        "app_key": app_key,
        "app_secret": app_secret
    }
]

for idx, data in enumerate(data_variants):
    print(f"\n{'='*60}")
    print(f"시도 #{idx+1}")
    print(f"{'='*60}")
    param_names = [k for k in data.keys() if k != 'grant_type']
    print(f"파라미터: {', '.join(param_names)}")

    try:
        response = requests.post(
            url,
            headers=headers,
            data=json.dumps(data),
            timeout=30
        )

        print(f"상태 코드: {response.status_code}")
        print(f"응답: {response.text[:200]}")

        if response.status_code == 200:
            token_data = response.json()
            access_token = token_data.get('access_token')

            if access_token:
                print(f"\n✅ 성공! 토큰: {access_token[:20]}...{access_token[-20:]}")
                print(f"\n올바른 파라미터:")
                print(json.dumps(data, indent=2, ensure_ascii=False))
                break
            else:
                print("⚠️ access_token 없음")

    except Exception as e:
        print(f"❌ 예외: {e}")
else:
    print("\n\n모든 시도 실패")
