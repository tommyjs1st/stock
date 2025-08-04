import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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
import sys


class PositionManager:
    """종목별 포지션 관리 클래스"""
    
    def __init__(self, trader):
        self.trader = trader
        self.position_history_file = "position_history.json"
        self.position_history = {}
        self.load_position_history()
    
    def load_position_history(self):
        """포지션 이력 로드"""
        try:
            if os.path.exists(self.position_history_file):
                with open(self.position_history_file, 'r', encoding='utf-8') as f:
                    self.position_history = json.load(f)
                self.trader.logger.info(f"📋 포지션 이력 로드: {len(self.position_history)}개 종목")
        except Exception as e:
            self.trader.logger.error(f"포지션 이력 로드 실패: {e}")
            self.position_history = {}
    
    def save_position_history(self):
        """포지션 이력 저장"""
        try:
            with open(self.position_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.position_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.trader.logger.error(f"포지션 이력 저장 실패: {e}")
    
    def record_purchase(self, symbol: str, quantity: int, price: float, strategy: str):
        """매수 기록"""
        now = datetime.now()
        
        if symbol not in self.position_history:
            self.position_history[symbol] = {
                'total_quantity': 0,
                'purchase_count': 0,
                'purchases': [],
                'last_purchase_time': None,
                'first_purchase_time': None
            }
        
        # 매수 기록 추가
        purchase_record = {
            'timestamp': now.isoformat(),
            'quantity': quantity,
            'price': price,
            'strategy': strategy,
            'order_type': 'BUY'
        }
        
        self.position_history[symbol]['purchases'].append(purchase_record)
        self.position_history[symbol]['total_quantity'] += quantity
        self.position_history[symbol]['purchase_count'] += 1
        self.position_history[symbol]['last_purchase_time'] = now.isoformat()
        
        if not self.position_history[symbol]['first_purchase_time']:
            self.position_history[symbol]['first_purchase_time'] = now.isoformat()
        
        self.save_position_history()
        
        self.trader.logger.info(f"📝 매수 기록: {symbol} {quantity}주 @ {price:,}원 "
                               f"(누적: {self.position_history[symbol]['total_quantity']}주)")
    
    def record_sale(self, symbol: str, quantity: int, price: float, reason: str):
        """매도 기록"""
        now = datetime.now()
        
        if symbol in self.position_history:
            sale_record = {
                'timestamp': now.isoformat(),
                'quantity': quantity,
                'price': price,
                'reason': reason,
                'order_type': 'SELL'
            }
            
            self.position_history[symbol]['purchases'].append(sale_record)
            self.position_history[symbol]['total_quantity'] -= quantity
            
            # 수량이 0이 되면 포지션 완전 정리
            if self.position_history[symbol]['total_quantity'] <= 0:
                self.position_history[symbol]['total_quantity'] = 0
                self.position_history[symbol]['position_closed_time'] = now.isoformat()
            
            self.save_position_history()
            
            self.trader.logger.info(f"📝 매도 기록: {symbol} {quantity}주 @ {price:,}원 "
                                   f"사유: {reason} (잔여: {self.position_history[symbol]['total_quantity']}주)")

class KISAutoTrader:

    def __init__(self, config_path: str = "config.yaml"):
        """KIS API 기반 모멘텀 자동매매 시스템"""

        # 먼저 필수 속성들을 초기화
        self.token_file = "token.json"  # 기존 프로그램과 동일한 파일명
        self.access_token = None
        self.positions = {}
        self.daily_pnl = 0
        self.trade_count = 0
        self.last_token_time = None
        self.strategy_map = {}  # 종목별 전략 매핑
        
        self.skip_stock_name_api = False
        self.api_error_count = 0

        # MACD 설정 추가
        self.macd_fast = 12
        self.macd_slow = 26
        self.macd_signal = 9
        self.macd_cross_lookback = 3
        self.macd_trend_confirmation = 5

        # 종목명 캐시 초기화
        self.stock_names = {}
        self.stock_names_file = "stock_names.json"
        
        # 로깅 설정을 먼저 수행
        self.setup_logging()
        
        # 저장된 종목명 로드
        self.load_stock_names()

        # 종목명 캐시 검증
        self.validate_stock_names_cache()

        # 그 다음 설정 파일 로드
        self.load_config(config_path)
        
        # 마지막으로 토큰 로드
        self.load_saved_token()

        # 모든 거래 종목의 이름 미리 업데이트
        self.update_all_stock_names()

        # 포지션 관리자 초기화
        self.position_manager = PositionManager(self)

        # 매수 제한 설정 (config에서 로드)
        self.max_purchases_per_symbol = 3  # 종목당 최대 매수 횟수
        self.max_quantity_per_symbol = 100  # 종목당 최대 보유 수량
        self.min_holding_period_hours = 24  # 최소 보유 기간 (시간)
        self.purchase_cooldown_hours = 6   # 매수 후 재매수 금지 기간
    
        # 설정 파일에서 로드하도록 수정
        self.load_position_settings()


        # 전체 보유 종목 저장용 (매도 로직용)
        self.all_positions = {}
    
        # 매수/매도 분리 실행 여부
        self.use_improved_logic = True  # config에서 설정 가능

        # 개선된 API 설정
        self.api_timeout = 30  # 타임아웃을 30초로 증가
        self.api_retry_count = 3  # 재시도 횟수 증가
        self.api_retry_delay = 2  # 재시도 간격 증가
        
        # 요청 세션 설정 (연결 재사용)
        self.session = self.create_robust_session()
        
        # API 호출 간격 제어
        self.last_api_call = None
        self.min_api_interval = 0.5  # 최소 0.5초 간격
        
        # 타임아웃 발생 시 대체 로직 활성화
        self.fallback_mode = False
        self.fallback_timeout_count = 0
        self.max_fallback_timeouts = 5

        # 종목명 조회 건너뛰기 플래그
        self.skip_stock_name_api = False
        self.api_error_count = 0

        
        # MACD 골든크로스 감지 설정
        self.macd_cross_lookback = 3  # 몇 봉 전까지 크로스 확인
        self.macd_trend_confirmation = 5  # 추세 확인 기간

    def load_position_settings(self):
        """포지션 관리 설정 로드"""
        try:
            # config.yaml에서 position_management 섹션 읽기
            with open('config.yaml', 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            position_config = config.get('position_management', {})
            
            self.max_purchases_per_symbol = position_config.get('max_purchases_per_symbol', 3)
            self.max_quantity_per_symbol = position_config.get('max_quantity_per_symbol', 100)
            self.min_holding_period_hours = position_config.get('min_holding_period_hours', 24)
            self.purchase_cooldown_hours = position_config.get('purchase_cooldown_hours', 6)
            
            self.logger.info(f"📊 포지션 관리 설정:")
            self.logger.info(f"  - 종목당 최대 매수 횟수: {self.max_purchases_per_symbol}회")
            self.logger.info(f"  - 종목당 최대 보유 수량: {self.max_quantity_per_symbol}주")
            self.logger.info(f"  - 최소 보유 기간: {self.min_holding_period_hours}시간")
            self.logger.info(f"  - 재매수 금지 기간: {self.purchase_cooldown_hours}시간")
            
        except Exception as e:
            self.logger.warning(f"포지션 설정 로드 실패, 기본값 사용: {e}")
    
    def can_sell_symbol(self, symbol: str) -> tuple[bool, str]:
        """종목 매도 가능 여부 확인"""
        
        # 1. 보유 여부 확인
        current_position = self.positions.get(symbol, {})
        if not current_position or current_position.get('quantity', 0) <= 0:
            return False, "보유 포지션 없음"
        
        # 2. 최소 보유 기간 확인
        history = self.position_manager.position_history.get(symbol, {})
        first_purchase_time = history.get('first_purchase_time')
        
        if first_purchase_time:
            first_time = datetime.fromisoformat(first_purchase_time)
            holding_time = datetime.now() - first_time
            
            if holding_time < timedelta(hours=self.min_holding_period_hours):
                remaining_hours = self.min_holding_period_hours - holding_time.total_seconds() / 3600
                return False, f"최소 보유 기간 미충족 (남은 시간: {remaining_hours:.1f}시간)"
        else:
            # 수동 매수한 경우 - 오늘 장 시작 시간을 기준으로 가정
            today_market_start = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        
            # 주말이면 이전 금요일로 조정
            while today_market_start.weekday() >= 5:
                today_market_start -= timedelta(days=1)
        
            holding_time = datetime.now() - today_market_start
        
            if holding_time < timedelta(hours=self.min_holding_period_hours):
                remaining_hours = self.min_holding_period_hours - holding_time.total_seconds() / 3600
                return False, f"수동 매수 종목 - 최소 보유 기간 미충족 (남은 시간: {remaining_hours:.1f}시간)"
        
        return True, "매도 가능"
    
    def initialize_manual_positions(self):
        """수동 매수 종목들의 이력 초기화"""
    
        for symbol in self.all_positions.keys():
            history = self.position_manager.position_history.get(symbol, {})
        
            if not history.get('first_purchase_time'):
                # 수동 매수 종목으로 판단하여 오늘 장 시작 시간으로 설정
                today_start = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
            
                # 주말 조정
                while today_start.weekday() >= 5:
                    today_start -= timedelta(days=1)
            
                # 이력 생성
                if symbol not in self.position_manager.position_history:
                    self.position_manager.position_history[symbol] = {
                        'total_quantity': 0,
                        'purchase_count': 0,
                        'purchases': [],
                        'last_purchase_time': None,
                        'first_purchase_time': None
                    }
            
                self.position_manager.position_history[symbol]['first_purchase_time'] = today_start.isoformat()
                self.position_manager.position_history[symbol]['manual_position'] = True
                
                self.logger.info(f"📝 {symbol} 수동 매수 종목 이력 초기화: {today_start}")
    
        self.position_manager.save_position_history()

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
            trading_config = config['trading']
            self.max_symbols = trading_config.get('max_symbols', 5)
            self.max_position_ratio = trading_config['max_position_ratio']
            self.daily_loss_limit = trading_config['daily_loss_limit']
            self.stop_loss_pct = trading_config['stop_loss_pct']
            self.take_profit_pct = trading_config['take_profit_pct']

            # 주문 전략 설정 추가
            self.order_strategy = trading_config.get('order_strategy', 'limit')
            self.price_offset_pct = trading_config.get('price_offset_pct', 0.003)
            self.order_timeout_minutes = trading_config.get('order_timeout_minutes', 5)
            self.partial_fill_allowed = trading_config.get('partial_fill_allowed', True)

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

            # 백테스트 설정
            backtest = config.get('backtest', {})
            self.backtest_results_file = backtest.get('results_file', 'backtest_results.json')
            self.min_return_threshold = backtest.get('min_return_threshold', 5.0)
            self.performance_tracking = backtest.get('performance_tracking', True)
            
            # 종목 설정 - 백테스트 결과에서 로드
            self.symbols = self.load_symbols_from_backtest(config)

        except FileNotFoundError:
            self.create_sample_config(config_path)
            raise Exception(f"설정 파일이 없습니다. {config_path} 파일을 생성했으니 설정을 입력해주세요.")
        except Exception as e:
            self.logger.error(f"설정 파일 로드 중 오류: {e}")
            raise

    def load_symbols_from_backtest(self, config: dict) -> List[str]:
        """백테스트 결과에서 종목 로드"""
        symbols = []
        
        # 1. 먼저 config에 직접 지정된 symbols가 있는지 확인
        if 'symbols' in config.get('trading', {}):
            symbols = config['trading']['symbols']
            self.logger.info(f"설정 파일에서 종목 로드: {symbols}")
            return symbols
        
        # 2. 백테스트 결과 파일에서 로드
        try:
            if os.path.exists(self.backtest_results_file):
                with open(self.backtest_results_file, 'r', encoding='utf-8') as f:
                    backtest_data = json.load(f)
                
                # 최소 수익률 기준으로 필터링
                verified_symbols = backtest_data.get('verified_symbols', [])
                filtered_symbols = [
                    item for item in verified_symbols 
                    if item['return'] >= self.min_return_threshold
                ]
                
                # 우선순위대로 정렬 (priority가 낮을수록 우선)
                filtered_symbols.sort(key=lambda x: x['priority'])
                
                # 최대 종목 수만큼 선택
                selected = filtered_symbols[:self.max_symbols]
                symbols = [item['symbol'] for item in selected]
                
                # 종목별 전략 매핑 저장
                for item in selected:
                    self.strategy_map[item['symbol']] = item['strategy']
                
                self.logger.info(f"백테스트 결과에서 종목 로드: {symbols}")
                
                # 선택된 종목의 상세 정보 출력
                for item in selected:
                    self.logger.info(f"  - {item['symbol']}: 수익률 {item['return']}%, "
                                   f"승률 {item['win_rate']:.1%}, 전략: {item['strategy']}")
                
                # 백테스트 결과 알림
                if self.discord_webhook and symbols:
                    self.notify_backtest_selection(selected, backtest_data.get('summary', {}))
                    
            else:
                self.logger.warning(f"백테스트 결과 파일을 찾을 수 없습니다: {self.backtest_results_file}")
                # config.yaml의 백테스트 섹션에서 가져오기
                backtest_symbols = config.get('backtest', {}).get('verified_symbols', [])
                if backtest_symbols:
                    # 수익률 기준으로 정렬
                    backtest_symbols.sort(key=lambda x: x.get('return', 0), reverse=True)
                    symbols = [s['symbol'] for s in backtest_symbols[:self.max_symbols]]
                    self.logger.info(f"config.yaml 백테스트 섹션에서 종목 로드: {symbols}")
                
        except Exception as e:
            self.logger.error(f"백테스트 결과 로드 실패: {e}")
            # 기본 종목 설정
            symbols = ['005930', '035720']  # 삼성전자, 카카오
            self.logger.warning(f"기본 종목으로 설정: {symbols}")
        
        return symbols

    def notify_backtest_selection(self, selected_symbols: List[Dict], summary: Dict):
        """백테스트 기반 종목 선택 알림"""
        title = "📊 백테스트 기반 종목 선택"
        
        symbol_info = []
        for item in selected_symbols:
            symbol_info.append(
                f"**{item['symbol']}**: 수익률 {item['return']}%, "
                f"전략: {item['strategy']}"
            )
        
        message = f"""
**선택된 종목**:
{chr(10).join(symbol_info)}

**백테스트 요약**:
- 평균 수익률: {summary.get('avg_return', 0):.2f}%
- 최고 종목: {summary.get('best_symbol', 'N/A')}
- 최고 수익률: {summary.get('best_return', 0):.2f}%

**시간**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        self.send_discord_notification(title, message, 0x00ff00)

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
                'max_symbols': 5,
                'max_position_ratio': 0.1,
                'daily_loss_limit': 0.02,
                'stop_loss_pct': 0.05,
                'take_profit_pct': 0.15
            },
            'momentum': {
                'period': 20,
                'threshold': 0.02,
                'volume_threshold': 1.5,
                'ma_short': 5,
                'ma_long': 20
            },
            'backtest': {
                'results_file': 'backtest_results.json',
                'min_return_threshold': 5.0,
                'performance_tracking': True
            },
            'notification': {
                'discord_webhook': '',
                'notify_on_trade': True,
                'notify_on_error': True,
                'notify_on_daily_summary': True
            }
        }

        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(sample_config, f, default_flow_style=False, allow_unicode=True)


    def setup_logging(self):
        """로깅 설정 - 디버그 모드"""
        # 로그 레벨을 DEBUG로 변경
        logging.basicConfig(
            level=logging.INFO,  # INFO -> DEBUG로 변경
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/autotrader.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def send_discord_notification(self, title: str, message: str, color: int = 0x00ff00):
        """디스코드 웹훅으로 알림 전송"""
        if not self.discord_webhook:
            return False

        try:
            korea_now = datetime.now()
            utc_time = korea_now - timedelta(hours=9)
            embed = {
                "title": title,
                "description": message,
                "color": color,
                "timestamp": utc_time.isoformat() + "Z",
                "footer": {
                    "text": "KIS 자동매매 시스템"
                }
            }

            data = {"embeds": [embed]}

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

        # 전략 정보 추가
        strategy = self.strategy_map.get(symbol, "momentum")
        
        stock_name = self.get_stock_name(symbol)
        title = f"{action_emoji} {action} 주문 체결!"
        message = f"""
**종목**: {symbol} ({stock_name})
**수량**: {quantity}주
**가격**: {price:,}원
**총액**: {quantity * price:,}원
**전략**: {strategy}
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

    def notify_signal_detected(self, symbol: str, signal: str, strength: float, momentum: float = 0):
        """신호 감지 알림"""
        if not self.notify_on_trade:
            return
    
        signal_emoji = {"BUY": "📈", "SELL": "📉", "HOLD": "⏸️"}.get(signal, "❓")
        color = {"BUY": 0x00ff00, "SELL": 0xff0000, "HOLD": 0xffff00}.get(signal, 0x888888)
    
        # 전략 정보 가져오기
        strategy = self.strategy_map.get(symbol, "momentum")
        
        title = f"{signal_emoji} 신호 감지: {signal}"
        
        # 전략별로 다른 정보 표시
        if strategy == 'momentum' and momentum != 0:
            message = f"""
**종목**: {symbol}
**전략**: {strategy}
**신호 강도**: {strength:.2f}
**모멘텀**: {momentum:.2%}
**시간**: {datetime.now().strftime('%H:%M:%S')}
            """
        elif strategy == 'scalping':
            message = f"""
**종목**: {symbol}
**전략**: {strategy}
**신호 강도**: {strength:.2f}
**타입**: 단기 매매 신호
**시간**: {datetime.now().strftime('%H:%M:%S')}
            """
        elif strategy == 'mean_reversion':
            message = f"""
**종목**: {symbol}
**전략**: {strategy}
**신호 강도**: {strength:.2f}
**타입**: 평균 회귀 신호
**시간**: {datetime.now().strftime('%H:%M:%S')}
            """
        elif strategy == 'breakout':
            message = f"""
**종목**: {symbol}
**전략**: {strategy}
**신호 강도**: {strength:.2f}
**타입**: 돌파 신호
**시간**: {datetime.now().strftime('%H:%M:%S')}
            """
        else:
            message = f"""
**종목**: {symbol}
**전략**: {strategy}
**신호 강도**: {strength:.2f}
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
**거래 종목**: {', '.join(self.symbols)}
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
            
            # 응답 구조 상세 로깅
            #self.logger.debug(f"토큰 API 응답: {token_response}")
            
            # 성공 조건 개선: access_token이 있으면 성공으로 판단
            access_token = token_response.get("access_token")
            
            if access_token:
                # 토큰이 있으면 성공
                self.access_token = access_token
                self.last_token_time = datetime.now()
    
                # 토큰을 기존 형식으로 파일에 저장
                self.save_token(token_response)
    
                self.logger.info("✅ 새로운 액세스 토큰 발급 완료")
                return self.access_token
            
            else:
                # 토큰이 없으면 실패 - rt_cd 기반 오류 처리
                rt_cd = token_response.get("rt_cd")
                
                if rt_cd and rt_cd != "0":
                    # rt_cd가 있고 실패인 경우
                    error_msg = token_response.get('msg1', 
                               token_response.get('message', 
                               token_response.get('error_description', 'Unknown error')))
                    error_code = token_response.get('msg_cd', token_response.get('error_code', 'Unknown'))
                    
                    self.logger.error(f"토큰 발급 실패 상세:")
                    self.logger.error(f"  - rt_cd: {rt_cd}")
                    self.logger.error(f"  - error_code: {error_code}")
                    self.logger.error(f"  - error_msg: {error_msg}")
                    
                    raise Exception(f"토큰 발급 실패 [{error_code}]: {error_msg}")
                else:
                    # access_token도 없고 rt_cd도 없는 경우
                    self.logger.error(f"예상치 못한 응답 형식: {token_response}")
                    raise Exception("토큰 응답에 access_token이 포함되지 않았습니다")
    
        except requests.exceptions.RequestException as e:
            self.logger.error(f"❌ 토큰 발급 네트워크 오류: {e}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"❌ 토큰 응답 JSON 파싱 오류: {e}")
            self.logger.error(f"응답 내용: {response.text if 'response' in locals() else 'N/A'}")
            raise
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


    def calculate_mean_reversion_signals(self, df: pd.DataFrame) -> Dict:
        """평균회귀 전략 신호 계산"""
        if len(df) < 20:
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
        
        # 볼린저 밴드
        df['bb_middle'] = df['stck_prpr'].rolling(20).mean()
        bb_std = df['stck_prpr'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        
        # RSI (간단 버전)
        delta = df['stck_prpr'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        current_price = df['stck_prpr'].iloc[-1]
        latest = df.iloc[-1]
        
        signal = 'HOLD'
        strength = 0
        
        # 매수: 볼린저 하단 터치 + RSI 과매도
        if current_price <= latest['bb_lower'] * 1.02 and latest['rsi'] < 35:
            signal = 'BUY'
            strength = min((latest['bb_middle'] - current_price) / current_price * 20, 5)
        
        # 매도: 볼린저 상단 터치 or RSI 과매수
        elif current_price >= latest['bb_upper'] * 0.98 or latest['rsi'] > 70:
            signal = 'SELL'
            strength = min((current_price - latest['bb_middle']) / current_price * 20, 5)
        
        return {
            'signal': signal,
            'strength': abs(strength),
            'current_price': current_price,
            'rsi': latest['rsi'],
            'bb_position': (current_price - latest['bb_lower']) / (latest['bb_upper'] - latest['bb_lower'])
        }
    
    def calculate_breakout_signals(self, df: pd.DataFrame) -> Dict:
        """돌파 전략 신호 계산"""
        if len(df) < 20:
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
        
        # 20일 고가/저가
        df['high_20'] = df['stck_hgpr'].rolling(20).max()
        df['low_20'] = df['stck_lwpr'].rolling(20).min()
        df['ma20'] = df['stck_prpr'].rolling(20).mean()
        
        # 거래량
        df['volume_ma'] = df['cntg_vol'].rolling(20).mean()
        
        current_price = df['stck_prpr'].iloc[-1]
        latest = df.iloc[-1]
        
        # 이전 봉의 20일 고가 (돌파 확인용)
        prev_high_20 = df['high_20'].iloc[-2]
        
        signal = 'HOLD'
        strength = 0
        volume_ratio = latest['cntg_vol'] / latest['volume_ma'] if latest['volume_ma'] > 0 else 1
        
        # 매수: 20일 신고가 돌파 + 거래량 증가
        if current_price > prev_high_20 and volume_ratio > 2.0:
            signal = 'BUY'
            strength = min(volume_ratio * 1.5, 5)
        
        # 매도: 20일 이동평균 하향 돌파
        elif current_price < latest['ma20']:
            signal = 'SELL'
            strength = 3
        
        return {
            'signal': signal,
            'strength': strength,
            'current_price': current_price,
            'volume_ratio': volume_ratio,
            'breakout_level': prev_high_20
        }
    
    
    def calculate_scalping_signals(self, df: pd.DataFrame) -> Dict:
        """스캘핑 전략 신호 계산"""
        if len(df) < 10:
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
    
        # 단기 이동평균
        df['ma3'] = df['stck_prpr'].rolling(3).mean()
        df['ma10'] = df['stck_prpr'].rolling(10).mean()
    
        # 가격 변화율
        df['price_change'] = df['stck_prpr'].pct_change()
    
        current_price = float(df['stck_prpr'].iloc[-1])  # float로 변환
        latest = df.iloc[-1]
        prev = df.iloc[-2]
    
        signal = 'HOLD'
        strength = 0
    
        # NaN 체크
        if pd.isna(latest['ma3']) or pd.isna(latest['ma10']) or pd.isna(prev['ma3']) or pd.isna(prev['ma10']):
            return {
                'signal': 'HOLD',
                'strength': 0,
                'current_price': current_price,
                'ma3': 0,
                'ma10': 0
            }
    
        # 매수: 3선이 10선을 상향 돌파
        if prev['ma3'] <= prev['ma10'] and latest['ma3'] > latest['ma10']:
            signal = 'BUY'
            # 신호 강도 계산 개선
            # 1. 가격 변화율 기반 (최소 1.0)
            price_strength = abs(latest['price_change']) * 100 if not pd.isna(latest['price_change']) else 0
            
            # 2. 이동평균선 간격 기반
            ma_gap = abs(latest['ma3'] - latest['ma10']) / latest['ma10'] * 100
            
            # 3. 두 값의 평균 + 기본값 1.0
            strength = max(1.0, (price_strength + ma_gap) / 2)
            strength = min(strength, 5)  # 최대 5
    
        # 매도: 3선이 10선을 하향 돌파 or 급락
        elif (prev['ma3'] >= prev['ma10'] and latest['ma3'] < latest['ma10']) or \
             (not pd.isna(latest['price_change']) and latest['price_change'] < -0.01):  # 1% 이상 급락
            signal = 'SELL'
            strength = 4
    
        return {
            'signal': signal,
            'strength': float(strength),  # float로 변환
            'current_price': current_price,
            'ma3': float(latest['ma3']),
            'ma10': float(latest['ma10'])
        }


    def calculate_combined_signals(self, df: pd.DataFrame, strategy: str) -> Dict:
        """복합 전략 신호 계산 (예: momentum + breakout)"""
        strategies = strategy.split(' + ')
        all_signals = []
        
        for strat in strategies:
            strat = strat.strip()
            if strat == 'momentum':
                signals = self.calculate_momentum_signals(df)
            elif strat == 'mean_reversion':
                signals = self.calculate_mean_reversion_signals(df)
            elif strat == 'breakout':
                signals = self.calculate_breakout_signals(df)
            elif strat == 'scalping':
                signals = self.calculate_scalping_signals(df)
            else:
                continue
                
            all_signals.append(signals)
        
        if not all_signals:
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
        
        # 신호 통합 (과반수 투표)
        buy_count = sum(1 for s in all_signals if s['signal'] == 'BUY')
        sell_count = sum(1 for s in all_signals if s['signal'] == 'SELL')
        
        if buy_count > len(all_signals) / 2:
            signal = 'BUY'
        elif sell_count > len(all_signals) / 2:
            signal = 'SELL'
        else:
            signal = 'HOLD'
        
        # 평균 강도
        avg_strength = sum(s['strength'] for s in all_signals) / len(all_signals)
        
        return {
            'signal': signal,
            'strength': avg_strength,
            'current_price': all_signals[0]['current_price'],
            'strategies_used': len(all_signals)
        }


    def place_order(self, symbol: str, side: str, quantity: int, price: int = 0) -> Dict:
        """주문 실행 - 시장가/지정가 자동 선택"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        
        # 실전/모의 자동 감지
        is_mock = "vts" in self.base_url.lower()
        
        if is_mock:
            # 모의투자
            tr_id = "VTTC0802U" if side == "BUY" else "VTTC0801U"
        else:
            # 실전투자
            tr_id = "TTTC0802U" if side == "BUY" else "TTTC0801U"
        
        # 주문 구분 결정
        # price가 0이면 시장가, 아니면 지정가
        if price == 0:
            ord_dvsn = "01"  # 시장가
            ord_unpr = "0"
            self.logger.info(f"📈 시장가 주문: {symbol} {side} {quantity}주")
        else:
            ord_dvsn = "00"  # 지정가
            ord_unpr = str(price)
            self.logger.info(f"📊 지정가 주문: {symbol} {side} {quantity}주 @ {price:,}원")
        
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
            "ORD_DVSN": ord_dvsn,  # 00:지정가, 01:시장가
            "ORD_QTY": str(quantity),
            "ORD_UNPR": ord_unpr   # 시장가는 "0", 지정가는 가격
        }
    
        self.logger.debug(f"주문 데이터: {data}")
    
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            result = response.json()
    
            if result.get('rt_cd') == '0':
                order_no = result.get('output', {}).get('odno', 'Unknown')
                self.logger.info(f"✅ 주문 성공: {symbol} {side} {quantity}주 (주문번호: {order_no})")
                self.trade_count += 1
                # 알림 전송
                self.notify_trade_success(side, symbol, quantity, price if price > 0 else 0, order_no)
                return {'success': True, 'order_no': order_no}
            else:
                error_msg = result.get('msg1', 'Unknown error')
                error_code = result.get('msg_cd', 'Unknown')
                self.logger.error(f"주문 실패: [{error_code}] {error_msg}")
                self.notify_trade_failure(side, symbol, error_msg)
                return {'success': False, 'error': error_msg}
    
        except Exception as e:
            self.logger.error(f"주문 실행 실패 ({symbol} {side}): {e}")
            self.notify_trade_failure(side, symbol, str(e))
            return {'success': False, 'error': str(e)}


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
        """포지션 업데이트 - 잔고조회 API 사용"""
        try:
            account_data = self.get_account_balance()
            if not account_data:
                return
    
            # 현재 보유 종목 업데이트
            self.positions = {}
            
            # output1: 보유종목 리스트
            holdings = account_data.get('output1', [])
            
            for position in holdings:
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
                        
                        self.logger.debug(f"포지션 업데이트 - {symbol}: {quantity}주, "
                                        f"평균가: {self.positions[symbol]['avg_price']:,}원")
    
        except Exception as e:
            self.logger.error(f"포지션 업데이트 실패: {e}")
    
    
    def get_account_balance(self) -> Dict:
        """계좌 잔고 조회 - 매수가능금액 조회 API 사용"""
        # 매수가능금액 조회 API 사용
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-order"
        
        # 실전/모의 자동 감지
        is_mock = "vts" in self.base_url.lower()
        tr_id = "VTTC8908R" if is_mock else "TTTC8908R"
        
        self.logger.debug(f"거래 모드: {'모의투자' if is_mock else '실전투자'} (tr_id: {tr_id})")
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id
        }
        
        # 삼성전자를 기준으로 매수가능금액 조회
        params = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "PDNO": "005930",  # 삼성전자 (필수값)
            "ORD_UNPR": "0",   # 시장가
            "ORD_DVSN": "01",  # 지정가
            "CMA_EVLU_AMT_ICLD_YN": "N",
            "OVRS_ICLD_YN": "N"
        }
    
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            
            # 응답 코드 확인
            if data.get('rt_cd') != '0':
                self.logger.error(f"계좌 조회 실패: {data.get('msg1', 'Unknown error')}")
                self.logger.error(f"msg_cd: {data.get('msg_cd')}, rt_cd: {data.get('rt_cd')}")
                
                # 대체 방법: 잔고 조회
                return self.get_balance_list()
                
            # output 데이터 확인
            output = data.get('output', {})
            if output:
                # 주요 금액 필드들
                cash_fields = {
                    'ord_psbl_cash': '주문가능현금',
                    'psbl_ord_amt': '가능주문금액',
                    'dnca_tot_amt': '예수금총액',
                    'max_buy_amt': '최대매수금액',
                    'nrcvb_buy_amt': '미수없는매수금액'
                }
                
                available_cash = 0
                for field, desc in cash_fields.items():
                    value = float(output.get(field, 0))
                    if value > 0:
                        self.logger.info(f"{desc} ({field}): {value:,}원")
                        if field == 'ord_psbl_cash' and available_cash == 0:
                            available_cash = value
                
                if available_cash == 0:
                    # ord_psbl_cash가 없으면 다른 필드 사용
                    available_cash = float(output.get('max_buy_amt', 0)) or \
                                   float(output.get('nrcvb_buy_amt', 0)) or \
                                   float(output.get('psbl_ord_amt', 0))
                
                self.logger.info(f"💵 가용자금: {available_cash:,}원")
                
                # output 구조 유지
                output['ord_psbl_cash'] = str(int(available_cash))
            
            return data
            
        except Exception as e:
            self.logger.error(f"계좌 조회 실패: {e}")
            import traceback
            self.logger.error(f"상세 오류: {traceback.format_exc()}")
            return {}
    
    def get_balance_list(self) -> Dict:
        """잔고 목록 조회 (보유종목 확인용)"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        
        is_mock = "vts" in self.base_url.lower()
        tr_id = "VTTC8434R" if is_mock else "TTTC8434R"  # 잔고조회용 tr_id
        
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
            "PRCS_DVSN": "01"
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            data = response.json()
            
            if data.get('rt_cd') == '0':
                # output2에서 총 예수금 확인
                output2 = data.get('output2', [])
                if output2:
                    summary = output2[0]
                    dnca_tot_amt = float(summary.get('dnca_tot_amt', 0))
                    thdt_buy_amt = float(summary.get('thdt_buy_amt', 0))
                    
                    # 가용자금 = 예수금 - 당일매수금액
                    available_cash = dnca_tot_amt - thdt_buy_amt
                    
                    self.logger.info(f"예수금: {dnca_tot_amt:,}원")
                    self.logger.info(f"당일매수금액: {thdt_buy_amt:,}원")
                    self.logger.info(f"💵 가용자금: {available_cash:,}원")
                    
                    # 기존 형식으로 반환
                    data['output'] = {
                        'ord_psbl_cash': str(int(available_cash))
                    }
            
            return data
            
        except Exception as e:
            self.logger.error(f"잔고 목록 조회 실패: {e}")
            return {}

    def get_buyable_cash(self) -> Dict:
        """매수가능금액 조회 (대체 방법)"""
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
        
        # 삼성전자로 테스트
        params = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "PDNO": "005930",  # 삼성전자
            "ORD_UNPR": "0",   # 시장가
            "ORD_DVSN": "01",  # 지정가
            "CMA_EVLU_AMT_ICLD_YN": "N",  # CMA평가금액포함여부
            "OVRS_ICLD_YN": "N"  # 해외포함여부
        }
        
        try:
            response = requests.get(url, headers=headers, params=params)
            data = response.json()
            
            if data.get('rt_cd') == '0':
                output = data.get('output', {})
                self.logger.info(f"매수가능금액: {output.get('ord_psbl_cash', 0)}원")
                
            return data
        except Exception as e:
            self.logger.error(f"매수가능금액 조회 실패: {e}")
            return {}



    def calculate_position_size(self, symbol: str, current_price: float, signal_strength: float) -> int:
        """디버깅이 강화된 포지션 크기 계산"""
        try:
            self.logger.info(f"📐 {symbol} - 포지션 크기 계산 상세 분석")
            self.logger.info(f"  입력값:")
            self.logger.info(f"    현재가: {current_price:,}원")
            self.logger.info(f"    신호강도: {signal_strength:.2f}")
            self.logger.info(f"    최대투자비율: {self.max_position_ratio:.1%}")
            
            account_data = self.get_account_balance()
            if not account_data:
                self.logger.error("❌ 계좌 데이터 조회 실패")
                return 0
    
            output = account_data.get('output', {})
            available_cash = float(output.get('ord_psbl_cash', 0))
            
            if available_cash == 0:
                self.logger.error("❌ 가용 자금이 0원입니다.")
                return 0
                
            self.logger.info(f"  💵 가용 자금: {available_cash:,}원")
    
            # 최대 투자 가능 금액
            max_investment = available_cash * self.max_position_ratio
            self.logger.info(f"  최대 투자 가능 금액: {max_investment:,}원 (비율: {self.max_position_ratio:.1%})")
    
            # 신호 강도에 따른 조정 - 기준 완화
            if signal_strength < 0.1:
                self.logger.warning(f"  ⚠️ 신호 강도가 너무 약함: {signal_strength:.2f} < 0.1")
                return 0
            elif signal_strength < 0.5:
                position_ratio = 0.2
                self.logger.info(f"  약한 신호 - 20% 투자")
            elif signal_strength < 1.0:
                position_ratio = 0.3
                self.logger.info(f"  보통 신호 - 30% 투자")
            elif signal_strength < 2.0:
                position_ratio = 0.5
                self.logger.info(f"  양호한 신호 - 50% 투자")
            elif signal_strength < 3.0:
                position_ratio = 0.7
                self.logger.info(f"  강한 신호 - 70% 투자")
            else:
                position_ratio = 1.0
                self.logger.info(f"  매우 강한 신호 - 100% 투자")
    
            self.logger.info(f"  포지션 비율: {position_ratio:.1%}")
            
            adjusted_investment = max_investment * position_ratio
            self.logger.info(f"  조정된 투자 금액: {adjusted_investment:,}원")
    
            # 주문 가능 수량 계산
            raw_quantity = adjusted_investment / current_price
            quantity = int(raw_quantity)
            
            self.logger.info(f"  계산 과정:")
            self.logger.info(f"    {adjusted_investment:,}원 ÷ {current_price:,}원 = {raw_quantity:.3f}주")
            self.logger.info(f"    정수화: {quantity}주")
    
            # 최소 주문 체크
            if quantity < 1 and adjusted_investment >= current_price:
                quantity = 1
                self.logger.info(f"  최소 1주로 조정")
            
            # 최소 투자 금액 체크 (예: 10만원 이상)
            min_investment = 100000  # 10만원
            if adjusted_investment < min_investment:
                self.logger.warning(f"  ⚠️ 투자 금액이 최소 기준 미달: {adjusted_investment:,}원 < {min_investment:,}원")
                
                # 최소 금액으로 조정
                if available_cash >= min_investment:
                    adjusted_investment = min_investment
                    quantity = int(adjusted_investment / current_price)
                    self.logger.info(f"  최소 투자 금액으로 조정: {adjusted_investment:,}원 → {quantity}주")
                else:
                    self.logger.warning(f"  가용 자금이 최소 투자 기준에도 미달")
                    return 0
    
            self.logger.info(f"📊 최종 계산된 주문 수량: {quantity}주")
            self.logger.info(f"  예상 투자 금액: {quantity * current_price:,}원")
            
            return max(quantity, 0)
    
        except Exception as e:
            self.logger.error(f"포지션 크기 계산 실패: {e}")
            import traceback
            self.logger.error(f"상세 오류:\n{traceback.format_exc()}")
            return 0


    def process_symbol(self, symbol: str):
        """개별 종목 처리 - 시장가 주문 사용"""
        try:
            stock_name = self.get_stock_name(symbol)

            # 분봉 데이터 조회
            df = self.get_minute_data(symbol)
            if df.empty:
                self.logger.warning(f"{symbol}({stock_name}) - 데이터 없음")
                return
    
            # 이 종목의 최적 전략 가져오기
            optimal_strategy = self.strategy_map.get(symbol, 'momentum')
    
            # 전략에 따라 다른 신호 계산 함수 호출
            if optimal_strategy == 'momentum':
                signals = self.calculate_momentum_signals(df)
            elif optimal_strategy == 'mean_reversion':
                signals = self.calculate_mean_reversion_signals(df)
            elif optimal_strategy == 'breakout':
                signals = self.calculate_breakout_signals(df)
            elif optimal_strategy == 'scalping':
                signals = self.calculate_scalping_signals(df)
            elif ' + ' in optimal_strategy:
                signals = self.calculate_combined_signals(df, optimal_strategy)
            else:
                signals = self.calculate_momentum_signals(df)
    
            current_price = signals['current_price']
    
            self.logger.info(f"{symbol}({stock_name}) - 전략: {optimal_strategy}, "
                           f"신호: {signals['signal']}, "
                           f"강도: {signals['strength']:.2f}, "
                           f"현재가: {current_price:,}원")
    
            # 현재 포지션 확인
            current_position = self.positions.get(symbol, {})
            has_position = current_position.get('quantity', 0) > 0
            
    
    
            # 매수 신호 처리
            if signals['signal'] == 'BUY':
                can_buy, buy_reason = self.can_purchase_symbol(symbol)
                
                if can_buy and not has_position:
                    self.logger.info(f"🔍 {symbol} - 매수 신호 감지! 포지션 계산 시작...")
                    
                    quantity = self.calculate_position_size(symbol, current_price, signals['strength'])
                    
                    if quantity > 0:
                        # 신호 강도에 따라 주문 전략 결정
                        order_strategy = self.determine_order_strategy(signals['strength'], 'BUY')
                        
                        self.logger.info(f"💰 {symbol} - 매수 주문 시도: {quantity}주 ({order_strategy})")
                        
                        # 지정가 주문 실행
                        result = self.place_order_with_strategy(symbol, 'BUY', quantity, order_strategy)
                        
                        if result['success']:
                            # 매수 기록 (실제 체결가가 아닌 지정가로 기록)
                            executed_price = result.get('limit_price', current_price)
                            self.position_manager.record_purchase(
                                symbol, quantity, executed_price, optimal_strategy
                            )
                            self.logger.info(f"✅ {symbol} 매수 주문 완료: {quantity}주 @ {executed_price:,}원")
                            
                            # 주문 모니터링 시작 (선택사항)
                            if self.order_timeout_minutes > 0:
                                self.monitor_order(result['order_no'], symbol, 'BUY')
                    else:
                        self.logger.warning(f"⚠️ {symbol} - 매수 수량이 0입니다.")
                        
                elif has_position:
                    self.logger.info(f"📌 {symbol} - 매수 신호가 있지만 이미 포지션 보유 중")
                else:
                    self.logger.warning(f"🚫 {symbol} - 매수 제한: {buy_reason}")
    
            # 매도 신호 처리
            elif signals['signal'] == 'SELL' and has_position:
                can_sell, sell_reason = self.can_sell_symbol(symbol)
                
                if can_sell:
                    quantity = current_position['quantity']
                    
                    # 매도는 보통 빠른 체결을 원하므로 적극적 전략 사용
                    order_strategy = "aggressive_limit"
                    
                    self.logger.info(f"💸 {symbol} - 매도 주문 시도: {quantity}주 ({order_strategy})")
                    result = self.place_order_with_strategy(symbol, 'SELL', quantity, order_strategy)
                    
                    if result['success']:
                        profit_loss = current_position['profit_loss']
                        executed_price = result.get('limit_price', current_price)
                        
                        self.position_manager.record_sale(
                            symbol, quantity, executed_price, "매도 신호"
                        )
                        self.logger.info(f"✅ {symbol} 매도 주문 완료: {quantity}주 @ {executed_price:,}원 "
                                       f"(수익률: {profit_loss:.2%})")
                else:
                    self.logger.warning(f"🚫 {symbol} - 매도 제한: {sell_reason}")
    
            # 손익 관리
            elif has_position:
                profit_loss = current_position['profit_loss'] / 100
                
                # 손절은 긴급 매도 (즉시 체결 우선)
                if profit_loss <= -self.stop_loss_pct:
                    quantity = current_position['quantity']
                    self.logger.warning(f"🛑 {symbol} - 손절 조건 충족! ({profit_loss:.2%})")
                    
                    # 손절은 긴급 주문 (빠른 체결 우선)
                    result = self.place_order_with_strategy(symbol, 'SELL', quantity, "urgent")
                    
                    if result['success']:
                        executed_price = result.get('limit_price', current_price)
                        self.position_manager.record_sale(
                            symbol, quantity, executed_price, "손절매"
                        )
                        self.logger.warning(f"🛑 {symbol} 손절 매도: {quantity}주 @ {executed_price:,}원 "
                                          f"(손실: {profit_loss:.2%})")
    
                # 익절은 조건부 매도
                elif profit_loss >= self.take_profit_pct:
                    can_sell, sell_reason = self.can_sell_symbol(symbol)
                    
                    if can_sell:
                        quantity = current_position['quantity']
                        self.logger.info(f"🎯 {symbol} - 익절 조건 충족! ({profit_loss:.2%})")
                        
                        # 익절은 조금 더 유리한 가격을 노릴 수 있음
                        result = self.place_order_with_strategy(symbol, 'SELL', quantity, "patient_limit")
                        
                        if result['success']:
                            executed_price = result.get('limit_price', current_price)
                            self.position_manager.record_sale(
                                symbol, quantity, executed_price, "익절매"
                            )
                            self.logger.info(f"🎯 {symbol} 익절 매도: {quantity}주 @ {executed_price:,}원 "
                                           f"(수익: {profit_loss:.2%})")
                    else:
                        self.logger.info(f"💎 {symbol} - 익절 조건이지만 보유 지속: {sell_reason}")
    
    
        except Exception as e:
            self.logger.error(f"{symbol} 처리 중 오류: {e}")
            self.notify_error("종목 처리 오류", f"{symbol}: {str(e)}")
    

    def process_symbol_with_detailed_logging(self, symbol: str):
        """상세 로깅이 포함된 종목 처리 - 매도 로직 디버깅"""
        try:
            stock_name = self.get_stock_name(symbol)
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"🔍 {symbol}({stock_name}) 처리 시작")
            self.logger.info(f"{'='*60}")
    
            # 분봉 데이터 조회
            df = self.get_minute_data(symbol)
            if df.empty:
                self.logger.warning(f"{symbol}({stock_name}) - 데이터 없음")
                return
    
            # 전략에 따른 신호 계산
            optimal_strategy = self.strategy_map.get(symbol, 'momentum')
            self.logger.debug(f"📋 {symbol} - 사용 전략: {optimal_strategy}")
            
            if optimal_strategy == 'momentum':
                signals = self.calculate_momentum_signals(df)
            elif optimal_strategy == 'mean_reversion':
                signals = self.calculate_mean_reversion_signals(df)
            elif optimal_strategy == 'breakout':
                signals = self.calculate_breakout_signals(df)
            elif optimal_strategy == 'scalping':
                signals = self.calculate_scalping_signals(df)
            elif ' + ' in optimal_strategy:
                signals = self.calculate_combined_signals(df, optimal_strategy)
            else:
                signals = self.calculate_momentum_signals(df)
    
            current_price = signals['current_price']
            signal = signals['signal']
            strength = signals['strength']
    
            self.logger.info(f"📊 {symbol} 신호 분석:")
            self.logger.info(f"  - 전략: {optimal_strategy}")
            self.logger.info(f"  - 신호: {signal}")
            self.logger.info(f"  - 강도: {strength:.2f}")
            self.logger.info(f"  - 현재가: {current_price:,}원")
    
            # 현재 포지션 상세 확인
            current_position = self.positions.get(symbol, {})
            has_position = current_position.get('quantity', 0) > 0
            
            self.logger.info(f"💼 {symbol} 포지션 상태:")
            self.logger.info(f"  - 보유 여부: {has_position}")
            
            if has_position:
                quantity = current_position.get('quantity', 0)
                avg_price = current_position.get('avg_price', 0)
                current_value = current_position.get('current_price', 0)
                profit_loss_pct = current_position.get('profit_loss', 0)
                
                self.logger.info(f"  - 보유 수량: {quantity}주")
                self.logger.info(f"  - 평균 단가: {avg_price:,}원")
                self.logger.info(f"  - 현재 가격: {current_value:,}원")
                self.logger.info(f"  - 손익률: {profit_loss_pct:+.2f}%")
                
                # 손익 관리 기준값 확인
                profit_loss_decimal = profit_loss_pct / 100
                self.logger.info(f"📈 손익 관리 기준:")
                self.logger.info(f"  - 손절 기준: {-self.stop_loss_pct:.2%} (현재: {profit_loss_decimal:.2%})")
                self.logger.info(f"  - 익절 기준: {self.take_profit_pct:.2%} (현재: {profit_loss_decimal:.2%})")
                self.logger.info(f"  - 손절 조건: {profit_loss_decimal <= -self.stop_loss_pct}")
                self.logger.info(f"  - 익절 조건: {profit_loss_decimal >= self.take_profit_pct}")
            else:
                self.logger.info("  - 보유 포지션 없음")
    
            # 매수 신호 처리
            if signal == 'BUY':
                self.logger.info(f"🛒 {symbol} - 매수 신호 처리")
                
                can_buy, buy_reason = self.can_purchase_symbol(symbol)
                self.logger.info(f"  - 매수 가능: {can_buy}")
                self.logger.info(f"  - 매수 사유/제한: {buy_reason}")
                
                if can_buy and not has_position:
                    self.logger.info(f"✅ {symbol} - 매수 조건 충족, 포지션 계산 중...")
                    
                    quantity = self.calculate_position_size(symbol, current_price, strength)
                    
                    if quantity > 0:
                        order_strategy = self.determine_order_strategy(strength, 'BUY')
                        self.logger.info(f"💰 {symbol} - 매수 실행: {quantity}주 ({order_strategy})")
                        
                        result = self.place_order_with_strategy(symbol, 'BUY', quantity, order_strategy)
                        
                        if result['success']:
                            executed_price = result.get('limit_price', current_price)
                            self.position_manager.record_purchase(
                                symbol, quantity, executed_price, optimal_strategy
                            )
                            self.logger.info(f"✅ {symbol} 매수 완료: {quantity}주 @ {executed_price:,}원")
                    else:
                        self.logger.warning(f"⚠️ {symbol} - 계산된 매수 수량이 0")
                        
                elif has_position:
                    self.logger.info(f"📌 {symbol} - 이미 포지션 보유 중, 매수 생략")
                else:
                    self.logger.warning(f"🚫 {symbol} - 매수 제한: {buy_reason}")
    
            # 매도 신호 처리 (상세 로깅)
            elif signal == 'SELL':
                self.logger.info(f"💸 {symbol} - 매도 신호 감지!")
                
                if has_position:
                    self.logger.info(f"✅ {symbol} - 보유 포지션 있음, 매도 조건 확인 중...")
                    
                    can_sell, sell_reason = self.can_sell_symbol(symbol)
                    self.logger.info(f"  - 매도 가능: {can_sell}")
                    self.logger.info(f"  - 매도 사유/제한: {sell_reason}")
                    
                    if can_sell:
                        quantity = current_position['quantity']
                        order_strategy = "aggressive_limit"
                        
                        self.logger.info(f"🎯 {symbol} - 매도 실행: {quantity}주 ({order_strategy})")
                        result = self.place_order_with_strategy(symbol, 'SELL', quantity, order_strategy)
                        
                        if result['success']:
                            profit_loss = current_position['profit_loss']
                            executed_price = result.get('limit_price', current_price)
                            
                            self.position_manager.record_sale(
                                symbol, quantity, executed_price, "매도 신호"
                            )
                            self.logger.info(f"✅ {symbol} 매도 완료: {quantity}주 @ {executed_price:,}원 "
                                           f"(수익률: {profit_loss:.2%})")
                        else:
                            self.logger.error(f"❌ {symbol} 매도 실패: {result.get('error', 'Unknown')}")
                    else:
                        self.logger.warning(f"🚫 {symbol} - 매도 제한: {sell_reason}")
                        
                        # 제한 사유가 최소 보유기간인 경우 상세 정보 출력
                        if "최소 보유 기간" in sell_reason:
                            history = self.position_manager.position_history.get(symbol, {})
                            first_purchase = history.get('first_purchase_time')
                            if first_purchase:
                                purchase_time = datetime.fromisoformat(first_purchase)
                                holding_hours = (datetime.now() - purchase_time).total_seconds() / 3600
                                remaining_hours = self.min_holding_period_hours - holding_hours
                                
                                self.logger.info(f"  📅 보유 시간: {holding_hours:.1f}시간")
                                self.logger.info(f"  ⏰ 남은 시간: {remaining_hours:.1f}시간")
                else:
                    self.logger.warning(f"❌ {symbol} - 매도 신호가 있지만 보유 포지션 없음")
    
            # HOLD 신호이지만 포지션이 있는 경우 손익 관리
            else:  # signal == 'HOLD' or other
                self.logger.info(f"⏸️ {symbol} - {signal} 신호")
                
                if has_position:
                    self.logger.info(f"💎 {symbol} - 포지션 보유 중, 손익 관리 확인...")
                    
                    profit_loss_decimal = current_position['profit_loss'] / 100
                    
                    # 손절 체크 (최소 보유기간 무시)
                    if profit_loss_decimal <= -self.stop_loss_pct:
                        quantity = current_position['quantity']
                        self.logger.warning(f"🛑 {symbol} - 손절 조건 충족! ({profit_loss_decimal:.2%})")
                        self.logger.warning(f"  손절 기준: {-self.stop_loss_pct:.2%} 이하")
                        
                        # 손절은 긴급 매도
                        result = self.place_order_with_strategy(symbol, 'SELL', quantity, "urgent")
                        
                        if result['success']:
                            executed_price = result.get('limit_price', current_price)
                            self.position_manager.record_sale(
                                symbol, quantity, executed_price, "손절매"
                            )
                            self.logger.warning(f"🛑 {symbol} 손절 완료: {quantity}주 @ {executed_price:,}원")
    
                    # 익절 체크 (최소 보유기간 확인)
                    elif profit_loss_decimal >= self.take_profit_pct:
                        self.logger.info(f"🎯 {symbol} - 익절 조건 충족! ({profit_loss_decimal:.2%})")
                        self.logger.info(f"  익절 기준: {self.take_profit_pct:.2%} 이상")
                        
                        can_sell, sell_reason = self.can_sell_symbol(symbol)
                        
                        if can_sell:
                            quantity = current_position['quantity']
                            result = self.place_order_with_strategy(symbol, 'SELL', quantity, "patient_limit")
                            
                            if result['success']:
                                executed_price = result.get('limit_price', current_price)
                                self.position_manager.record_sale(
                                    symbol, quantity, executed_price, "익절매"
                                )
                                self.logger.info(f"🎯 {symbol} 익절 완료: {quantity}주 @ {executed_price:,}원")
                        else:
                            self.logger.info(f"💎 {symbol} - 익절 조건이지만 보유 지속: {sell_reason}")
                    else:
                        self.logger.info(f"📊 {symbol} - 손익 관리 조건 미충족, 보유 지속")
    
            self.logger.info(f"✅ {symbol} 처리 완료\n")
    
        except Exception as e:
            self.logger.error(f"❌ {symbol} 처리 중 오류: {e}")
            import traceback
            self.logger.error(f"상세 오류:\n{traceback.format_exc()}")
            self.notify_error("종목 처리 오류", f"{symbol}: {str(e)}")
    
    def debug_sell_conditions(self, symbol: str):
        """매도 조건 상세 디버깅"""
        self.logger.info(f"\n🔍 {symbol} 매도 조건 디버깅")
        self.logger.info("="*50)
        
        # 1. 현재 포지션 확인
        current_position = self.positions.get(symbol, {})
        has_position = current_position.get('quantity', 0) > 0
        
        self.logger.info(f"1️⃣ 포지션 확인:")
        self.logger.info(f"   보유 여부: {has_position}")
        
        if not has_position:
            self.logger.warning(f"❌ {symbol} - 보유 포지션 없음")
            return
        
        # 2. 매도 가능 조건 확인
        can_sell, sell_reason = self.can_sell_symbol(symbol)
        self.logger.info(f"2️⃣ 매도 가능 조건:")
        self.logger.info(f"   매도 가능: {can_sell}")
        self.logger.info(f"   사유: {sell_reason}")
        
        # 3. 최소 보유기간 상세 확인
        history = self.position_manager.position_history.get(symbol, {})
        first_purchase = history.get('first_purchase_time')
        
        if first_purchase:
            purchase_time = datetime.fromisoformat(first_purchase)
            holding_time = datetime.now() - purchase_time
            holding_hours = holding_time.total_seconds() / 3600
            remaining_hours = self.min_holding_period_hours - holding_hours
            
            self.logger.info(f"3️⃣ 보유 기간 확인:")
            self.logger.info(f"   첫 매수 시간: {purchase_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"   현재 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"   보유 시간: {holding_hours:.1f}시간")
            self.logger.info(f"   최소 기간: {self.min_holding_period_hours}시간")
            self.logger.info(f"   남은 시간: {remaining_hours:.1f}시간")
            self.logger.info(f"   기간 충족: {holding_hours >= self.min_holding_period_hours}")
        
        # 4. 신호 상태 확인
        df = self.get_minute_data(symbol)
        if not df.empty:
            optimal_strategy = self.strategy_map.get(symbol, 'momentum')
            
            if optimal_strategy == 'momentum':
                signals = self.calculate_momentum_signals(df)
            elif optimal_strategy == 'scalping':
                signals = self.calculate_scalping_signals(df)
            else:
                signals = self.calculate_momentum_signals(df)
            
            self.logger.info(f"4️⃣ 현재 신호:")
            self.logger.info(f"   신호: {signals['signal']}")
            self.logger.info(f"   강도: {signals['strength']:.2f}")
        
        # 5. 손익 상태 확인
        profit_loss_pct = current_position.get('profit_loss', 0)
        profit_loss_decimal = profit_loss_pct / 100
        
        self.logger.info(f"5️⃣ 손익 상태:")
        self.logger.info(f"   현재 손익: {profit_loss_pct:+.2f}%")
        self.logger.info(f"   손절 기준: {-self.stop_loss_pct:.2%}")
        self.logger.info(f"   익절 기준: {self.take_profit_pct:.2%}")
        self.logger.info(f"   손절 조건: {profit_loss_decimal <= -self.stop_loss_pct}")
        self.logger.info(f"   익절 조건: {profit_loss_decimal >= self.take_profit_pct}")
    
    def force_sell_position(self, symbol: str, reason: str = "수동 매도"):
        """강제 매도 (테스트/긴급용)"""
        self.logger.warning(f"⚠️ {symbol} 강제 매도 시도: {reason}")
        
        current_position = self.positions.get(symbol, {})
        if not current_position or current_position.get('quantity', 0) <= 0:
            self.logger.error(f"❌ {symbol} - 매도할 포지션이 없습니다")
            return False
        
        quantity = current_position['quantity']
        
        # 시장가로 긴급 매도
        result = self.place_order(symbol, 'SELL', quantity, price=0)
        
        if result['success']:
            # 현재가 추정
            current_price_data = self.get_current_price(symbol)
            current_price = 0
            if current_price_data and current_price_data.get('output'):
                current_price = float(current_price_data['output'].get('stck_prpr', 0))
            
            self.position_manager.record_sale(symbol, quantity, current_price, reason)
            self.logger.warning(f"✅ {symbol} 강제 매도 완료: {quantity}주")
            return True
        else:
            self.logger.error(f"❌ {symbol} 강제 매도 실패: {result.get('error', 'Unknown')}")
            return False
    
    # 테스트용 함수들
    def test_sell_logic():
        """매도 로직 테스트"""
        trader = KISAutoTrader()
        
        print("🧪 매도 로직 테스트 시작")
        print("="*50)
        
        # 보유 종목들에 대해 디버깅
        for symbol in trader.symbols:
            if symbol in trader.positions:
                trader.debug_sell_conditions(symbol)
                print()
    


    def get_position_summary(self) -> Dict:
        """포지션 요약 정보"""
        summary = {
            'total_symbols': len(self.positions),
            'total_value': 0,
            'positions': {}
        }
        
        for symbol, position in self.positions.items():
            history = self.position_manager.position_history.get(symbol, {})
            
            # 보유 기간 계산
            first_purchase = history.get('first_purchase_time')
            holding_hours = 0
            if first_purchase:
                holding_time = datetime.now() - datetime.fromisoformat(first_purchase)
                holding_hours = holding_time.total_seconds() / 3600
            
            position_info = {
                'quantity': position['quantity'],
                'avg_price': position['avg_price'],
                'current_price': position['current_price'],
                'profit_loss': position['profit_loss'],
                'holding_hours': holding_hours,
                'purchase_count': history.get('purchase_count', 0),
                'can_sell': self.can_sell_symbol(symbol)[0],
                'can_buy_more': self.can_purchase_symbol(symbol)[0]
            }
            
            summary['positions'][symbol] = position_info
            summary['total_value'] += position['current_price'] * position['quantity']
        
        return summary
    def save_performance_data(self):
        """실전 성과 데이터 저장"""
        if not self.performance_tracking:
            return
            
        try:
            performance_file = "performance_log.json"
            
            # 기존 데이터 로드
            if os.path.exists(performance_file):
                with open(performance_file, 'r', encoding='utf-8') as f:
                    performance_history = json.load(f)
            else:
                performance_history = []
            
            # 현재 성과 계산
            total_value = 0
            total_cost = 0
            
            for symbol, position in self.positions.items():
                total_value += position['current_price'] * position['quantity']
                total_cost += position['avg_price'] * position['quantity']
            
            current_performance = {
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'symbols': list(self.positions.keys()),
                'total_trades': self.trade_count,
                'positions': len(self.positions),
                'total_value': total_value,
                'total_cost': total_cost,
                'unrealized_pnl': (total_value - total_cost) / total_cost if total_cost > 0 else 0,
                'daily_pnl': self.daily_pnl
            }
            
            performance_history.append(current_performance)
            
            # 최대 1000개 레코드만 유지
            if len(performance_history) > 1000:
                performance_history = performance_history[-1000:]
            
            # 저장
            with open(performance_file, 'w', encoding='utf-8') as f:
                json.dump(performance_history, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            self.logger.error(f"성과 데이터 저장 실패: {e}")

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
        
        # 성과 데이터 저장
        self.save_performance_data()

    def check_backtest_update(self):
        """백테스트 결과 파일 업데이트 확인"""
        try:
            if os.path.exists(self.backtest_results_file):
                # 파일 수정 시간 확인
                file_mtime = datetime.fromtimestamp(os.path.getmtime(self.backtest_results_file))
                
                # 마지막 확인 시간이 없거나 파일이 업데이트된 경우
                if not hasattr(self, 'last_backtest_check') or file_mtime > self.last_backtest_check:
                    self.logger.info("백테스트 결과 파일이 업데이트되었습니다. 종목 리로드...")
                    
                    # config 재로드
                    config_path = getattr(self, 'config_path', 'config.yaml')
                    with open(config_path, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                    
                    # 종목 재로드
                    new_symbols = self.load_symbols_from_backtest(config)
                    
                    if new_symbols != self.symbols:
                        self.logger.info(f"종목 변경: {self.symbols} → {new_symbols}")
                        self.symbols = new_symbols
                        
                        # 변경 알림
                        if self.discord_webhook:
                            self.send_discord_notification(
                                "🔄 종목 리스트 업데이트",
                                f"기존: {', '.join(self.symbols)}\n새로운: {', '.join(new_symbols)}",
                                0x00ffff
                            )
                    
                    self.last_backtest_check = datetime.now()
                    
        except Exception as e:
            self.logger.error(f"백테스트 업데이트 확인 실패: {e}")

    def run(self, interval_minutes: int = 5):
        """자동매매 시작"""
        self.logger.info("🚀 KIS API 모멘텀 자동매매 시작!")
        self.logger.info(f"대상 종목: {', '.join(self.symbols)}")
        self.logger.info(f"실행 간격: {interval_minutes}분")
    
        # 시작 알림
        if self.discord_webhook:
            strategy_info = []
            for symbol in self.symbols:
                strategy = self.strategy_map.get(symbol, "momentum")
                strategy_info.append(f"{symbol} ({strategy})")
    
            self.send_discord_notification(
                "🚀 자동매매 시작",
                f"대상 종목: {', '.join(strategy_info)}\n실행 간격: {interval_minutes}분",
                0x00ff00
            )
    
        daily_trades = 0
        successful_trades = 0
        last_daily_summary = datetime.now().date()
        last_backtest_check = datetime.now()
        last_backtest_date = None
    
        try:
            # 토큰 발급/로드 테스트
            token = self.get_access_token()
            if token:
                self.logger.info("토큰 준비 완료 ✅")
    
            while True:
                current_time = datetime.now()
    
                # 주말 오전 9시에 백테스트 실행
                if (current_time.weekday() == 5 and  # 토요일
                    current_time.hour == 9 and
                    current_time.minute < interval_minutes and
                    (last_backtest_date is None or last_backtest_date.date() != current_time.date())):
    
                    self.logger.info("🔄 주간 백테스트 시작...")
                    self.run_scheduled_backtest()
                    last_backtest_date = current_time
    
                # 또는 백테스트가 오래되었으면 실행
                elif self.should_run_backtest() and current_time.hour == 8:
                    self.logger.info("🔄 백테스트가 오래되어 재실행...")
                    self.run_scheduled_backtest()
    
                # 백테스트 결과 업데이트 확인 (1시간마다)
                if current_time - last_backtest_check > timedelta(hours=1):
                    self.check_backtest_update()
                    last_backtest_check = current_time
    
                # 일일 요약 알림 (하루 한 번)
                if current_time.date() != last_daily_summary and current_time.hour >= 16:
                    self.notify_daily_summary(daily_trades, self.daily_pnl, successful_trades)
                    daily_trades = 0
                    successful_trades = 0
                    self.daily_pnl = 0
                    last_daily_summary = current_time.date()
    
                # 장 시간 체크 (9:00 ~ 15:30)
                #if 9 <= current_time.hour < 15 or (current_time.hour == 15 and current_time.minute <= 30):
                if self.is_market_open(current_time):
                    self.logger.info(f"📊 거래 사이클 시작 - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
                    cycle_start_trades = self.trade_count
                    self.run_trading_cycle()
    
                    # 이번 사이클에서 거래가 발생했는지 확인
                    if self.trade_count > cycle_start_trades:
                        daily_trades += (self.trade_count - cycle_start_trades)
                        successful_trades += (self.trade_count - cycle_start_trades)
    
                    self.logger.info("✅ 거래 사이클 완료(2)\n")
                else:
                    self.logger.info("장 시간 외 - 대기 중...")
    
                # 다음 실행 시간 로그
                next_run = current_time + timedelta(minutes=interval_minutes)
                self.logger.info(f"다음 실행 예정: {next_run.strftime('%H:%M:%S')}")
                
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


    def run_scheduled_backtest(self):
        """주기적으로 백테스트 실행"""
        try:
            from backtest import KISBacktester
            
            self.logger.info("📊 예약된 백테스트 실행 시작...")
            
            # 백테스터 초기화
            backtester = KISBacktester(self.app_key, self.app_secret, mock=False)
            
            # 현재 거래 중인 종목 + 추가 후보 종목
            stock_codes = self.symbols.copy()
            
            # 추가 후보 종목 (config에서 읽거나 하드코딩)
            additional_candidates = [
                "352820",  # 하이브
            ]
            
            # 중복 제거
            all_stocks = list(set(stock_codes + additional_candidates))
            print(f"{all_stocks}")
            
            # 백테스트 실행
            results = backtester.run_comprehensive_backtest(all_stocks, days=100)
            
            if not results.empty:
                self.logger.info("✅ 백테스트 완료 - 결과 저장됨")
                
                # Discord 알림
                if self.discord_webhook:
                    self.send_discord_notification(
                        "📊 주간 백테스트 완료",
                        f"분석 종목 수: {len(all_stocks)}\n"
                        f"결과 파일: backtest_results.json\n"
                        f"다음 거래일부터 새로운 종목 리스트 적용",
                        0x00ff00
                    )
                
                # 종목 리스트 자동 업데이트
                self.check_backtest_update()
                
        except Exception as e:
            self.logger.error(f"백테스트 실행 실패: {e}")
            self.notify_error("백테스트 실행 실패", str(e))
    
    def should_run_backtest(self):
        """백테스트 실행 여부 확인"""
        try:
            # 백테스트 결과 파일의 마지막 수정 시간 확인
            if os.path.exists(self.backtest_results_file):
                file_mtime = datetime.fromtimestamp(os.path.getmtime(self.backtest_results_file))
                days_since_update = (datetime.now() - file_mtime).days
                
                # 7일 이상 지났으면 True
                return days_since_update >= 7
            else:
                # 파일이 없으면 즉시 실행
                return True
                
        except Exception as e:
            self.logger.error(f"백테스트 실행 여부 확인 실패: {e}")
            return False

    # run_debug 메서드 추가
    def run_debug(self, interval_minutes: int = 1):
        """디버그 모드 - 장시간 체크 없이 실행"""
        self.logger.info("🐛 디버그 모드로 실행 중...")
        self.logger.info(f"대상 종목: {', '.join(self.symbols)}")
        self.logger.info(f"실행 간격: {interval_minutes}분")
        
        try:
            token = self.get_access_token()
            if token:
                self.logger.info("토큰 준비 완료 ✅")
            
            while True:
                current_time = datetime.now()
                self.logger.info(f"\n{'='*60}")
                self.logger.info(f"디버그 사이클 - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                self.logger.info(f"{'='*60}")
                
                # 장시간 체크 없이 바로 실행
                self.run_trading_cycle()
                
                # 대기
                self.logger.info(f"다음 실행: {interval_minutes}분 후")
                time.sleep(interval_minutes * 60)
            
        except KeyboardInterrupt:
            self.logger.info("디버그 모드 종료")
        except Exception as e:
            self.logger.error(f"디버그 중 오류: {e}")


    def load_stock_names(self):
        """저장된 종목명 매핑 로드"""
        try:
            if os.path.exists(self.stock_names_file):
                with open(self.stock_names_file, 'r', encoding='utf-8') as f:
                    self.stock_names = json.load(f)
                self.logger.info(f"📚 종목명 {len(self.stock_names)}개 로드 완료")
            else:
                self.stock_names = {}
                self.logger.info("📚 종목명 캐시 파일이 없습니다. 새로 생성합니다.")
        except Exception as e:
            self.logger.warning(f"종목명 파일 로드 실패 (새로 생성됨): {e}")
            self.stock_names = {}
    
    def save_stock_names(self):
        """종목명 매핑을 파일로 저장"""
        try:
            with open(self.stock_names_file, 'w', encoding='utf-8') as f:
                json.dump(self.stock_names, f, ensure_ascii=False, indent=2)
            self.logger.debug("💾 종목명 캐시 저장 완료")
        except Exception as e:
            self.logger.error(f"종목명 저장 실패: {e}")
    
    def get_stock_name(self, code: str) -> str:
        """안전한 종목명 조회 - 속성 오류 방지"""
        
        # 필수 속성들 확인 및 초기화
        if not hasattr(self, 'skip_stock_name_api'):
            self.skip_stock_name_api = False
        if not hasattr(self, 'api_error_count'):
            self.api_error_count = 0
        
        # 1. 메모리 캐시 확인
        if code in self.stock_names and self.stock_names[code]:
            return self.stock_names[code]
        
        # 2. 하드코딩된 사전 확인
        hardcoded_stocks = {
            '005930': '삼성전자',
            '035720': '카카오', 
            '000660': 'SK하이닉스',
            '042660': '한화오션',
            '062040': '산일전기',
            '272210': '한화시스템',
            '161580': '필옵틱스',
            '281820': '케이씨텍',
            '014620': '성광밴드',
            '278470': '에이피알'
        }
        
        if code in hardcoded_stocks:
            name = hardcoded_stocks[code]
            self.stock_names[code] = name
            self.save_stock_names()
            self.logger.info(f"✅ 하드코딩에서 종목명 조회: {code} -> {name}")
            return name
        
        # 3. API 오류가 많으면 건너뛰기
        if self.skip_stock_name_api or self.api_error_count >= 3:
            self.logger.warning(f"⚠️ {code} 종목명 API 건너뛰기 (오류 {self.api_error_count}회)")
            self.stock_names[code] = code
            return code
        
        # 4. API 호출 (타임아웃 처리)
        try:
            name = self.fetch_stock_name_from_api(code)
            if name and name != code:
                self.stock_names[code] = name
                self.save_stock_names()
                self.logger.info(f"✅ API에서 종목명 조회: {code} -> {name}")
                return name
        except Exception as e:
            self.api_error_count += 1
            self.logger.error(f"종목명 조회 실패 ({self.api_error_count}/3): {e}")
            
            if self.api_error_count >= 3:
                self.skip_stock_name_api = True
                self.logger.warning("🚨 종목명 API 호출 중단 (타임아웃 빈발)")
        
        # 5. 실패 시 종목코드 반환
        self.stock_names[code] = code
        return code


    
    def fetch_stock_name_from_api(self, symbol: str) -> str:
        """안전한 API 종목명 조회 - 짧은 타임아웃"""
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST01010100"
            }
            params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol}
            
            # 짧은 타임아웃 (5초)
            response = requests.get(url, headers=headers, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('rt_cd') == '0' and data.get('output'):
                    output = data['output']
                    
                    # 종목명 필드들 확인
                    name_fields = ['hts_kor_isnm', 'prdt_abrv_name', 'stck_shnm']
                    for field in name_fields:
                        stock_name = output.get(field, '').strip()
                        if stock_name and stock_name != symbol:
                            return stock_name
            
        except requests.exceptions.Timeout:
            self.logger.warning(f"⏰ {symbol} 종목명 조회 타임아웃")
        except Exception as e:
            self.logger.debug(f"종목명 API 오류 ({symbol}): {e}")
        
        return symbol
    
    def update_all_stock_names(self):
        """안전한 종목명 업데이트 - 오류 방지"""
        self.logger.info("🔄 종목명 업데이트 시작...")
        
        # 필수 속성들이 없으면 초기화
        if not hasattr(self, 'skip_stock_name_api'):
            self.skip_stock_name_api = False
        if not hasattr(self, 'api_error_count'):
            self.api_error_count = 0
        
        updated_count = 0
        for symbol in self.symbols:
            try:
                if symbol not in self.stock_names or not self.stock_names[symbol] or self.stock_names[symbol] == symbol:
                    self.logger.info(f"📝 {symbol} 종목명 업데이트 중...")
                    name = self.get_stock_name(symbol)  # 안전한 버전 사용
                    if name != symbol:
                        updated_count += 1
                    time.sleep(0.5)  # API 호출 간격
            except Exception as e:
                self.logger.warning(f"⚠️ {symbol} 종목명 업데이트 실패: {e}")
                # 실패해도 계속 진행
                self.stock_names[symbol] = symbol
        
        if updated_count > 0:
            self.logger.info(f"✅ {updated_count}개 종목명 업데이트 완료")
        else:
            self.logger.info("✅ 모든 종목명이 이미 설정되어 있습니다")
    
    def validate_stock_names_cache(self):
        """종목명 캐시 유효성 검사 및 정리"""
        try:
            if not self.stock_names:
                return
                
            # 빈 값이나 None 제거
            invalid_keys = [k for k, v in self.stock_names.items() if not v or v.strip() == '']
            for key in invalid_keys:
                del self.stock_names[key]
                self.logger.debug(f"무효한 종목명 캐시 제거: {key}")
            
            # 현재 거래 종목이 아닌 것들 중 오래된 것 제거 (선택사항)
            # 캐시 크기가 너무 클 때만 실행
            if len(self.stock_names) > 100:
                trading_symbols = set(self.symbols)
                cache_symbols = set(self.stock_names.keys())
                unused_symbols = cache_symbols - trading_symbols
                
                if len(unused_symbols) > 50:  # 50개 이상일 때만 정리
                    # 무작위로 일부 제거
                    import random
                    to_remove = random.sample(list(unused_symbols), len(unused_symbols) // 2)
                    for symbol in to_remove:
                        del self.stock_names[symbol]
                    self.logger.info(f"사용하지 않는 종목명 캐시 {len(to_remove)}개 정리 완료")
            
            # 변경사항이 있으면 저장
            if invalid_keys:
                self.save_stock_names()
                
        except Exception as e:
            self.logger.error(f"종목명 캐시 검증 실패: {e}")
    

    def load_symbols_from_backtest(self, config: dict) -> List[str]:
        """백테스트 결과에서 종목 로드 - 종목명 업데이트 포함"""
        symbols = []
        
        # ... 기존 백테스트 로드 코드 ...
        
        # 2. 백테스트 결과 파일에서 로드
        try:
            if os.path.exists(self.backtest_results_file):
                with open(self.backtest_results_file, 'r', encoding='utf-8') as f:
                    backtest_data = json.load(f)

                # 최소 수익률 기준으로 필터링
                verified_symbols = backtest_data.get('verified_symbols', [])
                filtered_symbols = [
                    item for item in verified_symbols
                    if item['return'] >= self.min_return_threshold
                ]

                # 우선순위대로 정렬 (priority가 낮을수록 우선)
                filtered_symbols.sort(key=lambda x: x['priority'])

                # 최대 종목 수만큼 선택
                selected = filtered_symbols[:self.max_symbols]
                symbols = [item['symbol'] for item in selected]

                # 종목별 전략 매핑 저장
                for item in selected:
                    self.strategy_map[item['symbol']] = item['strategy']

                self.logger.info(f"백테스트 결과에서 종목 로드: {symbols}")

                # 선택된 종목의 상세 정보 출력 (종목명 포함)
                for item in selected:
                    stock_name = self.get_stock_name(item['symbol'])  # 종목명 조회
                    self.logger.info(f"  - {item['symbol']} ({stock_name}): "
                                   f"수익률 {item['return']}%, "
                                   f"승률 {item['win_rate']:.1%}, 전략: {item['strategy']}")

                # 백테스트 결과 알림
                if self.discord_webhook and symbols:
                    self.notify_backtest_selection(selected, backtest_data.get('summary', {}))
                    
        except Exception as e:
            self.logger.error(f"백테스트 결과 로드 실패: {e}")
            # 기본 종목 설정
            symbols = ['005930', '035720']  # 삼성전자, 카카오
            self.logger.warning(f"기본 종목으로 설정: {symbols}")

        return symbols

    def determine_order_strategy(self, signal_strength: float, side: str) -> str:
        """신호 강도에 따른 주문 전략 결정"""
        
        if side == "BUY":
            if signal_strength >= 4.0:
                return "urgent"  # 매우 강한 신호 - 즉시 체결
            elif signal_strength >= 2.5:
                return "aggressive_limit"  # 강한 신호 - 적극적 지정가
            elif signal_strength >= 1.0:
                return "limit"  # 보통 신호 - 일반 지정가
            else:
                return "patient_limit"  # 약한 신호 - 보수적 지정가
        
        else:  # SELL
            # 매도는 보통 빠른 체결을 선호
            if signal_strength >= 3.5:
                return "urgent"
            elif signal_strength >= 2.0:
                return "aggressive_limit"
            else:
                return "limit"
    
    def monitor_order(self, order_no: str, symbol: str, side: str):
        """주문 체결 모니터링 (백그라운드에서 실행)"""
        import threading
        
        def check_order_status():
            """주문 상태 확인"""
            try:
                for attempt in range(self.order_timeout_minutes):
                    time.sleep(60)  # 1분마다 확인
                    
                    # 주문 체결 조회 API 호출
                    order_status = self.get_order_status(order_no)
                    
                    if order_status:
                        status = order_status.get('order_status', 'PENDING')
                        filled_qty = int(order_status.get('filled_quantity', 0))
                        total_qty = int(order_status.get('total_quantity', 0))
                        
                        if status == 'FILLED':
                            # 완전 체결
                            self.logger.info(f"✅ 주문 완전 체결: {symbol} {side} {filled_qty}주 (주문번호: {order_no})")
                            break
                        elif status == 'PARTIALLY_FILLED' and self.partial_fill_allowed:
                            # 부분 체결
                            remaining = total_qty - filled_qty
                            self.logger.info(f"⚡ 주문 부분 체결: {symbol} {side} {filled_qty}/{total_qty}주 "
                                           f"(잔여: {remaining}주)")
                            
                            if attempt >= self.order_timeout_minutes - 1:
                                # 시간 초과 시 남은 주문 취소 여부 결정
                                self.handle_partial_fill(order_no, symbol, side, remaining)
                                break
                        elif status == 'CANCELLED':
                            self.logger.warning(f"❌ 주문 취소됨: {symbol} {side} (주문번호: {order_no})")
                            break
                        elif status == 'REJECTED':
                            self.logger.error(f"❌ 주문 거부됨: {symbol} {side} (주문번호: {order_no})")
                            break
                    
                    if attempt >= self.order_timeout_minutes - 1:
                        # 타임아웃 - 주문 취소 고려
                        self.logger.warning(f"⏰ 주문 체결 시간 초과: {symbol} {side} (주문번호: {order_no})")
                        self.handle_order_timeout(order_no, symbol, side)
                        
            except Exception as e:
                self.logger.error(f"주문 모니터링 오류: {e}")
        
        # 백그라운드 스레드로 실행
        monitor_thread = threading.Thread(target=check_order_status, daemon=True)
        monitor_thread.start()
    
    def get_order_status(self, order_no: str) -> Dict:
        """주문 체결 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-order"
        
        is_mock = "vts" in self.base_url.lower()
        tr_id = "VTTC8001R" if is_mock else "TTTC8001R"
        
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
            "PDNO": "",  # 전체 조회
            "ORD_STRT_DT": datetime.now().strftime("%Y%m%d"),
            "ORD_END_DT": datetime.now().strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00",  # 전체
            "ORD_DVSN": "00",  # 전체
            "CCLD_DVSN": "00",  # 전체
            "ORD_GNO_BRNO": "",
            "ODNO": order_no,  # 특정 주문번호
            "INQR_DVSN": "00",
            "UNPR": "",
            "FUTU_YN": "N"
        }
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('rt_cd') == '0' and data.get('output1'):
                    orders = data['output1'] if isinstance(data['output1'], list) else [data['output1']]
                    
                    # 해당 주문번호 찾기
                    for order in orders:
                        if order.get('odno') == order_no:
                            return {
                                'order_status': self.parse_order_status(order.get('ord_stat_cd', '')),
                                'filled_quantity': order.get('tot_ccld_qty', 0),
                                'total_quantity': order.get('ord_qty', 0),
                                'filled_price': order.get('avg_prvs', 0),
                                'order_time': order.get('ord_tmd', ''),
                                'order_type': order.get('ord_dvsn_name', '')
                            }
        except Exception as e:
            self.logger.error(f"주문 조회 실패: {e}")
        
        return {}
    
    def parse_order_status(self, status_code: str) -> str:
        """주문 상태 코드 해석"""
        status_map = {
            '01': 'PENDING',           # 접수
            '02': 'FILLED',            # 체결
            '03': 'PARTIALLY_FILLED',  # 부분체결
            '04': 'CANCELLED',         # 취소
            '05': 'REJECTED',          # 거부
            '06': 'MODIFIED',          # 정정
            '07': 'EXPIRED'            # 기간만료
        }
        return status_map.get(status_code, 'UNKNOWN')
    
    def handle_partial_fill(self, order_no: str, symbol: str, side: str, remaining_qty: int):
        """부분 체결 처리"""
        self.logger.info(f"🤔 부분 체결 처리: {symbol} {side} 잔여 {remaining_qty}주")
        
        # 잔여 주문 취소 후 시장가로 재주문 옵션
        try:
            # 1. 기존 주문 취소
            cancel_result = self.cancel_order(order_no)
            
            if cancel_result['success'] and remaining_qty > 0:
                # 2. 시장가로 재주문 (빠른 체결)
                self.logger.info(f"🔄 잔여 수량 시장가 재주문: {symbol} {side} {remaining_qty}주")
                market_result = self.place_order(symbol, side, remaining_qty, price=0)
                
                if market_result['success']:
                    self.logger.info(f"✅ 잔여 수량 시장가 체결: {symbol} {side} {remaining_qty}주")
                else:
                    self.logger.error(f"❌ 잔여 수량 재주문 실패: {symbol} {side}")
                    
        except Exception as e:
            self.logger.error(f"부분 체결 처리 오류: {e}")
    
    def handle_order_timeout(self, order_no: str, symbol: str, side: str):
        """주문 타임아웃 처리"""
        self.logger.warning(f"⏰ 주문 타임아웃: {symbol} {side} (주문번호: {order_no})")
        
        # 전략에 따라 취소 또는 대기 결정
        if side == "BUY":
            # 매수는 취소 후 다음 기회 대기
            self.cancel_order(order_no)
            self.logger.info(f"🔄 매수 주문 취소: {symbol} - 다음 기회 대기")
        else:
            # 매도는 시장가로 변경 고려 (보유 포지션 정리 우선)
            cancel_result = self.cancel_order(order_no)
            if cancel_result['success']:
                self.logger.info(f"🔄 매도 주문을 시장가로 재시도: {symbol}")
                # 여기서 수량 정보가 필요하므로 주문 정보 조회 필요
    
    def cancel_order(self, order_no: str) -> Dict:
        """주문 취소"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"
        
        is_mock = "vts" in self.base_url.lower()
        tr_id = "VTTC0803U" if is_mock else "TTTC0803U"
        
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
            "KRX_FWDG_ORD_ORGNO": "",
            "ORGN_ODNO": order_no,
            "ORD_DVSN": "00",  # 지정가
            "RVSE_CNCL_DVSN_CD": "02",  # 취소
            "ORD_QTY": "0",
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y"  # 전량 취소
        }
        
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            result = response.json()
            
            if result.get('rt_cd') == '0':
                self.logger.info(f"✅ 주문 취소 성공: {order_no}")
                return {'success': True}
            else:
                error_msg = result.get('msg1', 'Unknown error')
                self.logger.error(f"❌ 주문 취소 실패: {error_msg}")
                return {'success': False, 'error': error_msg}
                
        except Exception as e:
            self.logger.error(f"주문 취소 API 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    def print_position_status(self):
        """현재 포지션 상태 출력"""
        print("\n" + "="*80)
        print("📊 현재 포지션 상태")
        print("="*80)
        
        summary = self.get_position_summary()
        
        if not summary['positions']:
            print("💼 보유 포지션 없음")
            return
        
        print(f"💰 총 보유 종목: {summary['total_symbols']}개")
        print(f"💵 총 평가 금액: {summary['total_value']:,}원")
        print()
        
        for symbol, pos in summary['positions'].items():
            stock_name = self.get_stock_name(symbol)
            profit_pct = pos['profit_loss']
            
            # 이모티콘으로 상태 표시
            status_emoji = "📈" if profit_pct > 0 else "📉" if profit_pct < 0 else "➡️"
            buy_emoji = "✅" if pos['can_buy_more'] else "🚫"
            sell_emoji = "✅" if pos['can_sell'] else "🚫"
            
            print(f"{status_emoji} {symbol} ({stock_name})")
            print(f"   보유: {pos['quantity']}주 @ {pos['avg_price']:,}원")
            print(f"   현재: {pos['current_price']:,}원 ({profit_pct:+.2%})")
            print(f"   보유시간: {pos['holding_hours']:.1f}시간")
            print(f"   매수횟수: {pos['purchase_count']}회")
            print(f"   추가매수: {buy_emoji} / 매도: {sell_emoji}")
            print()
    
    def check_position_restrictions(self):
        """모든 종목의 제한 상황 체크"""
        print("\n" + "="*80)
        print("🔍 포지션 제한 상황 체크")
        print("="*80)
        
        for symbol in self.symbols:
            stock_name = self.get_stock_name(symbol)
            can_buy, buy_reason = self.can_purchase_symbol(symbol)
            can_sell, sell_reason = self.can_sell_symbol(symbol)
            
            print(f"\n📋 {symbol} ({stock_name}):")
            print(f"   매수: {'✅ 가능' if can_buy else '🚫 ' + buy_reason}")
            print(f"   매도: {'✅ 가능' if can_sell else '🚫 ' + sell_reason}")
    
    def reset_position_history(self, symbol: str = None):
        """포지션 이력 초기화 (테스트용)"""
        if symbol:
            # 특정 종목만 초기화
            if symbol in self.position_manager.position_history:
                del self.position_manager.position_history[symbol]
                self.position_manager.save_position_history()
                self.logger.info(f"🔄 {symbol} 포지션 이력 초기화 완료")
        else:
            # 전체 초기화
            self.position_manager.position_history = {}
            self.position_manager.save_position_history()
            self.logger.info("🔄 전체 포지션 이력 초기화 완료")
    
    def simulate_time_passage(self, hours: int):
        """시간 경과 시뮬레이션 (테스트용)"""
        """주의: 실제 시간을 변경하지 않고 기록된 시간만 조정"""
        adjustment = timedelta(hours=hours)
        
        for symbol, history in self.position_manager.position_history.items():
            # 첫 매수 시간 조정
            if history.get('first_purchase_time'):
                original_time = datetime.fromisoformat(history['first_purchase_time'])
                new_time = original_time - adjustment
                history['first_purchase_time'] = new_time.isoformat()
            
            # 마지막 매수 시간 조정
            if history.get('last_purchase_time'):
                original_time = datetime.fromisoformat(history['last_purchase_time'])
                new_time = original_time - adjustment
                history['last_purchase_time'] = new_time.isoformat()
            
            # 개별 매수 기록들도 조정
            for purchase in history.get('purchases', []):
                original_time = datetime.fromisoformat(purchase['timestamp'])
                new_time = original_time - adjustment
                purchase['timestamp'] = new_time.isoformat()
        
        self.position_manager.save_position_history()
        self.logger.info(f"⏰ 시간을 {hours}시간 앞당겼습니다 (테스트용)")
    
    def notify_position_limits(self, symbol: str, action: str, reason: str):
        """포지션 제한 알림"""
        if not self.notify_on_trade:
            return
    
        title = f"🚫 {action} 제한"
        stock_name = self.get_stock_name(symbol)
        
        message = f"""
    **종목**: {symbol} ({stock_name})
    **제한 사유**: {reason}
    **시간**: {datetime.now().strftime('%H:%M:%S')}
        """
    
        self.send_discord_notification(title, message, 0xffaa00)
    
    def get_purchase_history_summary(self) -> Dict:
        """매수 이력 요약"""
        summary = {
            'total_purchases': 0,
            'total_symbols_traded': 0,
            'average_holding_time': 0,
            'symbols': {}
        }
        
        total_holding_time = 0
        active_positions = 0
        
        for symbol, history in self.position_manager.position_history.items():
            purchases = len([p for p in history.get('purchases', []) if p['order_type'] == 'BUY'])
            
            if purchases > 0:
                summary['total_purchases'] += purchases
                summary['total_symbols_traded'] += 1
                
                # 보유 시간 계산
                first_purchase = history.get('first_purchase_time')
                if first_purchase:
                    start_time = datetime.fromisoformat(first_purchase)
                    
                    # 포지션이 정리되었으면 정리 시간까지, 아니면 현재까지
                    if history.get('position_closed_time'):
                        end_time = datetime.fromisoformat(history['position_closed_time'])
                    else:
                        end_time = datetime.now()
                        active_positions += 1
                    
                    holding_hours = (end_time - start_time).total_seconds() / 3600
                    total_holding_time += holding_hours
                
                summary['symbols'][symbol] = {
                    'purchases': purchases,
                    'total_quantity': history.get('total_quantity', 0),
                    'is_active': symbol in self.positions
                }
        
        if summary['total_symbols_traded'] > 0:
            summary['average_holding_time'] = total_holding_time / summary['total_symbols_traded']
        
        summary['active_positions'] = active_positions
        
        return summary
    

    def calculate_limit_price(self, current_price: float, side: str, price_offset_pct: float = 0.003) -> int:
        """지정가 계산 - 현재가 기준으로 약간의 여유를 둠"""
        
        if side == "BUY":
            # 매수: 현재가보다 약간 높게 설정 (빠른 체결을 위해)
            limit_price = current_price * (1 + price_offset_pct)
        else:  # SELL
            # 매도: 현재가보다 약간 낮게 설정 (빠른 체결을 위해)
            limit_price = current_price * (1 - price_offset_pct)
        
        # 한국 주식은 정수 단위로 가격 설정
        return int(limit_price)
    
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
                    
                    # 매수/매도 호가 정보
                    bid_ask_info = {
                        'current_price': int(output.get('stck_prpr', 0)),           # 현재가
                        'bid_price': int(output.get('bidp1', 0)),                  # 매수 1호가
                        'ask_price': int(output.get('askp1', 0)),                  # 매도 1호가
                        'bid_quantity': int(output.get('bidp_rsqn1', 0)),          # 매수 1호가 수량
                        'ask_quantity': int(output.get('askp_rsqn1', 0)),          # 매도 1호가 수량
                        'spread': int(output.get('askp1', 0)) - int(output.get('bidp1', 0))  # 스프레드
                    }
                    
                    self.logger.debug(f"📊 {symbol} 호가: 매수 {bid_ask_info['bid_price']:,}원 "
                                    f"/ 매도 {bid_ask_info['ask_price']:,}원 "
                                    f"(스프레드: {bid_ask_info['spread']:,}원)")
                    
                    return bid_ask_info
                    
        except Exception as e:
            self.logger.error(f"호가 조회 실패 ({symbol}): {e}")
        
        return {}
    
    def calculate_smart_limit_price(self, symbol: str, side: str, urgency: str = "normal") -> int:
        """스마트 지정가 계산 - 호가단위 적용"""
        
        # 1. 현재 호가 정보 조회
        bid_ask = self.get_current_bid_ask(symbol)
        
        if not bid_ask:
            # 호가 조회 실패 시 현재가 기반으로 계산
            current_price_data = self.get_current_price(symbol)
            if current_price_data and current_price_data.get('output'):
                current_price = float(current_price_data['output'].get('stck_prpr', 0))
                
                if current_price > 0:
                    if side == "BUY":
                        raw_price = current_price * 1.003  # 0.3% 높게
                    else:
                        raw_price = current_price * 0.997  # 0.3% 낮게
                    
                    # 호가단위 적용
                    limit_price = self.adjust_to_price_unit(raw_price)
                    
                    self.logger.info(f"💰 {symbol} {side} 현재가 기준 지정가: {limit_price:,}원 "
                                    f"(현재가: {current_price:,}원)")
                    return limit_price
                else:
                    raise Exception("현재가 정보를 가져올 수 없습니다")
            else:
                raise Exception("현재가 정보를 가져올 수 없습니다")
        
        current_price = bid_ask['current_price']
        bid_price = bid_ask['bid_price']
        ask_price = bid_ask['ask_price']
        spread = bid_ask['spread']
        
        if side == "BUY":
            if urgency == "urgent":
                # 긴급 매수: 매도 1호가에 주문
                raw_price = ask_price
            elif urgency == "aggressive":
                # 적극적 매수: 매도 1호가보다 살짝 높게
                raw_price = ask_price + max(spread // 4, self.get_min_price_unit(ask_price))
            else:  # normal
                # 일반 매수: 현재가와 매도 1호가 사이
                if spread <= self.get_min_price_unit(current_price) * 5:
                    raw_price = ask_price
                else:
                    raw_price = (current_price + ask_price) / 2
        
        else:  # SELL
            if urgency == "urgent":
                # 긴급 매도: 매수 1호가에 주문
                raw_price = bid_price
            elif urgency == "aggressive":
                # 적극적 매도: 매수 1호가보다 살짝 낮게
                raw_price = bid_price - max(spread // 4, self.get_min_price_unit(bid_price))
            else:  # normal
                # 일반 매도: 현재가와 매수 1호가 사이
                if spread <= self.get_min_price_unit(current_price) * 5:
                    raw_price = bid_price
                else:
                    raw_price = (current_price + bid_price) / 2
        
        # 호가단위 적용
        limit_price = self.adjust_to_price_unit(raw_price)
        
        # 최소 1원 이상
        limit_price = max(limit_price, 1)
        
        self.logger.info(f"💰 {symbol} {side} 지정가 계산: {limit_price:,}원 "
                        f"(현재가: {current_price:,}원, 긴급도: {urgency})")
        
        return limit_price
    
    def get_min_price_unit(self, price: float) -> int:
        """가격대별 최소 호가단위 반환"""
        if price < 1000:
            return 1
        elif price < 5000:
            return 5
        elif price < 10000:
            return 10
        elif price < 50000:
            return 50
        elif price < 100000:
            return 100
        elif price < 500000:
            return 500
        else:
            return 1000
    
    def place_limit_order(self, symbol: str, side: str, quantity: int, urgency: str = "normal") -> Dict:
        """수정된 지정가 주문 실행 - 호가단위 적용"""
        try:
            # 호가단위 적용된 지정가 계산
            limit_price = self.calculate_smart_limit_price(symbol, side, urgency)
            
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
            
            # 실전/모의 자동 감지
            is_mock = "vts" in self.base_url.lower()
            
            if is_mock:
                tr_id = "VTTC0802U" if side == "BUY" else "VTTC0801U"
            else:
                tr_id = "TTTC0802U" if side == "BUY" else "TTTC0801U"
            
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
                "ORD_DVSN": "00",  # 지정가
                "ORD_QTY": str(quantity),
                "ORD_UNPR": str(limit_price)  # 호가단위 적용된 가격
            }
            
            self.logger.info(f"📊 호가단위 적용 지정가 주문: {symbol} {side} {quantity}주 @ {limit_price:,}원")
            self.logger.debug(f"주문 데이터: {data}")
            
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            result = response.json()
            
            if result.get('rt_cd') == '0':
                order_no = result.get('output', {}).get('odno', 'Unknown')
                self.logger.info(f"✅ 지정가 주문 성공: {symbol} {side} {quantity}주 @ {limit_price:,}원 "
                               f"(주문번호: {order_no})")
                self.trade_count += 1
                
                # 알림 전송
                self.notify_limit_order_success(side, symbol, quantity, limit_price, order_no, urgency)
                
                return {
                    'success': True, 
                    'order_no': order_no, 
                    'limit_price': limit_price,
                    'urgency': urgency
                }
            else:
                error_msg = result.get('msg1', 'Unknown error')
                error_code = result.get('msg_cd', 'Unknown')
                self.logger.error(f"지정가 주문 실패: [{error_code}] {error_msg}")
                self.notify_trade_failure(side, symbol, error_msg)
                return {'success': False, 'error': error_msg}
        
        except Exception as e:
            self.logger.error(f"지정가 주문 실행 실패 ({symbol} {side}): {e}")
            self.notify_trade_failure(side, symbol, str(e))
            return {'success': False, 'error': str(e)}
    
    def place_order_with_strategy_old(self, symbol: str, side: str, quantity: int, strategy: str = "limit") -> Dict:
        """수정된 전략적 주문 실행 - 호가단위 적용"""
        
        if strategy == "market":
            # 시장가 주문
            return self.place_order(symbol, side, quantity, price=0)
        
        elif strategy in ["limit", "aggressive_limit", "patient_limit", "urgent"]:
            # 지정가 주문 (호가단위 적용)
            urgency_map = {
                "limit": "normal",
                "aggressive_limit": "aggressive", 
                "patient_limit": "normal",
                "urgent": "urgent"
            }
            urgency = urgency_map.get(strategy, "normal")
            
            return self.place_limit_order(symbol, side, quantity, urgency)
        
        elif strategy == "adaptive":
            # 적응형 주문
            return self.place_adaptive_order(symbol, side, quantity)
        
        else:
            self.logger.warning(f"알 수 없는 주문 전략: {strategy}, 기본 지정가 사용")
            return self.place_limit_order(symbol, side, quantity)

    def place_conservative_limit_order(self, symbol: str, side: str, quantity: int) -> Dict:
        """보수적 지정가 주문 - 더 유리한 가격 대기"""
        
        bid_ask = self.get_current_bid_ask(symbol)
        if not bid_ask:
            # 호가 정보 없으면 일반 지정가로 대체
            return self.place_limit_order(symbol, side, quantity, urgency="normal")
        
        current_price = bid_ask['current_price']
        
        if side == "BUY":
            # 매수: 현재가보다 1-2% 낮게 설정 (더 유리한 가격 대기)
            limit_price = int(current_price * 0.985)  # 1.5% 낮게
        else:  # SELL
            # 매도: 현재가보다 1-2% 높게 설정
            limit_price = int(current_price * 1.015)  # 1.5% 높게
        
        self.logger.info(f"🎯 보수적 지정가: {symbol} {side} {quantity}주 @ {limit_price:,}원 "
                        f"(현재가 대비 {((limit_price/current_price-1)*100):+.1f}%)")
        
        # 일반 지정가 주문 로직 사용 (가격만 다름)
        return self.place_order(symbol, side, quantity, price=limit_price)
    
    def place_adaptive_order(self, symbol: str, side: str, quantity: int) -> Dict:
        """수정된 적응형 주문 - 호가단위 적용"""
        
        # 시장 상황 분석
        bid_ask = self.get_current_bid_ask(symbol)
        if not bid_ask:
            self.logger.info(f"🤖 적응형 주문: 호가 정보 없음 → 시장가 사용")
            return self.place_order(symbol, side, quantity, price=0)
        
        spread = bid_ask['spread']
        current_price = bid_ask['current_price']
        min_unit = self.get_min_price_unit(current_price)
        spread_pct = (spread / current_price) * 100 if current_price > 0 else 0
        
        # 거래량 분석
        df = self.get_minute_data(symbol, minutes=10)
        
        if not df.empty and len(df) >= 3:
            recent_volumes = df['cntg_vol'].tail(3).tolist()
            avg_volume = df['cntg_vol'].mean()
            current_volume = recent_volumes[-1] if recent_volumes else 0
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1
            
            # 전략 결정 (호가단위 고려)
            if spread <= min_unit * 3:  # 스프레드가 호가단위 3배 이하
                strategy = "urgent"  # 즉시 체결
                reason = f"좁은 스프레드 ({spread}원 ≤ {min_unit*3}원)"
            elif spread_pct > 2.0:  # 스프레드가 2% 이상
                strategy = "normal"  # 일반 지정가
                reason = f"큰 스프레드 ({spread_pct:.1f}%)"
            elif volume_ratio > 3.0:  # 거래량이 평소의 3배 이상
                strategy = "aggressive"  # 적극적 지정가
                reason = f"높은 거래량 (평소의 {volume_ratio:.1f}배)"
            else:
                strategy = "normal"  # 기본 지정가
                reason = "일반적 시장 상황"
            
            self.logger.info(f"🤖 적응형 주문 분석: {reason} → {strategy}")
            
        else:
            strategy = "normal"
            self.logger.info(f"🤖 적응형 주문: 데이터 부족 → 기본 지정가")
        
        # 선택된 전략으로 주문 실행
        return self.place_limit_order(symbol, side, quantity, strategy)
    
    def notify_limit_order_success(self, action: str, symbol: str, quantity: int, 
                                  limit_price: int, order_no: str, urgency: str):
        """지정가 주문 성공 알림 (지정가 정보 포함)"""
        if not self.notify_on_trade:
            return
    
        action_emoji = "🛒" if action == "BUY" else "💸"
        color = 0x00ff00 if action == "BUY" else 0xff6600
        
        urgency_emoji = {
            "urgent": "🚨",
            "aggressive": "⚡",
            "normal": "📊",
            "patient": "🎯"
        }.get(urgency, "📊")
    
        strategy = self.strategy_map.get(symbol, "momentum")
        
        title = f"{action_emoji} {action} 지정가 주문 체결!"
        message = f"""
    **종목**: {symbol}
    **수량**: {quantity}주
    **지정가**: {limit_price:,}원
    **총액**: {quantity * limit_price:,}원
    **긴급도**: {urgency_emoji} {urgency}
    **전략**: {strategy}
    **주문번호**: {order_no}
    **시간**: {datetime.now().strftime('%H:%M:%S')}
        """
    
        self.send_discord_notification(title, message, color)
    
    # config.yaml에 추가할 주문 전략 설정
    def create_sample_config_with_order_strategy(self, config_path: str):
        """주문 전략 설정이 포함된 샘플 설정 파일 생성"""
        sample_config = {
            'kis': {
                'app_key': 'YOUR_APP_KEY',
                'app_secret': 'YOUR_APP_SECRET',
                'base_url': 'https://openapi.koreainvestment.com:9443',
                'account_no': 'YOUR_ACCOUNT_NO'
            },
            'trading': {
                'max_symbols': 5,
                'max_position_ratio': 0.1,
                'daily_loss_limit': 0.02,
                'stop_loss_pct': 0.05,
                'take_profit_pct': 0.15,
                
                # 주문 전략 설정 추가
                'order_strategy': 'adaptive',  # market, limit, aggressive_limit, patient_limit, adaptive
                'price_offset_pct': 0.003,     # 지정가 오프셋 (0.3%)
                'order_timeout_minutes': 5,    # 주문 대기 시간 (분)
                'partial_fill_allowed': True   # 부분 체결 허용
            },
            'position_management': {
                'max_purchases_per_symbol': 3,
                'max_quantity_per_symbol': 100,
                'min_holding_period_hours': 24,
                'purchase_cooldown_hours': 6
            },
            'momentum': {
                'period': 20,
                'threshold': 0.02,
                'volume_threshold': 1.5,
                'ma_short': 5,
                'ma_long': 20
            },
            'backtest': {
                'results_file': 'backtest_results.json',
                'min_return_threshold': 5.0,
                'performance_tracking': True
            },
            'notification': {
                'discord_webhook': '',
                'notify_on_trade': True,
                'notify_on_error': True,
                'notify_on_daily_summary': True
            }
        }
    
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(sample_config, f, default_flow_style=False, allow_unicode=True)

    def enhanced_sell_logic(self, symbol: str, signals: dict):
        """개선된 매도 로직 - 우선순위 기반"""
    
        current_position = self.positions.get(symbol, {})
        if not current_position or current_position.get('quantity', 0) <= 0:
            return  # 포지션 없음
    
        profit_loss = current_position['profit_loss'] / 100
    
        # 1순위: 손절 (제한 무시)
        if profit_loss <= -self.stop_loss_pct:
            self.execute_emergency_sell(symbol, "손절매")
            return
    
        # 2순위: 강한 매도 신호 (제한 무시)
        if signals['signal'] == 'SELL' and signals['strength'] >= 3.0:
            self.execute_emergency_sell(symbol, "강한 매도 신호")
            return
    
        # 3순위: 일반 매도 신호 (제한 확인)
        if signals['signal'] == 'SELL':
            can_sell, reason = self.can_sell_symbol(symbol)
            if can_sell:
                self.execute_normal_sell(symbol, "매도 신호")
            else:
                self.logger.info(f"💎 {symbol} - 매도 신호 있지만 제한: {reason}")
    
        # 4순위: 익절 (제한 확인)
        elif profit_loss >= self.take_profit_pct:
            can_sell, reason = self.can_sell_symbol(symbol)
            if can_sell:
                self.execute_normal_sell(symbol, "익절매")
            else:
                self.logger.info(f"💎 {symbol} - 익절 조건이지만 제한: {reason}")

    def execute_emergency_sell(self, symbol: str, reason: str):
        """긴급 매도 (제한 무시)"""
        quantity = self.positions[symbol]['quantity']
        result = self.place_order_with_strategy(symbol, 'SELL', quantity, "urgent")
    
        if result['success']:
            self.logger.warning(f"🚨 {symbol} 긴급 매도: {reason}")

    def execute_normal_sell(self, symbol: str, reason: str):
        """일반 매도"""
        quantity = self.positions[symbol]['quantity']
        result = self.place_order_with_strategy(symbol, 'SELL', quantity, "aggressive_limit")
        
        if result['success']:
            self.logger.info(f"💸 {symbol} 일반 매도: {reason}")


    def get_all_holdings(self) -> Dict:
        """실제 계좌의 모든 보유 종목 조회 (수정된 버전)"""
        try:
            self.logger.info("📋 전체 보유 종목 조회 중...")
            
            # 잔고 조회 API (CTX_AREA_FK100 오류 해결된 버전)
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
            
            # 수정된 파라미터 (CTX_AREA_FK100 오류 해결)
            params = {
                "CANO": self.account_no.split('-')[0],
                "ACNT_PRDT_CD": self.account_no.split('-')[1],
                "AFHR_FLPR_YN": "N",               # 시간외단일가 반영여부
                "OFL_YN": "",                      # 오프라인여부 (공백)
                "INQR_DVSN": "02",                 # 조회구분 (02: 잔고)
                "UNPR_DVSN": "01",                 # 단가구분 (01: 기본)
                "FUND_STTL_ICLD_YN": "N",          # 펀드결제분포함여부
                "FNCG_AMT_AUTO_RDPT_YN": "N",      # 융자금액자동상환여부
                "PRCS_DVSN": "01",                 # 처리구분 (01: 기본)
                "CTX_AREA_FK100": "",              # 연속조회검색조건100 (첫 조회시 공백)
                "CTX_AREA_NK100": ""               # 연속조회키100 (첫 조회시 공백)
            }
            
            self.logger.debug(f"잔고 조회 파라미터: {params}")
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                rt_cd = data.get('rt_cd')
                self.logger.debug(f"rt_cd: {rt_cd}")
                
                if rt_cd == '0':
                    all_holdings = {}
                    
                    # output1: 보유종목 리스트
                    holdings = data.get('output1', [])
                    
                    if isinstance(holdings, list):
                        self.logger.info(f"보유종목 리스트 크기: {len(holdings)}")
                        
                        for holding in holdings:
                            symbol = holding.get('pdno', '')
                            quantity = int(holding.get('hldg_qty', 0))
                            stock_name = holding.get('prdt_name', symbol)
                            
                            if quantity > 0 and symbol:  # 수량이 있는 종목만
                                try:
                                    all_holdings[symbol] = {
                                        'quantity': quantity,
                                        'avg_price': float(holding.get('pchs_avg_pric', 0)),
                                        'current_price': float(holding.get('prpr', 0)),
                                        'profit_loss': float(holding.get('evlu_pfls_rt', 0)),
                                        'stock_name': holding.get('prdt_name', symbol),
                                        'total_value': float(holding.get('evlu_amt', 0)),
                                        'purchase_amount': float(holding.get('pchs_amt', 0))
                                    }
                                    
                                    self.logger.info(f"📈 보유 종목: {symbol}({stock_name}) - {quantity}주 "
                                                   f"@ {all_holdings[symbol]['avg_price']:,}원 "
                                                   f"(손익: {all_holdings[symbol]['profit_loss']:+.2f}%)")
                                    
                                except (ValueError, TypeError) as e:
                                    self.logger.error(f"데이터 파싱 오류 ({symbol}): {e}")
                    else:
                        self.logger.warning(f"예상치 못한 데이터 형식: {type(holdings)}")
                    
                    self.logger.info(f"✅ 전체 보유 종목 {len(all_holdings)}개 조회 완료")
                    return all_holdings
                    
                else:
                    error_msg = data.get('msg1', 'Unknown error')
                    error_code = data.get('msg_cd', 'Unknown')
                    self.logger.error(f"잔고 조회 실패: [{error_code}] {error_msg}")
                    
            else:
                self.logger.error(f"잔고 조회 HTTP 오류: {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"전체 보유 종목 조회 실패: {e}")
            import traceback
            self.logger.error(f"상세 오류:\n{traceback.format_exc()}")
        
        return {}
    
    def get_all_holdings_backup(self) -> Dict:
        """수정된 전체 보유 종목 조회"""
        try:
            self.logger.info("📋 전체 보유 종목 조회 중...")
            
            # 잔고 조회 API (수정된 파라미터)
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
            
            # 수정된 파라미터 (CTX_AREA_FK100 오류 해결)
            params = {
                "CANO": self.account_no.split('-')[0],
                "ACNT_PRDT_CD": self.account_no.split('-')[1],
                "AFHR_FLPR_YN": "N",               # 시간외단일가 반영여부
                "OFL_YN": "",                      # 오프라인여부 (공백)
                "INQR_DVSN": "02",                 # 조회구분 (02: 잔고)
                "UNPR_DVSN": "01",                 # 단가구분 (01: 기본)
                "FUND_STTL_ICLD_YN": "N",          # 펀드결제분포함여부
                "FNCG_AMT_AUTO_RDPT_YN": "N",      # 융자금액자동상환여부
                "PRCS_DVSN": "01",                 # 처리구분 (01: 기본)
                "CTX_AREA_FK100": "",              # 연속조회검색조건100 (첫 조회시 공백)
                "CTX_AREA_NK100": ""               # 연속조회키100 (첫 조회시 공백)
            }
            
            self.logger.debug(f"잔고 조회 파라미터: {params}")
            
            response = requests.get(url, headers=headers, params=params, timeout=15)
            
            self.logger.debug(f"잔고 조회 응답 코드: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                
                rt_cd = data.get('rt_cd')
                self.logger.debug(f"rt_cd: {rt_cd}")
                
                if rt_cd == '0':
                    all_holdings = {}
                    
                    # output1: 보유종목 리스트
                    holdings = data.get('output1', [])
                    
                    self.logger.info(f"조회된 데이터 타입: {type(holdings)}")
                    
                    if isinstance(holdings, list):
                        self.logger.info(f"보유종목 리스트 크기: {len(holdings)}")
                        
                        for i, holding in enumerate(holdings):
                            symbol = holding.get('pdno', '')
                            quantity = int(holding.get('hldg_qty', 0))
                            
                            self.logger.debug(f"[{i}] 종목: {symbol}, 수량: {quantity}")
                            
                            if quantity > 0 and symbol:
                                try:
                                    stock_name = holding.get('prdt_name', symbol)
                                    
                                    all_holdings[symbol] = {
                                        'quantity': quantity,
                                        'avg_price': float(holding.get('pchs_avg_pric', 0)),
                                        'current_price': float(holding.get('prpr', 0)),
                                        'profit_loss': float(holding.get('evlu_pfls_rt', 0)),
                                        'stock_name': stock_name,
                                        'total_value': float(holding.get('evlu_amt', 0)),
                                        'purchase_amount': float(holding.get('pchs_amt', 0))
                                    }
                                    
                                    self.logger.info(f"📈 보유 종목: {symbol}({stock_name}) - {quantity}주 "
                                                   f"@ {all_holdings[symbol]['avg_price']:,}원 "
                                                   f"(손익: {all_holdings[symbol]['profit_loss']:+.2f}%)")
                                    
                                except (ValueError, TypeError) as e:
                                    self.logger.error(f"데이터 파싱 오류 ({symbol}): {e}")
                                    self.logger.debug(f"원본 데이터: {holding}")
                    else:
                        self.logger.warning(f"예상치 못한 데이터 형식: {holdings}")
                    
                    self.logger.info(f"✅ 전체 보유 종목 {len(all_holdings)}개 조회 완료")
                    return all_holdings
                    
                else:
                    error_msg = data.get('msg1', 'Unknown error')
                    error_code = data.get('msg_cd', 'Unknown')
                    self.logger.error(f"잔고 조회 실패: [{error_code}] {error_msg}")
                    
                    # 전체 응답 로깅 (디버깅용)
                    self.logger.debug(f"전체 응답: {data}")
                    
            else:
                self.logger.error(f"잔고 조회 HTTP 오류: {response.status_code}")
                self.logger.debug(f"응답 내용: {response.text}")
                
        except Exception as e:
            self.logger.error(f"전체 보유 종목 조회 실패: {e}")
            import traceback
            self.logger.error(f"상세 오류:\n{traceback.format_exc()}")
        
        return {}
    
    def get_holdings_alternative(self) -> Dict:
        """대체 방법: 매수가능금액 조회 API로 잔고 확인"""
        try:
            self.logger.info("🔄 대체 방법으로 보유 종목 조회...")
            
            account_data = self.get_account_balance()
            
            if account_data and account_data.get('rt_cd') == '0':
                # output1이 있는지 확인
                if 'output1' in account_data:
                    holdings = account_data['output1']
                    all_holdings = {}
                    
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
                else:
                    self.logger.warning("output1 필드가 없습니다")
            else:
                self.logger.error("매수가능금액 조회도 실패")
        
        except Exception as e:
            self.logger.error(f"대체 방법 실패: {e}")
        
        return {}
    
    def debug_api_responses(self):
        """API 응답 상세 분석"""
        self.logger.info("🔍 API 응답 상세 분석")
        
        # 1. 매수가능금액 조회 API 테스트
        self.logger.info("1️⃣ 매수가능금액 조회 API 테스트")
        try:
            balance_data = self.get_account_balance()
            if balance_data:
                self.logger.info(f"  ✅ 성공: rt_cd={balance_data.get('rt_cd')}")
                self.logger.info(f"  📊 응답 키: {list(balance_data.keys())}")
                
                for key in balance_data.keys():
                    value = balance_data[key]
                    if isinstance(value, list):
                        self.logger.info(f"    {key}: 리스트 ({len(value)}개 항목)")
                    elif isinstance(value, dict):
                        self.logger.info(f"    {key}: 딕셔너리 ({len(value)}개 키)")
                    else:
                        self.logger.info(f"    {key}: {type(value)} - {value}")
            else:
                self.logger.error("  ❌ 실패")
        except Exception as e:
            self.logger.error(f"  ❌ 오류: {e}")
        
        # 2. 잔고조회 API 테스트 (원본)
        self.logger.info("2️⃣ 잔고조회 API 테스트 (원본 파라미터)")
        try:
            original_holdings = self.get_all_holdings()
            if original_holdings:
                self.logger.info(f"  ✅ 성공: {len(original_holdings)}개 종목")
            else:
                self.logger.error("  ❌ 실패 또는 빈 결과")
        except Exception as e:
            self.logger.error(f"  ❌ 오류: {e}")
        
        # 3. 잔고조회 API 테스트 (수정된 버전)
        self.logger.info("3️⃣ 잔고조회 API 테스트 (수정된 파라미터)")
        try:
            fixed_holdings = self.get_all_holdings_backup()
            if fixed_holdings:
                self.logger.info(f"  ✅ 성공: {len(fixed_holdings)}개 종목")
            else:
                self.logger.error("  ❌ 실패 또는 빈 결과")
        except Exception as e:
            self.logger.error(f"  ❌ 오류: {e}")
    
    def debug_all_positions(self):
        """전체 포지션 디버깅 - 수정된 API 사용"""
        self.logger.info("🔍 전체 포지션 상태 디버깅")
        
        # 1. 전체 보유 종목 조회 (수정된 버전 사용)
        all_holdings = self.get_all_holdings()
        
        self.logger.info(f"📊 디버깅 결과:")
        self.logger.info(f"  - API에서 조회된 보유 종목: {len(all_holdings)}개")
        
        if all_holdings:
            self.logger.info("  📋 보유 종목 상세:")
            for symbol, pos in all_holdings.items():
                stock_name = self.get_stock_name(symbol)
                is_trading_target = symbol in self.symbols
                
                self.logger.info(f"    - {symbol}({stock_name}): {pos['quantity']}주 "
                               f"@ {pos['avg_price']:,}원 "
                               f"(손익: {pos['profit_loss']:+.2f}%) "
                               f"{'[거래대상]' if is_trading_target else '[기타]'}")
        else:
            self.logger.warning("  - 보유 종목이 없습니다")
        
        # 2. 메모리 상태 업데이트
        if all_holdings:
            self.all_positions = all_holdings
            
            # 거래 대상 종목만 별도 저장
            self.positions = {}
            for symbol in self.symbols:
                if symbol in all_holdings:
                    self.positions[symbol] = all_holdings[symbol]
            
            self.logger.info(f"  💾 메모리 업데이트:")
            self.logger.info(f"    - self.positions: {len(self.positions)}개 (거래대상)")
            self.logger.info(f"    - self.all_positions: {len(self.all_positions)}개 (전체)")
        
        # 3. 현재 메모리 상태 출력
        self.logger.info(f"  💾 현재 메모리 상태:")
        self.logger.info(f"    - self.positions: {len(getattr(self, 'positions', {}))}")
        self.logger.info(f"    - self.all_positions: {len(getattr(self, 'all_positions', {}))}")
    
    def update_all_positions(self):
        """모든 보유 종목 포지션 업데이트 (수정된 API 사용)"""
        try:
            # 1. 모든 보유 종목 조회 (수정된 버전)
            all_holdings = self.get_all_holdings()
            
            # 2. 기존 positions 업데이트 (거래 대상 종목만)
            old_positions_count = len(getattr(self, 'positions', {}))
            self.positions = {}
            for symbol in self.symbols:
                if symbol in all_holdings:
                    self.positions[symbol] = all_holdings[symbol]
            
            # 3. 전체 보유 종목 저장 (매도 로직용)
            old_all_positions_count = len(getattr(self, 'all_positions', {}))
            self.all_positions = all_holdings
            
            self.logger.info(f"💼 포지션 업데이트 완료:")
            self.logger.info(f"  - 거래 대상 보유: {len(self.positions)}개 (이전: {old_positions_count})")
            self.logger.info(f"  - 전체 보유: {len(self.all_positions)}개 (이전: {old_all_positions_count})")
            
            # 거래 대상이 아닌 보유 종목이 있으면 알림
            non_trading_symbols = set(self.all_positions.keys()) - set(self.symbols)
            if non_trading_symbols:
                self.logger.info(f"📋 거래 대상 외 보유 종목: {list(non_trading_symbols)}")
                
        except Exception as e:
            self.logger.error(f"포지션 업데이트 실패: {e}")
    
    def process_sell_signals(self):
        """매도 신호 처리 - 딕셔너리 변경 오류 수정"""
        self.logger.info("💸 매도 신호 처리 시작")
        
        if not hasattr(self, 'all_positions') or not self.all_positions:
            self.logger.warning("보유 종목이 없습니다")
            return
        
        # 중요: 딕셔너리를 복사하여 반복 중 변경 문제 해결
        positions_to_process = dict(self.all_positions)  # 복사본 생성
        
        for symbol, position in positions_to_process.items():
            try:
                # 현재 시점의 포지션 재확인 (매도 완료된 종목은 건너뛰기)
                if symbol not in self.all_positions:
                    self.logger.debug(f"📤 {symbol} - 이미 매도 완료됨, 건너뛰기")
                    continue
                    
                self.process_sell_for_symbol(symbol, position)
                time.sleep(0.5)  # API 호출 간격
            except Exception as e:
                self.logger.error(f"{symbol} 매도 처리 오류: {e}")
    
    def execute_sell(self, symbol: str, quantity: int, order_strategy: str, reason: str):
        """매도 실행 - 안전한 딕셔너리 업데이트"""
        self.logger.info(f"💸 {symbol} 매도 실행: {quantity}주 ({order_strategy}) - {reason}")
        
        result = self.place_order_with_strategy(symbol, 'SELL', quantity, order_strategy)
        
        if result['success']:
            executed_price = result.get('limit_price', 0)
            
            # 포지션 기록 업데이트
            self.position_manager.record_sale(symbol, quantity, executed_price, reason)
            
            # 메모리에서 포지션 안전하게 제거
            try:
                if symbol in self.positions:
                    del self.positions[symbol]
                    self.logger.debug(f"📤 {symbol} - positions에서 제거")
                
                if symbol in self.all_positions:
                    del self.all_positions[symbol]
                    self.logger.debug(f"📤 {symbol} - all_positions에서 제거")
            except KeyError as e:
                self.logger.warning(f"포지션 제거 중 KeyError: {e}")
            
            self.logger.info(f"✅ {symbol} 매도 완료: {quantity}주 @ {executed_price:,}원 - {reason}")
        else:
            self.logger.error(f"❌ {symbol} 매도 실패: {result.get('error', 'Unknown')}")
    
    def process_sell_for_symbol(self, symbol: str, position: Dict):
        """개별 종목 매도 처리 - 안전한 버전"""
        try:
            # 현재 시점에서 포지션이 여전히 존재하는지 확인
            if symbol not in self.all_positions:
                self.logger.debug(f"📤 {symbol} - 이미 매도된 종목, 건너뛰기")
                return
                
            stock_name = self.get_stock_name(symbol)
            quantity = position['quantity']
            avg_price = position['avg_price']
            current_price = position['current_price']
            profit_loss_pct = position['profit_loss']
            profit_loss_decimal = profit_loss_pct / 100
            
            self.logger.info(f"💎 {symbol}({stock_name}) 매도 분석:")
            self.logger.info(f"  - 보유: {quantity}주 @ {avg_price:,}원")
            self.logger.info(f"  - 현재가: {current_price:,}원")
            self.logger.info(f"  - 손익: {profit_loss_pct:+.2f}%")
            
            # 1순위: 손절 (무조건 실행)
            if profit_loss_decimal <= -self.stop_loss_pct:
                self.logger.warning(f"🛑 {symbol} 손절 조건 충족! ({profit_loss_pct:+.2f}%)")
                self.execute_sell(symbol, quantity, "urgent", "손절매")
                return
            
            # 2순위: 익절 (최소 보유기간 확인)
            if profit_loss_decimal >= self.take_profit_pct:
                can_sell, sell_reason = self.can_sell_symbol(symbol)
                
                if can_sell:
                    self.logger.info(f"🎯 {symbol} 익절 조건 충족! ({profit_loss_pct:+.2f}%)")
                    self.execute_sell(symbol, quantity, "patient_limit", "익절매")
                    return
                else:
                    self.logger.info(f"💎 {symbol} 익절 조건이지만 보유 지속: {sell_reason}")
            
            # 3순위: 매도 신호 확인 (거래 대상 종목만)
            if symbol in self.symbols:
                df = self.get_minute_data(symbol)
                if not df.empty:
                    optimal_strategy = self.strategy_map.get(symbol, 'momentum')
                    signals = self.calculate_signals_by_strategy(symbol, df, optimal_strategy)
                    
                    if signals['signal'] == 'SELL':
                        can_sell, sell_reason = self.can_sell_symbol(symbol)
                        
                        if can_sell:
                            self.logger.info(f"📉 {symbol} 매도 신호 감지 (강도: {signals['strength']:.2f})")
                            order_strategy = self.determine_order_strategy(signals['strength'], 'SELL')
                            self.execute_sell(symbol, quantity, order_strategy, "매도 신호")
                            return
                        else:
                            self.logger.info(f"🚫 {symbol} 매도 신호 있지만 제한: {sell_reason}")
            
            # 4순위: 보유 지속
            self.logger.debug(f"📊 {symbol} 보유 지속")
            
        except Exception as e:
            self.logger.error(f"{symbol} 매도 처리 중 오류: {e}")
            import traceback
            self.logger.error(f"상세 오류:\n{traceback.format_exc()}")
    
    def run_improved(self, interval_minutes: int = 5):
        """안전한 개선된 자동매매 실행"""
        self.logger.info("🚀 안전한 개선된 KIS API 자동매매 시작!")
        self.logger.info(f"🛒 매수 대상 종목: {', '.join(self.symbols)}")
        self.logger.info(f"💸 매도 대상: 모든 보유 종목")
        self.logger.info(f"⏰ 실행 간격: {interval_minutes}분")
    
        # 시작 알림
        if self.discord_webhook:
            strategy_info = []
            for symbol in self.symbols:
                strategy = self.strategy_map.get(symbol, "momentum")
                strategy_info.append(f"{symbol} ({strategy})")
    
            self.send_discord_notification(
                "🚀 안전한 개선된 자동매매 시작",
                f"매수 대상: {', '.join(strategy_info)}\n매도 대상: 모든 보유 종목\n실행 간격: {interval_minutes}분",
                0x00ff00
            )
    
        daily_trades = 0
        successful_trades = 0
        last_daily_summary = datetime.now().date()
    
        try:
            # 토큰 준비
            token = self.get_access_token()
            if token:
                self.logger.info("토큰 준비 완료 ✅")
    
            # 시작 시 전체 포지션 확인
            self.debug_all_positions()
    
            while True:
                current_time = datetime.now()
    
                # 백테스트 업데이트 확인 (1시간마다)
                if not hasattr(self, 'last_backtest_check'):
                    self.last_backtest_check = current_time
                
                if current_time - self.last_backtest_check > timedelta(hours=1):
                    self.check_backtest_update()
                    self.last_backtest_check = current_time
    
                # 일일 요약 알림
                if current_time.date() != last_daily_summary and current_time.hour >= 16:
                    self.notify_daily_summary(daily_trades, self.daily_pnl, successful_trades)
                    daily_trades = 0
                    successful_trades = 0
                    self.daily_pnl = 0
                    last_daily_summary = current_time.date()
    
                # 장 시간 체크 (9:00 ~ 15:30)
                #if 9 <= current_time.hour < 15 or (current_time.hour == 15 and current_time.minute <= 30):
                if self.is_market_open(current_time):
                    self.logger.info(f"📊 안전한 거래 사이클 시작 - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
                    cycle_start_trades = self.trade_count
                    
                    # 안전한 개선된 거래 사이클 실행
                    self.run_trading_cycle_improved()
    
                    # 거래 횟수 추적
                    if self.trade_count > cycle_start_trades:
                        cycle_trades = self.trade_count - cycle_start_trades
                        daily_trades += cycle_trades
                        successful_trades += cycle_trades
    
                    self.logger.info("✅ 안전한 거래 사이클 완료\n")
                else:
                    self.logger.info("장 시간 외 - 대기 중...")
    
                # 다음 실행 시간 로그
                next_run = current_time + timedelta(minutes=interval_minutes)
                self.logger.info(f"다음 실행 예정: {next_run.strftime('%H:%M:%S')}")
                
                # 지정된 간격만큼 대기
                time.sleep(interval_minutes * 60)
    
        except KeyboardInterrupt:
            self.logger.info("사용자가 프로그램을 종료했습니다.")
            if self.discord_webhook:
                self.send_discord_notification("⏹️ 자동매매 종료", "사용자가 프로그램을 종료했습니다.", 0xff6600)
        except Exception as e:
            self.logger.error(f"프로그램 실행 중 오류: {e}")
            import traceback
            self.logger.error(f"상세 오류:\n{traceback.format_exc()}")
            self.notify_error("프로그램 오류", str(e))
        finally:
            self.logger.info("안전한 개선된 자동매매 프로그램 종료")

    def calculate_signals_by_strategy(self, symbol: str, df: pd.DataFrame, strategy: str) -> Dict:
        """전략별 신호 계산"""
        if strategy == 'momentum':
            return self.calculate_enhanced_momentum_signals(df)
        elif strategy == 'mean_reversion':
            return self.calculate_mean_reversion_signals(df)
        elif strategy == 'breakout':
            return self.calculate_breakout_signals(df)
        elif strategy == 'scalping':
            return self.calculate_scalping_signals(df)
        elif ' + ' in strategy:
            return self.calculate_combined_signals(df, strategy)
        else:
            return self.calculate_momentum_signals(df)
    
    def run_debug_improved(self, interval_minutes: int = 1):
        """개선된 디버그 모드"""
        self.logger.info("🐛 개선된 디버그 모드로 실행 중...")
        self.logger.info(f"🛒 매수 대상: {', '.join(self.symbols)}")
        self.logger.info(f"💸 매도 대상: 모든 보유 종목")
        self.logger.info(f"⏰ 실행 간격: {interval_minutes}분")
        
        try:
            token = self.get_access_token()
            if token:
                self.logger.info("토큰 준비 완료 ✅")
            
            # 초기 상태 체크
            self.debug_all_positions()
            
            while True:
                current_time = datetime.now()
                self.logger.info(f"\n{'='*60}")
                self.logger.info(f"개선된 디버그 사이클 - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                self.logger.info(f"{'='*60}")
                
                # 장시간 체크 없이 바로 실행
                self.run_trading_cycle_improved()
                
                # 대기
                self.logger.info(f"다음 실행: {interval_minutes}분 후")
                time.sleep(interval_minutes * 60)
            
        except KeyboardInterrupt:
            self.logger.info("개선된 디버그 모드 종료")
        except Exception as e:
            self.logger.error(f"개선된 디버그 중 오류: {e}")
    
    # config.yaml에 추가할 설정
    def create_improved_config(self, config_path: str):
        """개선된 설정 파일 생성"""
        sample_config = {
            'kis': {
                'app_key': 'YOUR_APP_KEY',
                'app_secret': 'YOUR_APP_SECRET',
                'base_url': 'https://openapi.koreainvestment.com:9443',
                'account_no': 'YOUR_ACCOUNT_NO'
            },
            'trading': {
                'max_symbols': 5,
                'max_position_ratio': 0.1,
                'daily_loss_limit': 0.02,
                'stop_loss_pct': 0.05,
                'take_profit_pct': 0.15,
                
                # 매수/매도 분리 설정
                'use_improved_logic': True,        # 개선된 로직 사용
                'sell_all_holdings': True,         # 모든 보유 종목 매도 대상
                'buy_only_backtest_symbols': True, # 백테스트 종목만 매수
                
                # 주문 전략 설정
                'order_strategy': 'adaptive',
                'price_offset_pct': 0.003,
                'order_timeout_minutes': 5,
                'partial_fill_allowed': True
            },
            'position_management': {
                'max_purchases_per_symbol': 3,
                'max_quantity_per_symbol': 100,
                'min_holding_period_hours': 24,
                'purchase_cooldown_hours': 6,
                
                # 매도 우선순위 설정
                'stop_loss_priority': 1,     # 손절 최우선
                'take_profit_priority': 2,   # 익절 2순위
                'sell_signal_priority': 3,   # 매도신호 3순위
                'ignore_holding_period_for_stop_loss': True  # 손절시 보유기간 무시
            },
            'momentum': {
                'period': 20,
                'threshold': 0.02,
                'volume_threshold': 1.5,
                'ma_short': 5,
                'ma_long': 20
            },
            'backtest': {
                'results_file': 'backtest_results.json',
                'min_return_threshold': 5.0,
                'performance_tracking': True
            },
            'notification': {
                'discord_webhook': '',
                'notify_on_trade': True,
                'notify_on_error': True,
                'notify_on_daily_summary': True,
                'notify_on_position_update': True  # 포지션 업데이트 알림
            }
        }
    
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(sample_config, f, default_flow_style=False, allow_unicode=True)
    
    def adjust_to_price_unit(self, price: float) -> int:
        """한국 주식 호가단위에 맞게 가격 조정"""
        
        if price <= 0:
            return 1
        
        # 한국 주식 호가단위 규칙
        if price < 1000:
            # 1,000원 미만: 1원 단위
            return int(price)
        elif price < 5000:
            # 1,000원 이상 5,000원 미만: 5원 단위
            return int(price // 5) * 5
        elif price < 10000:
            # 5,000원 이상 10,000원 미만: 10원 단위
            return int(price // 10) * 10
        elif price < 50000:
            # 10,000원 이상 50,000원 미만: 50원 단위
            return int(price // 50) * 50
        elif price < 100000:
            # 50,000원 이상 100,000원 미만: 100원 단위
            return int(price // 100) * 100
        elif price < 500000:
            # 100,000원 이상 500,000원 미만: 500원 단위
            return int(price // 500) * 500
        else:
            # 500,000원 이상: 1,000원 단위
            return int(price // 1000) * 1000

    
    def get_current_price_enhanced(self, symbol: str) -> Dict:
        """향상된 현재가 조회 - 여러 방법 시도"""
        
        # 방법 1: 기본 현재가 조회 API
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST01010100"
            }
            params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol}
    
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('rt_cd') == '0' and data.get('output'):
                    output = data['output']
                    
                    current_price = float(output.get('stck_prpr', 0))
                    if current_price > 0:
                        result = {
                            'current_price': current_price,
                            'high_price': float(output.get('stck_hgpr', 0)),
                            'low_price': float(output.get('stck_lwpr', 0)),
                            'open_price': float(output.get('stck_oprc', 0)),
                            'prev_close': float(output.get('stck_sdpr', 0)),
                            'upper_limit': float(output.get('stck_mxpr', 0)),  # 상한가
                            'lower_limit': float(output.get('stck_llam', 0)),  # 하한가
                            'stock_name': output.get('hts_kor_isnm', symbol)
                        }
                        
                        self.logger.info(f"📊 {symbol} 현재가 조회 성공: {current_price:,}원 "
                                       f"(상한가: {result['upper_limit']:,}원, "
                                       f"하한가: {result['lower_limit']:,}원)")
                        
                        return result
                    else:
                        self.logger.warning(f"{symbol} 현재가가 0원입니다")
                else:
                    error_msg = data.get('msg1', 'Unknown error')
                    self.logger.warning(f"{symbol} 현재가 조회 오류: {error_msg}")
            else:
                self.logger.warning(f"{symbol} 현재가 조회 HTTP 오류: {response.status_code}")
                
        except Exception as e:
            self.logger.error(f"{symbol} 현재가 조회 실패: {e}")
        
        # 방법 2: 보유 종목에서 현재가 정보 가져오기
        try:
            if hasattr(self, 'all_positions') and symbol in self.all_positions:
                position = self.all_positions[symbol]
                current_price = position.get('current_price', 0)
                
                if current_price > 0:
                    self.logger.info(f"📈 {symbol} 포지션에서 현재가 사용: {current_price:,}원")
                    return {
                        'current_price': current_price,
                        'high_price': 0,
                        'low_price': 0,
                        'open_price': 0,
                        'prev_close': 0,
                        'upper_limit': current_price * 1.3,  # 추정 상한가 (30% 상승)
                        'lower_limit': current_price * 0.7,  # 추정 하한가 (30% 하락)
                        'stock_name': position.get('stock_name', symbol)
                    }
        except Exception as e:
            self.logger.debug(f"포지션에서 현재가 가져오기 실패: {e}")
        
        # 방법 3: 분봉 데이터에서 현재가 가져오기
        try:
            df = self.get_minute_data(symbol, minutes=5)
            if not df.empty:
                current_price = float(df['stck_prpr'].iloc[-1])
                if current_price > 0:
                    self.logger.info(f"📊 {symbol} 분봉에서 현재가 사용: {current_price:,}원")
                    return {
                        'current_price': current_price,
                        'high_price': float(df['stck_hgpr'].iloc[-1]),
                        'low_price': float(df['stck_lwpr'].iloc[-1]),
                        'open_price': float(df['stck_oprc'].iloc[-1]),
                        'prev_close': 0,
                        'upper_limit': current_price * 1.3,
                        'lower_limit': current_price * 0.7,
                        'stock_name': symbol
                    }
        except Exception as e:
            self.logger.debug(f"분봉에서 현재가 가져오기 실패: {e}")
        
        self.logger.error(f"❌ {symbol} 모든 방법으로 현재가 조회 실패")
        return {}
    
    def calculate_safe_limit_price(self, symbol: str, side: str, urgency: str = "normal") -> int:
        """안전한 지정가 계산 - 상한가/하한가 체크"""
        
        # 1. 향상된 현재가 조회
        price_info = self.get_current_price_enhanced(symbol)
        
        if not price_info or price_info.get('current_price', 0) <= 0:
            raise Exception(f"{symbol} 현재가 정보를 가져올 수 없습니다")
        
        current_price = price_info['current_price']
        upper_limit = price_info.get('upper_limit', current_price * 1.3)
        lower_limit = price_info.get('lower_limit', current_price * 0.7)
        
        self.logger.info(f"📊 {symbol} 가격 정보:")
        self.logger.info(f"  - 현재가: {current_price:,}원")
        self.logger.info(f"  - 상한가: {upper_limit:,}원")
        self.logger.info(f"  - 하한가: {lower_limit:,}원")
        
        # 2. 호가 정보 조회 (선택적)
        bid_ask = self.get_current_bid_ask(symbol)
        
        # 3. 기본 지정가 계산
        if side == "BUY":
            if urgency == "urgent":
                # 긴급 매수: 현재가 + 1~2%
                raw_price = current_price * 1.02
            elif urgency == "aggressive":
                # 적극적 매수: 현재가 + 0.5~1%
                raw_price = current_price * 1.005
            else:  # normal
                # 일반 매수: 현재가 + 0.1~0.3%
                raw_price = current_price * 1.002
            
            # 상한가 체크
            if raw_price > upper_limit:
                raw_price = upper_limit - self.get_min_price_unit(upper_limit)
                self.logger.warning(f"⚠️ 매수가가 상한가 근처로 조정됨: {raw_price:,}원")
        
        else:  # SELL
            if urgency == "urgent":
                # 긴급 매도: 현재가 - 1~2%
                raw_price = current_price * 0.98
            elif urgency == "aggressive":
                # 적극적 매도: 현재가 - 0.5~1%
                raw_price = current_price * 0.995
            else:  # normal
                # 일반 매도: 현재가 - 0.1~0.3%
                raw_price = current_price * 0.998
            
            # 하한가 체크
            if raw_price < lower_limit:
                raw_price = lower_limit + self.get_min_price_unit(lower_limit)
                self.logger.warning(f"⚠️ 매도가가 하한가 근처로 조정됨: {raw_price:,}원")
        
        # 4. 호가단위 적용
        limit_price = self.adjust_to_price_unit(raw_price)
        
        # 5. 최종 안전성 체크
        if side == "BUY" and limit_price >= upper_limit:
            limit_price = upper_limit - self.get_min_price_unit(upper_limit)
            self.logger.warning(f"🚨 매수가 상한가 조정: {limit_price:,}원")
        elif side == "SELL" and limit_price <= lower_limit:
            limit_price = lower_limit + self.get_min_price_unit(lower_limit)
            self.logger.warning(f"🚨 매도가 하한가 조정: {limit_price:,}원")
        
        # 최소 1원 이상
        limit_price = max(limit_price, 1)
        
        self.logger.info(f"💰 {symbol} {side} 안전 지정가: {limit_price:,}원 "
                        f"(현재가 대비 {((limit_price/current_price-1)*100):+.2f}%)")
        
        return limit_price
    
    def place_safe_limit_order(self, symbol: str, side: str, quantity: int, urgency: str = "normal") -> Dict:
        """안전한 지정가 주문 실행"""
        try:
            # 안전한 지정가 계산
            limit_price = self.calculate_safe_limit_price(symbol, side, urgency)
            
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
            
            # 실전/모의 자동 감지
            is_mock = "vts" in self.base_url.lower()
            
            if is_mock:
                tr_id = "VTTC0802U" if side == "BUY" else "VTTC0801U"
            else:
                tr_id = "TTTC0802U" if side == "BUY" else "TTTC0801U"
            
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
                "ORD_DVSN": "00",  # 지정가
                "ORD_QTY": str(quantity),
                "ORD_UNPR": str(limit_price)
            }
            
            self.logger.info(f"📊 안전 지정가 주문: {symbol} {side} {quantity}주 @ {limit_price:,}원")
            
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
            result = response.json()
            
            if result.get('rt_cd') == '0':
                order_no = result.get('output', {}).get('odno', 'Unknown')
                self.logger.info(f"✅ 안전 지정가 주문 성공: {symbol} {side} {quantity}주 @ {limit_price:,}원")
                self.trade_count += 1
                
                # 알림 전송
                self.notify_limit_order_success(side, symbol, quantity, limit_price, order_no, urgency)
                
                return {
                    'success': True, 
                    'order_no': order_no, 
                    'limit_price': limit_price,
                    'urgency': urgency
                }
            else:
                error_msg = result.get('msg1', 'Unknown error')
                error_code = result.get('msg_cd', 'Unknown')
                self.logger.error(f"안전 지정가 주문 실패: [{error_code}] {error_msg}")
                
                # 하한가/상한가 오류면 시장가로 재시도
                if "하한가" in error_msg or "상한가" in error_msg:
                    self.logger.warning(f"🔄 {symbol} 가격 제한 오류로 시장가 재시도")
                    return self.place_order(symbol, side, quantity, price=0)
                
                self.notify_trade_failure(side, symbol, error_msg)
                return {'success': False, 'error': error_msg}
        
        except Exception as e:
            self.logger.error(f"안전 지정가 주문 실행 실패 ({symbol} {side}): {e}")
            
            # 현재가 조회 실패시 시장가로 재시도
            if "현재가" in str(e):
                self.logger.warning(f"🔄 {symbol} 현재가 조회 실패로 시장가 재시도")
                return self.place_order(symbol, side, quantity, price=0)
            
            self.notify_trade_failure(side, symbol, str(e))
            return {'success': False, 'error': str(e)}
    
    def place_order_with_strategy(self, symbol: str, side: str, quantity: int, strategy: str = "limit") -> Dict:
        """최종 안전한 주문 실행"""
        
        if strategy == "market":
            # 시장가 주문
            return self.place_order(symbol, side, quantity, price=0)
        
        elif strategy in ["limit", "aggressive_limit", "patient_limit", "urgent"]:
            # 안전한 지정가 주문
            urgency_map = {
                "limit": "normal",
                "aggressive_limit": "aggressive", 
                "patient_limit": "normal",
                "urgent": "urgent"
            }
            urgency = urgency_map.get(strategy, "normal")
            
            return self.place_safe_limit_order(symbol, side, quantity, urgency)
        
        elif strategy == "adaptive":
            # 적응형 주문
            return self.place_adaptive_order(symbol, side, quantity)
        
        else:
            self.logger.warning(f"알 수 없는 주문 전략: {strategy}, 시장가 사용")
            return self.place_order(symbol, side, quantity, price=0)
    
    def place_adaptive_order(self, symbol: str, side: str, quantity: int) -> Dict:
        """안전한 적응형 주문"""
        
        # 현재가 정보 확인
        price_info = self.get_current_price_enhanced(symbol)
        
        if not price_info or price_info.get('current_price', 0) <= 0:
            self.logger.warning(f"🤖 {symbol} 현재가 조회 실패 → 시장가 사용")
            return self.place_order(symbol, side, quantity, price=0)
        
        current_price = price_info['current_price']
        
        # 호가 정보 확인
        bid_ask = self.get_current_bid_ask(symbol)
        
        if bid_ask and bid_ask.get('current_price', 0) > 0:
            # 호가 정보가 있으면 지정가 사용
            return self.place_safe_limit_order(symbol, side, quantity, "normal")
        else:
            # 호가 정보가 없으면 시장가 사용
            self.logger.info(f"🤖 {symbol} 호가 정보 없음 → 시장가 사용")
            return self.place_order(symbol, side, quantity, price=0)
    
    # 디버깅 함수
    def debug_price_info(self, symbol: str):
        """가격 정보 디버깅"""
        self.logger.info(f"🔍 {symbol} 가격 정보 디버깅")
        
        # 1. 현재가 조회
        price_info = self.get_current_price_enhanced(symbol)
        self.logger.info(f"  현재가 조회: {price_info}")
        
        # 2. 호가 조회
        bid_ask = self.get_current_bid_ask(symbol)
        self.logger.info(f"  호가 조회: {bid_ask}")
        
        # 3. 안전 지정가 계산
        try:
            for side in ["BUY", "SELL"]:
                for urgency in ["normal", "aggressive", "urgent"]:
                    safe_price = self.calculate_safe_limit_price(symbol, side, urgency)
                    self.logger.info(f"  {side} ({urgency}): {safe_price:,}원")
        except Exception as e:
            self.logger.error(f"  안전 지정가 계산 실패: {e}")

    def is_market_open(self, current_time=None):
        """한국 증시 개장 시간 확인 - 정확한 시간 적용"""
        if current_time is None:
            current_time = datetime.now()
        
        # 주말 체크
        weekday = current_time.weekday()  # 0=월요일, 6=일요일
        if weekday >= 5:  # 토요일(5), 일요일(6)
            self.logger.debug(f"주말입니다 ({['월','화','수','목','금','토','일'][weekday]})")
            return False
        
        # 한국 증시 시간: 09:00 ~ 15:30
        hour = current_time.hour
        minute = current_time.minute
        
        # 09:00 이전
        if hour < 9:
            self.logger.debug(f"장 시작 전: {hour:02d}:{minute:02d} (09:00 개장)")
            return False
        
        # 15:30 이후
        if hour > 15 or (hour == 15 and minute > 30):
            self.logger.debug(f"장 마감 후: {hour:02d}:{minute:02d} (15:30 마감)")
            return False
        
        # 09:00 ~ 15:30 사이
        self.logger.debug(f"장 시간 중: {hour:02d}:{minute:02d}")
        return True
    
    def get_next_market_open_time(self, current_time=None):
        """다음 장 개장 시간 계산"""
        if current_time is None:
            current_time = datetime.now()
        
        # 오늘 09:00
        today_open = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
        
        # 현재 시간이 오늘 장 시간 이전이면 오늘 09:00
        if current_time < today_open and current_time.weekday() < 5:
            return today_open
        
        # 그렇지 않으면 다음 영업일 09:00
        next_day = current_time + timedelta(days=1)
        while next_day.weekday() >= 5:  # 주말 건너뛰기
            next_day += timedelta(days=1)
        
        return next_day.replace(hour=9, minute=0, second=0, microsecond=0)
    
    def get_market_status_info(self, current_time=None):
        """장 상태 정보 반환"""
        if current_time is None:
            current_time = datetime.now()
        
        is_open = self.is_market_open(current_time)
        
        if is_open:
            # 장 중 - 마감까지 남은 시간
            today_close = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
            time_to_close = today_close - current_time
            
            return {
                'status': 'OPEN',
                'message': f'장 시간 중 (마감까지 {str(time_to_close).split(".")[0]})',
                'next_change': today_close,
                'is_trading_time': True
            }
        else:
            # 장 외 - 개장까지 남은 시간
            next_open = self.get_next_market_open_time(current_time)
            time_to_open = next_open - current_time
            
            # 주말인지 확인
            if current_time.weekday() >= 5:
                weekday_name = ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일'][next_open.weekday()]
                message = f'주말 휴장 ({weekday_name} 09:00 개장)'
            else:
                if current_time.hour < 9:
                    message = f'장 시작 전 (개장까지 {str(time_to_open).split(".")[0]})'
                else:
                    message = f'장 마감 후 (내일 09:00 개장)'
            
            return {
                'status': 'CLOSED',
                'message': message,
                'next_change': next_open,
                'is_trading_time': False
            }
    
    def run_improved_with_correct_hours(self, interval_minutes: int = 5):
        """정확한 장 시간을 적용한 개선된 자동매매"""
        self.logger.info("🚀 정확한 장시간 적용 자동매매 시작!")
        self.logger.info("📊 한국 증시 시간: 평일 09:00 ~ 15:30")
        
        daily_trades = 0
        successful_trades = 0
        last_daily_summary = datetime.now().date()
    
        try:
            # 토큰 준비
            token = self.get_access_token()
            if token:
                self.logger.info("토큰 준비 완료 ✅")
    
            # 시작 시 장 상태 확인
            self.initialize_manual_positions()
            current_time = datetime.now()
            market_info = self.get_market_status_info(current_time)
            self.logger.info(f"📈 현재 장 상태: {market_info['message']}")
    
            while True:
                current_time = datetime.now()
                market_info = self.get_market_status_info(current_time)
    
                # 장 시간 중일 때만 거래
                if market_info['is_trading_time']:
                    self.logger.info(f"📊 거래 사이클 시작 - {current_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    self.logger.info(f"📈 {market_info['message']}")
    
                    cycle_start_trades = self.trade_count
                    
                    # 거래 사이클 실행
                    self.run_trading_cycle_improved()
    
                    # 거래 횟수 추적
                    if self.trade_count > cycle_start_trades:
                        cycle_trades = self.trade_count - cycle_start_trades
                        daily_trades += cycle_trades
                        successful_trades += cycle_trades
    
                    #self.logger.info("✅ 거래 사이클 완료")
                else:
                    # 장 외 시간
                    self.logger.info(f"⏰ {market_info['message']}")
                    
                    # 주말이나 장 시간 외일 때는 더 긴 간격으로 체크
                    if current_time.weekday() >= 5:  # 주말
                        sleep_minutes = 60  # 1시간마다 체크
                    elif current_time.hour < 8:  # 새벽
                        sleep_minutes = 30  # 30분마다 체크
                    else:  # 장 마감 후
                        sleep_minutes = 10  # 10분마다 체크
    
                # 일일 요약 (장 마감 후)
                if (current_time.date() != last_daily_summary and 
                    current_time.hour >= 16 and 
                    not market_info['is_trading_time']):
                    
                    self.notify_daily_summary(daily_trades, self.daily_pnl, successful_trades)
                    daily_trades = 0
                    successful_trades = 0
                    self.daily_pnl = 0
                    last_daily_summary = current_time.date()
    
                # 다음 실행 시간 계산
                if market_info['is_trading_time']:
                    sleep_time = interval_minutes * 60
                    next_run = current_time + timedelta(minutes=interval_minutes)
                    self.logger.info(f"다음 거래 체크: {next_run.strftime('%H:%M:%S')}")
                else:
                    sleep_time = sleep_minutes * 60
                    next_run = current_time + timedelta(minutes=sleep_minutes)
                    self.logger.info(f"다음 장 상태 체크: {next_run.strftime('%H:%M:%S')}")
                
                # 대기
                time.sleep(sleep_time)
    
        except KeyboardInterrupt:
            self.logger.info("사용자가 프로그램을 종료했습니다.")
        except Exception as e:
            self.logger.error(f"프로그램 실행 중 오류: {e}")
            import traceback
            self.logger.error(f"상세 오류:\n{traceback.format_exc()}")
        finally:
            self.logger.info("자동매매 프로그램 종료")
    
    def debug_market_hours():
        """장 시간 디버깅"""
        trader = KISAutoTrader()
        
        print("🕐 한국 증시 시간 테스트")
        print("="*50)
        
        current_time = datetime.now()
        print(f"현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S (%A)')}")
        
        # 장 상태 확인
        market_info = trader.get_market_status_info(current_time)
        print(f"장 상태: {market_info['status']}")
        print(f"상태 메시지: {market_info['message']}")
        print(f"다음 변경: {market_info['next_change'].strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"거래 가능: {'예' if market_info['is_trading_time'] else '아니오'}")
        
        print(f"\n📊 시간별 테스트:")
        test_times = [
            datetime.now().replace(hour=8, minute=30),   # 장 시작 전
            datetime.now().replace(hour=9, minute=0),    # 장 시작
            datetime.now().replace(hour=12, minute=0),   # 장 중
            datetime.now().replace(hour=15, minute=30),  # 장 마감
            datetime.now().replace(hour=16, minute=0),   # 장 마감 후
        ]
        
        for test_time in test_times:
            is_open = trader.is_market_open(test_time)
            status = "거래 가능" if is_open else "거래 불가"
            print(f"  {test_time.strftime('%H:%M')}: {status}")


    def create_robust_session(self):
        """견고한 HTTP 세션 생성"""
        session = requests.Session()
        
        # 재시도 전략 설정
        retry_strategy = Retry(
            total=3,  # 총 재시도 횟수
            backoff_factor=1,  # 재시도 간격 (1초씩 증가)
            status_forcelist=[429, 500, 502, 503, 504],  # 재시도할 HTTP 상태 코드
            allowed_methods=["HEAD", "GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def rate_limit_api_call(self):
        """API 호출 속도 제한"""
        if self.last_api_call:
            elapsed = time.time() - self.last_api_call
            if elapsed < self.min_api_interval:
                time.sleep(self.min_api_interval - elapsed)
        
        self.last_api_call = time.time()
    
    def safe_api_request(self, method, url, **kwargs):
        """안전한 API 요청 - 타임아웃 및 재시도 처리"""
        self.rate_limit_api_call()
        
        # 기본 타임아웃 설정
        kwargs.setdefault('timeout', self.api_timeout)
        
        for attempt in range(self.api_retry_count + 1):
            try:
                if attempt > 0:
                    delay = self.api_retry_delay * (2 ** (attempt - 1))  # 지수 백오프
                    self.logger.info(f"API 재시도 {attempt}/{self.api_retry_count} (대기: {delay}초)")
                    time.sleep(delay)
                
                if method.upper() == 'GET':
                    response = self.session.get(url, **kwargs)
                elif method.upper() == 'POST':
                    response = self.session.post(url, **kwargs)
                else:
                    response = self.session.request(method, url, **kwargs)
                
                response.raise_for_status()
                return response
                
            except requests.exceptions.Timeout as e:
                self.fallback_timeout_count += 1
                if attempt < self.api_retry_count:
                    self.logger.warning(f"API 타임아웃 {attempt + 1}/{self.api_retry_count + 1}: {url}")
                    continue
                else:
                    self.logger.error(f"API 최종 타임아웃: {url}")
                    
                    # 타임아웃이 너무 많이 발생하면 대체 모드 활성화
                    if self.fallback_timeout_count >= self.max_fallback_timeouts:
                        self.fallback_mode = True
                        self.logger.warning("🚨 대체 모드 활성화: API 타임아웃이 너무 빈번함")
                    
                    raise
            
            except requests.exceptions.RequestException as e:
                if attempt < self.api_retry_count:
                    self.logger.warning(f"API 요청 오류 (재시도 예정): {e}")
                    continue
                else:
                    self.logger.error(f"API 최종 실패: {e}")
                    raise
        
        return None
    
    def get_current_price_with_fallback(self, symbol: str) -> Dict:
        """대체 로직이 포함된 현재가 조회"""
        
        # 대체 모드에서는 간소화된 방법만 사용
        if self.fallback_mode:
            return self.get_current_price_fallback(symbol)
        
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST01010100"
            }
            params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol}
            
            response = self.safe_api_request('GET', url, headers=headers, params=params)
            
            if response and response.status_code == 200:
                data = response.json()
                if data.get('rt_cd') == '0' and data.get('output'):
                    output = data['output']
                    current_price = float(output.get('stck_prpr', 0))
                    
                    if current_price > 0:
                        return {
                            'current_price': current_price,
                            'high_price': float(output.get('stck_hgpr', 0)),
                            'low_price': float(output.get('stck_lwpr', 0)),
                            'open_price': float(output.get('stck_oprc', 0)),
                            'stock_name': output.get('hts_kor_isnm', symbol)
                        }
                        
        except Exception as e:
            self.logger.error(f"{symbol} 현재가 조회 실패: {e}")
        
        # API 실패 시 대체 방법 사용
        return self.get_current_price_fallback(symbol)
    
    def get_current_price_fallback(self, symbol: str) -> Dict:
        """현재가 조회 대체 방법"""
        
        # 1. 포지션에서 가져오기
        if hasattr(self, 'all_positions') and symbol in self.all_positions:
            position = self.all_positions[symbol]
            current_price = position.get('current_price', 0)
            if current_price > 0:
                self.logger.info(f"📈 {symbol} 포지션에서 현재가 사용: {current_price:,}원")
                return {
                    'current_price': current_price,
                    'high_price': 0,
                    'low_price': 0,
                    'open_price': 0,
                    'stock_name': position.get('stock_name', symbol)
                }
        
        # 2. 마지막 알려진 가격 사용 (캐시)
        if hasattr(self, 'last_known_prices') and symbol in self.last_known_prices:
            cached_price = self.last_known_prices[symbol]
            self.logger.info(f"💾 {symbol} 캐시된 가격 사용: {cached_price:,}원")
            return {
                'current_price': cached_price,
                'high_price': 0,
                'low_price': 0,
                'open_price': 0,
                'stock_name': self.get_stock_name(symbol)
            }
        
        # 3. 기본값 반환 (거래 중단)
        self.logger.warning(f"❌ {symbol} 현재가를 알 수 없어 거래 중단")
        return {}
    
    def update_all_positions_with_retry(self):
        """재시도 로직이 포함된 포지션 업데이트"""
        
        if self.fallback_mode:
            self.logger.info("🔄 대체 모드: 포지션 업데이트 건너뛰기")
            return
        
        try:
            self.logger.info("📋 전체 보유 종목 조회 중...")
            
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
            
            response = self.safe_api_request('GET', url, headers=headers, params=params)
            
            if response and response.status_code == 200:
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
                    
                    # 메모리 업데이트
                    self.all_positions = all_holdings
                    self.positions = {k: v for k, v in all_holdings.items() if k in self.symbols}
                    
                    self.logger.info(f"✅ 포지션 업데이트: 전체 {len(all_holdings)}개, 거래대상 {len(self.positions)}개")
                    return
                    
        except Exception as e:
            self.logger.error(f"포지션 업데이트 실패: {e}")
            
            # 타임아웃 오류가 계속 발생하면 대체 모드 활성화
            if "timeout" in str(e).lower():
                self.fallback_timeout_count += 1
                if self.fallback_timeout_count >= self.max_fallback_timeouts:
                    self.fallback_mode = True
                    self.logger.warning("🚨 포지션 조회 타임아웃으로 대체 모드 활성화")
    
    def get_stock_name_fast(self, symbol: str) -> str:
        """빠른 종목명 조회 - 타임아웃 시 캐시/하드코딩만 사용"""
        
        # 1. 메모리 캐시 확인
        if symbol in self.stock_names and self.stock_names[symbol]:
            return self.stock_names[symbol]
        
        # 2. 하드코딩된 사전 확인
        hardcoded_stocks = {
            '005930': '삼성전자',
            '035720': '카카오', 
            '000660': 'SK하이닉스',
            '042660': '한화오션',
            '062040': '산일전기',
            '272210': '한화시스템',
            '161580': '필옵틱스',
            '281820': '케이씨텍',
            '014620': '성광밴드',
            '278470': '에이피알'
        }
        
        if symbol in hardcoded_stocks:
            name = hardcoded_stocks[symbol]
            self.stock_names[symbol] = name
            self.save_stock_names()
            return name
        
        # 3. 대체 모드이거나 타임아웃이 많으면 API 호출 건너뛰기
        if self.fallback_mode or self.fallback_timeout_count >= 3:
            self.logger.debug(f"⚠️ {symbol} API 호출 건너뛰기 (대체 모드)")
            self.stock_names[symbol] = symbol
            return symbol
        
        # 4. API 호출 (짧은 타임아웃)
        try:
            name = self.fetch_stock_name_with_short_timeout(symbol)
            if name and name != symbol:
                self.stock_names[symbol] = name
                self.save_stock_names()
                return name
        except Exception as e:
            self.logger.debug(f"종목명 API 실패: {symbol} - {e}")
        
        # 5. 실패 시 종목코드 반환
        self.stock_names[symbol] = symbol
        return symbol
    
    def fetch_stock_name_with_short_timeout(self, symbol: str) -> str:
        """짧은 타임아웃으로 종목명 조회"""
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST01010100"
            }
            params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol}
            
            # 짧은 타임아웃 (5초)
            response = self.session.get(url, headers=headers, params=params, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('rt_cd') == '0' and data.get('output'):
                    output = data['output']
                    name_fields = ['hts_kor_isnm', 'prdt_abrv_name', 'stck_shnm']
                    
                    for field in name_fields:
                        stock_name = output.get(field, '').strip()
                        if stock_name and stock_name != symbol:
                            return stock_name
            
        except Exception as e:
            # 타임아웃은 조용히 처리
            pass
        
        return symbol
    
    def run_trading_cycle_robust(self):
        """견고한 거래 사이클 - 타임아웃 내성"""
        
        # 대체 모드에서는 제한된 기능만 실행
        if self.fallback_mode:
            self.logger.info("🔄 대체 모드: 제한된 거래 사이클 실행")
            self.run_limited_trading_cycle()
            return
        
        if not self.check_risk_management():
            self.logger.warning("리스크 관리 조건 위반 - 거래 중단")
            return
        
        self.logger.info("🔄 견고한 거래 사이클 시작")
        
        try:
            # 1. 포지션 업데이트 (타임아웃 내성)
            self.update_all_positions_with_retry()
            
            # 2. 매도/매수 처리 (간격 두기)
            if hasattr(self, 'all_positions') and self.all_positions:
                self.process_sell_signals_robust()
                time.sleep(1)  # API 호출 간격
            
            self.process_buy_signals_robust()
            
            # 3. 성과 데이터 저장
            self.save_performance_data()
            
            self.logger.info("✅ 견고한 거래 사이클 완료")
            
        except Exception as e:
            self.logger.error(f"거래 사이클 실행 중 오류: {e}")
            
            # 타임아웃 오류가 지속되면 대체 모드로 전환
            if "timeout" in str(e).lower():
                self.fallback_timeout_count += 1
                if self.fallback_timeout_count >= self.max_fallback_timeouts:
                    self.fallback_mode = True
                    self.logger.warning("🚨 거래 사이클 타임아웃으로 대체 모드 활성화")
    
    def run_limited_trading_cycle(self):
        """제한된 거래 사이클 - 대체 모드용"""
        self.logger.info("🔄 제한된 거래 사이클: 최소한의 API 호출만 사용")
        
        # 기존 포지션 정보로만 작업
        if hasattr(self, 'all_positions') and self.all_positions:
            # 간단한 손절/익절만 처리
            self.process_emergency_sells_only()
        
        # 일정 시간 후 대체 모드 해제 시도
        self.try_exit_fallback_mode()
    
    def try_exit_fallback_mode(self):
        """대체 모드 해제 시도"""
        if not hasattr(self, 'fallback_start_time'):
            self.fallback_start_time = datetime.now()
        
        # 10분 후 대체 모드 해제 시도
        if datetime.now() - self.fallback_start_time > timedelta(minutes=10):
            self.logger.info("🔄 대체 모드 해제 시도...")
            try:
                # 간단한 API 호출로 연결 테스트
                token = self.get_access_token()
                if token:
                    self.fallback_mode = False
                    self.fallback_timeout_count = 0
                    self.fallback_start_time = None
                    self.logger.info("✅ 대체 모드 해제 성공")
            except Exception as e:
                self.logger.warning(f"대체 모드 해제 실패: {e}")
                self.fallback_start_time = datetime.now()  # 다시 10분 대기

    def process_buy_for_symbol(self, symbol: str):
        """개선된 개별 종목 매수 처리"""
        stock_name = self.get_stock_name(symbol)
        
        # 현재 보유 여부 확인
        current_position = self.positions.get(symbol, {})
        has_position = current_position.get('quantity', 0) > 0
        
        self.logger.debug(f"🔍 {symbol}({stock_name}) 매수 분석 시작")
        
        # 매수 가능 여부 확인 (보유 중이어도 추가 매수 가능한지 체크)
        can_buy, buy_reason = self.can_purchase_symbol(symbol)
        
        if not can_buy:
            self.logger.info(f"🚫 {symbol} - {buy_reason}")
            return
        
        if has_position:
            self.logger.info(f"📌 {symbol} - 이미 보유 중이지만 추가 매수 검토")
        
        # 분봉 데이터 조회
        df = self.get_minute_data(symbol)
        if df.empty:
            self.logger.warning(f"{symbol}({stock_name}) - 데이터 없음")
            return
        
        # 전략에 따른 신호 계산
        optimal_strategy = self.strategy_map.get(symbol, 'momentum')
        signals = self.calculate_signals_by_strategy(symbol, df, optimal_strategy)
        
        current_price = signals['current_price']
        
        self.logger.info(f"📊 {symbol}({stock_name}) 매수 분석 결과:")
        self.logger.info(f"  - 전략: {optimal_strategy}")
        self.logger.info(f"  - 신호: {signals['signal']}")
        self.logger.info(f"  - 강도: {signals['strength']:.2f}")
        self.logger.info(f"  - 현재가: {current_price:,}원")
        self.logger.info(f"  - 보유 여부: {'예' if has_position else '아니오'}")
        
        # 매수 신호 처리
        if signals['signal'] == 'BUY':
            quantity = self.calculate_position_size(symbol, current_price, signals['strength'])
            
            if quantity > 0:
                order_strategy = self.determine_order_strategy(signals['strength'], 'BUY')
                
                action_type = "추가 매수" if has_position else "신규 매수"
                self.logger.info(f"💰 {symbol} {action_type} 실행: {quantity}주 ({order_strategy})")
                
                result = self.place_order_with_strategy(symbol, 'BUY', quantity, order_strategy)
                
                if result['success']:
                    executed_price = result.get('limit_price', current_price)
                    self.position_manager.record_purchase(
                        symbol, quantity, executed_price, optimal_strategy
                    )
                    self.logger.info(f"✅ {symbol} {action_type} 완료: {quantity}주 @ {executed_price:,}원")
                    
                    # 포지션 업데이트
                    if has_position:
                        # 기존 보유량에 추가
                        old_quantity = current_position['quantity']
                        old_avg_price = current_position['avg_price']
                        new_total_quantity = old_quantity + quantity
                        new_avg_price = ((old_avg_price * old_quantity) + (executed_price * quantity)) / new_total_quantity
                        
                        self.positions[symbol]['quantity'] = new_total_quantity
                        self.positions[symbol]['avg_price'] = new_avg_price
                    else:
                        # 신규 포지션 생성
                        self.positions[symbol] = {
                            'quantity': quantity,
                            'avg_price': executed_price,
                            'current_price': current_price,
                            'profit_loss': 0
                        }
            else:
                self.logger.warning(f"⚠️ {symbol} - 매수 수량이 0입니다.")
        else:
            self.logger.info(f"📉 {symbol} - 매수 신호 없음 ({signals['signal']})")
    
    # 문제 2: process_buy_signals에서 로깅 부족
    def process_buy_signals(self):
        """상세 로깅이 포함된 매수 신호 처리"""
        self.logger.info("🛒 매수 신호 처리 시작")
        self.logger.info(f"📋 분석 대상 종목: {self.symbols}")
        
        if not self.symbols:
            self.logger.warning("❌ 분석할 종목이 없습니다")
            return
        
        for i, symbol in enumerate(self.symbols, 1):
            try:
                self.logger.info(f"🔍 [{i}/{len(self.symbols)}] {symbol} 매수 분석 중...")
                self.process_buy_for_symbol(symbol)
                time.sleep(0.5)  # API 호출 간격
            except Exception as e:
                self.logger.error(f"❌ {symbol} 매수 처리 오류: {e}")
        
        self.logger.info("✅ 매수 신호 처리 완료")
    
    # 문제 3: 거래 사이클에서 매수 처리가 제대로 호출되지 않을 수 있음
    def run_trading_cycle_improved(self):
        """디버깅이 강화된 거래 사이클"""
        if not self.check_risk_management():
            self.logger.warning("리스크 관리 조건 위반 - 거래 중단")
            return
    
        self.logger.info("🔄 개선된 거래 사이클 시작")
        
        try:
            # 1. 모든 포지션 업데이트 (매도용)
            self.logger.info("1️⃣ 포지션 업데이트 중...")
            self.update_all_positions()
            
            # 2. 매도 처리 우선 (모든 보유 종목)
            self.logger.info("2️⃣ 매도 신호 처리 중...")
            if hasattr(self, 'all_positions') and self.all_positions:
                self.logger.info(f"   매도 분석 대상: {len(self.all_positions)}개 종목")
                self.process_sell_signals()
            else:
                self.logger.info("   보유 종목 없음 - 매도 처리 건너뛰기")
            
            # 3. 매수 처리 (백테스트 선정 종목) - 강화된 로깅
            self.logger.info("3️⃣ 매수 신호 처리 중...")
            self.logger.info(f"   매수 분석 대상: {self.symbols}")
            
            # 현재 상황 체크
            available_cash = self.get_available_cash()
            self.logger.info(f"   💵 현재 가용 자금: {available_cash:,}원")
            
            if available_cash <= 0:
                self.logger.warning("   ⚠️ 가용 자금 부족 - 매수 건너뛰기")
            else:
                self.process_buy_signals()
            
            # 4. 성과 데이터 저장
            self.logger.info("4️⃣ 성과 데이터 저장 중...")
            self.save_performance_data()
            
            self.logger.info("✅ 거래 사이클 완료")
            
        except Exception as e:
            self.logger.error(f"거래 사이클 실행 중 오류: {e}")
            import traceback
            self.logger.error(f"상세 오류:\n{traceback.format_exc()}")
    
    # 가용 자금 확인 함수 추가
    def get_available_cash(self) -> float:
        """가용 자금 조회"""
        try:
            account_data = self.get_account_balance()
            if account_data and account_data.get('output'):
                available_cash = float(account_data['output'].get('ord_psbl_cash', 0))
                return available_cash
        except Exception as e:
            self.logger.error(f"가용 자금 조회 실패: {e}")
        return 0
    
    # 문제 4: can_purchase_symbol 함수가 너무 엄격할 수 있음
    def can_purchase_symbol(self, symbol: str) -> tuple[bool, str]:
        """디버깅이 강화된 종목 매수 가능 여부 확인"""
        
        self.logger.debug(f"🔍 {symbol} 매수 가능 여부 확인 중...")
        
        # 1. 현재 보유 수량 확인
        current_position = self.positions.get(symbol, {})
        current_quantity = current_position.get('quantity', 0)
        
        self.logger.debug(f"   현재 보유: {current_quantity}주 / 최대: {self.max_quantity_per_symbol}주")
        
        if current_quantity >= self.max_quantity_per_symbol:
            reason = f"최대 보유 수량 초과 ({current_quantity}/{self.max_quantity_per_symbol}주)"
            self.logger.debug(f"   ❌ {reason}")
            return False, reason
        
        # 2. 매수 횟수 제한 확인
        history = self.position_manager.position_history.get(symbol, {})
        purchase_count = history.get('purchase_count', 0)
        
        self.logger.debug(f"   매수 횟수: {purchase_count}회 / 최대: {self.max_purchases_per_symbol}회")
        
        if purchase_count >= self.max_purchases_per_symbol:
            reason = f"최대 매수 횟수 초과 ({purchase_count}/{self.max_purchases_per_symbol}회)"
            self.logger.debug(f"   ❌ {reason}")
            return False, reason
        
        # 3. 재매수 금지 기간 확인
        last_purchase_time = history.get('last_purchase_time')
        if last_purchase_time:
            last_time = datetime.fromisoformat(last_purchase_time)
            time_since_last = datetime.now() - last_time
            hours_since_last = time_since_last.total_seconds() / 3600
            
            self.logger.debug(f"   마지막 매수: {hours_since_last:.1f}시간 전 / 금지기간: {self.purchase_cooldown_hours}시간")
            
            if time_since_last < timedelta(hours=self.purchase_cooldown_hours):
                remaining_hours = self.purchase_cooldown_hours - hours_since_last
                reason = f"재매수 금지 기간 중 (남은 시간: {remaining_hours:.1f}시간)"
                self.logger.debug(f"   ❌ {reason}")
                return False, reason
        
        self.logger.debug(f"   ✅ 매수 가능")
        return True, "매수 가능"
    

    def calculate_macd(self, df: pd.DataFrame, price_col: str = 'stck_prpr') -> pd.DataFrame:
        """MACD 지표 계산"""
        if len(df) < self.macd_slow + self.macd_signal:
            return df
        
        try:
            # 종가 데이터
            close = df[price_col].astype(float)
            
            # EMA 계산
            ema_fast = close.ewm(span=self.macd_fast).mean()
            ema_slow = close.ewm(span=self.macd_slow).mean()
            
            # MACD Line = 빠른EMA - 느린EMA
            df['macd_line'] = ema_fast - ema_slow
            
            # Signal Line = MACD Line의 9일 EMA
            df['macd_signal'] = df['macd_line'].ewm(span=self.macd_signal).mean()
            
            # Histogram = MACD Line - Signal Line
            df['macd_histogram'] = df['macd_line'] - df['macd_signal']
            
            # 골든크로스/데드크로스 감지
            df['macd_cross'] = 0
            for i in range(1, len(df)):
                # 골든크로스: MACD Line이 Signal Line을 위로 돌파
                if (df['macd_line'].iloc[i] > df['macd_signal'].iloc[i] and 
                    df['macd_line'].iloc[i-1] <= df['macd_signal'].iloc[i-1]):
                    df.loc[df.index[i], 'macd_cross'] = 1  # 골든크로스
                
                # 데드크로스: MACD Line이 Signal Line을 아래로 돌파
                elif (df['macd_line'].iloc[i] < df['macd_signal'].iloc[i] and 
                      df['macd_line'].iloc[i-1] >= df['macd_signal'].iloc[i-1]):
                    df.loc[df.index[i], 'macd_cross'] = -1  # 데드크로스
            
            self.logger.debug(f"MACD 계산 완료: {len(df)}개 봉")
            
            return df
            
        except Exception as e:
            self.logger.error(f"MACD 계산 실패: {e}")
            return df
    
    def detect_macd_golden_cross(self, df: pd.DataFrame) -> Dict:
        """MACD 골든크로스 감지 및 신호 강도 계산"""
        
        if 'macd_cross' not in df.columns or len(df) < 10:
            return {
                'golden_cross': False,
                'cross_strength': 0,
                'trend_strength': 0,
                'histogram_trend': 'neutral',
                'signal_age': 999
            }
        
        try:
            # 최근 몇 봉에서 골든크로스 발생했는지 확인
            recent_crosses = df['macd_cross'].tail(self.macd_cross_lookback)
            golden_cross_occurred = any(recent_crosses == 1)
            
            # 골든크로스 발생 시점 찾기
            signal_age = 999
            if golden_cross_occurred:
                cross_indices = df[df['macd_cross'] == 1].index
                if len(cross_indices) > 0:
                    last_cross_idx = cross_indices[-1]
                    signal_age = len(df) - df.index.get_loc(last_cross_idx) - 1
            
            # MACD 신호 강도 계산
            latest = df.iloc[-1]
            
            # 1. MACD Line과 Signal Line 간격 (클수록 강한 신호)
            macd_gap = abs(latest['macd_line'] - latest['macd_signal'])
            
            # 2. 히스토그램 추세 (연속 상승 중인지)
            histogram_trend = 'neutral'
            if len(df) >= 3:
                recent_hist = df['macd_histogram'].tail(3).tolist()
                if all(recent_hist[i] < recent_hist[i+1] for i in range(len(recent_hist)-1)):
                    histogram_trend = 'rising'
                elif all(recent_hist[i] > recent_hist[i+1] for i in range(len(recent_hist)-1)):
                    histogram_trend = 'falling'
            
            # 3. MACD Line의 위치 (0선 위에 있으면 더 강함)
            macd_above_zero = latest['macd_line'] > 0
            
            # 4. 추세 지속성 확인
            if len(df) >= self.macd_trend_confirmation:
                trend_data = df['macd_line'].tail(self.macd_trend_confirmation)
                trend_strength = 1 if trend_data.iloc[-1] > trend_data.iloc[0] else 0
            else:
                trend_strength = 0
            
            # 신호 강도 종합 계산 (0~5점)
            cross_strength = 0
            if golden_cross_occurred:
                cross_strength = 2.0  # 기본 골든크로스 점수
                
                # 보너스 점수
                if macd_above_zero:
                    cross_strength += 0.5
                if histogram_trend == 'rising':
                    cross_strength += 0.5
                if signal_age <= 2:  # 최근 2봉 이내 발생
                    cross_strength += 0.5
                if macd_gap > df['macd_line'].std() * 0.5:  # 충분한 간격
                    cross_strength += 0.5
                if trend_strength > 0:
                    cross_strength += 0.5
            
            result = {
                'golden_cross': golden_cross_occurred,
                'cross_strength': min(cross_strength, 5.0),
                'trend_strength': trend_strength,
                'histogram_trend': histogram_trend,
                'signal_age': signal_age,
                'macd_line': latest['macd_line'],
                'macd_signal': latest['macd_signal'],
                'macd_histogram': latest['macd_histogram'],
                'macd_above_zero': macd_above_zero
            }
            
            self.logger.debug(f"MACD 골든크로스 분석: {result}")
            return result
            
        except Exception as e:
            self.logger.error(f"MACD 골든크로스 감지 실패: {e}")
            return {
                'golden_cross': False,
                'cross_strength': 0,
                'trend_strength': 0,
                'histogram_trend': 'neutral',
                'signal_age': 999
            }
    
    def calculate_enhanced_momentum_signals(self, df: pd.DataFrame) -> Dict:
        """MACD 골든크로스가 포함된 강화된 모멘텀 신호"""
        if len(df) < max(self.ma_long, self.momentum_period, self.macd_slow + self.macd_signal):
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
        
        try:
            # 기존 모멘텀 지표들
            df['ma_short'] = df['stck_prpr'].rolling(self.ma_short).mean()
            df['ma_long'] = df['stck_prpr'].rolling(self.ma_long).mean()
            
            # MACD 계산
            df = self.calculate_macd(df)
            
            # 모멘텀 계산
            current_price = float(df['stck_prpr'].iloc[-1])
            past_price = float(df['stck_prpr'].iloc[-(self.momentum_period+1)])
            momentum = (current_price - past_price) / past_price
            
            # 거래량 증가율
            avg_volume = df['cntg_vol'].rolling(20).mean().iloc[-2]
            current_volume = df['cntg_vol'].iloc[-1]
            volume_ratio = float(current_volume / avg_volume) if avg_volume > 0 else 1
            
            # MACD 골든크로스 분석
            macd_analysis = self.detect_macd_golden_cross(df)
            
            # 신호 생성 로직
            signal = 'HOLD'
            strength = 0
            signal_components = []
            
            latest = df.iloc[-1]
            
            # 매수 신호 조건들
            ma_bullish = latest['ma_short'] > latest['ma_long']
            momentum_bullish = momentum > self.momentum_threshold
            volume_bullish = volume_ratio > self.volume_threshold
            macd_bullish = macd_analysis['golden_cross']
            
            # 매도 신호 조건들
            ma_bearish = latest['ma_short'] < latest['ma_long']
            momentum_bearish = momentum < -self.momentum_threshold/2
            macd_bearish = macd_analysis['histogram_trend'] == 'falling'
            
            # 매수 신호 강도 계산
            if ma_bullish or momentum_bullish or macd_bullish:
                buy_score = 0
                
                # 각 지표별 점수 (최대 5점)
                if ma_bullish:
                    buy_score += 1.0
                    signal_components.append("MA상승")
                
                if momentum_bullish:
                    momentum_score = min((momentum / self.momentum_threshold), 2.0)
                    buy_score += momentum_score
                    signal_components.append(f"모멘텀{momentum:.1%}")
                
                if volume_bullish:
                    volume_score = min((volume_ratio / self.volume_threshold), 1.5)
                    buy_score += volume_score
                    signal_components.append(f"거래량{volume_ratio:.1f}배")
                
                if macd_bullish:
                    buy_score += macd_analysis['cross_strength']
                    signal_components.append(f"MACD골든크로스({macd_analysis['signal_age']}봉전)")
                
                # MACD 추가 보너스
                if macd_analysis['macd_above_zero']:
                    buy_score += 0.3
                    signal_components.append("MACD>0")
                
                if macd_analysis['histogram_trend'] == 'rising':
                    buy_score += 0.2
                    signal_components.append("히스토그램상승")
                
                # 매수 신호 임계값 확인
                if buy_score >= 1.5:  # 최소 1.5점 이상
                    signal = 'BUY'
                    strength = min(buy_score, 5.0)
            
            # 매도 신호 강도 계산
            elif ma_bearish or momentum_bearish or macd_bearish:
                sell_score = 0
                
                if ma_bearish:
                    sell_score += 1.5
                    signal_components.append("MA하락")
                
                if momentum_bearish:
                    sell_score += abs(momentum) / self.momentum_threshold * 2
                    signal_components.append(f"모멘텀{momentum:.1%}")
                
                if macd_bearish:
                    sell_score += 1.0
                    signal_components.append("MACD약화")
                
                # 데드크로스 추가 확인
                recent_crosses = df['macd_cross'].tail(3)
                if any(recent_crosses == -1):
                    sell_score += 1.5
                    signal_components.append("MACD데드크로스")
                
                if sell_score >= 1.0:
                    signal = 'SELL'
                    strength = min(sell_score, 5.0)
            
            # 결과 반환
            result = {
                'signal': signal,
                'strength': strength,
                'momentum': momentum,
                'volume_ratio': volume_ratio,
                'ma_short': float(latest['ma_short']),
                'ma_long': float(latest['ma_long']),
                'current_price': current_price,
                'macd_analysis': macd_analysis,
                'signal_components': signal_components
            }
            
            # 상세 로깅
            if signal != 'HOLD':
                components_str = ', '.join(signal_components)
                self.logger.info(f"📊 {signal} 신호 감지! 강도: {strength:.2f}")
                self.logger.info(f"   구성요소: {components_str}")
                if macd_bullish:
                    self.logger.info(f"   🌟 MACD 골든크로스: {macd_analysis['signal_age']}봉 전 발생")
            
            return result
            
        except Exception as e:
            self.logger.error(f"강화된 모멘텀 신호 계산 실패: {e}")
            return {'signal': 'HOLD', 'strength': 0, 'current_price': float(df['stck_prpr'].iloc[-1])}
    
    def calculate_macd_strategy_signals(self, df: pd.DataFrame) -> Dict:
        """MACD 전용 전략 신호"""
        if len(df) < self.macd_slow + self.macd_signal + 5:
            return {'signal': 'HOLD', 'strength': 0, 'current_price': 0}
        
        try:
            # MACD 계산
            df = self.calculate_macd(df)
            
            # MACD 골든크로스 분석
            macd_analysis = self.detect_macd_golden_cross(df)
            
            current_price = float(df['stck_prpr'].iloc[-1])
            latest = df.iloc[-1]
            
            signal = 'HOLD'
            strength = 0
            
            # MACD 기반 신호 생성
            if macd_analysis['golden_cross']:
                # 골든크로스 발생 → 매수 신호
                signal = 'BUY'
                strength = macd_analysis['cross_strength']
                
                # 추가 확인 조건들
                if macd_analysis['macd_above_zero']:
                    strength += 0.5
                if macd_analysis['histogram_trend'] == 'rising':
                    strength += 0.5
                if macd_analysis['signal_age'] <= 1:  # 매우 최근 발생
                    strength += 0.5
                
                strength = min(strength, 5.0)
                
            elif latest['macd_line'] < latest['macd_signal'] and latest['macd_histogram'] < 0:
                # MACD Line이 Signal Line 아래 + 히스토그램 음수
                recent_crosses = df['macd_cross'].tail(3)
                if any(recent_crosses == -1):  # 최근 데드크로스 발생
                    signal = 'SELL'
                    strength = 2.0
                    
                    # 추가 약세 조건
                    if latest['macd_line'] < 0:  # MACD가 0선 아래
                        strength += 0.5
                    if macd_analysis['histogram_trend'] == 'falling':
                        strength += 0.5
                    
                    strength = min(strength, 5.0)
            
            return {
                'signal': signal,
                'strength': strength,
                'current_price': current_price,
                'macd_line': float(latest['macd_line']),
                'macd_signal': float(latest['macd_signal']),
                'macd_histogram': float(latest['macd_histogram']),
                'golden_cross': macd_analysis['golden_cross'],
                'signal_age': macd_analysis['signal_age']
            }
            
        except Exception as e:
            self.logger.error(f"MACD 전략 신호 계산 실패: {e}")
            return {'signal': 'HOLD', 'strength': 0, 'current_price': float(df['stck_prpr'].iloc[-1])}
    
    def calculate_signals_by_strategy_enhanced(self, symbol: str, df: pd.DataFrame, strategy: str) -> Dict:
        """MACD가 강화된 전략별 신호 계산"""
        
        if strategy == 'momentum':
            return self.calculate_enhanced_momentum_signals(df)
        elif strategy == 'macd':
            return self.calculate_macd_strategy_signals(df)
        elif strategy == 'momentum_macd':
            # 모멘텀 + MACD 조합 전략
            momentum_signals = self.calculate_enhanced_momentum_signals(df)
            macd_signals = self.calculate_macd_strategy_signals(df)
            
            # 두 신호의 조합
            if momentum_signals['signal'] == 'BUY' and macd_signals['signal'] == 'BUY':
                strength = (momentum_signals['strength'] + macd_signals['strength']) * 0.7  # 조금 보수적으로
                return {
                    'signal': 'BUY',
                    'strength': min(strength, 5.0),
                    'current_price': momentum_signals['current_price'],
                    'strategy_components': ['momentum', 'macd']
                }
            elif momentum_signals['signal'] == 'SELL' or macd_signals['signal'] == 'SELL':
                strength = max(momentum_signals['strength'], macd_signals['strength'])
                return {
                    'signal': 'SELL',
                    'strength': strength,
                    'current_price': momentum_signals['current_price'],
                    'strategy_components': ['momentum', 'macd']
                }
            else:
                return {
                    'signal': 'HOLD',
                    'strength': 0,
                    'current_price': momentum_signals['current_price']
                }
        
        elif strategy == 'mean_reversion':
            return self.calculate_mean_reversion_signals(df)
        elif strategy == 'breakout':
            return self.calculate_breakout_signals(df)
        elif strategy == 'scalping':
            return self.calculate_scalping_signals(df)
        else:
            # 기본값으로 강화된 모멘텀 사용
            return self.calculate_enhanced_momentum_signals(df)
    
    def notify_macd_signal(self, symbol: str, macd_analysis: Dict, signal: str):
        """MACD 신호 전용 알림"""
        if not self.notify_on_trade:
            return
        
        stock_name = self.get_stock_name(symbol)
        
        if macd_analysis['golden_cross']:
            title = "🌟 MACD 골든크로스 감지!"
            color = 0x00ff00
        else:
            title = "📊 MACD 신호"
            color = 0xffaa00
        
        message = f"""
