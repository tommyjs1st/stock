"""
KIS API 클라이언트 모듈
토큰 관리, API 호출 등 기본 기능
"""
import requests
import json
import time
import os
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

class KISAPIClient:
    def __init__(self):
        self.app_key = os.getenv("KIS_APP_KEY")
        self.app_secret = os.getenv("KIS_APP_SECRET")
        self.token_file = "token.json"
        self.access_token = None
        self.logger = logging.getLogger(__name__)

    def load_keys(self):
        if not self.app_key or not self.app_secret:
            raise ValueError("환경변수 KIS_APP_KEY 또는 KIS_APP_SECRET이 설정되지 않았습니다.")
        return self.app_key, self.app_secret

    def request_new_token(self):
        """새로운 액세스 토큰 요청"""
        url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
        headers = {"Content-Type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        
        try:
            res = requests.post(url, headers=headers, data=json.dumps(data))
            res.raise_for_status()
            token_data = res.json()
            token_data["requested_at"] = int(time.time())
            
            with open(self.token_file, "w") as f:
                json.dump(token_data, f)
            
            self.logger.info("✅ 새로운 액세스 토큰 발급 완료")
            return token_data["access_token"]
        except Exception as e:
            self.logger.error(f"❌ 토큰 발급 실패: {e}")
            raise

    def load_token(self):
        """저장된 토큰 로드 또는 새 토큰 요청"""
        if not os.path.exists(self.token_file):
            return self.request_new_token()
        
        try:
            with open(self.token_file, "r") as f:
                token_data = json.load(f)

            now = int(time.time())
            issued_at = token_data.get("requested_at", 0)
            expires_in = int(token_data.get("expires_in", 0))
            
            # 토큰이 만료되었으면 새로 요청
            if now - issued_at >= expires_in - 3600:  # 1시간 여유
                return self.request_new_token()
            else:
                self.access_token = token_data["access_token"]
                return self.access_token
        except Exception as e:
            self.logger.error(f"❌ 토큰 로드 실패: {e}")
            return self.request_new_token()

    def get_headers(self, tr_id):
        """API 요청 헤더 생성"""
        return {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.load_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id
        }

    def api_request(self, url, params, tr_id, max_retries=3):
        """통합 API 요청 함수"""
        headers = self.get_headers(tr_id)
        
        for attempt in range(max_retries):
            try:
                time.sleep(0.1)  # API 호출 제한 고려
                response = requests.get(url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                self.logger.error(f"❌ API 요청 실패 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    raise
        return None
