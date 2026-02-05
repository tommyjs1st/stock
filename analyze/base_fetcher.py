"""
증권사 API 공통 인터페이스
KIS, 키움 등 여러 증권사 API의 공통 추상 클래스
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional
import pandas as pd


class BaseAPIClient(ABC):
    """증권사 API 기본 추상 클래스"""
    
    @abstractmethod
    def get_access_token(self) -> str:
        """
        액세스 토큰 발급/갱신
        
        Returns:
            str: 액세스 토큰
        """
        pass
    
    @abstractmethod
    def get_account_balance(self, account_no: str) -> Dict:
        """
        계좌 잔고 조회
        
        Args:
            account_no: 계좌번호
            
        Returns:
            Dict: 계좌 잔고 정보
        """
        pass
    
    @abstractmethod
    def get_holdings(self, account_no: str) -> pd.DataFrame:
        """
        보유종목 조회
        
        Args:
            account_no: 계좌번호
            
        Returns:
            DataFrame: 보유종목 정보
                - stock_code: 종목코드
                - stock_name: 종목명
                - quantity: 보유수량
                - avg_price: 평균단가
                - current_price: 현재가
                - eval_amount: 평가금액
                - profit_loss: 평가손익
                - profit_rate: 수익률
        """
        pass
    
    @abstractmethod
    def get_current_price(self, stock_code: str) -> Optional[float]:
        """
        현재가 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            float: 현재가 (조회 실패시 None)
        """
        pass


class BaseStockFetcher(ABC):
    """주가 데이터 조회 공통 인터페이스"""
    
    @abstractmethod
    def get_period_price_data(
        self, 
        stock_code: str, 
        days: int = 90, 
        period: str = "D"
    ) -> Optional[pd.DataFrame]:
        """
        기간별 주가 데이터 조회
        
        Args:
            stock_code: 종목코드
            days: 조회 기간 (일)
            period: 기간 구분 (D:일봉, W:주봉, M:월봉)
            
        Returns:
            DataFrame: 주가 데이터
                - date: 날짜
                - open: 시가
                - high: 고가
                - low: 저가
                - close: 종가
                - volume: 거래량
        """
        pass
    
    @abstractmethod
    def get_investor_trading_data(
        self, 
        stock_code: str, 
        days: int = 30
    ) -> Optional[pd.DataFrame]:
        """
        투자자별 매매 데이터 조회
        
        Args:
            stock_code: 종목코드
            days: 조회 기간 (일)
            
        Returns:
            DataFrame: 투자자별 매매 데이터
                - date: 날짜
                - foreign_buy: 외국인 매수
                - foreign_sell: 외국인 매도
                - institution_buy: 기관 매수
                - institution_sell: 기관 매도
                - individual_buy: 개인 매수
                - individual_sell: 개인 매도
        """
        pass
