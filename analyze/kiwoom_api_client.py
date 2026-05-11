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
        
        # 계좌별 독립 토큰 캐시 {alias: {'token': ..., 'time': ...}}
        self._account_tokens: Dict[str, dict] = {}

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

        ※ 키움 API 특성: 신규 토큰 발급 시 이전 토큰 즉시 무효화.
           파일 만료시각이 유효해 보여도 다른 프로세스가 재발급했다면 서버에서 무효.
           따라서 파일 토큰 로드 후 반드시 서버 검증을 거칩니다.

        흐름:
          1. 메모리 토큰 (같은 프로세스 내 발급) → 재사용
          2. 파일 토큰 로드 → 서버 검증 통과 시 재사용
          3. 파일 토큰 무효 또는 없음 → 신규 발급 후 파일 갱신
        """
        # 1. 이번 프로세스에서 발급한 메모리 토큰 재사용 (23시간 이내)
        if self.access_token and self.last_token_time:
            if datetime.now() - self.last_token_time < timedelta(hours=23):
                return self.access_token

        # 2. 파일 토큰 로드 후 서버 검증
        if self.load_saved_token() and self.access_token:
            if self._is_token_valid(self.access_token):
                self.last_token_time = datetime.now()
                self.logger.info("✅ 파일 토큰 서버 검증 성공, 재사용")
                return self.access_token
            else:
                self.logger.warning(
                    "⚠️ 파일 토큰 서버 검증 실패 (다른 프로세스가 재발급한 것으로 추정). "
                    "신규 발급합니다."
                )
                self.access_token = None
                self.last_token_time = None

        # 3. 신규 토큰 발급
        return self._request_new_token()

    def get_account_token(self, alias: str, app_key: str, app_secret: str) -> str:
        """
        계좌별 독립 토큰 발급/캐시 반환

        Args:
            alias: 계좌 별칭 (토큰 파일 구분용)
            app_key: 해당 계좌의 app_key
            app_secret: 해당 계좌의 app_secret

        Returns:
            str: 액세스 토큰
        """
        token_file = f"kiwoom_token_{alias}.json"

        # 캐시 확인
        cached = self._account_tokens.get(alias)
        if cached:
            # 서버 검증
            if self._is_token_valid(cached['token']):
                return cached['token']
            else:
                self.logger.warning(f"⚠️ {alias} 캐시 토큰 만료, 재발급")
                self._account_tokens.pop(alias, None)

        # 파일 캐시 확인
        try:
            if os.path.exists(token_file):
                with open(token_file, 'r', encoding='utf-8') as f:
                    token_data = json.load(f)
                expire_str = token_data.get('access_token_token_expired', '')
                if expire_str:
                    expire_time = datetime.strptime(expire_str, '%Y-%m-%d %H:%M:%S')
                    if datetime.now() < expire_time - timedelta(minutes=10):
                        token = token_data.get('access_token')
                        if token and self._is_token_valid(token):
                            self._account_tokens[alias] = {'token': token}
                            self.logger.info(f"✅ {alias} 파일 토큰 재사용")
                            return token
        except Exception as e:
            self.logger.warning(f"⚠️ {alias} 토큰 파일 로드 실패: {e}")

        # 신규 발급
        self.logger.info(f"🔄 {alias} 토큰 신규 발급 중...")
        url = f"{self.base_url}/oauth2/token"
        headers = {"Content-Type": "application/json; charset=UTF-8"}
        data = {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "secretkey": app_secret
        }

        try:
            response = requests.post(url, headers=headers,
                                     data=json.dumps(data),
                                     timeout=self.config.TIMEOUT)
            response.raise_for_status()
            token_response = response.json()

            if token_response.get('return_code') != 0:
                raise Exception(f"토큰 발급 실패: {token_response.get('return_msg', '')}")

            token = token_response.get('token')
            self._account_tokens[alias] = {'token': token}

            # 파일 저장
            token_response['requested_at'] = datetime.now().timestamp()
            with open(token_file, 'w', encoding='utf-8') as f:
                json.dump(token_response, f, ensure_ascii=False, indent=2)

            self.logger.info(f"✅ {alias} 토큰 발급 완료")
            return token

        except Exception as e:
            self.logger.error(f"❌ {alias} 토큰 발급 실패: {e}")
            raise

    def _is_token_valid(self, token: str) -> bool:
        """토큰 서버 유효성 검증 (ka10080으로 실제 확인)"""
        if not token:
            return False
        try:
            resp = requests.post(
                f"{self.base_url}/api/dostk/chart",
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "authorization": f"Bearer {token}",
                    "api-id": "ka10080",
                },
                json={"stk_cd": "005930", "tic_scope": "1", "upd_stkpc_tp": "1"},
                timeout=5
            )
            if resp.status_code != 200:
                return False
            data = resp.json()
            rc  = data.get('return_code', -1)
            msg = data.get('return_msg', '')
            if '8005' in msg or 'Token이 유효하지 않습니다' in msg:
                return False
            return rc in (0, 2)
        except Exception:
            return False

    def _request_new_token(self) -> str:
        """신규 토큰 발급 및 파일 저장"""
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
                url, headers=headers,
                data=json.dumps(data),
                timeout=self.config.TIMEOUT
            )
            response.raise_for_status()

            token_response = response.json()
            return_code = token_response.get('return_code')
            if return_code != 0:
                raise Exception(f"토큰 발급 실패: {token_response.get('return_msg', '')}")

            self.access_token = token_response.get('token')
            self.last_token_time = datetime.now()
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
    
    def get_account_balance(self, account_no: str = None) -> Dict:
        """
        전체 활성 계좌 잔고 합산 조회

        Returns:
            Dict: 합산 계좌 잔고 정보
        """
        enabled_accounts = self.config.get_enabled_accounts()
        total = {
            'total_eval_amount': 0.0,
            'total_purchase_amount': 0.0,
            'total_profit_loss': 0.0,
            'deposit': 0.0,
            'holdings_count': 0,
        }

        for alias, account_info in enabled_accounts.items():
            try:
                token = self.get_account_token(
                    alias,
                    account_info['app_key'],
                    account_info['app_secret']
                )
                data = self._request_with_token(token, params={'qry_dt': datetime.now().strftime('%Y%m%d')}, api_id="ka01690")
                if not data:
                    continue

                total['total_eval_amount']    += float(data.get('tot_evlt_amt', 0))
                total['total_purchase_amount']+= float(data.get('tot_buy_amt', 0))
                total['total_profit_loss']    += float(data.get('tot_evltv_prft', 0))
                total['deposit']              += float(data.get('dbst_bal', 0))
                total['holdings_count']       += len(data.get('day_bal_rt', []))

                self.logger.info(
                    f"💰 {alias} 잔고: 평가 {float(data.get('tot_evlt_amt',0)):,.0f}원 "
                    f"/ 예수금 {float(data.get('dbst_bal',0)):,.0f}원"
                )
            except Exception as e:
                self.logger.error(f"❌ {alias} 잔고 조회 실패: {e}")

        # 합산 수익률 계산
        purchase = total['total_purchase_amount']
        total['profit_loss_rate'] = (
            total['total_profit_loss'] / purchase * 100 if purchase > 0 else 0.0
        )
        total['query_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        return total
    
    def get_deposit(self) -> float:
        """
        전체 활성 계좌의 D+2 추정예수금 합산 조회
        (kt00001 - 예수금상세현황요청, 계좌별 독립 토큰 사용)

        Returns:
            float: 전 계좌 D+2 추정예수금 합계
        """
        url = f"{self.base_url}/api/dostk/acnt"
        params = {'qry_tp': '2'}  # 2:일반조회

        enabled_accounts = self.config.get_enabled_accounts()
        total_deposit = 0.0

        for alias, account_info in enabled_accounts.items():
            try:
                token = self.get_account_token(
                    alias,
                    account_info['app_key'],
                    account_info['app_secret']
                )
                data = self._request_with_token(token, params, api_id="kt00001")

                if not data:
                    self.logger.warning(f"⚠️ {alias} 예수금 조회 응답 없음")
                    continue

                deposit = float(data.get('100stk_ord_alow_amt', 0))
                total_deposit += deposit
                self.logger.debug(f"💰 {alias} 주문가능금액(100%): {deposit:,.0f}원")

            except Exception as e:
                self.logger.error(f"❌ {alias} 예수금 조회 실패: {e}")

        self.logger.info(f"💰 전계좌 D+2 추정예수금 합계: {total_deposit:,.0f}원")
        return total_deposit
    
    def get_holdings(self, account_no: str = None) -> pd.DataFrame:
        """
        단일 토큰 기준 보유종목 조회 (내부용)
        계좌별 조회는 get_holdings_all() 사용 권장
        """
        url = f"{self.base_url}/api/dostk/acnt"
        params = {'qry_dt': datetime.now().strftime('%Y%m%d')}

        try:
            data = self.api_request(url, params, api_id="ka01690")
            if not data:
                return pd.DataFrame()
            return self._parse_holdings(data, account_no or 'main')
        except Exception as e:
            self.logger.error(f"❌ 보유종목 조회 실패: {e}")
            return pd.DataFrame()

    def _parse_holdings(self, data: dict, account_no: str) -> pd.DataFrame:
        """API 응답에서 보유종목 DataFrame 파싱 (공통)"""
        holdings_list = []
        for item in data.get('day_bal_rt', []):
            stock_code = item.get('stk_cd', '').strip()
            if not stock_code:
                continue
            quantity = int(item.get('rmnd_qty', 0))
            if quantity == 0:
                continue
            holdings_list.append({
                'account_no':       account_no,
                'stock_code':       stock_code,
                'stock_name':       item.get('stk_nm', ''),
                'quantity':         quantity,
                'avg_price':        float(item.get('buy_uv', 0)),
                'current_price':    float(item.get('cur_prc', 0)),
                'eval_amount':      float(item.get('evlt_amt', 0)),
                'purchase_amount':  float(item.get('buy_uv', 0)) * quantity,
                'profit_loss':      float(item.get('evltv_prft', 0)),
                'profit_rate':      float(item.get('prft_rt', 0)),
            })
        return pd.DataFrame(holdings_list)

    def _request_with_token(self, token: str, params: dict, api_id: str) -> Optional[dict]:
        """지정 토큰으로 API 요청"""
        url = f"{self.base_url}/api/dostk/acnt"
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "authorization": f"Bearer {token}",
            "api-id": api_id,
        }
        try:
            time.sleep(self.config.API_DELAY)
            response = requests.post(url, headers=headers,
                                     json=params or {},
                                     timeout=self.config.TIMEOUT)
            if response.status_code == 200:
                return response.json()
            self.logger.error(f"❌ HTTP {response.status_code}: {response.text[:300]}")
            return None
        except Exception as e:
            self.logger.error(f"❌ _request_with_token 실패: {e}")
            return None
    
    def get_holdings_all(self) -> pd.DataFrame:
        """
        활성화된 모든 계좌의 보유종목 조회 (계좌별 독립 토큰 사용, 로컬 합산)

        Returns:
            DataFrame: 전체 보유종목 (계좌별 구분 포함)
        """
        enabled_accounts = self.config.get_enabled_accounts()

        if not enabled_accounts:
            self.logger.warning("⚠️ 활성화된 계좌가 없습니다.")
            return pd.DataFrame()

        all_holdings = []

        for alias, account_info in enabled_accounts.items():
            account_no = account_info['account_no']
            self.logger.info(f"📊 계좌 조회 중: {alias} ({account_no})")
            try:
                token = self.get_account_token(
                    alias,
                    account_info['app_key'],
                    account_info['app_secret']
                )
                data = self._request_with_token(
                    token,
                    params={'qry_dt': datetime.now().strftime('%Y%m%d')},
                    api_id="ka01690"
                )
                if not data:
                    self.logger.warning(f"⚠️ {alias} 데이터 없음")
                    continue

                df = self._parse_holdings(data, account_no)
                if not df.empty:
                    df['account_alias'] = alias
                    df['account_description'] = account_info.get('description', alias)
                    all_holdings.append(df)
                    self.logger.info(f"✅ {alias} ({account_no}): {len(df)}개 종목")

            except Exception as e:
                self.logger.error(f"❌ {alias} 보유종목 조회 실패: {e}")

        if all_holdings:
            result_df = pd.concat(all_holdings, ignore_index=True)
            self.logger.info(f"✅ 전체 조회 완료: {len(result_df)}개 종목 ({len(all_holdings)}개 계좌)")
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
    

    def get_minute_price_data(self, stock_code: str, count: int = 120) -> list:
        """
        키움 REST API (ka10080) 주식분봉차트 조회
        NXT 시간외 거래(15:30 ~ 20:00) 포함 데이터 수집

        Args:
            stock_code: 종목코드 (6자리)
            count: 수집할 분봉 개수 (기본 120개)

        Returns:
            List[Dict]: DB 저장용 분봉 레코드 리스트
              - stock_code, trade_datetime, open_price, high_price,
                low_price, close_price, volume, trading_value
        """
        url = f"{self.base_url}/api/dostk/chart"

        all_records = []
        cont_yn  = "N"
        next_key = ""

        # 1회 900건 반환 → count를 채울 때까지 연속조회
        max_pages = max(1, (count // 900) + 2)   # 여유분 포함

        for page in range(max_pages):
            headers = {
                "Content-Type": "application/json;charset=UTF-8",
                "authorization": f"Bearer {self.get_access_token()}",
                "api-id": "ka10080",
            }
            if cont_yn == "Y":
                headers["cont-yn"]  = "Y"
                headers["next-key"] = next_key

            params = {
                "stk_cd":       stock_code,
                "tic_scope":    "1",        # 1분봉 고정
                "upd_stkpc_tp": "1",        # 수정주가 적용 (필수값)
            }

            try:
                time.sleep(self.config.API_DELAY)
                response = requests.post(
                    url,
                    headers=headers,
                    json=params,
                    timeout=self.config.TIMEOUT
                )
                response.raise_for_status()
                data = response.json()

            except Exception as e:
                self.logger.error(f"❌ {stock_code} 분봉 조회 실패 (page {page+1}): {e}")
                break

            if data.get("return_code", -1) != 0:
                self.logger.warning(
                    f"⚠️ {stock_code} 분봉 API 오류: {data.get('return_msg', '')}"
                )
                break

            raw_list = data.get("stk_min_pole_chart_qry", [])
            if not raw_list:
                break

            # 필드 변환 → DB 포맷
            for row in raw_list:
                try:
                    # cntr_tm: "20260226153000" → datetime
                    cntr_tm = str(row.get("cntr_tm", "")).strip()
                    if len(cntr_tm) != 14 or not cntr_tm.isdigit():
                        continue
                    trade_dt = datetime.strptime(cntr_tm, "%Y%m%d%H%M%S")

                    def to_int(val):
                        """'+1099000', '-500', '12345' → int"""
                        try:
                            return int(str(val).replace("+", "").replace(",", ""))
                        except (ValueError, TypeError):
                            return None

                    record = {
                        "stock_code":    stock_code,
                        "trade_datetime": trade_dt,
                        "open_price":    to_int(row.get("open_pric")),
                        "high_price":    to_int(row.get("high_pric")),
                        "low_price":     to_int(row.get("low_pric")),
                        "close_price":   to_int(row.get("cur_prc")),
                        "volume":        to_int(row.get("trde_qty")),
                        "trading_value": to_int(row.get("trde_qty")),  # 거래대금 없음 → 거래량 대체
                    }
                    all_records.append(record)

                except Exception as e:
                    self.logger.debug(f"레코드 변환 오류 ({stock_code}): {e}")
                    continue

            # count 충족 시 종료
            if len(all_records) >= count:
                all_records = all_records[:count]
                break

            # 연속조회 여부 확인 (헤더 우선, 없으면 본문)
            cont_yn  = response.headers.get("cont-yn",  data.get("cont_yn",  "N"))
            next_key = response.headers.get("next-key", data.get("next_key", ""))

            if cont_yn != "Y" or not next_key:
                break

        self.logger.info(
            f"✅ {stock_code}: 분봉 {len(all_records)}건 수집 "
            f"(NXT 포함, 키움 ka10080)"
        )
        return all_records

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
