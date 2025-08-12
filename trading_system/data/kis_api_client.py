"""
KIS API 클라이언트 모듈
"""
import requests
import json
import time
import os
from datetime import datetime, timedelta
from typing import Dict, Optional
import pandas as pd
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class KISAPIClient:
    """KIS API 클라이언트"""
    
    def __init__(self, app_key: str, app_secret: str, base_url: str, account_no: str):
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = base_url
        self.account_no = account_no
        self.token_file = "token.json"
        self.access_token = None
        self.last_token_time = None
        self.session = self.create_robust_session()
    
    def create_robust_session(self):
        """견고한 HTTP 세션 생성"""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def load_saved_token(self) -> bool:
        """저장된 토큰 파일에서 토큰 로드"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    token_data = json.load(f)
                
                expire_time_str = token_data.get('access_token_token_expired', '')
                if expire_time_str:
                    expire_time = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')

                    if datetime.now() < expire_time - timedelta(minutes=10):
                        self.access_token = token_data.get('access_token')
                        self.last_token_time = datetime.fromtimestamp(token_data.get('requested_at', 0))
                        return True
        except Exception:
            pass
        
        return False
    
    def save_token(self, token_response: dict):
        """토큰을 파일에 저장"""
        try:
            current_time = int(time.time())
            expires_in = token_response.get('expires_in', 86400)
            expire_datetime = datetime.fromtimestamp(current_time + expires_in)

            token_data = {
                'access_token': token_response.get('access_token'),
                'access_token_token_expired': expire_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'token_type': token_response.get('token_type', 'Bearer'),
                'expires_in': expires_in,
                'requested_at': current_time
            }

            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
    
    def get_access_token(self) -> str:
        """KIS API 액세스 토큰 발급 또는 재사용"""
        if self.access_token and self.last_token_time:
            if datetime.now() - self.last_token_time < timedelta(hours=23):
                return self.access_token

        if self.load_saved_token():
            return self.access_token

        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()

            token_response = response.json()
            access_token = token_response.get("access_token")
            
            if access_token:
                self.access_token = access_token
                self.last_token_time = datetime.now()
                self.save_token(token_response)
                return self.access_token
            else:
                error_msg = token_response.get('msg1', 'Unknown error')
                raise Exception(f"토큰 발급 실패: {error_msg}")

        except Exception as e:
            raise Exception(f"토큰 발급 실패: {e}")
    
    def get_daily_data(self, symbol: str, days: int = 180) -> pd.DataFrame:
        """일봉 데이터 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010100"
        }

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol,
            "fid_input_date_1": start_date,
            "fid_input_date_2": end_date,
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "0"
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                
                if 'stck_bsop_date' in df.columns:
                    df = df.sort_values('stck_bsop_date').reset_index(drop=True)
                
                column_mapping = {
                    'stck_clpr': 'stck_prpr',
                    'stck_oprc': 'stck_oprc',
                    'stck_hgpr': 'stck_hgpr',
                    'stck_lwpr': 'stck_lwpr',
                    'acml_vol': 'cntg_vol'
                }
                
                for old_col, new_col in column_mapping.items():
                    if old_col in df.columns:
                        df[new_col] = df[old_col]
                
                numeric_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'cntg_vol']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                df = df.dropna(subset=['stck_prpr'])
                return df
                
        except Exception:
            pass

        return pd.DataFrame()
    
    def get_minute_data(self, symbol: str, minutes: int = 240) -> pd.DataFrame:
        """분봉 데이터 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010200"
        }

        end_time = datetime.now().strftime("%H%M%S")
        params = {
            "fid_etc_cls_code": "",
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol,
            "fid_input_hour_1": end_time,
            "fid_pw_data_incu_yn": "Y"
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                if not df.empty and 'stck_cntg_hour' in df.columns:
                    df['stck_cntg_hour'] = pd.to_datetime(df['stck_cntg_hour'], format='%H%M%S', errors='coerce')
                    numeric_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'cntg_vol']
                    for col in numeric_cols:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    df = df.dropna(subset=['stck_prpr'])
                    
                    if not df.empty:
                        return df.sort_values('stck_cntg_hour').reset_index(drop=True)

        except Exception:
            pass

        return pd.DataFrame()
    
    def get_current_price(self, symbol: str) -> Dict:
        """현재가 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100"
        }
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol}

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception:
            return {}
    
    def get_current_bid_ask(self, symbol: str) -> Dict:
        """현재 호가 정보 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010200"
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('rt_cd') == '0' and data.get('output1'):
                    output = data['output1']
                    
                    bid_ask_info = {
                        'current_price': int(output.get('stck_prpr', 0)),
                        'bid_price': int(output.get('bidp1', 0)),
                        'ask_price': int(output.get('askp1', 0)),
                        'bid_quantity': int(output.get('bidp_rsqn1', 0)),
                        'ask_quantity': int(output.get('askp_rsqn1', 0)),
                        'spread': int(output.get('askp1', 0)) - int(output.get('bidp1', 0))
                    }
                    
                    return bid_ask_info
                    
        except Exception:
            pass
        
        return {}
    
    def get_account_balance(self) -> Dict:
        """계좌 잔고 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        
        is_mock = "vts" in self.base_url.lower()
        tr_id = "VTTC8908R" if is_mock else "TTTC8908R"
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id
        }
        
        params = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "PDNO": "005930",
            "ORD_UNPR": "0",
            "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N"
        }

        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('rt_cd') != '0':
                return {}
                
            output = data.get('output', {})
            if output:
                available_cash = float(output.get('ord_psbl_cash', 0))
                output['ord_psbl_cash'] = str(int(available_cash))
            
            return data
            
        except Exception:
            return {}
    
    def get_all_holdings(self) -> Dict:
        """실제 계좌의 모든 보유 종목 조회"""
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
            
            is_mock = "vts" in self.base_url.lower()
            tr_id = "VTTC8434R" if is_mock else "TTTC8434R"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": tr_id
            }
            
            params = {
                "CANO": self.account_no.split('-')[0],
                "ACNT_PRDT_CD": self.account_no.split('-')[1],
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('rt_cd') == '0':
                    all_holdings = {}
                    holdings = data.get('output1', [])
                    
                    if isinstance(holdings, list):
                        for holding in holdings:
                            symbol = holding.get('pdno', '')
                            quantity = int(holding.get('hldg_qty', 0))
                            
                            if quantity > 0 and symbol:
                                all_holdings[symbol] = {
                                    'quantity': quantity,
                                    'avg_price': float(holding.get('pchs_avg_pric', 0)),
                                    'current_price': float(holding.get('prpr', 0)),
                                    'profit_loss': float(holding.get('evlu_pfls_rt', 0)),
                                    'stock_name': holding.get('prdt_name', symbol),
                                    'total_value': float(holding.get('evlu_amt', 0)),
                                    'purchase_amount': float(holding.get('pchs_amt', 0))
                                }
                    
                    return all_holdings
                    
        except Exception:
            pass
        
        return {}
    
    def place_order(self, symbol: str, side: str, quantity: int, price: int = 0) -> Dict:
        """주문 실행"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        is_mock = "vts" in self.base_url.lower()
        
        if is_mock:
            tr_id = "VTTC0802U" if side == "BUY" else "VTTC0801U"
        else:
            tr_id = "TTTC0802U" if side == "BUY" else "TTTC0801U"
        
        if price == 0:
            ord_dvsn = "01"
            ord_unpr = "0"
        else:
            ord_dvsn = "00"
            ord_unpr = str(price)
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id
        }

        data = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "PDNO": symbol,
            "ORD_DVSN": ord_dvsn,
            "ORD_QTY": str(quantity),
            "ORD_UNPR": ord_unpr
        }

        try:
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get('rt_cd') == '0':
                order_no = result.get('output', {}).get('odno', 'Unknown')
                return {'success': True, 'order_no': order_no, 'limit_price': price}
            else:
                error_msg = result.get('msg1', 'Unknown error')
                return {'success': False, 'error': error_msg}

        except Exception as e:
            return {'success': False, 'error': str(e)}
