"""
KIS API 기반 백테스트 모듈
모듈화된 구조에 맞게 개선된 버전
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import time
import os
from typing import Dict, List, Tuple
import logging
import warnings
warnings.filterwarnings('ignore')

# 분리된 모듈들 import
from kis_api_client import KISAPIClient
from utils import setup_logger, convert_numpy_types, safe_json_save, load_stock_codes_from_file

class KISBacktester(KISAPIClient):
    def __init__(self):
        super().__init__()
        self.setup_logging()

    def setup_logging(self):
        """로깅 설정"""
        self.logger = setup_logger(log_filename="backtest.log")

    def get_stock_data(self, stock_code: str, period: str = "D", count: int = 100) -> pd.DataFrame:
        """주식 데이터 조회"""
        url = f"https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
            "fid_input_date_1": "",
            "fid_input_date_2": "",
            "fid_period_div_code": period,
            "fid_org_adj_prc": "0"
        }

        try:
            data = self.api_request(url, params, "FHKST03010100")
            if data and 'output2' in data and data['output2']:
                df = pd.DataFrame(data['output2'])

                # 컬럼명 변경 및 데이터 타입 변환
                df = df.rename(columns={
                    'stck_bsop_date': 'date',
                    'stck_oprc': 'open',
                    'stck_hgpr': 'high',
                    'stck_lwpr': 'low',
                    'stck_clpr': 'close',
                    'acml_vol': 'volume'
                })

                # 필요한 컬럼만 선택
                df = df[['date', 'open', 'high', 'low', 'close', 'volume']].copy()

                # 데이터 타입 변환
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date').reset_index(drop=True)

                # 최근 count개만 선택
                df = df.tail(count).reset_index(drop=True)

                return df
            else:
                self.logger.warning(f"❌ 데이터 없음: {stock_code}")
                return pd.DataFrame()
                
        except Exception as e:
            self.logger.error(f"❌ {stock_code}: 데이터 조회 중 오류: {e}")
            return pd.DataFrame()

    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기술적 지표 계산"""
        if len(df) < 20:
            self.logger.warning("❌ 데이터가 부족합니다 (최소 20개 필요)")
            return df

        # 이동평균
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma10'] = df['close'].rolling(window=10).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()

        # 볼린저 밴드
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD
        exp1 = df['close'].ewm(span=12).mean()
        exp2 = df['close'].ewm(span=26).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        # 거래량 비율 (현재 거래량 / 5일 평균 거래량)
        df['volume_ma5'] = df['volume'].rolling(window=5).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma5']

        # 가격 변화율
        df['price_change'] = df['close'].pct_change()
        df['price_change_5d'] = df['close'].pct_change(periods=5)

        # 변동성 (20일 표준편차)
        df['volatility'] = df['close'].rolling(window=20).std()

        return df

    def momentum_strategy(self, df: pd.DataFrame) -> pd.Series:
        """모멘텀 전략"""
        signals = pd.Series(0, index=df.index)

        # 조건: 5일선 > 20일선, RSI > 50, 거래량 증가
        buy_condition = (
            (df['ma5'] > df['ma20']) &
            (df['rsi'] > 50) &
            (df['volume_ratio'] > 1.2)
        )

        sell_condition = (
            (df['ma5'] < df['ma20']) |
            (df['rsi'] < 30)
        )

        signals[buy_condition] = 1
        signals[sell_condition] = -1

        return signals

    def mean_reversion_strategy(self, df: pd.DataFrame) -> pd.Series:
        """평균회귀 전략"""
        signals = pd.Series(0, index=df.index)

        # 조건: 가격이 볼린저 밴드 하한선 근처, RSI 과매도
        buy_condition = (
            (df['close'] <= df['bb_lower'] * 1.02) &
            (df['rsi'] < 35)
        )

        sell_condition = (
            (df['close'] >= df['bb_upper'] * 0.98) |
            (df['rsi'] > 65)
        )

        signals[buy_condition] = 1
        signals[sell_condition] = -1

        return signals

    def breakout_strategy(self, df: pd.DataFrame) -> pd.Series:
        """돌파 전략"""
        signals = pd.Series(0, index=df.index)

        # 조건: 20일 최고가 돌파, 거래량 급증
        df['high_20'] = df['high'].rolling(window=20).max()

        buy_condition = (
            (df['close'] > df['high_20'].shift(1)) &
            (df['volume_ratio'] > 2.0)
        )

        sell_condition = df['close'] < df['ma20']

        signals[buy_condition] = 1
        signals[sell_condition] = -1

        return signals

    def scalping_strategy(self, df: pd.DataFrame) -> pd.Series:
        """스캘핑 전략"""
        signals = pd.Series(0, index=df.index)

        # 조건: MACD 골든크로스, 단기 상승 추세
        buy_condition = (
            (df['macd'] > df['macd_signal']) &
            (df['macd'].shift(1) <= df['macd_signal'].shift(1)) &
            (df['close'] > df['ma5'])
        )

        sell_condition = (
            (df['macd'] < df['macd_signal']) |
            (df['close'] < df['ma5'] * 0.98)
        )

        signals[buy_condition] = 1
        signals[sell_condition] = -1

        return signals

    def backtest_strategy(self, df: pd.DataFrame, strategy_func, initial_capital: float = 1000000) -> Dict:
        """전략 백테스트"""
        if len(df) < 30:
            return {'error': '데이터 부족'}

        try:
            signals = strategy_func(df)

            # 포지션 계산
            positions = signals.replace(0, np.nan).fillna(method='ffill').fillna(0)

            # 수익률 계산
            returns = df['close'].pct_change()
            strategy_returns = positions.shift(1) * returns

            # 누적 수익률
            cumulative_returns = (1 + strategy_returns).cumprod()
            total_return = cumulative_returns.iloc[-1] - 1

            # 통계 계산
            winning_trades = len(strategy_returns[strategy_returns > 0])
            losing_trades = len(strategy_returns[strategy_returns < 0])
            total_trades = winning_trades + losing_trades

            win_rate = winning_trades / total_trades if total_trades > 0 else 0

            # 최대 낙폭 계산
            rolling_max = cumulative_returns.cummax()
            drawdown = (cumulative_returns - rolling_max) / rolling_max
            max_drawdown = drawdown.min()

            # 샤프 비율 (연간화)
            annual_return = total_return * (252 / len(df))
            annual_volatility = strategy_returns.std() * np.sqrt(252)
            sharpe_ratio = annual_return / annual_volatility if annual_volatility > 0 else 0

            return {
                'total_return': total_return,
                'annual_return': annual_return,
                'win_rate': win_rate,
                'total_trades': total_trades,
                'max_drawdown': max_drawdown,
                'sharpe_ratio': sharpe_ratio,
                'final_capital': initial_capital * (1 + total_return)
            }

        except Exception as e:
            self.logger.error(f"❌ 백테스트 오류: {e}")
            return {'error': str(e)}

    def save_backtest_results(self, results_df: pd.DataFrame, stock_names: Dict[str, str], filename: str = "backtest_results.json"):
        """백테스트 결과를 JSON 파일로 저장"""
        if results_df.empty:
            self.logger.warning("저장할 결과가 없습니다.")
            return
        
        # 종목별 최고 전략 선택
        best_strategies = {}
        for stock_code in results_df['stock_code'].unique():
            stock_results = results_df[results_df['stock_code'] == stock_code]
            valid_results = stock_results[stock_results['total_trades'] >= 3]
            if valid_results.empty:
                best_row = stock_results.loc[stock_results['total_return'].idxmax()]
            else:
                best_row = valid_results.loc[valid_results['total_return'].idxmax()]
            
            best_strategies[stock_code] = {
                'symbol': stock_code,
                'name': stock_names.get(stock_code, stock_code),
                'strategy': best_row['strategy'],
                'return': round(best_row['total_return'] * 100, 2),
                'win_rate': round(best_row['win_rate'], 3),
                'sharpe_ratio': round(best_row['sharpe_ratio'], 3),
                'max_drawdown': round(best_row['max_drawdown'], 3),
                'total_trades': int(best_row['total_trades']),
                'priority': 0,
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        
        # 수익률 기준으로 우선순위 설정
        sorted_symbols = sorted(best_strategies.items(), 
                              key=lambda x: x[1]['return'], 
                              reverse=True)
        
        for i, (symbol, data) in enumerate(sorted_symbols):
            best_strategies[symbol]['priority'] = i + 1
        
        # 전체 결과 구성
        backtest_data = {
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'backtest_period': f"{len(results_df)} days",
            'verified_symbols': list(best_strategies.values()),
            'summary': {
                'total_symbols': len(best_strategies),
                'avg_return': round(results_df.groupby('stock_code')['total_return'].max().mean() * 100, 2),
                'best_symbol': sorted_symbols[0][0] if sorted_symbols else None,
                'best_return': sorted_symbols[0][1]['return'] if sorted_symbols else 0
            }
        }
        
        # JSON 파일로 저장
        success, error = safe_json_save(backtest_data, filename)
        if success:
            self.logger.info(f"✅ 백테스트 결과가 {filename}에 저장되었습니다.")
            
            # stock_names.json 별도 저장
            if os.path.exists('stock_names.json'):
                with open('stock_names.json', 'r', encoding='utf-8') as f:
                    existing_names = json.load(f)
            else:
                existing_names = {}
    
            # 기존 데이터와 새 데이터 병합
            merged_names = {**existing_names, **stock_names}
    
            # 병합된 데이터 저장
            success_names, error_names = safe_json_save(merged_names, 'stock_names.json')
            if success_names:
                self.logger.info("✅ 종목명 매핑이 stock_names.json에 저장되었습니다.")
            else:
                self.logger.error(f"❌ 종목명 저장 실패: {error_names}")
            
        else:
            self.logger.error(f"❌ 결과 저장 실패: {error}")

    def run_comprehensive_backtest(self, stock_codes: List[str], stock_names: Dict[str, str] = None, days: int = 100):
        """종합 백테스트 실행"""
        self.logger.info("🚀 KIS API 기반 시간단위 매매 백테스트 시작!")
        print("🚀 KIS API 기반 시간단위 매매 백테스트 시작!")
        print("=" * 60)

        if stock_names is None:
            stock_names = {}

        strategies = {
            'momentum': self.momentum_strategy,
            'mean_reversion': self.mean_reversion_strategy,
            'breakout': self.breakout_strategy,
            'scalping': self.scalping_strategy
        }

        # 전략 조합
        strategy_combinations = [
            ['momentum'],
            ['mean_reversion'],
            ['breakout'],
            ['scalping'],
            ['momentum', 'breakout'],
            ['mean_reversion', 'scalping']
        ]

        all_results = []

        for stock_code in stock_codes:
            stock_name = stock_names.get(stock_code, stock_code)
            print(f"📊 {stock_code}({stock_name}) 종목 분석 중...")
            self.logger.info(f"📊 {stock_code}({stock_name}) 종목 분석 중...")

            # 데이터 조회
            df = self.get_stock_data(stock_code, count=days)
            if df.empty:
                self.logger.warning(f"❌ {stock_code} - 데이터 조회 실패")
                continue

            # 기술적 지표 계산
            df = self.calculate_technical_indicators(df)

            # 각 전략 조합별 백테스트
            for combination in strategy_combinations:
                try:
                    if len(combination) == 1:
                        # 단일 전략
                        strategy_name = combination[0]
                        result = self.backtest_strategy(df, strategies[strategy_name])
                    else:
                        # 전략 조합 (신호 평균)
                        combined_signals = pd.Series(0, index=df.index)
                        for strategy_name in combination:
                            signals = strategies[strategy_name](df)
                            combined_signals += signals
                        combined_signals = combined_signals / len(combination)

                        # 임계값으로 신호 변환
                        final_signals = pd.Series(0, index=df.index)
                        final_signals[combined_signals > 0.5] = 1
                        final_signals[combined_signals < -0.5] = -1

                        def combined_strategy(df):
                            return final_signals

                        result = self.backtest_strategy(df, combined_strategy)

                    if 'error' in result:
                        self.logger.error(f"❌ {stock_code} - {combination} 오류: {result['error']}")
                        continue

                    result['stock_code'] = stock_code
                    result['strategy'] = ' + '.join(combination)
                    all_results.append(result)

                    print(f"✅ {stock_code} - {combination}: 수익률 {result['total_return']:.2%}")

                except Exception as e:
                    self.logger.error(f"❌ {stock_code} - {combination} 오류: {str(e)}")
                    continue

            # API 호출 제한 방지
            time.sleep(0.1)

        # 결과 정리 및 출력
        if all_results:
            results_df = pd.DataFrame(all_results)

            print("\n" + "=" * 60)
            print("📈 백테스트 결과 요약")
            print("=" * 60)

            # 전략별 평균 성과
            strategy_summary = results_df.groupby('strategy').agg({
                'total_return': 'mean',
                'win_rate': 'mean',
                'sharpe_ratio': 'mean',
                'max_drawdown': 'mean'
            }).round(4)

            print("\n🏆 전략별 평균 성과:")
            print(strategy_summary.to_string())

            # 종목별 최고 성과
            print(f"\n⭐ 종목별 최고 성과:")
            best_by_stock = results_df.loc[results_df.groupby('stock_code')['total_return'].idxmax()].sort_values(by='total_return', ascending=False)
            for _, row in best_by_stock.iterrows():
                stock_name = stock_names.get(row['stock_code'], row['stock_code'])
                print(f"{row['stock_code']}({stock_name}): {row['strategy']} - 수익률 {row['total_return']:.2%}")

            # 전체 최고 성과
            best_overall = results_df.loc[results_df['total_return'].idxmax()]
            print(f"\n🥇 전체 최고 성과:")
            print(f"종목: {best_overall['stock_code']}, 전략: {best_overall['strategy']}")
            print(f"수익률: {best_overall['total_return']:.2%}, 승률: {best_overall['win_rate']:.2%}")
            print(f"샤프비율: {best_overall['sharpe_ratio']:.3f}, 최대낙폭: {best_overall['max_drawdown']:.2%}")

            # JSON 파일로 저장
            self.save_backtest_results(results_df, stock_names)

            return results_df
        else:
            self.logger.warning("❌ 백테스트 결과가 없습니다.")
            return pd.DataFrame()


def main():
    """메인 실행 함수"""
    try:
        # 환경변수 체크
        from dotenv import load_dotenv
        load_dotenv()
        
        required_env_vars = ["KIS_APP_KEY", "KIS_APP_SECRET"]
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        
        if missing_vars:
            print(f"❌ 필수 환경변수가 설정되지 않았습니다: {missing_vars}")
            return

        # 백테스터 초기화
        backtester = KISBacktester()

        # 분석할 종목 리스트
        base_stock_info = {
            "062040": "산일전기",
            "278470": "에이피알",
        }
        
        # 종목코드 리스트와 이름 딕셔너리 분리
        base_stock_list = list(base_stock_info.keys())
        base_stock_names = base_stock_info

        # backtest_list.json에서 종목 로드
        additional_codes, additional_names = load_stock_codes_from_file("backtest_list.json")
        
        # 종목 리스트와 이름 딕셔너리 합치기
        all_stock_codes = list(set(base_stock_list + additional_codes))
        all_stock_names = {**base_stock_names, **additional_names}
        
        print(f"📋 분석대상 목록: {', '.join([f'{code}({all_stock_names.get(code, code)})' for code in all_stock_codes[:5]])}{'...' if len(all_stock_codes) > 5 else ''}")
        
        # 백테스트 실행
        results = backtester.run_comprehensive_backtest(all_stock_codes, all_stock_names, days=100)

        if not results.empty:
            print("\n✅ 백테스트 완료!")
            print(f"📊 총 {len(results)}개 결과 생성")
        else:
            print("❌ 백테스트 결과 없음")

    except Exception as e:
        print(f"❌ 백테스트 실행 중 오류: {e}")
        logging.error(f"❌ 백테스트 실행 중 오류: {e}")


if __name__ == "__main__":
    main()
