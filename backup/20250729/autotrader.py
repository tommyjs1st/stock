import requests
import json
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import logging
from typing import Dict, List, Optional
import yaml
import os
from pathlib import Path

class KISAutoTrader:
    def __init__(self, config_path: str = "config.yaml"):
        """KIS API 기반 모멘텀 자동매매 시스템"""
        self.load_config(config_path)
        self.setup_logging()
        self.token_file = "token.json"  # 기존 프로그램과 동일한 파일명
        self.access_token = None
        self.positions = {}
        self.daily_pnl = 0
        self.trade_count = 0
        self.last_token_time = None
        self.load_saved_token()
        
    def load_config(self, config_path: str):
        """설정 파일 로드"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                
            # API 설정
            self.app_key = config['kis']['app_key']
            self.app_secret = config['kis']['app_secret']
            self.base_url = config['kis']['base_url']
            self.account_no = config['kis']['account_no']
            
            # 거래 설정
            self.symbols = config['trading']['symbols']
            self.max_position_ratio = config['trading']['max_position_ratio']
            self.daily_loss_limit = config['trading']['daily_loss_limit']
            self.stop_loss_pct = config['trading']['stop_loss_pct']
            self.take_profit_pct = config['trading']['take_profit_pct']
            
            # 모멘텀 설정
            self.momentum_period = config['momentum']['period']
            self.momentum_threshold = config['momentum']['threshold']
            self.volume_threshold = config['momentum']['volume_threshold']
            self.ma_short = config['momentum']['ma_short']
            self.ma_long = config['momentum']['ma_long']
            
            # 알림 설정
            notification = config.get('notification', {})
            self.discord_webhook = notification.get('discord_webhook', '')
            self.notify_on_trade = notification.get('notify_on_trade', True)
            self.notify_on_error = notification.get('notify_on_error', True)
            self.notify_on_daily_summary = notification.get('notify_on_daily_summary', True)
            
        except FileNotFoundError:
            self.create_sample_config(config_path)
            raise Exception(f"설정 파일이 없습니다. {config_path} 파일을 생성했으니 설정을 입력해주세요.")
    
    def create_sample_config(self, config_path: str):
        """샘플 설정 파일 생성"""
        sample_config = {
            'kis': {
                'app_key': 'YOUR_APP_KEY',
                'app_secret': 'YOUR_APP_SECRET',
                'base_url': 'https://openapi.koreainvestment.com:9443',
                'account_no': 'YOUR_ACCOUNT_NO'
            },
            'trading': {
                'symbols': ['005930', '062040', '278470'],
                'max_position_ratio': 0.1,  # 종목당 최대 10%
                'daily_loss_limit': 0.02,   # 일일 손실 한도 2%
                'stop_loss_pct': 0.05,      # 손절 5%
                'take_profit_pct': 0.15     # 익절 15%
            },
            'momentum': {
                'period': 20,               # 모멘텀 계산 기간
                'threshold': 0.02,          # 모멘텀 임계값 2%
                'volume_threshold': 1.5,    # 거래량 증가 배수
                'ma_short': 5,              # 단기 이동평균
                'ma_long': 20               # 장기 이동평균
            }
        }
        
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(sample_config, f, default_flow_style=False, allow_unicode=True)
    
    def setup_logging(self):
        """로깅 설정"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('autotrader.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def send_discord_notification(self, title: str, message: str, color: int = 0x00ff00):
        """디스코드 웹훅으로 알림 전송"""
        if not self.discord_webhook:
            return False
        
        try:
            # 임베드 형태로 예쁘게 메시지 구성
            embed = {
                "title": title,
                "description": message,
                "color": color,
                "timestamp": datetime.now().isoformat(),
                "footer": {
                    "text": "KIS 자동매매 시스템"
                }
            }
            
            data = {
                "embeds": [embed]
            }
            
            response = requests.post(
                self.discord_webhook,
                json=data,
                timeout=10
            )
            
            if response.status_code == 204:
                return True
            else:
                self.logger.error(f"디스코드 알림 전송 실패: {response.status_code}")
                return False
                
        except Exception as e:
            self.logger.error(f"디스코드 알림 오류: {e}")
            return False
    
    def notify_trade_success(self, action: str, symbol: str, quantity: int, price: int, order_no: str):
        """매매 성공 알림"""
        if not self.notify_on_trade:
            return
        
        action_emoji = "🛒" if action == "매수" else "💸"
        color = 0x00ff00 if action == "매수" else 0xff6600
        
        title = f"{action_emoji} {action} 주문 체결!"
        message = f"""
**종목**: {symbol}
**수량**: {quantity}주
**가격**: {price:,}원
**총액**: {quantity * price:,}원
**주문번호**: {order_no}
**시간**: {datetime.now().strftime('%H:%M:%S')}
        """
        
        self.send_discord_notification(title, message, color)
    
    def notify_trade_failure(self, action: str, symbol: str, error_msg: str):
        """매매 실패 알림"""
        if not self.notify_on_error:
            return
        
        title = f"❌ {action} 주문 실패"
        message = f"""
**종목**: {symbol}
**오류**: {error_msg}
**시간**: {datetime.now().strftime('%H:%M:%S')}
        """
        
        self.send_discord_notification(title, message, 0xff0000)
    
    def notify_signal_detected(self, symbol: str, signal: str, strength: float, momentum: float):
        """신호 감지 알림"""
        if not self.notify_on_trade:
            return
        
        signal_emoji = {"BUY": "📈", "SELL": "📉", "HOLD": "⏸️"}.get(signal, "❓")
        color = {"BUY": 0x00ff00, "SELL": 0xff0000, "HOLD": 0xffff00}.get(signal, 0x888888)
        
        title = f"{signal_emoji} 신호 감지: {signal}"
        message = f"""
**종목**: {symbol}
**신호 강도**: {strength:.2f}
**모멘텀**: {momentum:.2%}
**시간**: {datetime.now().strftime('%H:%M:%S')}
        """
        
        self.send_discord_notification(title, message, color)
    
    def notify_daily_summary(self, total_trades: int, profit_loss: float, successful_trades: int):
        """일일 요약 알림"""
        if not self.notify_on_daily_summary:
            return
        
        title = "📊 일일 거래 요약"
        color = 0x00ff00 if profit_loss >= 0 else 0xff0000
        
        message = f"""
**총 거래 횟수**: {total_trades}회
**성공한 거래**: {successful_trades}회
**일일 수익률**: {profit_loss:.2%}
**날짜**: {datetime.now().strftime('%Y-%m-%d')}
        """
        
        self.send_discord_notification(title, message, color)
    
    def notify_error(self, error_type: str, error_msg: str):
        """오류 알림"""
        if not self.notify_on_error:
            return
        
        title = f"⚠️ 시스템 오류: {error_type}"
        message = f"""
**오류 내용**: {error_msg}
**시간**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        self.send_discord_notification(title, message, 0xff0000)
    
    def load_saved_token(self):
        """저장된 토큰 파일에서 토큰 로드 (기존 프로그램과 호환)"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    token_data = json.load(f)
                
                # 기존 형식의 만료시간 파싱
                expire_time_str = token_data.get('access_token_token_expired', '')
                if expire_time_str:
                    expire_time = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')
                    
                    # 토큰이 아직 유효한지 확인 (10분 여유 둠)
                    if datetime.now() < expire_time - timedelta(minutes=10):
                        self.access_token = token_data.get('access_token')
                        self.last_token_time = datetime.fromtimestamp(token_data.get('requested_at', 0))
                        self.logger.info(f"기존 토큰을 재사용합니다. (만료: {expire_time_str})")
                        return True
                    else:
                        self.logger.info(f"저장된 토큰이 만료되었습니다. (만료: {expire_time_str})")
                        
        except Exception as e:
            self.logger.warning(f"토큰 파일 로드 실패: {e}")
        
        return False
    
    def save_token(self, token_response: dict):
        """토큰을 기존 프로그램과 호환되는 형식으로 저장"""
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
            
            self.logger.info(f"토큰이 저장되었습니다. (만료: {token_data['access_token_token_expired']})")
            
        except Exception as e:
            self.logger.error(f"토큰 저장 실패: {e}")
    
    def get_access_token(self) -> str:
        """KIS API 액세스 토큰 발급 또는 재사용 (기존 프로그램과 호환)"""
        # 메모리에 유효한 토큰이 있는지 확인
        if self.access_token and self.last_token_time:
            # 23시간 이내면 메모리 토큰 재사용
            if datetime.now() - self.last_token_time < timedelta(hours=23):
                return self.access_token
        
        # 저장된 토큰 재확인
        if self.load_saved_token():
            return self.access_token
        
        # 새 토큰 발급
        self.logger.info("새로운 액세스 토큰을 발급받습니다...")
        
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
            
            if token_response.get("rt_cd") != "0":
                raise Exception(f"토큰 발급 실패: {token_response.get('msg1', 'Unknown error')}")
            
            self.access_token = token_response["access_token"]
            self.last_token_time = datetime.now()
            
            # 토큰을 기존 형식으로 파일에 저장
            self.save_token(token_response)
            
            self.logger.info("✅ 새로운 액세스 토큰 발급 완료")
            return self.access_token
            
        except Exception as e:
            self.logger.error(f"❌ 토큰 발급 실패: {e}")
            raise
    
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
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"현재가 조회 실패 ({symbol}): {e}")
            return None
    
    def get_minute_data(self, symbol: str, minutes: int = 60) -> pd.DataFrame:
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
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                df['stck_cntg_hour'] = pd.to_datetime(df['stck_cntg_hour'], format='%H%M%S')
                numeric_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'cntg_vol']
                for col in numeric_cols:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                return df.sort_values('stck_cntg_hour').reset_index(drop=True)
            
        except Exception as e:
            self.logger.error(f"분봉 데이터 조회 실패 ({symbol}): {e}")
        
        return pd.DataFrame()
    
    def calculate_momentum_signals(self, df: pd.DataFrame) -> Dict:
        """모멘텀 신호 계산"""
        if len(df) < max(self.ma_long, self.momentum_period):
            return {'signal': 'HOLD', 'strength': 0}
        
        # 이동평균선
        df['ma_short'] = df['stck_prpr'].rolling(self.ma_short).mean()
        df['ma_long'] = df['stck_prpr'].rolling(self.ma_long).mean()
        
        # 모멘텀 계산
        current_price = df['stck_prpr'].iloc[-1]
        past_price = df['stck_prpr'].iloc[-(self.momentum_period+1)]
        momentum = (current_price - past_price) / past_price
        
        # 거래량 증가율
        avg_volume = df['cntg_vol'].rolling(20).mean().iloc[-2]
        current_volume = df['cntg_vol'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
        
        # 신호 생성
        signal = 'HOLD'
        strength = 0
        
        latest = df.iloc[-1]
        if (latest['ma_short'] > latest['ma_long'] and 
            momentum > self.momentum_threshold and 
            volume_ratio > self.volume_threshold):
            signal = 'BUY'
            strength = min((momentum / self.momentum_threshold) * (volume_ratio / self.volume_threshold), 5)
            
        elif (latest['ma_short'] < latest['ma_long'] or 
              momentum < -self.momentum_threshold/2):
            signal = 'SELL'
            strength = abs(momentum) / self.momentum_threshold
        
        return {
            'signal': signal,
            'strength': strength,
            'momentum': momentum,
            'volume_ratio': volume_ratio,
            'ma_short': latest['ma_short'],
            'ma_long': latest['ma_long'],
            'current_price': current_price
        }
    
    def get_account_balance(self) -> Dict:
        """계좌 잔고 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "TTTC8434R"
        }
        params = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "PDNO": "",
            "ORD_UNPR": "",
            "ORD_DVSN": "01",
            "CMA_EVLU_AMT_ICLD_YN": "Y",
            "OVRS_ICLD_YN": "Y"
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            self.logger.error(f"계좌 조회 실패: {e}")
            return {}
    
    def place_order(self, symbol: str, side: str, quantity: int, price: int = 0) -> Dict:
        """주문 실행"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "TTTC0802U" if side == "BUY" else "TTTC0801U"
        }
        
        data = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "PDNO": symbol,
            "ORD_DVSN": "01" if price > 0 else "01",  # 지정가 주문
            "ORD_QTY": str(quantity),
            "ORD_UNPR": str(price) if price > 0 else "0"
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            result = response.json()
            
            if result.get('rt_cd') == '0':
                order_no = result.get('output', {}).get('odno', 'Unknown')
                self.logger.info(f"주문 성공: {symbol} {side} {quantity}주 (주문번호: {order_no})")
                self.trade_count += 1
                return {'success': True, 'order_no': order_no}
            else:
                self.logger.error(f"주문 실패: {result.get('msg1', 'Unknown error')}")
                return {'success': False, 'error': result.get('msg1')}
                
        except Exception as e:
            self.logger.error(f"주문 실행 실패 ({symbol} {side}): {e}")
            return {'success': False, 'error': str(e)}
    
    def calculate_position_size(self, symbol: str, current_price: float, signal_strength: float) -> int:
        """포지션 크기 계산"""
        try:
            account_data = self.get_account_balance()
            if not account_data:
                return 0
                
            # 가용 자금 계산
            available_cash = float(account_data.get('output', {}).get('ord_psbl_cash', 0))
            
            # 최대 투자 가능 금액
            max_investment = available_cash * self.max_position_ratio
            
            # 신호 강도에 따른 조정
            adjusted_investment = max_investment * min(signal_strength / 3, 1.0)
            
            # 주문 가능 수량
            quantity = int(adjusted_investment / current_price)
            
            return max(quantity, 0)
            
        except Exception as e:
            self.logger.error(f"포지션 크기 계산 실패: {e}")
            return 0
    
    def check_risk_management(self) -> bool:
        """리스크 관리 체크"""
        # 일일 손실 한도 체크
        if abs(self.daily_pnl) > self.daily_loss_limit:
            self.logger.warning(f"일일 손실 한도 초과: {self.daily_pnl:.2%}")
            return False
        
        # 최대 거래 횟수 체크 (하루 100회 제한)
        if self.trade_count > 100:
            self.logger.warning("일일 최대 거래 횟수 초과")
            return False
            
        return True
    
    def update_positions(self):
        """포지션 업데이트"""
        try:
            account_data = self.get_account_balance()
            if not account_data:
                return
                
            # 현재 보유 종목 업데이트
            self.positions = {}
            outputs = account_data.get('output1', [])
            
            for position in outputs:
                symbol = position.get('pdno', '')
                if symbol in self.symbols:
                    quantity = int(position.get('hldg_qty', 0))
                    if quantity > 0:
                        self.positions[symbol] = {
                            'quantity': quantity,
                            'avg_price': float(position.get('pchs_avg_pric', 0)),
                            'current_price': float(position.get('prpr', 0)),
                            'profit_loss': float(position.get('evlu_pfls_rt', 0))
                        }
                        
        except Exception as e:
            self.logger.error(f"포지션 업데이트 실패: {e}")
    
    def process_symbol(self, symbol: str):
        """개별 종목 처리"""
        try:
            # 분봉 데이터 조회
            df = self.get_minute_data(symbol)
            if df.empty:
                return
            
            # 모멘텀 신호 계산
            signals = self.calculate_momentum_signals(df)
            current_price = signals['current_price']
            
            self.logger.info(f"{symbol} - 신호: {signals['signal']}, "
                           f"강도: {signals['strength']:.2f}, "
                           f"모멘텀: {signals['momentum']:.2%}, "
                           f"현재가: {current_price:,}원")
            
            # 강한 신호일 때만 디스코드 알림 (노이즈 방지)
            if signals['strength'] > 2.0:
                self.notify_signal_detected(symbol, signals['signal'], signals['strength'], signals['momentum'])
            
            # 현재 포지션 확인
            current_position = self.positions.get(symbol, {})
            has_position = current_position.get('quantity', 0) > 0
            
            if signals['signal'] == 'BUY' and not has_position:
                # 매수 신호 & 포지션 없음
                quantity = self.calculate_position_size(symbol, current_price, signals['strength'])
                if quantity > 0:
                    result = self.place_order(symbol, 'BUY', quantity, int(current_price))
                    if result['success']:
                        self.logger.info(f"✅ {symbol} 매수 주문 완료: {quantity}주 @ {current_price:,}원")
                        
            elif signals['signal'] == 'SELL' and has_position:
                # 매도 신호 & 포지션 있음
                quantity = current_position['quantity']
                result = self.place_order(symbol, 'SELL', quantity, int(current_price))
                if result['success']:
                    profit_loss = current_position['profit_loss']
                    self.logger.info(f"✅ {symbol} 매도 주문 완료: {quantity}주 @ {current_price:,}원 "
                                   f"(수익률: {profit_loss:.2%})")
                    # 디스코드 알림
                    order_no = result.get('order_no', 'Unknown')
                    self.notify_trade_success("매도", symbol, quantity, current_price, order_no)
                else:
                    error_msg = result.get('error', 'Unknown error')
                    self.logger.error(f"❌ {symbol} 매도 주문 실패: {error_msg}")
                    self.notify_trade_failure("매도", symbol, error_msg)
                    
            elif has_position:
                # 포지션 있는 경우 손익 관리
                profit_loss = current_position['profit_loss'] / 100
                avg_price = current_position['avg_price']
                
                # 손절 체크
                if profit_loss <= -self.stop_loss_pct:
                    quantity = current_position['quantity']
                    result = self.place_order(symbol, 'SELL', quantity, int(current_price))
                    if result['success']:
                        self.logger.warning(f"🛑 {symbol} 손절 매도: {quantity}주 @ {current_price:,}원 "
                                          f"(손실: {profit_loss:.2%})")
                        order_no = result.get('order_no', 'Unknown')
                        self.notify_trade_success("손절매도", symbol, quantity, current_price, order_no)
                
                # 익절 체크
                elif profit_loss >= self.take_profit_pct:
                    quantity = current_position['quantity']
                    result = self.place_order(symbol, 'SELL', quantity, int(current_price))
                    if result['success']:
                        self.logger.info(f"🎯 {symbol} 익절 매도: {quantity}주 @ {current_price:,}원 "
                                       f"(수익: {profit_loss:.2%})")
                        order_no = result.get('order_no', 'Unknown')
                        self.notify_trade_success("익절매도", symbol, quantity, current_price, order_no)
                        
        except Exception as e:
            self.logger.error(f"{symbol} 처리 중 오류: {e}")
            self.notify_error("종목 처리 오류", f"{symbol}: {str(e)}")
    
    def run_trading_cycle(self):
        """한 번의 트레이딩 사이클 실행"""
        if not self.check_risk_management():
            self.logger.warning("리스크 관리 조건 위반 - 거래 중단")
            return
        
        # 포지션 업데이트
        self.update_positions()
        
        # 각 종목별로 처리
        for symbol in self.symbols:
            self.process_symbol(symbol)
            time.sleep(1)  # API 호출 간격 조절
    
    def run(self, interval_minutes: int = 5):
        """자동매매 시작"""
        self.logger.info("🚀 KIS API 모멘텀 자동매매 시작!")
        self.logger.info(f"대상 종목: {', '.join(self.symbols)}")
        self.logger.info(f"실행 간격: {interval_minutes}분")
        
        # 시작 알림
        if self.discord_webhook:
            self.send_discord_notification(
                "🚀 자동매매 시작", 
                f"대상 종목: {', '.join(self.symbols)}\n실행 간격: {interval_minutes}분",
                0x00ff00
            )
        
        daily_trades = 0
        successful_trades = 0
        last_daily_summary = datetime.now().date()
        
        try:
            # 토큰 발급/로드 테스트
            token = self.get_access_token()
            if token:
                self.logger.info("토큰 준비 완료 ✅")
            
            while True:
                current_time = datetime.now()
                
                # 일일 요약 알림 (하루 한 번)
                if current_time.date() != last_daily_summary and current_time.hour >= 16:
                    self.notify_daily_summary(daily_trades, self.daily_pnl, successful_trades)
                    daily_trades = 0
                    successful_trades = 0
                    self.daily_pnl = 0
                    last_daily_summary = current_time.date()
                
                # 장 시간 체크 (9:00 ~ 15:30)
                if 9 <= current_time.hour < 15 or (current_time.hour == 15 and current_time.minute <= 30):
                    self.logger.info(f"📊 거래 사이클 시작 - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    cycle_start_trades = self.trade_count
                    self.run_trading_cycle()
                    
                    # 이번 사이클에서 거래가 발생했는지 확인
                    if self.trade_count > cycle_start_trades:
                        daily_trades += (self.trade_count - cycle_start_trades)
                        successful_trades += (self.trade_count - cycle_start_trades)  # 간단히 거래=성공으로 가정
                    
                    self.logger.info("✅ 거래 사이클 완료\n")
                else:
                    self.logger.info("장 시간 외 - 대기 중...")
                
                # 지정된 간격만큼 대기
                time.sleep(interval_minutes * 60)
                
        except KeyboardInterrupt:
            self.logger.info("사용자가 프로그램을 종료했습니다.")
            if self.discord_webhook:
                self.send_discord_notification("⏹️ 자동매매 종료", "사용자가 프로그램을 종료했습니다.", 0xff6600)
        except Exception as e:
            self.logger.error(f"프로그램 실행 중 오류: {e}")
            self.notify_error("프로그램 오류", str(e))
        finally:
            self.logger.info("자동매매 프로그램 종료")
            # 프로그램 종료 시 토큰 파일은 유지 (다른 프로그램과 공유)
            # 필요시 수동 삭제: rm token.json

if __name__ == "__main__":
    # 자동매매 실행
    trader = KISAutoTrader()
    trader.run(interval_minutes=5)  # 5분마다 실행
