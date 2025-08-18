"""
설정 관리 모듈
"""
import yaml
import os
from typing import Dict, Any
from pathlib import Path


class ConfigManager:
    """설정 파일 관리 클래스"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = {}
        self.load_config()
    
    def load_config(self):
        """설정 파일 로드"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
        except FileNotFoundError:
            self.create_sample_config()
            raise Exception(f"설정 파일이 없습니다. {self.config_path} 파일을 생성했으니 설정을 입력해주세요.")
        except Exception as e:
            raise Exception(f"설정 파일 로드 중 오류: {e}")
    
    def get_kis_config(self) -> Dict[str, str]:
        """KIS API 설정 반환"""
        return self.config.get('kis', {})
    
    def get_trading_config(self) -> Dict[str, Any]:
        """거래 설정 반환"""
        return self.config.get('trading', {})
    
    def get_position_config(self) -> Dict[str, Any]:
        """포지션 관리 설정 반환"""
        return self.config.get('position_management', {})
    
    def get_notification_config(self) -> Dict[str, Any]:
        """알림 설정 반환"""
        return self.config.get('notification', {})
    
    def get_backtest_config(self) -> Dict[str, Any]:
        """백테스트 설정 반환"""
        return self.config.get('backtest', {})
    
    def get_openapi_config(self) -> Dict[str, Any]:
        """백테스트 설정 반환"""
        return self.config.get('openapi', {})
    
    def get_system_config(self) -> Dict[str, Any]:
        """시스템 설정 반환"""
        return self.config.get('system', {
            'auto_shutdown_enabled': True,
            'weekend_shutdown_enabled': True,
            'shutdown_delay_hours': 1
        })

    def get_daily_strategy_config(self) -> Dict[str, Any]:
        """일봉 전략 설정 반환"""
        return self.config.get('daily_strategy', {})
    
    def get_minute_timing_config(self) -> Dict[str, Any]:
        """분봉 타이밍 설정 반환"""
        return self.config.get('minute_timing', {})
    
    def create_sample_config(self):
        """샘플 설정 파일 생성"""
        sample_config = {
            'kis': {
                'app_key': 'YOUR_APP_KEY',
                'app_secret': 'YOUR_APP_SECRET',
                'base_url': 'https://openapi.koreainvestment.com:9443',
                'account_no': 'YOUR_ACCOUNT_NO'
            },
            'trading': {
                'max_symbols': 3,
                'max_position_ratio': 0.4,
                'daily_loss_limit': 0.05,
                'stop_loss_pct': 0.08,
                'take_profit_pct': 0.25,
                'strategy_type': 'hybrid',
                'symbols': ['005930', '035720', '042660']
            },
            'position_management': {
                'max_purchases_per_symbol': 2,
                'max_quantity_per_symbol': 300,
                'min_holding_period_hours': 72,
                'purchase_cooldown_hours': 48
            },
            'momentum': {
                'period': 20,
                'threshold': 0.02,
                'volume_threshold': 1.5,
                'ma_short': 5,
                'ma_long': 20
            },
            'daily_strategy': {
                'trend_analysis_days': 180,
                'min_buy_score': 5.0,
                'min_sell_score': 3.0
            },
            'minute_timing': {
                'min_timing_score': 4,
                'sell_timing_score': 3,
                'rsi_period': 14,
                'volume_lookback': 20,
                'max_spread': 500
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
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(sample_config, f, default_flow_style=False, allow_unicode=True)
