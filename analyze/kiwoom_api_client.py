"""
키움 REST API 클라이언트
계좌 조회, 보유종목 조회 등
"""
import requests
import json
import time
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd

from kiwoom_config import KiwoomConfig
from base_fetcher import BaseAPIClient
import yaml


class KiwoomAPIClient(BaseAPIClient):
    """키움 REST API 클라이언트"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config = KiwoomConfig(config_path)
        self.config.validate_config()

        self.app_key = self.config.APP_KEY
        self.app_secret = self.config.APP_SECRET
        self.base_url = self.config.BASE_URL
        self.token_file = self.config.TOKEN_FILE

        self.access_token = None
        self.last_token_time = None

        self.logger = logging.getLogger(__name__)

        # KIS API 설정 (시세 조회용)
        with open(config_path, 'r', encoding='utf-8') as f:
            full_config = yaml.safe_load(f)

        kis_config = full_config.get('kis', {})
        self.kis_app_key = kis_config.get('app_key')
        self.kis_app_secret = kis_config.get('app_secret')
        self.kis_base_url = kis_config.get('base_url')
        self.kis_token = None
        self.kis_token_time = None
    
    def load_saved_token(self) -> bool:
        """저장된 토큰 파일에서 토큰 로드"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    token_data = json.load(f)

                expire_time_str = token_data.get('access_token_token_expired', '')
                if expire_time_str:
                    expire_time = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')

                    # 만료 10분 전이면 재발급
                    if datetime.now() < expire_time - timedelta(minutes=10):
                        token = token_data.get('access_token')
                        if token:
                            self.access_token = token
                            self.last_token_time = datetime.fromtimestamp(
                                token_data.get('requested_at', 0)
                            )
                            self.logger.info("✅ 저장된 토큰 로드 성공")
                            return True
        except Exception as e:
            self.logger.warning(f"⚠️ 토큰 로드 실패: {e}")

        return False
    
    def save_token(self, token_response: dict):
        """토큰을 파일에 저장"""
        try:
            current_time = int(time.time())

            # expires_dt는 "20260206102638" 형식
            expires_dt = token_response.get('expires_dt', '')
            if expires_dt:
                expire_datetime = datetime.strptime(expires_dt, '%Y%m%d%H%M%S')
            else:
                expire_datetime = datetime.fromtimestamp(current_time + 86400)

            token_data = {
                'access_token': token_response.get('token'),
                'access_token_token_expired': expire_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'token_type': token_response.get('token_type', 'Bearer'),
                'expires_dt': expires_dt,
                'requested_at': current_time
            }
            
            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info("✅ 토큰 저장 완료")
        except Exception as e:
            self.logger.error(f"❌ 토큰 저장 실패: {e}")
    
    def get_access_token(self) -> str:
        """
        키움 REST API 액세스 토큰 발급 또는 재사용
        
        Returns:
            str: 액세스 토큰
        """
        # 기존 토큰이 유효하면 재사용
        if self.access_token and self.last_token_time:
            if datetime.now() - self.last_token_time < timedelta(hours=23):
                return self.access_token
        
        # 저장된 토큰 로드 시도
        if self.load_saved_token():
            return self.access_token
        
        # 새 토큰 발급
        self.logger.info("🔄 새로운 토큰 발급 중...")
        
        url = f"{self.base_url}/oauth2/token"
        headers = {"Content-Type": "application/json; charset=UTF-8"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret
        }
        
        try:
            response = requests.post(
                url,
                headers=headers,
                data=json.dumps(data),
                timeout=self.config.TIMEOUT
            )
            response.raise_for_status()

            token_response = response.json()

            # 키움 API는 return_code로 성공/실패 확인
            return_code = token_response.get('return_code')
            if return_code != 0:
                error_msg = token_response.get('return_msg', 'Unknown error')
                raise Exception(f"토큰 발급 실패: {error_msg}")

            self.access_token = token_response.get('token')
            self.last_token_time = datetime.now()

            # 토큰 저장
            self.save_token(token_response)

            self.logger.info("✅ 새 토큰 발급 완료")
            return self.access_token

        except Exception as e:
            self.logger.error(f"❌ 토큰 발급 실패: {e}")
            raise
    
    def api_request(
        self,
        url: str,
        params: dict = None,
        api_id: str = None,
        method: str = "POST"
    ) -> Optional[dict]:
        """
        키움 REST API 요청

        Args:
            url: API URL
            params: 요청 파라미터
            api_id: API ID (TR명, 예: ka01690)
            method: HTTP 메서드

        Returns:
            dict: API 응답 데이터
        """
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {self.get_access_token()}"
        }

        if api_id:
            headers["api-id"] = api_id
        
        for attempt in range(self.config.MAX_RETRIES):
            try:
                time.sleep(self.config.API_DELAY)

                # 키움 API는 기본적으로 POST 사용
                response = requests.post(
                    url,
                    headers=headers,
                    json=params if params else {},
                    timeout=self.config.TIMEOUT
                )
                
                # 상태 코드 확인
                if response.status_code != 200:
                    error_detail = response.text[:500]
                    self.logger.error(
                        f"❌ API 요청 실패 (시도 {attempt + 1}/{self.config.MAX_RETRIES}): "
                        f"HTTP {response.status_code}, 응답: {error_detail}"
                    )
                    if attempt < self.config.MAX_RETRIES - 1:
                        time.sleep(1)
                        continue
                    else:
                        raise Exception(f"HTTP {response.status_code}: {error_detail}")

                return response.json()

            except Exception as e:
                if "HTTP" not in str(e):
                    self.logger.error(
                        f"❌ API 요청 실패 (시도 {attempt + 1}/{self.config.MAX_RETRIES}): {e}"
                    )
                if attempt < self.config.MAX_RETRIES - 1:
                    time.sleep(1)
                else:
                    raise
        
        return None
    
    def get_account_balance(self, account_no: str) -> Dict:
        """
        계좌 잔고 조회 (일별잔고수익률 API 사용)

        Args:
            account_no: 계좌번호 (예: 6349-6548)

        Returns:
            Dict: 계좌 잔고 정보
        """
        url = f"{self.base_url}/api/dostk/acnt"

        # 오늘 날짜
        from datetime import datetime
        today = datetime.now().strftime('%Y%m%d')

        params = {
            'qry_dt': today  # 조회일자
        }

        try:
            data = self.api_request(url, params, api_id="ka01690")

            if not data:
                return {}

            return {
                'account_no': account_no,
                'total_eval_amount': float(data.get('tot_evlt_amt', 0)),  # 총평가금액
                'total_purchase_amount': float(data.get('tot_buy_amt', 0)),  # 총매입가
                'total_profit_loss': float(data.get('tot_evltv_prft', 0)),  # 총평가손익
                'profit_loss_rate': float(data.get('tot_prft_rt', 0)),  # 수익률
                'deposit': float(data.get('dbst_bal', 0)),  # 예수금
                'holdings_count': len(data.get('day_bal_rt', [])),  # 보유종목수
                'query_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }

        except Exception as e:
            self.logger.error(f"❌ 계좌 잔고 조회 실패 ({account_no}): {e}")
            return {}
    
    def get_holdings(self, account_no: str) -> pd.DataFrame:
        """
        보유종목 조회 (일별잔고수익률 API 사용)

        Args:
            account_no: 계좌번호

        Returns:
            DataFrame: 보유종목 정보
        """
        url = f"{self.base_url}/api/dostk/acnt"

        # 오늘 날짜
        today = datetime.now().strftime('%Y%m%d')

        params = {
            'qry_dt': today  # 조회일자
        }

        try:
            data = self.api_request(url, params, api_id="ka01690")

            if not data:
                return pd.DataFrame()

            holdings_list = []

            # day_bal_rt: 일별잔고수익률 리스트
            day_bal_rt = data.get('day_bal_rt', [])

            for item in day_bal_rt:
                stock_code = item.get('stk_cd', '')  # 종목코드
                if not stock_code or stock_code.strip() == '':
                    continue

                # 보유수량이 0이면 스킵
                quantity = int(item.get('rmnd_qty', 0))
                if quantity == 0:
                    continue

                holdings_list.append({
                    'account_no': account_no,
                    'stock_code': stock_code,
                    'stock_name': item.get('stk_nm', ''),  # 종목명
                    'quantity': quantity,  # 잔고수량
                    'avg_price': float(item.get('buy_uv', 0)),  # 매입단가
                    'current_price': float(item.get('cur_prc', 0)),  # 현재가
                    'eval_amount': float(item.get('evlt_amt', 0)),  # 평가금액
                    'purchase_amount': float(item.get('buy_uv', 0)) * quantity,  # 매입금액
                    'profit_loss': float(item.get('evltv_prft', 0)),  # 평가손익
                    'profit_rate': float(item.get('prft_rt', 0)),  # 수익률
                })

            df = pd.DataFrame(holdings_list)

            if not df.empty:
                self.logger.info(f"✅ 보유종목 조회 완료 ({account_no}): {len(df)}개")

            return df

        except Exception as e:
            self.logger.error(f"❌ 보유종목 조회 실패 ({account_no}): {e}")
            return pd.DataFrame()
    
    def get_holdings_all(self) -> pd.DataFrame:
        """
        활성화된 모든 계좌의 보유종목 조회
        
        Returns:
            DataFrame: 전체 보유종목 정보 (계좌별 구분 포함)
        """
        enabled_accounts = self.config.get_enabled_accounts()
        
        if not enabled_accounts:
            self.logger.warning("⚠️ 활성화된 계좌가 없습니다.")
            return pd.DataFrame()
        
        all_holdings = []
        
        for alias, account_info in enabled_accounts.items():
            account_no = account_info['account_no']
            self.logger.info(f"📊 계좌 조회 중: {alias} ({account_no})")
            
            df = self.get_holdings(account_no)
            
            if not df.empty:
                df['account_alias'] = alias
                df['account_description'] = account_info['description']
                all_holdings.append(df)
        
        if all_holdings:
            result_df = pd.concat(all_holdings, ignore_index=True)
            self.logger.info(f"✅ 전체 조회 완료: {len(result_df)}개 종목")
            return result_df
        else:
            return pd.DataFrame()
    
    def get_holdings_by_accounts(self, account_aliases: List[str]) -> pd.DataFrame:
        """
        특정 계좌들의 보유종목 조회

        Args:
            account_aliases: 계좌 별칭 리스트 (예: ['main', 'sub1'])

        Returns:
            DataFrame: 보유종목 정보
        """
        all_holdings = []

        for alias in account_aliases:
            account_info = self.config.get_account(alias)

            if not account_info:
                self.logger.warning(f"⚠️ 알 수 없는 계좌 별칭: {alias}")
                continue

            if not account_info['enabled']:
                self.logger.info(f"⏭️ 비활성화된 계좌 스킵: {alias}")
                continue

            account_no = account_info['account_no']
            df = self.get_holdings(account_no)

            if not df.empty:
                df['account_alias'] = alias
                df['account_description'] = account_info['description']
                all_holdings.append(df)

        if all_holdings:
            return pd.concat(all_holdings, ignore_index=True)
        else:
            return pd.DataFrame()

    def get_daily_profit_history(self, days: int = 30) -> pd.DataFrame:
        """
        일별 수익률 히스토리 조회 (모든 활성화된 계좌 통합)

        Args:
            days: 조회할 일수 (기본 30일)

        Returns:
            DataFrame: 일별 수익률 데이터 (columns: date, profit_rate, total_eval_amount, total_profit_loss)
        """
        enabled_accounts = self.config.get_enabled_accounts()

        if not enabled_accounts:
            self.logger.warning("⚠️ 활성화된 계좌가 없습니다.")
            return pd.DataFrame()

        url = f"{self.base_url}/api/dostk/acnt"

        # 날짜 범위 생성 (오늘부터 과거로)
        date_list = []
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            # 주말 제외 (토요일: 5, 일요일: 6)
            if date.weekday() < 5:
                date_list.append(date.strftime('%Y%m%d'))

        daily_data = []

        for date_str in date_list:
            # 각 날짜별로 조회
            params = {'qry_dt': date_str}

            try:
                data = self.api_request(url, params, api_id="ka01690")

                if data:
                    # 총평가금액, 총손익, 수익률 추출
                    total_eval = float(data.get('tot_evlt_amt', 0))
                    total_purchase = float(data.get('tot_buy_amt', 0))
                    total_profit = float(data.get('tot_evltv_prft', 0))

                    # 수익률 계산
                    if total_purchase > 0:
                        profit_rate = (total_profit / total_purchase) * 100
                    else:
                        profit_rate = 0

                    daily_data.append({
                        'date': datetime.strptime(date_str, '%Y%m%d'),
                        'profit_rate': profit_rate,
                        'total_eval_amount': total_eval,
                        'total_profit_loss': total_profit
                    })

                    self.logger.debug(f"✅ {date_str} 수익률: {profit_rate:.2f}%")

            except Exception as e:
                self.logger.error(f"❌ {date_str} 조회 실패: {e}")

        if daily_data:
            df = pd.DataFrame(daily_data)
            df = df.sort_values('date')  # 날짜순 정렬
            self.logger.info(f"✅ 일별 수익률 히스토리 조회 완료: {len(df)}일")
            return df
        else:
            return pd.DataFrame()
    
    def get_kis_token(self) -> str:
        """KIS API 토큰 발급"""
        # 기존 토큰이 유효하면 재사용
        if self.kis_token and self.kis_token_time:
            if datetime.now() - self.kis_token_time < timedelta(hours=23):
                return self.kis_token

        url = f"{self.kis_base_url}/oauth2/tokenP"
        headers = {"Content-Type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.kis_app_key,
            "appsecret": self.kis_app_secret
        }

        try:
            response = requests.post(url, headers=headers, json=data, timeout=10)
            response.raise_for_status()

            token_data = response.json()
            self.kis_token = token_data.get('access_token')
            self.kis_token_time = datetime.now()

            self.logger.info("✅ KIS 토큰 발급 완료")
            return self.kis_token

        except Exception as e:
            self.logger.error(f"❌ KIS 토큰 발급 실패: {e}")
            raise

    def get_current_price(self, stock_code: str) -> Optional[float]:
        """
        현재가 조회 (KIS API 사용)

        Args:
            stock_code: 종목코드 (6자리)

        Returns:
            float: 현재가 (실패시 None)
        """
        url = f"{self.kis_base_url}/uapi/domestic-stock/v1/quotations/inquire-price"

        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.get_kis_token()}",
            "appkey": self.kis_app_key,
            "appsecret": self.kis_app_secret,
            "tr_id": "FHKST01010100"
        }

        params = {
            "FID_COND_MRKT_DIV_CODE": "J",  # 시장구분 (J:주식)
            "FID_INPUT_ISCD": stock_code
        }

        try:
            time.sleep(0.1)  # API 호출 제한
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()

            data = response.json()

            if data and 'output' in data:
                current_price = float(data['output'].get('stck_prpr', 0))
                return current_price if current_price > 0 else None

        except Exception as e:
            self.logger.error(f"❌ 현재가 조회 실패 ({stock_code}): {e}")

        return None
