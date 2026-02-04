"""
MySQL 데이터베이스 관리 모듈
analyze 디렉토리용
"""
import pymysql
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, date
import time


class DBManager:
    """MySQL 데이터베이스 관리 클래스"""
    
    def __init__(self, db_config: Dict[str, Any], logger=None):
        """
        Args:
            db_config: 데이터베이스 설정 딕셔너리
            logger: 로거 객체
        """
        self.config = db_config
        self.logger = logger or logging.getLogger(__name__)
        self.connection = None
        self.cursor = None
    
    def connect(self) -> bool:
        """데이터베이스 연결"""
        try:
            # 설정값 확인
            host = self.config.get('host', 'localhost')
            port = self.config.get('port', 3306)
            user = self.config.get('user')
            password = self.config.get('password')
            database = self.config.get('database')
            charset = self.config.get('charset', 'utf8mb4')
            
            # 필수 항목 체크
            if not user:
                raise Exception("DB 사용자(user)가 설정되지 않았습니다.")
            if not password:
                raise Exception("DB 비밀번호(password)가 설정되지 않았습니다.")
            if not database:
                raise Exception("DB 이름(database)이 설정되지 않았습니다.")
            
            self.logger.debug(f"DB 연결 시도: {user}@{host}:{port}/{database}")
            
            self.connection = pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                charset=charset,
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False
            )
            self.cursor = self.connection.cursor()
            self.logger.info("✅ 데이터베이스 연결 성공")
            return True
        except Exception as e:
            self.logger.error(f"❌ 데이터베이스 연결 실패: {e}")
            return False
    
    def disconnect(self):
        """데이터베이스 연결 해제"""
        try:
            if self.cursor:
                self.cursor.close()
            if self.connection:
                self.connection.close()
            self.logger.info("✅ 데이터베이스 연결 해제")
        except Exception as e:
            self.logger.error(f"⚠️ 연결 해제 중 오류: {e}")
    
    def create_tables(self) -> bool:
        """필요한 테이블 생성"""
        try:
            # 종목 정보 테이블
            create_stock_info = """
            CREATE TABLE IF NOT EXISTS stock_info (
                stock_code VARCHAR(6) PRIMARY KEY COMMENT '종목코드',
                stock_name VARCHAR(100) NOT NULL COMMENT '종목명',
                market_cap BIGINT COMMENT '시가총액',
                sector VARCHAR(50) COMMENT '업종',
                listing_date DATE COMMENT '상장일',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
                INDEX idx_name (stock_name),
                INDEX idx_market_cap (market_cap DESC)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='종목 기본정보';
            """
            
            # 일봉 데이터 테이블
            create_daily_prices = """
            CREATE TABLE IF NOT EXISTS daily_stock_prices (
                stock_code VARCHAR(6) NOT NULL COMMENT '종목코드',
                trade_date DATE NOT NULL COMMENT '거래일자',
                open_price INT COMMENT '시가',
                high_price INT COMMENT '고가',
                low_price INT COMMENT '저가',
                close_price INT NOT NULL COMMENT '종가',
                volume BIGINT COMMENT '거래량',
                trading_value BIGINT COMMENT '거래대금',
                foreign_buy_qty BIGINT COMMENT '외국인 매수량',
                foreign_sell_qty BIGINT COMMENT '외국인 매도량',
                foreign_net_qty BIGINT COMMENT '외국인 순매수량',
                institution_buy_qty BIGINT COMMENT '기관 매수량',
                institution_sell_qty BIGINT COMMENT '기관 매도량',
                institution_net_qty BIGINT COMMENT '기관 순매수량',
                individual_buy_qty BIGINT COMMENT '개인 매수량',
                individual_sell_qty BIGINT COMMENT '개인 매도량',
                individual_net_qty BIGINT COMMENT '개인 순매수량',
                market_cap BIGINT COMMENT '시가총액',
                prev_day_diff INT COMMENT '전일대비',
                prev_day_diff_sign CHAR(1) COMMENT '전일대비부호',
                change_rate DECIMAL(10,2) COMMENT '등락률',
                split_ratio DECIMAL(10,2) COMMENT '분할비율',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '생성일시',
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '수정일시',
                PRIMARY KEY (stock_code, trade_date),
                INDEX idx_date (trade_date DESC),
                INDEX idx_code_date (stock_code, trade_date DESC),
                INDEX idx_volume (volume DESC),
                FOREIGN KEY (stock_code) REFERENCES stock_info(stock_code) ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='일봉 주가 데이터';
            """
            
            # 배치 실행 이력 테이블
            create_batch_history = """
            CREATE TABLE IF NOT EXISTS batch_history (
                batch_id INT AUTO_INCREMENT PRIMARY KEY,
                batch_type VARCHAR(50) NOT NULL COMMENT '배치 타입',
                start_time DATETIME NOT NULL COMMENT '시작시간',
                end_time DATETIME COMMENT '종료시간',
                status VARCHAR(20) NOT NULL COMMENT '상태(SUCCESS/FAIL/RUNNING)',
                total_stocks INT COMMENT '총 종목수',
                success_count INT COMMENT '성공 종목수',
                fail_count INT COMMENT '실패 종목수',
                error_message TEXT COMMENT '에러 메시지',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_type_date (batch_type, start_time DESC)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='배치 실행 이력';
            """
            
            self.cursor.execute(create_stock_info)
            self.cursor.execute(create_daily_prices)
            self.cursor.execute(create_batch_history)
            self.connection.commit()
            
            self.logger.info("✅ 테이블 생성/확인 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 테이블 생성 실패: {e}")
            self.connection.rollback()
            return False
    
    def upsert_stock_info(self, stock_code: str, stock_name: str, 
                          market_cap: Optional[int] = None) -> bool:
        """종목 정보 추가/업데이트"""
        try:
            sql = """
            INSERT INTO stock_info (stock_code, stock_name, market_cap)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                stock_name = VALUES(stock_name),
                market_cap = VALUES(market_cap),
                updated_at = CURRENT_TIMESTAMP
            """
            self.cursor.execute(sql, (stock_code, stock_name, market_cap))
            return True
        except Exception as e:
            self.logger.error(f"❌ 종목 정보 저장 실패 ({stock_code}): {e}")
            return False
    
    def upsert_fundamental_data(self, data: Dict[str, Any]) -> bool:
        """펀더멘털 데이터 추가/업데이트
        
        Args:
            data: {
                'stock_code': str,
                'trade_date': date,
                'per': float,
                'pbr': float,
                'roe': float,
                'debt_ratio': float,
                'market_cap': int,
                'listed_shares': int
            }
        
        Returns:
            bool: 성공 여부
        """
        try:
            sql = """
            INSERT INTO fundamental_data (
                stock_code, trade_date, per, pbr, roe, debt_ratio, 
                market_cap, listed_shares, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                per = VALUES(per),
                pbr = VALUES(pbr),
                roe = VALUES(roe),
                debt_ratio = VALUES(debt_ratio),
                market_cap = VALUES(market_cap),
                listed_shares = VALUES(listed_shares),
                updated_at = NOW()
            """
            
            self.cursor.execute(sql, (
                data.get('stock_code'),
                data.get('trade_date'),
                data.get('per'),
                data.get('pbr'),
                data.get('roe'),
                data.get('debt_ratio'),
                data.get('market_cap'),
                data.get('listed_shares')
            ))
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 펀더멘털 데이터 저장 실패 ({data.get('stock_code')}): {e}")
            return False
    
    
    def get_fundamental_data(self, stock_code: str, days: int = 30) -> Optional[Dict]:
        """DB에서 펀더멘털 데이터 조회
        
        Args:
            stock_code: 종목코드
            days: 조회 기간 (기본 30일)
        
        Returns:
            Dict: 최신 펀더멘털 데이터 또는 None
        """
        try:
            sql = """
            SELECT stock_code, trade_date, per, pbr, roe, debt_ratio, 
                   market_cap, listed_shares, created_at, updated_at
            FROM fundamental_data
            WHERE stock_code = %s
              AND trade_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            ORDER BY trade_date DESC
            LIMIT 1
            """
            
            self.cursor.execute(sql, (stock_code, days))
            result = self.cursor.fetchone()
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ 펀더멘털 데이터 조회 실패 ({stock_code}): {e}")
            return None
    
    def upsert_fundamental_data(self, data: Dict[str, Any]) -> bool:
        """펀더멘털 데이터 추가/업데이트
        
        Args:
            data: {
                'stock_code': str,
                'trade_date': date,
                'per': float,
                'pbr': float,
                'roe': float,
                'debt_ratio': float,
                'market_cap': int,
                'listed_shares': int
            }
        
        Returns:
            bool: 성공 여부
        """
        try:
            sql = """
            INSERT INTO fundamental_data (
                stock_code, trade_date, per, pbr, roe, debt_ratio, 
                market_cap, listed_shares, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
            ON DUPLICATE KEY UPDATE
                per = VALUES(per),
                pbr = VALUES(pbr),
                roe = VALUES(roe),
                debt_ratio = VALUES(debt_ratio),
                market_cap = VALUES(market_cap),
                listed_shares = VALUES(listed_shares),
                updated_at = NOW()
            """
            
            self.cursor.execute(sql, (
                data.get('stock_code'),
                data.get('trade_date'),
                data.get('per'),
                data.get('pbr'),
                data.get('roe'),
                data.get('debt_ratio'),
                data.get('market_cap'),
                data.get('listed_shares')
            ))
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 펀더멘털 데이터 저장 실패 ({data.get('stock_code')}): {e}")
            return False
    
    
    def get_fundamental_data(self, stock_code: str, days: int = 30) -> Optional[Dict]:
        """DB에서 펀더멘털 데이터 조회
        
        Args:
            stock_code: 종목코드
            days: 조회 기간 (기본 30일)
        
        Returns:
            Dict: 최신 펀더멘털 데이터 또는 None
        """
        try:
            sql = """
            SELECT stock_code, trade_date, per, pbr, roe, debt_ratio, 
                   market_cap, listed_shares, created_at, updated_at
            FROM fundamental_data
            WHERE stock_code = %s
              AND trade_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            ORDER BY trade_date DESC
            LIMIT 1
            """
            
            self.cursor.execute(sql, (stock_code, days))
            result = self.cursor.fetchone()
            
            return result
        
        except Exception as e:
            self.logger.error(f"❌ 펀더멘털 데이터 조회 실패 ({stock_code}): {e}")
            return None

    def bulk_insert_daily_prices(self, data_list: List[Dict[str, Any]]) -> tuple:
        """일봉 데이터 대량 삽입 (투자자별 매매 데이터 포함)"""
        success_count = 0
        fail_count = 0
        
        try:
            sql = """
            INSERT INTO daily_stock_prices (
                stock_code, trade_date, open_price, high_price, low_price, 
                close_price, volume, trading_value,
                foreign_buy_qty, foreign_sell_qty, foreign_net_qty,
                institution_buy_qty, institution_sell_qty, institution_net_qty,
                individual_buy_qty, individual_sell_qty, individual_net_qty
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                open_price = VALUES(open_price),
                high_price = VALUES(high_price),
                low_price = VALUES(low_price),
                close_price = VALUES(close_price),
                volume = VALUES(volume),
                trading_value = VALUES(trading_value),
                foreign_buy_qty = VALUES(foreign_buy_qty),
                foreign_sell_qty = VALUES(foreign_sell_qty),
                foreign_net_qty = VALUES(foreign_net_qty),
                institution_buy_qty = VALUES(institution_buy_qty),
                institution_sell_qty = VALUES(institution_sell_qty),
                institution_net_qty = VALUES(institution_net_qty),
                individual_buy_qty = VALUES(individual_buy_qty),
                individual_sell_qty = VALUES(individual_sell_qty),
                individual_net_qty = VALUES(individual_net_qty)
            """
            
            values = []
            for data in data_list:
                values.append((
                    data.get('stock_code'),
                    data.get('trade_date'),
                    data.get('open_price'),
                    data.get('high_price'),
                    data.get('low_price'),
                    data.get('close_price'),
                    data.get('volume'),
                    data.get('trading_value'),
                    data.get('foreign_buy_qty'),
                    data.get('foreign_sell_qty'),
                    data.get('foreign_net_qty'),
                    data.get('institution_buy_qty'),
                    data.get('institution_sell_qty'),
                    data.get('institution_net_qty'),
                    data.get('individual_buy_qty'),
                    data.get('individual_sell_qty'),
                    data.get('individual_net_qty')
                ))
            
            self.cursor.executemany(sql, values)
            success_count = len(data_list)
            
        except Exception as e:
            self.logger.error(f"❌ 대량 삽입 실패: {e}")
            fail_count = len(data_list)
        
        return success_count, fail_count
    
    def commit(self):
        """트랜잭션 커밋"""
        try:
            self.connection.commit()
        except Exception as e:
            self.logger.error(f"❌ 커밋 실패: {e}")
            raise
    
    def rollback(self):
        """트랜잭션 롤백"""
        try:
            self.connection.rollback()
        except Exception as e:
            self.logger.error(f"❌ 롤백 실패: {e}")
    
    def start_batch(self, batch_type: str) -> int:
        """배치 실행 시작 기록"""
        try:
            sql = """
            INSERT INTO batch_history (batch_type, start_time, status)
            VALUES (%s, %s, 'RUNNING')
            """
            self.cursor.execute(sql, (batch_type, datetime.now()))
            self.connection.commit()
            return self.cursor.lastrowid
        except Exception as e:
            self.logger.error(f"❌ 배치 시작 기록 실패: {e}")
            return 0
    
    def end_batch(self, batch_id: int, status: str,
                  total_stocks: int, success_count: int, fail_count: int,
                  error_message: str = None):
        """배치 실행 종료 기록"""
        try:
            sql = """
            UPDATE batch_history
            SET end_time = %s, status = %s, total_stocks = %s,
                success_count = %s, fail_count = %s, error_message = %s
            WHERE batch_id = %s
            """
            self.cursor.execute(sql, (
                datetime.now(), status, total_stocks,
                success_count, fail_count, error_message, batch_id
            ))
            self.connection.commit()
        except Exception as e:
            self.logger.error(f"❌ 배치 종료 기록 실패: {e}")

    def get_daily_prices(self, stock_code: str, days: int = 90) -> Optional[List[Dict]]:
        """DB에서 일봉 데이터 조회

        Args:
            stock_code: 종목코드
            days: 조회 일수 (기본 90일)

        Returns:
            List[Dict]: 일봉 데이터 리스트 (날짜 오름차순) 또는 None
        """
        try:
            sql = """
            SELECT
                stock_code,
                trade_date as stck_bsop_date,
                open_price as stck_oprc,
                high_price as stck_hgpr,
                low_price as stck_lwpr,
                close_price as stck_clpr,
                volume as acml_vol,
                trading_value as acml_tr_pbmn,
                foreign_buy_qty,
                foreign_sell_qty,
                foreign_net_qty,
                institution_buy_qty,
                institution_sell_qty,
                institution_net_qty,
                individual_buy_qty,
                individual_sell_qty,
                individual_net_qty
            FROM daily_stock_prices
            WHERE stock_code = %s
              AND trade_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
            ORDER BY trade_date ASC
            """

            self.cursor.execute(sql, (stock_code, days))
            results = self.cursor.fetchall()

            if not results:
                return None

            # trade_date를 문자열로 변환 (YYYYMMDD 형식)
            for row in results:
                if isinstance(row['stck_bsop_date'], date):
                    row['stck_bsop_date'] = row['stck_bsop_date'].strftime('%Y%m%d')

            return results

        except Exception as e:
            self.logger.error(f"❌ 일봉 데이터 조회 실패 ({stock_code}): {e}")
            return None

    def __enter__(self):
        """컨텍스트 매니저 진입"""
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """컨텍스트 매니저 종료"""
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.disconnect()