**종목**: {symbol} ({stock_name})
**신호**: {signal}
**MACD Line**: {macd_analysis.get('macd_line', 0):.4f}
**Signal Line**: {macd_analysis.get('macd_signal', 0):.4f}
**히스토그램**: {macd_analysis.get('macd_histogram', 0):.4f}
**골든크로스**: {'예' if macd_analysis['golden_cross'] else '아니오'}
**신호 발생**: {macd_analysis['signal_age']}봉 전
**추세**: {macd_analysis['histogram_trend']}
**시간**: {datetime.now().strftime('%H:%M:%S')}
        """
        
        self.send_discord_notification(title, message, color)
    
    # config.yaml에 추가할 MACD 설정
    def create_config_with_macd(self, config_path: str):
        """MACD 설정이 포함된 설정 파일 생성"""
        sample_config = {
            'kis': {
                'app_key': 'YOUR_APP_KEY',
                'app_secret': 'YOUR_APP_SECRET',
                'base_url': 'https://openapi.koreainvestment.com:9443',
                'account_no': 'YOUR_ACCOUNT_NO'
            },
            'trading': {
                'max_symbols': 5,
                'max_position_ratio': 0.3,  # MACD 신호를 위해 30%로 증가
                'daily_loss_limit': 0.02,
                'stop_loss_pct': 0.05,
                'take_profit_pct': 0.15
            },
            'momentum': {
                'period': 20,
                'threshold': 0.02,
                'volume_threshold': 1.5,
                'ma_short': 5,
                'ma_long': 20
            },
            'macd': {  # MACD 설정 추가
                'fast_period': 12,     # 빠른 EMA
                'slow_period': 26,     # 느린 EMA
                'signal_period': 9,    # 신호선 EMA
                'cross_lookback': 3,   # 크로스 감지 기간
                'trend_confirmation': 5, # 추세 확인 기간
                'enable_notifications': True  # MACD 알림 활성화
            },
            'strategies': {  # 전략별 설정
                'momentum': {
                    'include_macd': True,    # 모멘텀 전략에 MACD 포함
                    'macd_weight': 0.3       # MACD 가중치
                },
                'macd_only': {
                    'enabled': True,         # MACD 전용 전략 활성화
                    'min_strength': 2.0      # 최소 신호 강도
                }
            },
            'backtest': {
                'results_file': 'backtest_results.json',
                'min_return_threshold': 5.0,
                'performance_tracking': True
            },
            'notification': {
                'discord_webhook': '',
                'notify_on_trade': True,
                'notify_on_error': True,
                'notify_on_daily_summary': True,
                'notify_on_macd_signals': True  # MACD 신호 알림
            }
        }
        
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(sample_config, f, default_flow_style=False, allow_unicode=True)

    def debug_macd_calculation(self, symbol: str, df: pd.DataFrame):
        """MACD 계산 과정 상세 디버깅"""
        print(f"\n🔍 {symbol} MACD 계산 디버깅")
        print("="*60)
        
        if df.empty:
            print("❌ 데이터프레임이 비어있습니다")
            return
        
        print(f"📊 데이터 정보:")
        print(f"  - 데이터 길이: {len(df)}개 봉")
        print(f"  - 필요한 최소 길이: {self.macd_slow + self.macd_signal} ({self.macd_slow}+{self.macd_signal})")
        print(f"  - 현재가: {df['stck_prpr'].iloc[-1]:,}원")
        print(f"  - 가격 범위: {df['stck_prpr'].min():,} ~ {df['stck_prpr'].max():,}")
        
        if len(df) < self.macd_slow + self.macd_signal:
            print(f"❌ 데이터 부족: {len(df)} < {self.macd_slow + self.macd_signal}")
            return
        
        try:
            # MACD 계산
            close = df['stck_prpr'].astype(float)
            
            # EMA 계산
            ema_fast = close.ewm(span=self.macd_fast).mean()
            ema_slow = close.ewm(span=self.macd_slow).mean()
            
            # MACD Line
            macd_line = ema_fast - ema_slow
            
            # Signal Line
            macd_signal = macd_line.ewm(span=self.macd_signal).mean()
            
            # Histogram
            macd_histogram = macd_line - macd_signal
            
            print(f"\n📈 최근 5개 봉 MACD 데이터:")
            print("시간\t\t가격\t\tMACD\t\tSignal\t\tHist\t\tCross")
            print("-" * 80)
            
            for i in range(max(0, len(df)-5), len(df)):
                time_str = f"봉{i}"
                price = close.iloc[i]
                macd_val = macd_line.iloc[i]
                signal_val = macd_signal.iloc[i]
                hist_val = macd_histogram.iloc[i]
                
                # 크로스 확인
                cross_type = ""
                if i > 0:
                    prev_macd = macd_line.iloc[i-1]
                    prev_signal = macd_signal.iloc[i-1]
                    
                    if macd_val > signal_val and prev_macd <= prev_signal:
                        cross_type = "🌟GOLDEN"
                    elif macd_val < signal_val and prev_macd >= prev_signal:
                        cross_type = "💀DEAD"
                
                print(f"{time_str}\t\t{price:,.0f}\t\t{macd_val:.4f}\t\t{signal_val:.4f}\t\t{hist_val:.4f}\t\t{cross_type}")
            
            # 최근 크로스 확인
            print(f"\n🔍 최근 {self.macd_cross_lookback}봉 크로스 확인:")
            recent_crosses = []
            for i in range(max(1, len(df)-self.macd_cross_lookback), len(df)):
                prev_macd = macd_line.iloc[i-1]
                prev_signal = macd_signal.iloc[i-1]
                curr_macd = macd_line.iloc[i]
                curr_signal = macd_signal.iloc[i]
                
                if curr_macd > curr_signal and prev_macd <= prev_signal:
                    recent_crosses.append(f"봉{i}: 골든크로스")
                elif curr_macd < curr_signal and prev_macd >= prev_signal:
                    recent_crosses.append(f"봉{i}: 데드크로스")
            
            if recent_crosses:
                for cross in recent_crosses:
                    print(f"  🔥 {cross}")
            else:
                print("  ⚪ 최근 크로스 없음")
            
            # 현재 상태 분석
            latest_macd = macd_line.iloc[-1]
            latest_signal = macd_signal.iloc[-1]
            latest_hist = macd_histogram.iloc[-1]
            
            print(f"\n📊 현재 MACD 상태:")
            print(f"  - MACD Line: {latest_macd:.6f}")
            print(f"  - Signal Line: {latest_signal:.6f}")
            print(f"  - Histogram: {latest_hist:.6f}")
            print(f"  - MACD > Signal: {'예' if latest_macd > latest_signal else '아니오'}")
            print(f"  - MACD > 0: {'예' if latest_macd > 0 else '아니오'}")
            
            # 히스토그램 추세 확인
            if len(df) >= 3:
                hist_trend = []
                for i in range(len(df)-3, len(df)):
                    hist_trend.append(macd_histogram.iloc[i])
                
                if all(hist_trend[i] < hist_trend[i+1] for i in range(len(hist_trend)-1)):
                    trend = "상승"
                elif all(hist_trend[i] > hist_trend[i+1] for i in range(len(hist_trend)-1)):
                    trend = "하락"
                else:
                    trend = "횡보"
                
                print(f"  - 히스토그램 추세: {trend}")
                print(f"  - 최근 3봉 히스토그램: {[f'{h:.4f}' for h in hist_trend]}")
            
        except Exception as e:
            print(f"❌ MACD 계산 오류: {e}")
            import traceback
            traceback.print_exc()
    
    def test_macd_signals_verbose(self):
        """상세한 MACD 신호 테스트"""
        print("🧪 상세한 MACD 골든크로스 신호 테스트")
        print("="*60)
        
        for symbol in self.symbols:
            stock_name = self.get_stock_name(symbol)
            print(f"\n📊 {symbol}({stock_name}) 상세 분석:")
            
            # 더 많은 분봉 데이터 조회 (MACD 계산을 위해)
            df = self.get_minute_data(symbol, minutes=200)  # 200분봉 (충분한 데이터)
            
            if df.empty:
                print("❌ 분봉 데이터를 가져올 수 없습니다")
                continue
            
            # MACD 계산 디버깅
            self.debug_macd_calculation(symbol, df)
            
            # 실제 신호 계산
            try:
                signals = self.calculate_enhanced_momentum_signals(df)
                
                print(f"\n🎯 종합 신호 결과:")
                print(f"  신호: {signals['signal']}")
                print(f"  강도: {signals['strength']:.2f}")
                print(f"  구성요소: {signals.get('signal_components', [])}")
                
                if 'macd_analysis' in signals:
                    macd = signals['macd_analysis']
                    print(f"\n🌟 MACD 분석 상세:")
                    print(f"  - 골든크로스: {macd['golden_cross']}")
                    print(f"  - 크로스 강도: {macd['cross_strength']:.2f}")
                    print(f"  - 신호 나이: {macd['signal_age']}봉")
                    print(f"  - 추세 강도: {macd['trend_strength']}")
                    print(f"  - 히스토그램 추세: {macd['histogram_trend']}")
                    print(f"  - MACD > 0: {macd.get('macd_above_zero', False)}")
            
            except Exception as e:
                print(f"❌ 신호 계산 오류: {e}")
                import traceback
                traceback.print_exc()
    
    def create_sample_macd_data(self):
        """MACD 테스트용 샘플 데이터 생성"""
        print("🧪 MACD 테스트용 샘플 데이터 생성")
        
        import numpy as np
        
        # 가상의 가격 데이터 생성 (골든크로스 패턴 포함)
        np.random.seed(42)
        
        # 기본 추세 + 노이즈
        base_price = 100000  # 10만원 기준
        trend = np.linspace(0, 0.1, 100)  # 10% 상승 추세
        noise = np.random.normal(0, 0.02, 100)  # 2% 노이즈
        
        # 가격 데이터 생성
        prices = base_price * (1 + trend + noise)
        
        # 중간에 강한 상승 구간 추가 (골든크로스 유발)
        prices[70:80] *= 1.05  # 5% 급등
        
        # DataFrame 생성
        df = pd.DataFrame({
            'stck_prpr': prices,
            'stck_oprc': prices * 0.998,
            'stck_hgpr': prices * 1.01,
            'stck_lwpr': prices * 0.99,
            'cntg_vol': np.random.randint(1000, 10000, 100)
        })
        
        # MACD 계산
        df = self.calculate_macd(df)
        
        print(f"📊 샘플 데이터 정보:")
        print(f"  - 데이터 길이: {len(df)}")
        print(f"  - 가격 범위: {df['stck_prpr'].min():.0f} ~ {df['stck_prpr'].max():.0f}")
        
        # 골든크로스 확인
        golden_crosses = []
        for i in range(1, len(df)):
            if (df['macd_line'].iloc[i] > df['macd_signal'].iloc[i] and 
                df['macd_line'].iloc[i-1] <= df['macd_signal'].iloc[i-1]):
                golden_crosses.append(i)
        
        print(f"  - 골든크로스 발생: {len(golden_crosses)}회")
        for idx in golden_crosses:
            print(f"    🌟 {idx}번째 봉에서 골든크로스")
        
        # MACD 신호 테스트
        macd_analysis = self.detect_macd_golden_cross(df)
        print(f"\n🎯 MACD 분석 결과:")
        for key, value in macd_analysis.items():
            print(f"  - {key}: {value}")
        
        return df
    
    def fix_macd_integration(self):
        """MACD 통합 문제 수정"""
        print("🔧 MACD 통합 수정 중...")
        
        # 1. MACD 설정 확인
        if not hasattr(self, 'macd_fast'):
            self.macd_fast = 12
            self.macd_slow = 26
            self.macd_signal = 9
            self.macd_cross_lookback = 3
            self.macd_trend_confirmation = 5
            print("✅ MACD 설정 초기화 완료")
        
        # 2. 함수 바인딩 확인
        if not hasattr(self, 'calculate_macd'):
            print("❌ calculate_macd 함수가 없습니다")
            return False
        
        if not hasattr(self, 'detect_macd_golden_cross'):
            print("❌ detect_macd_golden_cross 함수가 없습니다")
            return False
        
        if not hasattr(self, 'calculate_enhanced_momentum_signals'):
            print("❌ calculate_enhanced_momentum_signals 함수가 없습니다")
            return False
        
        # 3. 기존 함수 교체
        original_func = getattr(self, 'calculate_signals_by_strategy', None)
        if original_func:
            self.calculate_signals_by_strategy_original = original_func
            self.calculate_signals_by_strategy = self.calculate_signals_by_strategy_enhanced
            print("✅ 신호 계산 함수 업그레이드 완료")
        
        print("✅ MACD 통합 수정 완료")
        return True
    
    
    # 일봉 데이터 컬럼명 수정 및 MACD 완전 구현
    def get_daily_data(self, symbol: str, days: int = 100) -> pd.DataFrame:
        """수정된 일봉 데이터 조회"""
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
            self.logger.info(f"📅 {symbol} 일봉 데이터 조회: {days}일간")
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
    
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                
                # 일봉 데이터 컬럼명 확인 및 출력
                self.logger.debug(f"일봉 데이터 컬럼: {df.columns.tolist()}")
                
                # 날짜 순으로 정렬
                if 'stck_bsop_date' in df.columns:
                    df = df.sort_values('stck_bsop_date').reset_index(drop=True)
                
                # 컬럼명 매핑 (일봉 → 분봉 형식으로 통일)
                column_mapping = {
                    'stck_clpr': 'stck_prpr',    # 종가 → 현재가
                    'stck_oprc': 'stck_oprc',    # 시가 (동일)
                    'stck_hgpr': 'stck_hgpr',    # 고가 (동일)
                    'stck_lwpr': 'stck_lwpr',    # 저가 (동일)
                    'acml_vol': 'cntg_vol',      # 누적거래량 → 거래량
                    'acml_tr_pbmn': 'acml_tr_pbmn'  # 누적거래대금
                }
                
                # 컬럼명 변경
                for old_col, new_col in column_mapping.items():
                    if old_col in df.columns:
                        df[new_col] = df[old_col]
                
                # 숫자형 변환
                numeric_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'cntg_vol']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # NaN 제거
                df = df.dropna(subset=['stck_prpr'])
                
                self.logger.info(f"✅ {symbol} 일봉 데이터 {len(df)}개 조회 완료")
                self.logger.debug(f"가격 범위: {df['stck_prpr'].min():,} ~ {df['stck_prpr'].max():,}")
                
                return df
            else:
                self.logger.warning(f"❌ {symbol} 일봉 데이터 없음")
                
        except Exception as e:
            self.logger.error(f"일봉 데이터 조회 실패 ({symbol}): {e}")
    
        return pd.DataFrame()
    
    def debug_daily_data_columns(self, symbol: str):
        """일봉 데이터 컬럼 구조 확인"""
        print(f"🔍 {symbol} 일봉 데이터 구조 분석")
        
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST03010100"
            }
    
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": symbol,
                "fid_input_date_1": start_date,
                "fid_input_date_2": end_date,
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "0"
            }
    
            response = requests.get(url, headers=headers, params=params, timeout=15)
            data = response.json()
    
            print(f"📊 API 응답 구조:")
            print(f"  - rt_cd: {data.get('rt_cd')}")
            print(f"  - msg1: {data.get('msg1', 'N/A')}")
            
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                print(f"  - 데이터 개수: {len(df)}개")
                print(f"  - 컬럼 목록: {df.columns.tolist()}")
                
                if len(df) > 0:
                    print(f"\n📈 첫 번째 행 데이터:")
                    first_row = df.iloc[0]
                    for col in df.columns:
                        print(f"  {col}: {first_row[col]}")
                    
                    # 가격 관련 컬럼 찾기
                    price_cols = [col for col in df.columns if 'pr' in col.lower() or 'prc' in col.lower()]
                    print(f"\n💰 가격 관련 컬럼: {price_cols}")
                    
                    volume_cols = [col for col in df.columns if 'vol' in col.lower()]
                    print(f"📊 거래량 관련 컬럼: {volume_cols}")
            else:
                print("❌ output2 데이터 없음")
                
        except Exception as e:
            print(f"❌ 디버깅 실패: {e}")
    
    def test_macd_with_fixed_daily_data(self):
        """수정된 일봉 데이터로 MACD 테스트"""
        print("🧪 수정된 일봉 데이터로 MACD 테스트")
        print("="*60)
        
        for symbol in self.symbols:
            stock_name = self.get_stock_name(symbol)
            print(f"\n📊 {symbol}({stock_name}) 분석:")
            
            # 1. 컬럼 구조 먼저 확인
            print("🔍 컬럼 구조 확인:")
            self.debug_daily_data_columns(symbol)
            
            # 2. 수정된 일봉 데이터 조회
            print("\n📅 수정된 일봉 데이터 조회:")
            df = self.get_daily_data(symbol, days=100)
            
            if df.empty:
                print("❌ 일봉 데이터를 가져올 수 없습니다")
                continue
            
            print(f"✅ 일봉 데이터: {len(df)}일")
            print(f"가격 범위: {df['stck_prpr'].min():,} ~ {df['stck_prpr'].max():,}")
            print(f"최근 가격: {df['stck_prpr'].iloc[-1]:,}원")
            print(f"고유가격 수: {df['stck_prpr'].nunique()}개")
            
            if len(df) >= 35:
                # 3. MACD 계산
                print("\n📈 MACD 계산:")
                try:
                    df_with_macd = self.calculate_macd(df)
                    
                    # MACD 데이터 확인
                    if 'macd_line' in df_with_macd.columns:
                        print(f"✅ MACD 계산 성공")
                        
                        # 최근 5일 데이터 출력
                        print(f"\n📊 최근 5일 MACD 데이터:")
                        recent = df_with_macd.tail(5)
                        for i, row in recent.iterrows():
                            date = row.get('stck_bsop_date', f'Day{i}')
                            price = row['stck_prpr']
                            macd_line = row.get('macd_line', 0)
                            macd_signal = row.get('macd_signal', 0)
                            macd_hist = row.get('macd_histogram', 0)
                            cross = row.get('macd_cross', 0)
                            
                            cross_icon = ""
                            if cross == 1:
                                cross_icon = "🌟골든"
                            elif cross == -1:
                                cross_icon = "💀데드"
                            
                            print(f"  {date}: {price:,}원, MACD={macd_line:.4f}, Signal={macd_signal:.4f}, Hist={macd_hist:.4f} {cross_icon}")
                        
                        # 4. 골든크로스 분석
                        print(f"\n🎯 골든크로스 분석:")
                        macd_analysis = self.detect_macd_golden_cross(df_with_macd)
                        
                        for key, value in macd_analysis.items():
                            print(f"  {key}: {value}")
                        
                        # 5. 종합 신호 (만약 함수가 있다면)
                        if hasattr(self, 'calculate_enhanced_momentum_signals'):
                            print(f"\n🎯 종합 신호:")
                            try:
                                signals = self.calculate_enhanced_momentum_signals(df_with_macd)
                                print(f"  신호: {signals['signal']}")
                                print(f"  강도: {signals['strength']:.2f}")
                                if 'signal_components' in signals:
                                    print(f"  구성요소: {signals['signal_components']}")
                            except Exception as e:
                                print(f"  ❌ 종합 신호 계산 실패: {e}")
                    else:
                        print(f"❌ MACD 계산 실패 - macd_line 컬럼 없음")
                        
                except Exception as e:
                    print(f"❌ MACD 계산 오류: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"❌ 데이터 부족: {len(df)} < 35일")
    
    def simple_macd_implementation(self, df: pd.DataFrame, price_col: str = 'stck_prpr') -> pd.DataFrame:
        """간단하고 안전한 MACD 구현"""
        try:
            if len(df) < 35 or price_col not in df.columns:
                return df
            
            # 가격 데이터 정리
            prices = df[price_col].astype(float).ffill()
            
            # EMA 계산
            ema12 = prices.ewm(span=12, adjust=False).mean()
            ema26 = prices.ewm(span=26, adjust=False).mean()
            
            # MACD 지표 계산
            df['macd_line'] = ema12 - ema26
            df['macd_signal'] = df['macd_line'].ewm(span=9, adjust=False).mean()
            df['macd_histogram'] = df['macd_line'] - df['macd_signal']
            
            # 골든크로스/데드크로스 감지
            df['macd_cross'] = 0
            for i in range(1, len(df)):
                current_macd = df['macd_line'].iloc[i]
                current_signal = df['macd_signal'].iloc[i]
                prev_macd = df['macd_line'].iloc[i-1]
                prev_signal = df['macd_signal'].iloc[i-1]
                
                if current_macd > current_signal and prev_macd <= prev_signal:
                    df.iloc[i, df.columns.get_loc('macd_cross')] = 1  # 골든크로스
                elif current_macd < current_signal and prev_macd >= prev_signal:
                    df.iloc[i, df.columns.get_loc('macd_cross')] = -1  # 데드크로스
            
            print(f"✅ MACD 계산 완료: {len(df)}개 데이터")
            return df
            
        except Exception as e:
            print(f"❌ MACD 계산 실패: {e}")
            return df
    
    def analyze_macd_signals_simple(self, df: pd.DataFrame) -> Dict:
        """간단한 MACD 신호 분석"""
        try:
            if 'macd_cross' not in df.columns or len(df) < 10:
                return {
                    'golden_cross': False,
                    'signal_strength': 0,
                    'current_trend': 'neutral'
                }
            
            # 최근 5일 내 골든크로스 확인
            recent_crosses = df['macd_cross'].tail(5)
            golden_cross = any(recent_crosses == 1)
            dead_cross = any(recent_crosses == -1)
            
            # 현재 상태
            latest = df.iloc[-1]
            macd_above_signal = latest['macd_line'] > latest['macd_signal']
            macd_above_zero = latest['macd_line'] > 0
            
            # 신호 강도 계산
            signal_strength = 0
            current_trend = 'neutral'
            
            if golden_cross:
                signal_strength = 2.0
                current_trend = 'bullish'
                
                if macd_above_zero:
                    signal_strength += 1.0
                
                # 골든크로스 발생 시점 확인
                cross_age = 999
                for i in range(len(df)-1, max(0, len(df)-6), -1):
                    if df['macd_cross'].iloc[i] == 1:
                        cross_age = len(df) - i - 1
                        break
                
                if cross_age <= 2:  # 최근 2일 내
                    signal_strength += 0.5
                    
            elif dead_cross:
                current_trend = 'bearish'
                signal_strength = -1.0
            elif macd_above_signal and macd_above_zero:
                current_trend = 'bullish'
                signal_strength = 1.0
            elif not macd_above_signal and not macd_above_zero:
                current_trend = 'bearish'
                signal_strength = -0.5
            
            return {
                'golden_cross': golden_cross,
                'signal_strength': signal_strength,
                'current_trend': current_trend,
                'macd_above_zero': macd_above_zero,
                'macd_above_signal': macd_above_signal,
                'recent_cross_age': cross_age if golden_cross else 999
            }
            
        except Exception as e:
            print(f"❌ MACD 신호 분석 실패: {e}")
            return {
                'golden_cross': False,
                'signal_strength': 0,
                'current_trend': 'neutral'
            }
    
    def complete_macd_test(self):
        """완전한 MACD 테스트"""
        print("🚀 완전한 MACD 시스템 테스트")
        print("="*60)
        
        for symbol in self.symbols:
            stock_name = self.get_stock_name(symbol)
            print(f"\n📊 {symbol}({stock_name}) 완전 분석:")
            
            # 1. 일봉 데이터 조회
            df = self.get_daily_data(symbol, days=100)
            
            if df.empty:
                print("❌ 데이터 조회 실패")
                continue
            
            print(f"📅 데이터: {len(df)}일, 가격 범위: {df['stck_prpr'].min():,}~{df['stck_prpr'].max():,}")
            
            if len(df) < 35:
                print(f"❌ 데이터 부족: {len(df)} < 35")
                continue
            
            # 2. MACD 계산
            df_with_macd = self.simple_macd_implementation(df)
            
            # 3. 신호 분석
            signals = self.analyze_macd_signals_simple(df_with_macd)
            
            print(f"🎯 MACD 분석 결과:")
            print(f"  골든크로스: {signals['golden_cross']}")
            print(f"  신호 강도: {signals['signal_strength']:.1f}")
            print(f"  현재 추세: {signals['current_trend']}")
            print(f"  MACD > 0: {signals['macd_above_zero']}")
            print(f"  MACD > Signal: {signals['macd_above_signal']}")
            
            if signals['golden_cross']:
                print(f"  🌟 골든크로스 {signals['recent_cross_age']}일 전 발생!")
            
            # 4. 투자 권고
            if signals['signal_strength'] >= 2.0:
                print(f"  💰 투자 권고: 강한 매수 신호")
            elif signals['signal_strength'] >= 1.0:
                print(f"  📈 투자 권고: 약한 매수 신호")
            elif signals['signal_strength'] <= -1.0:
                print(f"  📉 투자 권고: 매도 신호")
            else:
                print(f"  ⏸️ 투자 권고: 관망")
    
    def get_extended_minute_data(self, symbol: str, days: int = 5) -> pd.DataFrame:
        """확장된 분봉 데이터 조회 - 여러 일자 조합"""
        all_data = []
        
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            
            # 주말 건너뛰기
            if date.weekday() >= 5:
                continue
                
            daily_minute_data = self.get_minute_data_for_date(symbol, date)
            if not daily_minute_data.empty:
                all_data.append(daily_minute_data)
        
        if all_data:
            combined_df = pd.concat(all_data, ignore_index=True)
            # 시간순 정렬
            combined_df = combined_df.sort_values('stck_cntg_hour').reset_index(drop=True)
            
            self.logger.info(f"📊 {symbol} 확장 분봉 데이터: {len(combined_df)}개 봉")
            return combined_df
        
        return pd.DataFrame()
    
    def get_minute_data_for_date(self, symbol: str, date: datetime) -> pd.DataFrame:
        """특정 날짜의 분봉 데이터 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010200"
        }
    
        # 해당 날짜의 장마감 시간으로 설정
        end_time = "153000"  # 15:30:00
        target_date = date.strftime("%Y%m%d")
    
        params = {
            "fid_etc_cls_code": "",
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol,
            "fid_input_hour_1": end_time,
            "fid_pw_data_incu_yn": "Y",
            "fid_input_date_1": target_date  # 날짜 지정
        }
    
        try:
            response = requests.get(url, headers=headers, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()
    
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                if not df.empty:
                    # 시간 컬럼 추가
                    df['stck_cntg_hour'] = pd.to_datetime(
                        target_date + df['stck_cntg_hour'], 
                        format='%Y%m%d%H%M%S',
                        errors='coerce'
                    )
                    
                    numeric_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'cntg_vol']
                    for col in numeric_cols:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    return df
    
        except Exception as e:
            self.logger.debug(f"분봉 데이터 조회 실패 ({symbol}, {target_date}): {e}")
    
        return pd.DataFrame()
    
    def test_macd_with_daily_data(self):
        """일봉 데이터로 MACD 테스트"""
        print("🧪 일봉 데이터로 MACD 테스트")
        print("="*60)
        
        for symbol in self.symbols:
            stock_name = self.get_stock_name(symbol)
            print(f"\n📊 {symbol}({stock_name}) 일봉 MACD 분석:")
            
            # 일봉 데이터 조회 (100일)
            df = self.get_daily_data(symbol, days=100)
            
            if df.empty:
                print("❌ 일봉 데이터를 가져올 수 없습니다")
                continue
            
            print(f"📅 일봉 데이터: {len(df)}일")
            print(f"가격 범위: {df['stck_prpr'].min():,} ~ {df['stck_prpr'].max():,}")
            print(f"최근 가격: {df['stck_prpr'].iloc[-1]:,}원")
            
            if len(df) >= 35:
                # MACD 계산 (일봉 기준)
                try:
                    df_with_macd = self.calculate_macd(df)
                    macd_analysis = self.detect_macd_golden_cross(df_with_macd)
                    
                    print(f"🎯 일봉 MACD 분석:")
                    print(f"  - 골든크로스: {macd_analysis['golden_cross']}")
                    print(f"  - 크로스 강도: {macd_analysis['cross_strength']:.2f}")
                    print(f"  - 신호 나이: {macd_analysis['signal_age']}일")
                    print(f"  - MACD > 0: {macd_analysis.get('macd_above_zero', False)}")
                    print(f"  - 히스토그램 추세: {macd_analysis['histogram_trend']}")
                    
                    # 최근 5일 MACD 상태
                    if 'macd_line' in df_with_macd.columns:
                        print(f"\n📈 최근 5일 MACD 상태:")
                        recent_data = df_with_macd.tail(5)
                        for i, row in recent_data.iterrows():
                            date = row.get('stck_bsop_date', f'Day{i}')
                            macd_val = row.get('macd_line', 0)
                            signal_val = row.get('macd_signal', 0)
                            hist_val = row.get('macd_histogram', 0)
                            cross_val = row.get('macd_cross', 0)
                            
                            cross_symbol = ""
                            if cross_val == 1:
                                cross_symbol = "🌟"
                            elif cross_val == -1:
                                cross_symbol = "💀"
                            
                            print(f"  {date}: MACD={macd_val:.4f}, Signal={signal_val:.4f}, Hist={hist_val:.4f} {cross_symbol}")
                    
                    # 종합 신호 계산
                    if hasattr(self, 'calculate_enhanced_momentum_signals'):
                        signals = self.calculate_enhanced_momentum_signals(df_with_macd)
                        print(f"\n🎯 종합 신호 (일봉 기준):")
                        print(f"  신호: {signals['signal']}")
                        print(f"  강도: {signals['strength']:.2f}")
                        print(f"  구성요소: {signals.get('signal_components', [])}")
                    
                except Exception as e:
                    print(f"❌ MACD 계산 오류: {e}")
            else:
                print(f"❌ 데이터 부족: {len(df)} < 35일")
    
    def fix_minute_data_issue(self):
        """분봉 데이터 문제 해결"""
        print("🔧 분봉 데이터 문제 해결 중...")
        
        # 현재 분봉 데이터 조회 함수 상태 확인
        test_symbol = self.symbols[0] if self.symbols else "005930"
        
        print(f"🧪 {test_symbol} 분봉 데이터 테스트:")
        
        # 1. 기본 분봉 조회
        df1 = self.get_minute_data(test_symbol, minutes=60)
        print(f"  기본 60분봉: {len(df1)}개")
        
        # 2. 더 많은 분봉 조회 시도
        df2 = self.get_minute_data(test_symbol, minutes=200)
        print(f"  확장 200분봉: {len(df2)}개")
        
        # 3. 일봉 조회
        df3 = self.get_daily_data(test_symbol, days=50)
        print(f"  일봉 50일: {len(df3)}개")
        
        # 4. 데이터 내용 확인
        if not df1.empty:
            unique_prices = df1['stck_prpr'].nunique()
            print(f"  분봉 고유가격 수: {unique_prices}개")
            if unique_prices == 1:
                print("  ⚠️ 모든 분봉이 동일한 가격 (장마감 후 상태)")
        
        if not df3.empty:
            unique_prices = df3['stck_prpr'].nunique()
            print(f"  일봉 고유가격 수: {unique_prices}개")
            price_range = df3['stck_prpr'].max() - df3['stck_prpr'].min()
            print(f"  일봉 가격 변동폭: {price_range:,}원")
        
        # 권장사항
        print(f"\n💡 권장사항:")
        if df3.empty or len(df3) < 35:
            print("  ❌ 일봉 데이터도 부족합니다")
            print("  📞 KIS API 문제이거나 계좌 권한 문제일 수 있습니다")
        else:
            print("  ✅ 일봉 데이터 사용을 권장합니다")
            print("  📊 MACD는 일봉에서 더 안정적으로 작동합니다")
    
    def create_hybrid_macd_strategy(self):
        """일봉/분봉 하이브리드 MACD 전략"""
        print("🚀 하이브리드 MACD 전략 생성")
        
        # 일봉으로 중장기 추세 파악, 분봉으로 진입 타이밍 결정
        def hybrid_macd_signals(symbol: str) -> Dict:
            """하이브리드 MACD 신호"""
            
            # 1. 일봉으로 중장기 추세 파악
            daily_df = self.get_daily_data(symbol, days=100)
            daily_trend = 'neutral'
            
            if not daily_df.empty and len(daily_df) >= 35:
                daily_df = self.calculate_macd(daily_df)
                daily_macd = self.detect_macd_golden_cross(daily_df)
                
                if daily_macd['golden_cross'] and daily_macd['signal_age'] <= 5:
                    daily_trend = 'bullish'
                elif daily_macd.get('macd_above_zero', False):
                    daily_trend = 'bullish'
                elif not daily_macd.get('macd_above_zero', True):
                    daily_trend = 'bearish'
            
            # 2. 분봉으로 단기 신호 (가능한 경우만)
            minute_df = self.get_minute_data(symbol, minutes=100)
            minute_signal = 'HOLD'
            minute_strength = 0
            
            if not minute_df.empty and len(minute_df) >= 35:
                try:
                    signals = self.calculate_enhanced_momentum_signals(minute_df)
                    minute_signal = signals['signal']
                    minute_strength = signals['strength']
                except:
                    pass
            
            # 3. 하이브리드 판단
            final_signal = 'HOLD'
            final_strength = 0
            
            if daily_trend == 'bullish':
                if minute_signal == 'BUY':
                    final_signal = 'BUY'
                    final_strength = minute_strength + 1.0  # 일봉 추세 보너스
                elif minute_signal == 'HOLD':
                    final_signal = 'BUY'
                    final_strength = 2.0  # 일봉 추세만으로 약한 매수
            elif daily_trend == 'bearish' and minute_signal == 'SELL':
                final_signal = 'SELL'
                final_strength = minute_strength + 0.5
            
            return {
                'signal': final_signal,
                'strength': min(final_strength, 5.0),
                'daily_trend': daily_trend,
                'minute_signal': minute_signal,
                'strategy': 'hybrid_macd'
            }
        
        # 함수 바인딩
        self.hybrid_macd_signals = hybrid_macd_signals
        print("✅ 하이브리드 MACD 전략 생성 완료")
    
    def ensure_required_attributes(self):
        """필수 속성들이 있는지 확인하고 없으면 초기화"""
        
        # MACD 관련 속성들
        if not hasattr(self, 'macd_fast'):
            self.macd_fast = 12
        if not hasattr(self, 'macd_slow'):
            self.macd_slow = 26
        if not hasattr(self, 'macd_signal'):
            self.macd_signal = 9
        if not hasattr(self, 'macd_cross_lookback'):
            self.macd_cross_lookback = 3
        if not hasattr(self, 'macd_trend_confirmation'):
            self.macd_trend_confirmation = 5
        
        # API 오류 관련 속성들
        if not hasattr(self, 'skip_stock_name_api'):
            self.skip_stock_name_api = False
        if not hasattr(self, 'api_error_count'):
            self.api_error_count = 0
        
        # 포지션 관리 관련
        if not hasattr(self, 'all_positions'):
            self.all_positions = {}
        if not hasattr(self, 'use_improved_logic'):
            self.use_improved_logic = True
        
        self.logger.debug("✅ 필수 속성 확인 완료")
    #END----------------------

