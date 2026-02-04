"""
백테스팅 시스템
과거 데이터로 종목 발굴 전략을 검증하고 성과를 측정
"""
import os
import sys
import json
import yaml
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import pandas as pd
from collections import defaultdict

# 현재 디렉토리 모듈 import
from data_fetcher import DataFetcher
from technical_indicators import SignalAnalyzer
from db_manager import DBManager
from utils import setup_logger


class BacktestAnalyzer:
    """백테스팅 분석 클래스"""
    
    def __init__(self, config_path="../trading_system/config.yaml"):
        """초기화"""
        self.logger = setup_logger("backtest")
        
        # 설정 로드
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                self.backtest_config = config.get('backtest_analysis', {})
                self.analysis_config = config.get('analysis', {})
        except Exception as e:
            self.logger.error(f"❌ 설정 로드 실패: {e}")
            self.backtest_config = {}
            self.analysis_config = {}
        
        # 데이터 소스
        self.data_fetcher = DataFetcher()
        self.signal_analyzer = SignalAnalyzer(self.data_fetcher)
        self.db_manager = DBManager()
        
        # 결과 저장
        self.backtest_results = []
        self.signal_performance = defaultdict(lambda: {
            'total': 0,
            'success': 0,
            'total_return': 0.0,
            'returns': []
        })
        
        self.logger.info("🎯 백테스팅 분석기 초기화 완료")
    
    def get_historical_stock_list(self, date_str: str) -> List[Dict]:
        """
        특정 날짜의 시가총액 상위 종목 리스트 조회
        실제로는 현재 상위 200개를 사용 (과거 데이터 제약)
        """
        try:
            stock_list = self.data_fetcher.get_top_200_stocks()
            self.logger.debug(f"📊 {date_str} 기준 종목: {len(stock_list)}개")
            return stock_list
        except Exception as e:
            self.logger.error(f"❌ 종목 리스트 조회 실패: {e}")
            return []
    
    def simulate_stock_analysis(self, name: str, code: str, analysis_date: datetime) -> Optional[Dict]:
        """
        특정 날짜 기준으로 종목 분석 시뮬레이션
        
        Args:
            name: 종목명
            code: 종목코드
            analysis_date: 분석 기준일
            
        Returns:
            분석 결과 딕셔너리 또는 None
        """
        try:
            # 해당 날짜까지의 데이터만 사용 (미래 데이터 누출 방지)
            df = self.get_historical_data_until(code, analysis_date)
            
            if df is None or df.empty or len(df) < 30:
                return None
            
            # 외국인 데이터도 해당 날짜까지만
            foreign_netbuy_list = self.get_foreign_data_until(code, analysis_date)
            
            # 절대조건 및 신호 점수 계산
            score, active_signals, passes_absolute, filter_reason = \
                self.signal_analyzer.calculate_buy_signal_score(
                    df, name, code, 
                    foreign_trend=None,
                    foreign_netbuy_list=foreign_netbuy_list
                )
            
            # 절대조건 미통과
            if not passes_absolute:
                return None
            
            # 현재가
            current_price = df.iloc[-1]['stck_clpr']
            
            return {
                'name': name,
                'code': code,
                'analysis_date': analysis_date.strftime('%Y-%m-%d'),
                'score': score,
                'signals': active_signals,
                'price': current_price,
                'passes_absolute': passes_absolute
            }
            
        except Exception as e:
            self.logger.debug(f"⚠️ {name}({code}) 시뮬레이션 실패: {e}")
            return None
    
    def get_historical_data_until(self, code: str, end_date: datetime) -> Optional[pd.DataFrame]:
        """
        특정 날짜까지의 과거 데이터 조회
        
        Args:
            code: 종목코드
            end_date: 종료일
            
        Returns:
            DataFrame 또는 None
        """
        try:
            # DB에서 데이터 조회 (테이블명 수정!)
            query = """
                SELECT trade_date, close_price, high_price, low_price, volume
                FROM daily_stock_prices
                WHERE stock_code = %s AND trade_date <= %s
                ORDER BY trade_date DESC
                LIMIT 100
            """
            
            self.db_manager.connect()
            cursor = self.db_manager.connection.cursor()
            cursor.execute(query, (code, end_date.strftime('%Y-%m-%d')))
            
            rows = cursor.fetchall()
            
            if not rows:
                return None
            
            # DataFrame 생성 (기존 컬럼명으로 변환)
            df = pd.DataFrame(rows, columns=['trade_date', 'stck_clpr', 'stck_hgpr', 'stck_lwpr', 'acml_vol'])
            
            # 데이터 타입 변환
            numeric_cols = ['stck_clpr', 'stck_hgpr', 'stck_lwpr', 'acml_vol']
            for col in numeric_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 날짜 컬럼 변환 (YYYY-MM-DD -> YYYYMMDD)
            df['stck_bsop_date'] = df['trade_date'].astype(str).str.replace('-', '')
            df = df.drop('trade_date', axis=1)
            
            # 정렬 (오래된 것부터)
            df = df.sort_values('stck_bsop_date').reset_index(drop=True)
            
            return df
            
        except Exception as e:
            self.logger.debug(f"⚠️ {code} 과거 데이터 조회 실패: {e}")
            return None
        finally:
            self.db_manager.disconnect()
    
    def get_foreign_data_until(self, code: str, end_date: datetime) -> List[int]:
        """특정 날짜까지의 외국인 순매수 데이터"""
        try:
            # DB에서 외국인 데이터 조회 (테이블명 수정!)
            query = """
                SELECT foreign_net_qty
                FROM daily_stock_prices
                WHERE stock_code = %s AND trade_date <= %s
                ORDER BY trade_date DESC
                LIMIT 5
            """
            
            self.db_manager.connect()
            cursor = self.db_manager.connection.cursor()
            cursor.execute(query, (code, end_date.strftime('%Y-%m-%d')))
            
            rows = cursor.fetchall()
            
            if not rows:
                return []
            
            # 순매수량 리스트
            netbuy_list = [int(row[0]) if row[0] else 0 for row in rows]
            
            return netbuy_list
            
        except Exception as e:
            return []
        finally:
            self.db_manager.disconnect()
    
    def calculate_future_returns(self, code: str, buy_date: datetime, buy_price: float, 
                                 holding_periods: List[int]) -> Dict[int, float]:
        """
        매수 후 보유기간별 수익률 계산
        
        Args:
            code: 종목코드
            buy_date: 매수일
            buy_price: 매수가
            holding_periods: 보유기간 리스트 (예: [5, 10, 20])
            
        Returns:
            {보유기간: 수익률} 딕셔너리
        """
        returns = {}
        
        try:
            for days in holding_periods:
                sell_date = buy_date + timedelta(days=days)
                sell_price = self.get_price_on_date(code, sell_date)
                
                if sell_price and sell_price > 0:
                    return_pct = ((sell_price - buy_price) / buy_price) * 100
                    returns[days] = round(return_pct, 2)
                else:
                    returns[days] = None
                    
        except Exception as e:
            self.logger.debug(f"⚠️ {code} 수익률 계산 실패: {e}")
        
        return returns
    
    def get_price_on_date(self, code: str, target_date: datetime) -> Optional[float]:
        """특정 날짜의 종가 조회 (거래일 기준)"""
        try:
            # 해당 날짜 이후 첫 거래일의 종가 (테이블명 수정!)
            query = """
                SELECT close_price
                FROM daily_stock_prices
                WHERE stock_code = %s AND trade_date >= %s
                ORDER BY trade_date ASC
                LIMIT 1
            """
            
            self.db_manager.connect()
            cursor = self.db_manager.connection.cursor()
            cursor.execute(query, (code, target_date.strftime('%Y-%m-%d')))
            
            row = cursor.fetchone()
            
            if row:
                return float(row[0])
            
            return None
            
        except Exception as e:
            return None
        finally:
            self.db_manager.disconnect()
    
    def run_backtest(self, start_date: str, end_date: str, interval_days: int = 7):
        """
        백테스팅 실행
        
        Args:
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
            interval_days: 테스트 간격 (일)
        """
        self.logger.info("="*70)
        self.logger.info(f"🚀 백테스팅 시작: {start_date} ~ {end_date}")
        self.logger.info("="*70)
        
        # 날짜 범위 생성
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
        
        current_date = start_dt
        test_count = 0
        total_discoveries = 0
        
        holding_periods = self.backtest_config.get('performance', {}).get('holding_periods', [5, 10, 20])
        
        while current_date <= end_dt:
            self.logger.info(f"\n📅 분석일: {current_date.strftime('%Y-%m-%d')}")
            
            # 해당 날짜의 종목 리스트
            stock_list = self.get_historical_stock_list(current_date.strftime('%Y-%m-%d'))
            
            daily_discoveries = []
            
            # 각 종목 분석
            for name, code in list(stock_list.items())[:50]:  # 테스트: 상위 50개만
                result = self.simulate_stock_analysis(name, code, current_date)
                
                if result and result['score'] >= 3:  # 3점 이상만
                    # 향후 수익률 계산
                    returns = self.calculate_future_returns(
                        code, current_date, result['price'], holding_periods
                    )
                    
                    result['returns'] = returns
                    daily_discoveries.append(result)
                    
                    # 신호별 성과 기록
                    for signal in result['signals']:
                        for period, return_pct in returns.items():
                            if return_pct is not None:
                                self.signal_performance[signal]['total'] += 1
                                self.signal_performance[signal]['total_return'] += return_pct
                                self.signal_performance[signal]['returns'].append(return_pct)
                                
                                if return_pct > 0:
                                    self.signal_performance[signal]['success'] += 1
            
            if daily_discoveries:
                self.logger.info(f"✅ 발굴: {len(daily_discoveries)}개")
                total_discoveries += len(daily_discoveries)
                
                # 결과 저장
                self.backtest_results.extend(daily_discoveries)
            else:
                self.logger.info("❌ 발굴 종목 없음")
            
            test_count += 1
            current_date += timedelta(days=interval_days)
        
        self.logger.info("\n" + "="*70)
        self.logger.info(f"✅ 백테스팅 완료")
        self.logger.info(f"   총 테스트: {test_count}회")
        self.logger.info(f"   총 발굴: {total_discoveries}개")
        self.logger.info("="*70)
        
        # 결과 분석 및 저장
        self.analyze_results()
        self.save_results()
    
    def analyze_results(self):
        """백테스팅 결과 분석"""
        if not self.backtest_results:
            self.logger.warning("⚠️ 분석할 결과가 없습니다.")
            return
        
        self.logger.info("\n" + "="*70)
        self.logger.info("📊 백테스팅 결과 분석")
        self.logger.info("="*70)
        
        # 전체 통계
        total_stocks = len(self.backtest_results)
        holding_periods = [5, 10, 20]
        
        for period in holding_periods:
            valid_returns = [r['returns'].get(period) for r in self.backtest_results 
                           if r['returns'].get(period) is not None]
            
            if valid_returns:
                success_count = sum(1 for r in valid_returns if r > 0)
                success_rate = (success_count / len(valid_returns)) * 100
                avg_return = sum(valid_returns) / len(valid_returns)
                
                self.logger.info(f"\n{period}일 보유:")
                self.logger.info(f"  성공률: {success_rate:.1f}% ({success_count}/{len(valid_returns)})")
                self.logger.info(f"  평균 수익률: {avg_return:+.2f}%")
        
        # 신호별 성과
        self.logger.info("\n" + "-"*70)
        self.logger.info("📈 신호별 성과 (5일 보유 기준)")
        self.logger.info("-"*70)
        
        signal_stats = []
        for signal, perf in self.signal_performance.items():
            if perf['total'] > 0:
                success_rate = (perf['success'] / perf['total']) * 100
                avg_return = perf['total_return'] / perf['total']
                
                signal_stats.append({
                    'signal': signal,
                    'count': perf['total'],
                    'success_rate': success_rate,
                    'avg_return': avg_return
                })
        
        # 성공률 순 정렬
        signal_stats.sort(key=lambda x: x['success_rate'], reverse=True)
        
        for stat in signal_stats[:10]:  # 상위 10개
            self.logger.info(
                f"{stat['signal']:20s}: "
                f"{stat['success_rate']:5.1f}% "
                f"(평균 {stat['avg_return']:+.2f}%, "
                f"발생 {stat['count']:3d}회)"
            )
    
    def save_results(self):
        """결과 저장"""
        try:
            output_config = self.backtest_config.get('output', {})
            results_file = output_config.get('results_file', 'backtest_results.json')
            
            # JSON 저장
            output_data = {
                'timestamp': datetime.now().isoformat(),
                'total_discoveries': len(self.backtest_results),
                'discoveries': self.backtest_results,
                'signal_performance': dict(self.signal_performance)
            }
            
            with open(results_file, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"\n💾 결과 저장: {results_file}")
            
        except Exception as e:
            self.logger.error(f"❌ 결과 저장 실패: {e}")


def main():
    """메인 실행"""
    import argparse
    
    parser = argparse.ArgumentParser(description='백테스팅 실행')
    parser.add_argument('--start', type=str, required=True, help='시작일 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, required=True, help='종료일 (YYYY-MM-DD)')
    parser.add_argument('--interval', type=int, default=7, help='테스트 간격 (일)')
    
    args = parser.parse_args()
    
    try:
        analyzer = BacktestAnalyzer()
        analyzer.run_backtest(args.start, args.end, args.interval)
        
        print("\n✅ 백테스팅 완료!")
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

