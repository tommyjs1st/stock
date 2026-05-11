# test_deposit.py
import yaml
import requests
import json

with open('config.yaml', 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

kiwoom_config = config.get('kiwoom', {})
base_url = kiwoom_config.get('base_url', 'https://api.kiwoom.com')
accounts = kiwoom_config.get('accounts', {})

for alias, account_info in accounts.items():
    if not account_info.get('enabled', False):
        continue

    app_key = account_info.get('app_key')
    app_secret = account_info.get('app_secret')

    print(f"\n{'='*60}")
    print(f"계좌: {alias} ({account_info.get('account_no')})")

    # 토큰 발급
    token_resp = requests.post(
        f"{base_url}/oauth2/token",
        headers={"Content-Type": "application/json; charset=UTF-8"},
        json={"grant_type": "client_credentials",
              "appkey": app_key, "secretkey": app_secret}
    )
    token = token_resp.json().get('token')
    print(f"토큰: {token[:20]}..." if token else "❌ 토큰 발급 실패")

    if not token:
        continue

    # kt00001 호출
    resp = requests.post(
        f"{base_url}/api/dostk/acnt",
        headers={
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {token}",
            "api-id": "kt00001"
        },
        json={"qry_tp": "2"}
    )

    print(f"HTTP 상태: {resp.status_code}")
    data = resp.json()
    print(f"전체 응답:\n{json.dumps(data, ensure_ascii=False, indent=2)}")