# 포지션 관리 디버깅용 명령어들
def debug_position_management():
    """포지션 관리 시스템 디버깅"""
    trader = KISAutoTrader()
    
    print("🔧 포지션 관리 시스템 디버깅")
    print("="*50)
    
    # 1. 현재 설정 확인
    print(f"최대 매수 횟수: {trader.max_purchases_per_symbol}")
    print(f"최대 보유 수량: {trader.max_quantity_per_symbol}")
    print(f"최소 보유 기간: {trader.min_holding_period_hours}시간")
    print(f"재매수 금지 기간: {trader.purchase_cooldown_hours}시간")
    
    # 2. 포지션 상태 출력
    trader.print_position_status()
    
    # 3. 제한 상황 체크
    trader.check_position_restrictions()
    
    # 4. 매수 이력 요약
    history_summary = trader.get_purchase_history_summary()
    print(f"\n📈 매수 이력 요약:")
    print(f"   총 매수 횟수: {history_summary['total_purchases']}")
    print(f"   거래한 종목: {history_summary['total_symbols_traded']}")
    print(f"   평균 보유 시간: {history_summary['average_holding_time']:.1f}시간")
    print(f"   활성 포지션: {history_summary['active_positions']}")
   

# 테스트용 함수 업데이트
def test_enhanced_positions():
    """향상된 포지션 테스트"""
    trader = KISAutoTrader()
    
    print("🧪 향상된 포지션 테스트")
    print("="*50)
    
    trader.debug_all_positions_enhanced()


