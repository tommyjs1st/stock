import os
import time
import json
import requests
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

APP_KEY = os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_APP_SECRET")
ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO")
ACCOUNT_PW = os.getenv("KIS_ACCOUNT_PW")
CUSTTYPE = os.getenv("KIS_CUSTTYPE")  # 'P' or 'T'
BASE_URL = os.getenv("KIS_ACCESS_URL")

TOKEN_FILE = "token.json"

# 👉 토큰 발급
def request_new_token():
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    data = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    res = requests.post(url, headers=headers, data=json.dumps(data)).json()
    res["requested_at"] = int(time.time())  # 현재 시각 기록
    with open(TOKEN_FILE, "w") as f:
        json.dump(res, f)
    return res["access_token"]

def load_token():
    if not os.path.exists(TOKEN_FILE):
        return request_new_token()
    
    with open(TOKEN_FILE, "r") as f:
        token_data = json.load(f)

    now = int(time.time())
    issued_at = token_data.get("requested_at", 0)
    expires_in = int(token_data.get("expires_in", 0))
    
    # 23시간 이상 지났으면 재발급 (안전 여유시간 확보)
    if now - issued_at >= expires_in - 3600:
        return request_new_token()
    else:
        return token_data["access_token"]

def get_holdings():
    token = load_token()
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "TTTC8434R" if CUSTTYPE == "T" else "TTTC8434R",  # 실전/모의 모두 동일
    }
    params = {
        "CANO": ACCOUNT_NO[:8],
        "ACNT_PRDT_CD": ACCOUNT_NO[8:],
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "SORT_SQN": "ASC",
        "INQR_STRT_POS": "0",
        "INQR_MAX_LINE": "100",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
        "FNCG_AMT_AUTO_RDPT_YN": "N", 
        "PRCS_DVSN": "01"
    }
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
    try:
        response = requests.get(url, headers=headers, params=params)
        #print("🔍 응답 상태코드:", response.status_code)
        #print("🔍 응답 본문:\n", response.text)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        print("요청 실패:", e)
        raise e

    data = response.json()

    if data["rt_cd"] != "0":
        raise Exception(f"조회 실패: {data['msg1']}")

    stocks = data["output1"]
    if not stocks:
        print("📭 보유 종목이 없습니다.")
        return pd.DataFrame(columns=["code", "name", "quantity", "avg_price", "eval_profit"])

    df = pd.DataFrame(stocks)
    df = df[df["hldg_qty"].astype(float) > 0]  # 보유 수량 있는 종목만 필터링
    df = df[["pdno", "prdt_name", "hldg_qty", "pchs_avg_pric", "evlu_pfls_amt"]]
    df.columns = ["code", "name", "quantity", "avg_price", "eval_profit"]
    
    return df

if __name__ == "__main__":
    holdings_df = get_holdings()
    print(holdings_df)
