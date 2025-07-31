import os
import time
import json
import requests
import pandas as pd
from datetime import datetime, timedelta
from dotenv import load_dotenv

TOKEN_FILE = "token.json"
load_dotenv()

APP_KEY = os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_APP_SECRET")
CUSTTYPE = os.getenv("KIS_CUSTTYPE")
BASE_URL = os.getenv("KIS_ACCESS_URL")

def request_new_token():
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    data = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    res = requests.post(url, headers=headers, data=json.dumps(data))
    token_data = res.json()
    token_data["requested_at"] = int(time.time())
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)
    return token_data["access_token"]

def load_token():
    if not os.path.exists(TOKEN_FILE):
        return request_new_token()
    with open(TOKEN_FILE, "r") as f:
        token_data = json.load(f)
    now = int(time.time())
    issued_at = token_data.get("requested_at", 0)
    expires_in = int(token_data.get("expires_in", 0))
    if now - issued_at >= expires_in - 3600:
        return request_new_token()
    return token_data["access_token"]


def get_ohlcv(stock_code, adjust_price=True, start_date=None, end_date=None):
    token = load_token()

    if end_date is None:
        end_dt = datetime.today()
        end_date = end_dt.strftime("%Y%m%d")
    else:
        end_dt = datetime.strptime(end_date, "%Y%m%d")

    if start_date is None:
        # 종료일 기준으로 140일 전을 시작일로 설정 (약 100 영업일 커버)
        start_dt = end_dt - timedelta(days=140)
        start_date = start_dt.strftime("%Y%m%d")

    print(f"[INFO] 조회기간: {start_date} ~ {end_date}")

    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"

    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST03010100",
        "custtype": CUSTTYPE or "P"
    }

    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code.zfill(6),
        "fid_input_date_1": start_date,
        "fid_input_date_2": end_date,
        "fid_period_div_code": "D",
        "fid_org_adj_prc": "1" if adjust_price else "0"
    }

    response = requests.get(url, headers=headers, params=params)
    #print(f"[DEBUG] status_code: {response.status_code}")
    #print(f"[DEBUG] 응답 내용: {response.text[:3000]}")  # 일부만 출력

    data = response.json()
    if data.get("rt_cd") != "0":
        raise Exception(f"조회 실패: {data.get('msg1', 'Unknown error')}")

    output = data.get("output2", [])
    if not output:
        print("[INFO] output2 데이터가 비어 있습니다.")
        print(f"[DEBUG] output1 정보: {json.dumps(data.get('output1', {}), indent=2, ensure_ascii=False)}")
        raise Exception("받은 OHLCV 데이터가 없습니다.")

    df = pd.DataFrame(output)
    df = df[[
        "stck_bsop_date", "stck_oprc", "stck_hgpr", "stck_lwpr", "stck_clpr", "acml_vol"
    ]].rename(columns={
        "stck_bsop_date": "date",
        "stck_oprc": "open",
        "stck_hgpr": "high",
        "stck_lwpr": "low",
        "stck_clpr": "close",
        "acml_vol": "volume"
    })

    # 변환
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    numeric_cols = ["open", "high", "low", "close", "volume"]
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")

    df = df.dropna().sort_values("date").reset_index(drop=True)

    filename = f"ohlcv_{stock_code}.csv"
    df.to_csv(filename, index=False, encoding="utf-8-sig")
    print(f"✅ CSV 저장 완료: {filename}")
    return df

if __name__ == "__main__":
    code = "062040"  # 예: 한국전자금융
    df = get_ohlcv(code)
    print(df.tail())

