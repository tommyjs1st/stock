import os
import time
import json
import requests
from dotenv import load_dotenv

load_dotenv()

APP_KEY = os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_APP_SECRET")
BASE_URL = os.getenv("KIS_ACCESS_URL")
CUSTTYPE = os.getenv("KIS_CUSTTYPE", "P")

TOKEN_FILE = "token.json"

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