# 추가로, 더 나은 에러 처리를 위한 함수들:
def check_dependencies():
    """필수 라이브러리 확인"""
    required_modules = ['requests', 'pandas', 'numpy', 'yaml']
    missing_modules = []
    
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing_modules.append(module)
    
    if missing_modules:
        print(f"❌ 필수 라이브러리가 설치되지 않았습니다: {', '.join(missing_modules)}")
        print("다음 명령어로 설치하세요:")
        print(f"pip install {' '.join(missing_modules)}")
        return False
    
    return True

def check_config_file():
    """설정 파일 존재 확인"""
    if not os.path.exists('config.yaml'):
        print("❌ config.yaml 파일이 없습니다.")
        print("샘플 설정 파일을 생성하시겠습니까? (y/n): ", end="")
        
        try:
            response = input().lower()
            if response in ['y', 'yes', '예']:
                from dynamic_autotrader import KISAutoTrader
                trader = KISAutoTrader.__new__(KISAutoTrader)  # __init__ 호출하지 않고 생성
                trader.create_sample_config('config.yaml')
                print("✅ config.yaml 파일이 생성되었습니다. 설정을 입력한 후 다시 실행하세요.")
            return False
        except KeyboardInterrupt:
            print("\n프로그램을 종료합니다.")
            return False
    
    return True

