"""
키움 REST API 설정 모듈
config.yaml 파일 기반 설정 로드
"""
import os
import yaml
from typing import Dict, Any


class KiwoomConfig:
    """키움 REST API 설정 클래스 (config.yaml 기반)"""
    
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
        self.config = self._load_config()
        
        # 키움 설정 추출
        kiwoom_config = self.config.get('kiwoom', {})
        
        # API 기본 정보
        self.BASE_URL = kiwoom_config.get('base_url', 'https://api.kiwoom.com')
        self.APP_KEY = kiwoom_config.get('app_key', '')
        self.APP_SECRET = kiwoom_config.get('app_secret', '')
        
        # 토큰 파일
        self.TOKEN_FILE = "kiwoom_token.json"
        
        # 계좌 정보
        self.ACCOUNTS = kiwoom_config.get('accounts', {})
        
        # API 설정
        api_config = kiwoom_config.get('api', {})
        self.API_DELAY = api_config.get('call_delay', 0.2)
        self.MAX_RETRIES = api_config.get('max_retries', 3)
        self.TIMEOUT = api_config.get('timeout', 30)
        
        # 모니터링 설정
        self.MONITOR_CONFIG = kiwoom_config.get('monitor', {})
    
    def _load_config(self) -> Dict[str, Any]:
        """config.yaml 파일 로드"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"설정 파일을 찾을 수 없습니다: {self.config_path}\n"
                "config.yaml 파일에 kiwoom 섹션을 추가해주세요."
            )
        except Exception as e:
            raise Exception(f"설정 파일 로드 중 오류: {e}")
    
    def get_enabled_accounts(self) -> Dict:
        """활성화된 계좌 목록 반환"""
        return {
            alias: info 
            for alias, info in self.ACCOUNTS.items() 
            if info.get('enabled', False) and info.get('account_no')
        }
    
    def get_account(self, alias: str) -> Dict:
        """특정 계좌 정보 반환"""
        return self.ACCOUNTS.get(alias)
    
    def get_monitor_config(self) -> Dict:
        """모니터링 설정 반환"""
        return self.MONITOR_CONFIG
    
    def validate_config(self):
        """설정 유효성 검증"""
        errors = []
        
        if not self.APP_KEY:
            errors.append("KIWOOM app_key가 설정되지 않았습니다.")
        
        if not self.APP_SECRET:
            errors.append("KIWOOM app_secret이 설정되지 않았습니다.")
        
        enabled_accounts = self.get_enabled_accounts()
        if not enabled_accounts:
            errors.append("활성화된 계좌가 없습니다. 최소 1개 계좌를 설정해주세요.")
        
        if errors:
            raise ValueError("\n".join(errors))
        
        return True
