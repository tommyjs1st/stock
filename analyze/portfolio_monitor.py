"""
키움 포트폴리오 모니터링 모듈
보유종목 조회 및 DB 저장
"""
import sys
import logging
from datetime import datetime
from typing import Dict, List
import pandas as pd

from kiwoom_api_client import KiwoomAPIClient


class PortfolioMonitor:
    """포트폴리오 모니터링 클래스"""
    
    def __init__(self, db_manager=None, logger=None):
        """
        초기화
        
        Args:
            db_manager: DBManager 인스턴스 (analyze/db_manager.py)
            logger: 로거 인스턴스
        """
        self.logger = logger or logging.getLogger(__name__)
        self.db_manager = db_manager
        
        # 키움 API 클라이언트
        self.kiwoom_client = KiwoomAPIClient()
        
        # 통계
        self.stats = {
            'total_accounts': 0,
            'total_stocks': 0,
            'success_count': 0,
            'fail_count': 0
        }
    
    def collect_holdings(self, account_aliases: List[str] = None) -> pd.DataFrame:
        """
        보유종목 수집
        
        Args:
            account_aliases: 조회할 계좌 별칭 리스트 (None이면 전체 활성 계좌)
            
        Returns:
            DataFrame: 보유종목 데이터
        """
        self.logger.info("=" * 60)
        self.logger.info("📊 포트폴리오 수집 시작")
        self.logger.info("=" * 60)
        
        start_time = datetime.now()
        
        try:
            # 보유종목 조회
            if account_aliases:
                df = self.kiwoom_client.get_holdings_by_accounts(account_aliases)
            else:
                df = self.kiwoom_client.get_holdings_all()
            
            if df.empty:
                self.logger.warning("⚠️ 보유종목이 없습니다.")
                return df
            
            # 통계 업데이트
            self.stats['total_accounts'] = df['account_alias'].nunique()
            self.stats['total_stocks'] = len(df)
            
            # 요약 출력
            self.logger.info(f"✅ 수집 완료: {self.stats['total_accounts']}개 계좌, "
                           f"{self.stats['total_stocks']}개 종목")
            
            # 계좌별 요약
            for alias in df['account_alias'].unique():
                account_df = df[df['account_alias'] == alias]
                total_eval = account_df['eval_amount'].sum()
                total_profit = account_df['profit_loss'].sum()
                
                self.logger.info(
                    f"  📈 {alias}: {len(account_df)}개 종목, "
                    f"평가금액 {total_eval:,.0f}원, "
                    f"손익 {total_profit:+,.0f}원"
                )
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            self.logger.info(f"⏱️ 소요시간: {duration:.1f}초")
            
            return df
            
        except Exception as e:
            self.logger.error(f"❌ 보유종목 수집 실패: {e}")
            raise
    
    def save_to_db(self, df: pd.DataFrame) -> bool:
        """
        보유종목을 DB에 저장
        
        Args:
            df: 보유종목 DataFrame
            
        Returns:
            bool: 성공 여부
        """
        if self.db_manager is None:
            self.logger.error("❌ DB Manager가 설정되지 않았습니다.")
            return False
        
        if df.empty:
            self.logger.info("💡 저장할 데이터가 없습니다.")
            return True
        
        self.logger.info("💾 DB 저장 시작...")
        
        try:
            success_count = 0
            fail_count = 0
            
            for _, row in df.iterrows():
                try:
                    # UPSERT 쿼리
                    query = """
                    INSERT INTO portfolio_holdings 
                        (account_no, account_alias, stock_code, stock_name, 
                         quantity, avg_price, current_price, purchase_amount,
                         eval_amount, profit_loss, profit_rate, updated_at)
                    VALUES 
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON DUPLICATE KEY UPDATE
                        stock_name = VALUES(stock_name),
                        quantity = VALUES(quantity),
                        avg_price = VALUES(avg_price),
                        current_price = VALUES(current_price),
                        purchase_amount = VALUES(purchase_amount),
                        eval_amount = VALUES(eval_amount),
                        profit_loss = VALUES(profit_loss),
                        profit_rate = VALUES(profit_rate),
                        updated_at = NOW()
                    """
                    
                    params = (
                        row['account_no'],
                        row['account_alias'],
                        row['stock_code'],
                        row['stock_name'],
                        int(row['quantity']),
                        float(row['avg_price']),
                        float(row['current_price']),
                        float(row.get('purchase_amount', 0)),
                        float(row['eval_amount']),
                        float(row['profit_loss']),
                        float(row['profit_rate'])
                    )
                    
                    self.db_manager.execute_query(query, params)
                    success_count += 1
                    
                except Exception as e:
                    self.logger.error(
                        f"❌ DB 저장 실패 ({row['stock_code']}): {e}"
                    )
                    fail_count += 1
            
            # 커밋
            self.db_manager.commit()
            
            self.stats['success_count'] = success_count
            self.stats['fail_count'] = fail_count
            
            self.logger.info(
                f"✅ DB 저장 완료: 성공 {success_count}건, 실패 {fail_count}건"
            )
            
            return fail_count == 0
            
        except Exception as e:
            self.logger.error(f"❌ DB 저장 중 오류: {e}")
            self.db_manager.rollback()
            return False
    
    def save_account_balance(self, account_aliases: List[str] = None) -> bool:
        """
        계좌 잔고 요약 정보 저장
        
        Args:
            account_aliases: 조회할 계좌 별칭 리스트
            
        Returns:
            bool: 성공 여부
        """
        if self.db_manager is None:
            self.logger.error("❌ DB Manager가 설정되지 않았습니다.")
            return False
        
        self.logger.info("💰 계좌 잔고 정보 저장 중...")
        
        try:
            from kiwoom_config import KiwoomConfig
            
            # 조회할 계좌 결정
            if account_aliases:
                accounts = {
                    alias: KiwoomConfig.get_account(alias)
                    for alias in account_aliases
                    if KiwoomConfig.get_account(alias)
                }
            else:
                accounts = KiwoomConfig.get_enabled_accounts()
            
            today = datetime.now().date()
            
            for alias, account_info in accounts.items():
                account_no = account_info['account_no']
                
                # 잔고 조회
                balance = self.kiwoom_client.get_account_balance(account_no)
                
                if not balance:
                    self.logger.warning(f"⚠️ 잔고 조회 실패: {alias}")
                    continue
                
                # DB 저장
                query = """
                INSERT INTO account_balance 
                    (account_no, account_alias, date, total_eval_amount,
                     total_purchase_amount, total_profit_loss, profit_loss_rate,
                     deposit, holdings_count, created_at)
                VALUES 
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    total_eval_amount = VALUES(total_eval_amount),
                    total_purchase_amount = VALUES(total_purchase_amount),
                    total_profit_loss = VALUES(total_profit_loss),
                    profit_loss_rate = VALUES(profit_loss_rate),
                    deposit = VALUES(deposit),
                    holdings_count = VALUES(holdings_count),
                    created_at = NOW()
                """
                
                params = (
                    account_no,
                    alias,
                    today,
                    balance.get('total_eval_amount', 0),
                    balance.get('total_purchase_amount', 0),
                    balance.get('total_profit_loss', 0),
                    balance.get('profit_loss_rate', 0),
                    balance.get('deposit', 0),
                    balance.get('holdings_count', 0)
                )
                
                self.db_manager.execute_query(query, params)
            
            self.db_manager.commit()
            self.logger.info("✅ 계좌 잔고 정보 저장 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 계좌 잔고 저장 실패: {e}")
            self.db_manager.rollback()
            return False
    
    def save_history(self, df: pd.DataFrame, date=None) -> bool:
        """
        포트폴리오 히스토리 저장 (일별 스냅샷)
        
        Args:
            df: 보유종목 DataFrame
            date: 기준일 (None이면 오늘)
            
        Returns:
            bool: 성공 여부
        """
        if self.db_manager is None:
            self.logger.error("❌ DB Manager가 설정되지 않았습니다.")
            return False
        
        if df.empty:
            return True
        
        if date is None:
            date = datetime.now().date()
        
        self.logger.info(f"📅 히스토리 저장 중 ({date})...")
        
        try:
            for _, row in df.iterrows():
                query = """
                INSERT INTO portfolio_history 
                    (account_no, account_alias, stock_code, stock_name, date,
                     quantity, avg_price, close_price, eval_amount,
                     profit_loss, profit_rate, created_at)
                VALUES 
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    stock_name = VALUES(stock_name),
                    quantity = VALUES(quantity),
                    avg_price = VALUES(avg_price),
                    close_price = VALUES(close_price),
                    eval_amount = VALUES(eval_amount),
                    profit_loss = VALUES(profit_loss),
                    profit_rate = VALUES(profit_rate),
                    created_at = NOW()
                """
                
                params = (
                    row['account_no'],
                    row['account_alias'],
                    row['stock_code'],
                    row['stock_name'],
                    date,
                    int(row['quantity']),
                    float(row['avg_price']),
                    float(row['current_price']),  # 종가로 사용
                    float(row['eval_amount']),
                    float(row['profit_loss']),
                    float(row['profit_rate'])
                )
                
                self.db_manager.execute_query(query, params)
            
            self.db_manager.commit()
            self.logger.info("✅ 히스토리 저장 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 히스토리 저장 실패: {e}")
            self.db_manager.rollback()
            return False
    
    def run(
        self, 
        account_aliases: List[str] = None,
        save_history: bool = True
    ) -> Dict:
        """
        전체 모니터링 프로세스 실행
        
        Args:
            account_aliases: 조회할 계좌 별칭 리스트
            save_history: 히스토리 저장 여부
            
        Returns:
            Dict: 실행 결과 통계
        """
        start_time = datetime.now()
        
        try:
            # 1. 보유종목 수집
            df = self.collect_holdings(account_aliases)
            
            if df.empty:
                return self.stats
            
            # 2. DB 저장
            if self.db_manager:
                # 현재 보유종목 저장
                self.save_to_db(df)
                
                # 계좌 잔고 저장
                self.save_account_balance(account_aliases)
                
                # 히스토리 저장
                if save_history:
                    self.save_history(df)
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # 실행 로그 저장
            if self.db_manager:
                self._save_monitor_log(start_time, end_time, duration)
            
            return self.stats
            
        except Exception as e:
            self.logger.error(f"❌ 모니터링 실행 실패: {e}")
            
            # 에러 로그 저장
            if self.db_manager:
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                self._save_monitor_log(start_time, end_time, duration, str(e))
            
            raise
    
    def _save_monitor_log(
        self, 
        start_time: datetime,
        end_time: datetime,
        duration: float,
        error_message: str = None
    ):
        """모니터링 실행 로그 저장"""
        try:
            query = """
            INSERT INTO portfolio_monitor_log 
                (run_type, total_accounts, total_stocks, success_count,
                 fail_count, start_time, end_time, duration_seconds,
                 error_message, created_at)
            VALUES 
                (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """
            
            params = (
                'manual',
                self.stats['total_accounts'],
                self.stats['total_stocks'],
                self.stats['success_count'],
                self.stats['fail_count'],
                start_time,
                end_time,
                int(duration),
                error_message
            )
            
            self.db_manager.execute_query(query, params)
            self.db_manager.commit()
            
        except Exception as e:
            self.logger.error(f"❌ 실행 로그 저장 실패: {e}")