# main 함수 수정 (더 안전한 버전)
def main():
    """안전한 메인 실행 함수"""
    
    # 의존성 확인
    if not check_dependencies():
        sys.exit(1)
    
    # 설정 파일 확인
    if not check_config_file():
        sys.exit(1)
    
    try:
        trader = KISAutoTrader()
        
        # 연결 테스트
        token = trader.get_access_token()
        if not token:
            trader.logger.error("❌ KIS API 연결 실패")
            return
            
        trader.logger.info("✅ KIS API 연결 테스트 성공")
        
        # 실행 모드 결정
        debug_mode = '--debug' in sys.argv
        improved_mode = '--improved' in sys.argv
        
        trader.logger.info(f"🚀 실행 모드: {'디버그' if debug_mode else '일반'}, {'개선된' if improved_mode else '기본'}")
        
        # 적절한 모드로 실행
        if debug_mode and improved_mode:
            trader.run_debug_improved(interval_minutes=1)
        elif improved_mode:
            trader.run_improved_with_correct_hours(interval_minutes=5)
        elif debug_mode:
            trader.run_debug(interval_minutes=1)
        else:
            trader.run(interval_minutes=5)
            
    except FileNotFoundError as e:
        print(f"❌ 필수 파일이 없습니다: {e}")
        print("config.yaml 파일을 확인하세요.")
    except KeyboardInterrupt:
        print("\n🛑 사용자가 프로그램을 종료했습니다.")
    except Exception as e:
        print(f"❌ 프로그램 실행 중 오류: {e}")
        import traceback
        print(f"상세 오류:\n{traceback.format_exc()}")



def standalone_macd_test():
    """독립적인 MACD 테스트 - 초기화 문제 회피"""
    print("🧪 독립적 MACD 테스트 (초기화 문제 회피)")
    print("="*60)
    
    # 직접 API 호출로 데이터 가져오기
    import yaml
    
    try:
        # config 로드
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        app_key = config['kis']['app_key']
        app_secret = config['kis']['app_secret']
        base_url = config['kis']['base_url']
        
        # 토큰 로드
        try:
            with open('token.json', 'r', encoding='utf-8') as f:
                token_data = json.load(f)
            access_token = token_data.get('access_token')
        except:
            print("❌ 토큰 파일을 찾을 수 없습니다")
            return
        
        # 테스트 종목
        test_symbols = ['042660', '062040', '272210', '161580']
        
        for symbol in test_symbols:
            print(f"\n📊 {symbol} 독립 MACD 테스트:")
            
            # 일봉 데이터 직접 조회
            url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {access_token}",
                "appkey": app_key,
                "appsecret": app_secret,
                "tr_id": "FHKST03010100"
            }
            
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=100)).strftime("%Y%m%d")
            
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": symbol,
                "fid_input_date_1": start_date,
                "fid_input_date_2": end_date,
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "0"
            }
            
            try:
                response = requests.get(url, headers=headers, params=params, timeout=15)
                data = response.json()
                
                if data.get('output2'):
                    df = pd.DataFrame(data['output2'])
                    df = df.sort_values('stck_bsop_date').reset_index(drop=True)
                    
                    # 컬럼명 매핑
                    if 'stck_clpr' in df.columns:
                        df['stck_prpr'] = pd.to_numeric(df['stck_clpr'], errors='coerce')
                    
                    if len(df) >= 35 and 'stck_prpr' in df.columns:
                        # 간단한 MACD 계산
                        prices = df['stck_prpr'].dropna()
                        ema12 = prices.ewm(span=12).mean()
                        ema26 = prices.ewm(span=26).mean()
                        macd_line = ema12 - ema26
                        signal_line = macd_line.ewm(span=9).mean()
                        
                        # 골든크로스 찾기
                        golden_crosses = []
                        for i in range(1, len(macd_line)):
                            if (macd_line.iloc[i] > signal_line.iloc[i] and 
                                macd_line.iloc[i-1] <= signal_line.iloc[i-1]):
                                golden_crosses.append(i)
                        
                        print(f"  📅 데이터: {len(df)}일")
                        print(f"  💰 가격: {prices.iloc[-1]:,}원")
                        print(f"  📈 MACD: {macd_line.iloc[-1]:.4f}")
                        print(f"  📊 Signal: {signal_line.iloc[-1]:.4f}")
                        print(f"  🌟 골든크로스: {len(golden_crosses)}회")
                        
                        if golden_crosses:
                            last_cross = golden_crosses[-1]
                            days_ago = len(df) - last_cross - 1
                            print(f"  🎯 최근 골든크로스: {days_ago}일 전")
                            
                            if days_ago <= 5:
                                print(f"  💰 투자 권고: 매수 고려")
                    else:
                        print(f"  ❌ 데이터 부족 또는 컬럼 없음")
                else:
                    print(f"  ❌ API 데이터 없음")
                    
            except Exception as e:
                print(f"  ❌ API 호출 실패: {e}")
    
    except Exception as e:
        print(f"❌ 독립 테스트 실패: {e}")



# 메인 테스트 함수 업데이트
def main_macd_test():
    print("🚀 완전한 MACD 시스템 테스트")
    print("="*60)
    
    try:
        trader = KISAutoTrader()
        
        # 완전한 MACD 테스트 실행
        trader.complete_macd_test()
        
    except Exception as e:
        print(f"❌ 테스트 실패: {e}")
        import traceback
        traceback.print_exc()

# 메인 실행 함수
if __name__ == "__main__":
    # 테스트 함수들 실행
    if '--test-enhanced-positions' in sys.argv:
        test_enhanced_positions()
        sys.exit(0)

    if '--debug-position' in sys.argv:
        debug_position_management()
        sys.exit(0)

    if '--debug-market-hours' in sys.argv:
        # 장 시간 테스트 함수 (위에서 정의된 함수)
        try:
            from dynamic_autotrader import KISAutoTrader
            trader = KISAutoTrader()

            print("🕐 한국 증시 시간 테스트")
            print("="*50)

            current_time = datetime.now()
            print(f"현재 시간: {current_time.strftime('%Y-%m-%d %H:%M:%S (%A)')}")

            market_info = trader.get_market_status_info(current_time)
            print(f"장 상태: {market_info['status']}")
            print(f"상태 메시지: {market_info['message']}")
            print(f"다음 변경: {market_info['next_change'].strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"거래 가능: {'예' if market_info['is_trading_time'] else '아니오'}")
        except Exception as e:
            print(f"장 시간 테스트 오류: {e}")
        sys.exit(0)

    # 메인 프로그램 실행
    if '--test-macd' in sys.argv:
        main_macd_test()
    else:
        main()
