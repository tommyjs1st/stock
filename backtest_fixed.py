import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import json
import time
import os
from dotenv import load_dotenv
from typing import Dict, List, Tuple
import logging
import warnings
warnings.filterwarnings('ignore')

load_dotenv()

class EnhancedKISBacktester:
    def __init__(self, app_key: str, app_secret: str):
        """강화된 KIS API 백테스터 초기화"""
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.token_file = "token.json" 
        self.access_token = None
        self.setup_logging()
        
        # 리스크 관리 파라미터
        self.max_position_size = 0.15  # 단일 종목 최대 15%
        self.max_drawdown_limit = 0.10  # 최대 낙폭 10%
        self.stop_loss_pct = 0.08  # 손절선 8%
        self.take_profit_pct = 0.25  # 익절선 25%

    def setup_logging(self):
        """로깅 설정"""
        os.makedirs("logs", exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/enhanced_backtest.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def load_saved_token(self):
        """저장된 토큰 파일에서 토큰 로드"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    token_data = json.load(f)

                expire_time_str = token_data.get('access_token_token_expired', '')
                if expire_time_str:
                    expire_time = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')

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

    def get_access_token(self) -> str:
        """KIS API 액세스 토큰 발급 또는 재사용"""
        if self.access_token and hasattr(self, 'last_token_time'):
            if datetime.now() - self.last_token_time < timedelta(hours=23):
                return self.access_token
    
        if self.load_saved_token():
            return self.access_token
    
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
            access_token = token_response.get("access_token")
            
            if access_token:
                self.access_token = access_token
                self.last_token_time = datetime.now()
                self.save_token(token_response)
                self.logger.info("✅ 새로운 액세스 토큰 발급 완료")
                return self.access_token
            else:
                raise Exception("토큰 응답에 access_token이 포함되지 않았습니다")
    
        except Exception as e:
            self.logger.error(f"❌ 토큰 발급 실패: {e}")
            raise

    def save_token(self, token_response: dict):
        """토큰을 저장"""
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

    def get_stock_data_with_retry(self, stock_code: str, period: str = "D", count: int = 300, max_retries: int = 3) -> pd.DataFrame:
        """재시도 로직이 포함된 주식 데이터 조회 (더 많은 데이터 확보)"""
        
        for attempt in range(max_retries):
            try:
                # 더 긴 기간으로 데이터 조회 시도
                end_date = datetime.now()
                start_date = end_date - timedelta(days=count + 100)  # 여유분 포함
                
                url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
                headers = {
                    "content-type": "application/json; charset=utf-8",
                    "authorization": f"Bearer {self.get_access_token()}",
                    "appkey": self.app_key,
                    "appsecret": self.app_secret,
                    "tr_id": "FHKST03010100"
                }

                params = {
                    "fid_cond_mrkt_div_code": "J",
                    "fid_input_iscd": stock_code,
                    "fid_input_date_1": start_date.strftime("%Y%m%d"),
                    "fid_input_date_2": end_date.strftime("%Y%m%d"),
                    "fid_period_div_code": period,
                    "fid_org_adj_prc": "0"
                }

                response = requests.get(url, headers=headers, params=params, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # output2가 없으면 output 시도
                    chart_data = data.get('output2', data.get('output', []))
                    
                    if chart_data:
                        df = pd.DataFrame(chart_data)

                        # 컬럼명 확인 및 변경
                        df = df.rename(columns={
                            'stck_bsop_date': 'date',
                            'stck_oprc': 'open',
                            'stck_hgpr': 'high',
                            'stck_lwpr': 'low',
                            'stck_clpr': 'close',
                            'acml_vol': 'volume'
                        })

                        # 필요한 컬럼만 선택
                        required_cols = ['date', 'open', 'high', 'low', 'close', 'volume']
                        available_cols = [col for col in required_cols if col in df.columns]
                        
                        if len(available_cols) < 5:  # 최소 5개 컬럼 필요
                            self.logger.warning(f"❌ {stock_code}: 필요한 컬럼 부족 - {available_cols}")
                            time.sleep(0.2)
                            continue
                        
                        df = df[available_cols].copy()

                        # 데이터 타입 변환
                        for col in ['open', 'high', 'low', 'close', 'volume']:
                            if col in df.columns:
                                df[col] = pd.to_numeric(df[col], errors='coerce')

                        # 날짜 변환
                        df['date'] = pd.to_datetime(df['date'], errors='coerce')
                        
                        # 결측치 제거
                        df = df.dropna(subset=['close'])
                        df = df.sort_values('date').reset_index(drop=True)
                        
                        # 최소 데이터 확보 확인
                        if len(df) >= 50:  # 최소 50일 데이터
                            self.logger.info(f"✅ {stock_code}: {len(df)}일 데이터 조회 성공")
                            return df.tail(count).reset_index(drop=True)
                        else:
                            self.logger.warning(f"⚠️ {stock_code}: 데이터 부족 ({len(df)}일) - 재시도 {attempt + 1}/{max_retries}")
                            
                    else:
                        self.logger.warning(f"❌ {stock_code}: 차트 데이터 없음 - 재시도 {attempt + 1}/{max_retries}")
                        
                else:
                    self.logger.warning(f"❌ {stock_code}: API 호출 실패 ({response.status_code}) - 재시도 {attempt + 1}/{max_retries}")
                    
            except Exception as e:
                self.logger.error(f"❌ {stock_code}: 데이터 조회 오류 (시도 {attempt + 1}/{max_retries}): {e}")
                
            # 재시도 전 대기
            if attempt < max_retries - 1:
                time.sleep(1)
        
        self.logger.error(f"❌ {stock_code}: 모든 재시도 실패")
        return pd.DataFrame()

    def calculate_basic_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기본 기술적 지표 계산 (데이터 부족 시에도 동작)"""
        if len(df) < 20:
            self.logger.warning("❌ 데이터가 너무 부족합니다 (최소 20개 필요)")
            return df

        # 기본 이동평균 (짧은 기간도 고려)
        df['ma5'] = df['close'].rolling(window=min(5, len(df)//4)).mean()
        df['ma10'] = df['close'].rolling(window=min(10, len(df)//3)).mean()
        df['ma20'] = df['close'].rolling(window=min(20, len(df)//2)).mean()

        # RSI (기간 조정)
        rsi_period = min(14, len(df)//3)
        if rsi_period >= 5:
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))
        else:
            df['rsi'] = 50  # 기본값

        # 간단한 MACD
        if len(df) >= 26:
            exp1 = df['close'].ewm(span=12).mean()
            exp2 = df['close'].ewm(span=26).mean()
            df['macd'] = exp1 - exp2
            df['macd_signal'] = df['macd'].ewm(span=9).mean()
        else:
            df['macd'] = 0
            df['macd_signal'] = 0

        # 볼린저 밴드 (기간 조정)
        bb_period = min(20, len(df)//2)
        if bb_period >= 10:
            df['bb_middle'] = df['close'].rolling(window=bb_period).mean()
            bb_std = df['close'].rolling(window=bb_period).std()
            df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
            df['bb_lower'] = df['bb_middle'] - (bb_std * 2)
        else:
            df['bb_middle'] = df['close']
            df['bb_upper'] = df['close'] * 1.02
            df['bb_lower'] = df['close'] * 0.98

        # 거래량 비율
        vol_period = min(10, len(df)//2)
        if vol_period >= 5:
            df['volume_ma'] = df['volume'].rolling(window=vol_period).mean()
            df['volume_ratio'] = df['volume'] / df['volume_ma']
        else:
            df['volume_ratio'] = 1.0

        # 가격 변화율
        df['price_change'] = df['close'].pct_change()
        df['price_change_5d'] = df['close'].pct_change(periods=min(5, len(df)//4))

        return df

    def simple_momentum_strategy(self, df: pd.DataFrame) -> pd.Series:
        """간단한 모멘텀 전략 (데이터 부족 시에도 동작)"""
        signals = pd.Series(0, index=df.index)

        try:
            # 기본 조건들 (유연하게 적용)
            conditions = []
            
            # 이동평균 조건
            if 'ma5' in df.columns and 'ma10' in df.columns:
                conditions.append(df['ma5'] > df['ma10'])
                
            # RSI 조건
            if 'rsi' in df.columns:
                conditions.append((df['rsi'] > 40) & (df['rsi'] < 80))
                
            # 가격 상승 조건
            if 'price_change' in df.columns:
                conditions.append(df['price_change'] > -0.03)
                
            # 거래량 조건
            if 'volume_ratio' in df.columns:
                conditions.append(df['volume_ratio'] > 0.8)

            # 매수 신호: 조건의 60% 이상 만족
            if conditions:
                buy_signal = sum(conditions) >= max(1, len(conditions) * 0.6)
                signals[buy_signal] = 1

            # 매도 신호: 단순 조건
            sell_conditions = []
            if 'ma5' in df.columns and 'ma10' in df.columns:
                sell_conditions.append(df['ma5'] < df['ma10'])
            if 'rsi' in df.columns:
                sell_conditions.append(df['rsi'] > 85)
                
            if sell_conditions:
                sell_signal = any(sell_conditions)
                signals[sell_signal] = -1

        except Exception as e:
            self.logger.error(f"전략 계산 오류: {e}")

        return signals

    def simple_mean_reversion_strategy(self, df: pd.DataFrame) -> pd.Series:
        """간단한 평균회귀 전략"""
        signals = pd.Series(0, index=df.index)

        try:
            buy_conditions = []
            
            # 볼린저 밴드 조건
            if 'bb_lower' in df.columns and 'close' in df.columns:
                buy_conditions.append(df['close'] <= df['bb_lower'] * 1.02)
                
            # RSI 과매도 조건
            if 'rsi' in df.columns:
                buy_conditions.append(df['rsi'] < 40)
                
            # 매수 신호
            if buy_conditions:
                buy_signal = sum(buy_conditions) >= max(1, len(buy_conditions) * 0.5)
                signals[buy_signal] = 1

            # 매도 신호
            sell_conditions = []
            if 'bb_upper' in df.columns and 'close' in df.columns:
                sell_conditions.append(df['close'] >= df['bb_upper'] * 0.98)
            if 'rsi' in df.columns:
                sell_conditions.append(df['rsi'] > 70)
                
            if sell_conditions:
                sell_signal = any(sell_conditions)
                signals[sell_signal] = -1

        except Exception as e:
            self.logger.error(f"평균회귀 전략 계산 오류: {e}")

        return signals

    def simple_breakout_strategy(self, df: pd.DataFrame) -> pd.Series:
        """간단한 돌파 전략"""
        signals = pd.Series(0, index=df.index)

        try:
            # 최근 고점 돌파
            period = min(20, len(df)//3)
            if period >= 5:
                df['high_period'] = df['high'].rolling(window=period).max()
                
                buy_conditions = [
                    df['close'] > df['high_period'].shift(1),
                    df.get('volume_ratio', 1) > 1.2
                ]
                
                buy_signal = sum(buy_conditions) >= 1
                signals[buy_signal] = 1

                # 매도 조건
                if 'ma10' in df.columns:
                    sell_signal = df['close'] < df['ma10']
                    signals[sell_signal] = -1

        except Exception as e:
            self.logger.error(f"돌파 전략 계산 오류: {e}")

        return signals

    def simple_backtest(self, df: pd.DataFrame, strategy_func, initial_capital: float = 1000000) -> Dict:
        """간단한 백테스트 (에러 처리 강화)"""
        if len(df) < 20:
            return {'error': '데이터 부족'}

        try:
            signals = strategy_func(df)
            
            if signals is None or len(signals) == 0:
                return {'error': '신호 생성 실패'}
                
            positions = pd.Series(0, index=df.index)
            portfolio_value = initial_capital
            trades = []
            
            current_position = 0
            entry_price = 0
            
            for i in range(1, len(df)):
                current_price = df['close'].iloc[i]
                signal = signals.iloc[i] if i < len(signals) else 0
                
                # 매수 신호
                if current_position == 0 and signal == 1:
                    current_position = 1
                    entry_price = current_price
                    trades.append({'type': 'buy', 'price': current_price, 'date': df['date'].iloc[i] if 'date' in df.columns else i})
                
                # 매도 신호 또는 손절/익절
                elif current_position == 1:
                    should_sell = False
                    
                    if signal == -1:
                        should_sell = True
                    elif (current_price - entry_price) / entry_price <= -0.08:  # 8% 손절
                        should_sell = True
                    elif (current_price - entry_price) / entry_price >= 0.25:  # 25% 익절
                        should_sell = True
                    
                    if should_sell:
                        return_pct = (current_price - entry_price) / entry_price
                        portfolio_value *= (1 + return_pct)
                        trades.append({
                            'type': 'sell', 
                            'price': current_price, 
                            'return': return_pct,
                            'date': df['date'].iloc[i] if 'date' in df.columns else i
                        })
                        current_position = 0
                
                positions.iloc[i] = current_position

            # 성과 계산
            completed_trades = len([t for t in trades if t['type'] == 'sell'])
            if completed_trades == 0:
                return {'error': '완료된 거래 없음'}
            
            returns = [t['return'] for t in trades if t['type'] == 'sell']
            total_return = portfolio_value / initial_capital - 1
            
            winning_trades = len([r for r in returns if r > 0])
            total_trades = len(returns)
            win_rate = winning_trades / total_trades if total_trades > 0 else 0
            
            avg_return = np.mean(returns)
            volatility = np.std(returns) if len(returns) > 1 else 0
            sharpe_ratio = avg_return / volatility if volatility > 0 else 0
            
            # 간단한 최대 낙폭 계산
            max_drawdown = min(returns) if returns else 0

            return {
                'total_return': total_return,
                'win_rate': win_rate,
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': total_trades - winning_trades,
                'avg_win': np.mean([r for r in returns if r > 0]) if winning_trades > 0 else 0,
                'avg_loss': np.mean([r for r in returns if r <= 0]) if (total_trades - winning_trades) > 0 else 0,
                'max_drawdown': max_drawdown,
                'sharpe_ratio': sharpe_ratio,
                'profit_factor': abs(sum([r for r in returns if r > 0]) / sum([r for r in returns if r <= 0])) if sum([r for r in returns if r <= 0]) != 0 else 0,
                'final_capital': portfolio_value
            }

        except Exception as e:
            self.logger.error(f"백테스트 오류: {e}")
            return {'error': str(e)}

    def run_comprehensive_backtest(self, stock_codes: List[str], stock_names: Dict[str, str] = None, days: int = 200):
        """종합 백테스트 실행 (개선된 버전)"""
        self.logger.info("🚀 강화된 KIS API 백테스트 시작!")
        self.logger.info("=" * 60)

        if stock_names is None:
            stock_names = {}

        strategies = {
            'simple_momentum': self.simple_momentum_strategy,
            'simple_mean_reversion': self.simple_mean_reversion_strategy,
            'simple_breakout': self.simple_breakout_strategy,
        }

        all_results = []
        successful_analysis = 0
        failed_analysis = 0

        for i, stock_code in enumerate(stock_codes, 1):
            stock_name = stock_names.get(stock_code, stock_code)
            self.logger.info(f"📊 [{i}/{len(stock_codes)}] {stock_name}({stock_code}) 종목 분석 중...")

            # 데이터 조회 (재시도 포함)
            df = self.get_stock_data_with_retry(stock_code, count=days)
            if df.empty:
                self.logger.warning(f"❌ {stock_code} - 데이터 조회 실패")
                failed_analysis += 1
                continue

            # 기술적 지표 계산
            df = self.calculate_basic_indicators(df)

            # 각 전략별 백테스트
            stock_success = False
            for strategy_name, strategy_func in strategies.items():
                try:
                    result = self.simple_backtest(df, strategy_func)

                    if 'error' in result:
                        self.logger.warning(f"❌ {stock_code} - {strategy_name} 오류: {result['error']}")
                        continue

                    result['stock_code'] = stock_code
                    result['stock_name'] = stock_name
                    result['strategy'] = strategy_name
                    all_results.append(result)
                    stock_success = True

                    self.logger.info(f"✅ {stock_name} - {strategy_name}: 수익률 {result['total_return']:.2%}, 승률 {result['win_rate']:.1%}")

                except Exception as e:
                    self.logger.error(f"❌ {stock_code} - {strategy_name} 오류: {str(e)}")
                    continue

            if stock_success:
                successful_analysis += 1
            else:
                failed_analysis += 1

            # API 호출 제한 방지
            time.sleep(0.3)

        # 결과 정리
        self.logger.info(f"\n📊 분석 완료: 성공 {successful_analysis}개, 실패 {failed_analysis}개")
        
        if all_results:
            results_df = pd.DataFrame(all_results)
            self.save_simple_results(results_df, stock_names)
            return results_df
        else:
            self.logger.warning("❌ 백테스트 결과가 없습니다.")
            return pd.DataFrame()

    def save_simple_results(self, results_df: pd.DataFrame, stock_names: Dict[str, str]):
        """간단한 결과 저장"""
        try:
            # 최소 거래 조건 필터링
            valid_results = results_df[results_df['total_trades'] >= 2]
            
            if valid_results.empty:
                self.logger.warning("❌ 유효한 백테스트 결과가 없습니다.")
                return

            # 종목별 최고 전략 선택
            best_strategies = []
            for stock_code in valid_results['stock_code'].unique():
                stock_results = valid_results[valid_results['stock_code'] == stock_code]
                best_row = stock_results.loc[stock_results['total_return'].idxmax()]
                
                best_strategies.append({
                    'symbol': stock_code,
                    'name': stock_names.get(stock_code, stock_code),
                    'strategy': best_row['strategy'],
                    'total_return': round(best_row['total_return'] * 100, 2),
                    'win_rate': round(best_row['win_rate'] * 100, 1),
                    'sharpe_ratio': round(best_row['sharpe_ratio'], 3),
                    'max_drawdown': round(best_row['max_drawdown'] * 100, 2),
                    'total_trades': int(best_row['total_trades']),
                    'final_capital': round(best_row['final_capital']),
                    'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })

            # 수익률 기준 정렬
            best_strategies.sort(key=lambda x: x['total_return'], reverse=True)

            # 추천 종목 선별 (수익률 10% 이상, 승률 50% 이상)
            recommended = [s for s in best_strategies if s['total_return'] >= 10 and s['win_rate'] >= 50]

            # 결과 구성
            enhanced_results = {
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'backtest_period': f"{len(results_df)} strategies tested",
                'analysis_summary': {
                    'total_symbols': len(best_strategies),
                    'recommended_count': len(recommended),
                    'avg_return': round(valid_results['total_return'].mean() * 100, 2),
                    'best_return': round(valid_results['total_return'].max() * 100, 2),
                    'avg_win_rate': round(valid_results['win_rate'].mean() * 100, 1)
                },
                'recommended_stocks': recommended,
                'all_tested_symbols': best_strategies,
                'strategy_performance': {
                    strategy: {
                        'avg_return': round(results_df[results_df['strategy'] == strategy]['total_return'].mean() * 100, 2),
                        'success_rate': round(len(results_df[(results_df['strategy'] == strategy) & (results_df['total_return'] > 0)]) / len(results_df[results_df['strategy'] == strategy]) * 100, 1)
                    }
                    for strategy in results_df['strategy'].unique()
                }
            }

            # JSON 파일로 저장
            with open("enhanced_backtest_results.json", 'w', encoding='utf-8') as f:
                json.dump(enhanced_results, f, ensure_ascii=False, indent=2)
            
            self.logger.info(f"✅ 백테스트 결과가 enhanced_backtest_results.json에 저장되었습니다.")
            self.logger.info(f"📊 총 {len(best_strategies)}개 종목, {len(recommended)}개 추천 종목")
            
            # 상위 결과 로깅
            self.logger.info(f"\n🏆 상위 5개 종목:")
            for i, stock in enumerate(best_strategies[:5], 1):
                self.logger.info(f"  {i}. {stock['name']}({stock['symbol']}) - {stock['strategy']}")
                self.logger.info(f"     수익률: {stock['total_return']:.1f}%, 승률: {stock['win_rate']:.1f}%, 거래수: {stock['total_trades']}")
            
        except Exception as e:
            self.logger.error(f"❌ 결과 저장 실패: {e}")

def load_stock_codes_from_file(file_path: str) -> Tuple[List[str], Dict[str, str]]:
    """파일에서 종목 코드와 종목명 로드 (에러 처리 강화)"""
    if not os.path.exists(file_path):
        print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return [], {}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            
        if not content:
            print(f"❌ 파일이 비어있습니다: {file_path}")
            return [], {}
            
        data = json.loads(content)
        
        stock_codes = []
        stock_names = {}
        
        if isinstance(data, list) and data:
            if isinstance(data[0], dict) and 'code' in data[0]:
                # [{"code": "034020", "name": "두산에너빌리티", ...}, ...] 형태
                for item in data:
                    if 'code' in item:
                        code = str(item['code']).zfill(6)
                        name = item.get('name', code)
                        stock_codes.append(code)
                        stock_names[code] = name
                print(f"✅ {len(stock_codes)}개 종목 로드 완료: {file_path}")
            else:
                # ["062040", "278470", ...] 형태
                stock_codes = [str(code).zfill(6) for code in data if str(code).strip()]
                stock_names = {code: code for code in stock_codes}
                print(f"✅ {len(stock_codes)}개 종목 로드 완료: {file_path}")
        
        return stock_codes, stock_names
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON 파싱 오류 ({file_path}): {e}")
        print("파일 내용을 확인해주세요.")
        return [], {}
    except Exception as e:
        print(f"❌ 파일 읽기 오류 ({file_path}): {e}")
        return [], {}

def load_enhanced_analysis_results(file_path: str = "enhanced_analysis_results.json") -> Tuple[List[str], Dict[str, str]]:
    """강화된 분석 결과에서 추천 종목 로드 (에러 처리 강화)"""
    if not os.path.exists(file_path):
        print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return [], {}
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            
        if not content:
            print(f"❌ 파일이 비어있습니다: {file_path}")
            return [], {}
            
        data = json.loads(content)
        
        stock_codes = []
        stock_names = {}
        
        # recommended_stocks에서 고품질 종목 우선 로드
        if 'recommended_stocks' in data and data['recommended_stocks']:
            for stock in data['recommended_stocks']:
                code = str(stock.get('symbol', '')).zfill(6)
                name = stock.get('name', code)
                if code and len(code) == 6 and code.isdigit():
                    stock_codes.append(code)
                    stock_names[code] = name
        
        # top_stocks에서 추가 로드 (상위 10개만)
        elif 'top_stocks' in data and data['top_stocks']:
            for stock in data['top_stocks'][:10]:
                code = str(stock.get('code', '')).zfill(6)
                name = stock.get('name', code)
                if code and len(code) == 6 and code.isdigit():
                    stock_codes.append(code)
                    stock_names[code] = name
        
        # verified_symbols 에서 로드 (백테스트 결과)
        elif 'verified_symbols' in data and data['verified_symbols']:
            for stock in data['verified_symbols'][:10]:
                code = str(stock.get('symbol', '')).zfill(6)
                name = stock.get('name', code)
                if code and len(code) == 6 and code.isdigit():
                    stock_codes.append(code)
                    stock_names[code] = name
        
        print(f"✅ 강화된 분석 결과에서 {len(stock_codes)}개 추천 종목 로드")
        return stock_codes, stock_names
        
    except json.JSONDecodeError as e:
        print(f"❌ 강화된 분석 결과 JSON 파싱 오류: {e}")
        return [], {}
    except Exception as e:
        print(f"❌ 강화된 분석 결과 파일 읽기 오류: {e}")
        return [], {}

def create_portfolio_from_backtest(backtest_results_file: str = "enhanced_backtest_results.json"):
    """백테스트 결과를 바탕으로 최적 포트폴리오 생성"""
    if not os.path.exists(backtest_results_file):
        print(f"❌ 백테스트 결과 파일을 찾을 수 없습니다: {backtest_results_file}")
        return
    
    try:
        with open(backtest_results_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        recommended = data.get('recommended_stocks', [])
        all_tested = data.get('all_tested_symbols', [])
        
        # 추천 종목이 없으면 전체에서 상위 선별
        if not recommended and all_tested:
            # 수익률 5% 이상인 종목들을 추천으로 분류
            recommended = [s for s in all_tested if s.get('total_return', 0) >= 5][:8]
        
        if not recommended:
            print("❌ 추천 종목이 없습니다.")
            return
        
        # 포트폴리오 구성 (상위 5-8개 종목)
        portfolio_size = min(8, len(recommended))
        selected_stocks = recommended[:portfolio_size]
        
        print(f"\n💎 최적 포트폴리오 구성 ({portfolio_size}개 종목)")
        print("=" * 60)
        
        total_score = sum(max(1, stock.get('total_return', 1)) for stock in selected_stocks)
        
        for i, stock in enumerate(selected_stocks, 1):
            # 수익률 기반 가중치 계산
            return_score = max(1, stock.get('total_return', 1))
            weight = (return_score / total_score) * 100
            weight = max(8, min(20, weight))  # 8-20% 사이로 제한
            
            print(f"{i}. {stock.get('name', 'Unknown')} ({stock.get('symbol', 'N/A')})")
            print(f"   📊 전략: {stock.get('strategy', 'N/A')}")
            print(f"   📈 수익률: {stock.get('total_return', 0):.1f}% | 승률: {stock.get('win_rate', 0):.1f}%")
            print(f"   🛡️ 최대낙폭: {stock.get('max_drawdown', 0):.1f}% | 샤프: {stock.get('sharpe_ratio', 0):.2f}")
            print(f"   💰 권장 비중: {weight:.1f}%")
            print()
        
        # 포트폴리오 요약
        returns = [s.get('total_return', 0) for s in selected_stocks]
        sharpes = [s.get('sharpe_ratio', 0) for s in selected_stocks if s.get('sharpe_ratio', 0) != 0]
        drawdowns = [abs(s.get('max_drawdown', 0)) for s in selected_stocks]
        
        avg_return = np.mean(returns) if returns else 0
        avg_sharpe = np.mean(sharpes) if sharpes else 0
        max_drawdown = max(drawdowns) if drawdowns else 0
        
        print(f"🎯 포트폴리오 예상 성과:")
        print(f"   📊 평균 수익률: {avg_return:.1f}%")
        print(f"   📊 평균 샤프비율: {avg_sharpe:.2f}")
        print(f"   📊 최대 예상 낙폭: -{max_drawdown:.1f}%")
        print(f"   📊 리스크 등급: {'낮음' if max_drawdown < 8 else '보통' if max_drawdown < 15 else '높음'}")
        
        # 포트폴리오를 별도 파일로 저장
        portfolio_data = {
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'portfolio_summary': {
                'total_stocks': portfolio_size,
                'expected_return': round(avg_return, 1),
                'expected_sharpe': round(avg_sharpe, 2),
                'max_expected_drawdown': round(max_drawdown, 1),
                'risk_level': 'LOW' if max_drawdown < 8 else 'MEDIUM' if max_drawdown < 15 else 'HIGH'
            },
            'holdings': []
        }
        
        for i, stock in enumerate(selected_stocks):
            return_score = max(1, stock.get('total_return', 1))
            weight = max(8, min(20, (return_score / total_score) * 100))
            portfolio_data['holdings'].append({
                'rank': i + 1,
                'symbol': stock.get('symbol', 'N/A'),
                'name': stock.get('name', 'Unknown'),
                'strategy': stock.get('strategy', 'N/A'),
                'weight_percent': round(weight, 1),
                'expected_return': stock.get('total_return', 0),
                'win_rate': stock.get('win_rate', 0),
                'sharpe_ratio': stock.get('sharpe_ratio', 0),
                'max_drawdown': stock.get('max_drawdown', 0)
            })
        
        with open('optimal_portfolio.json', 'w', encoding='utf-8') as f:
            json.dump(portfolio_data, f, ensure_ascii=False, indent=2)
        
        print(f"\n✅ 최적 포트폴리오가 optimal_portfolio.json에 저장되었습니다.")
        
    except Exception as e:
        print(f"❌ 포트폴리오 생성 실패: {e}")

# 실행 코드
if __name__ == "__main__":
    print("🚀 문제 해결된 KIS 백테스트 시스템 시작")
    print("=" * 60)
    
    APP_KEY = os.getenv("KIS_APP_KEY")
    APP_SECRET = os.getenv("KIS_APP_SECRET")
    
    if not APP_KEY or not APP_SECRET:
        print("❌ KIS API 키가 설정되지 않았습니다.")
        print("   환경변수 KIS_APP_KEY, KIS_APP_SECRET을 확인해주세요.")
        exit(1)

    # 강화된 백테스터 초기화
    backtester = EnhancedKISBacktester(APP_KEY, APP_SECRET)

    # 1. 기본 우량주 종목 리스트 (확실히 데이터가 있는 종목들)
    base_stock_info = {
        "005930": "삼성전자",
        "000660": "SK하이닉스", 
        "207940": "삼성바이오로직스",
        "005380": "현대차",
        "006400": "삼성SDI",
        "051910": "LG화학",
        "035420": "NAVER",
        "028260": "삼성물산",
        "068270": "셀트리온",
        "105560": "KB금융",
        "096770": "SK이노베이션",
        "003670": "포스코홀딩스",
        "017670": "SK텔레콤",
        "018260": "삼성SDS",
        "032830": "삼성생명",
        "012330": "현대모비스",
        "009150": "삼성전기",
        "011200": "HMM",
        "034730": "SK",
        "000270": "기아",
    }
    
    base_stock_list = list(base_stock_info.keys())
    base_stock_names = base_stock_info

    # 2. 강화된 분석 결과에서 추천 종목 로드 (에러 처리)
    enhanced_codes, enhanced_names = load_enhanced_analysis_results("enhanced_analysis_results.json")
    
    # 3. 기존 백테스트 리스트에서 종목 로드 (에러 처리)
    backtest_codes, backtest_names = load_stock_codes_from_file("backtest_list.json")
    
    # 4. 모든 종목 합치기 (중복 제거)
    all_stock_codes = list(set(base_stock_list + enhanced_codes + backtest_codes))
    all_stock_names = {**base_stock_names, **enhanced_names, **backtest_names}
    
    # 5. 종목 수 제한 (API 제한 고려)
    max_stocks = 25  # 안정적인 분석을 위해 25개로 제한
    if len(all_stock_codes) > max_stocks:
        print(f"⚠️ 총 {len(all_stock_codes)}개 종목 중 상위 {max_stocks}개만 선택하여 백테스트를 진행합니다.")
        # 기본 우량주를 우선으로 하고 나머지 추가
        priority_codes = base_stock_list[:15] + all_stock_codes[len(base_stock_list):max_stocks-15]
        all_stock_codes = priority_codes[:max_stocks]
    
    print(f"\n📋 백테스트 대상 종목: {len(all_stock_codes)}개")
    print(f"📋 주요 종목: {', '.join([f'{code}({all_stock_names.get(code, code)})' for code in all_stock_codes[:5]])}{'...' if len(all_stock_codes) > 5 else ''}")
    
    # 6. 백테스트 실행
    estimated_time = len(all_stock_codes) * 3 * 0.4 / 60  # 3개 전략 * 0.4초
    print(f"\n🚀 백테스트 시작... (예상 소요시간: {estimated_time:.1f}분)")
    print("   - 3개 간단한 전략 테스트 (모멘텀, 평균회귀, 돌파)")
    print("   - 데이터 부족 시 자동 조정")
    print("   - 에러 처리 강화")
    print()
    
    try:
        results = backtester.run_comprehensive_backtest(all_stock_codes, all_stock_names, days=200)
        
        if not results.empty:
            print(f"\n🎉 백테스트 완료!")
            print("=" * 50)
            print(f"📊 총 {len(results)}개 전략 조합 테스트 완료")
            print(f"🎯 평균 수익률: {results['total_return'].mean():.2%}")
            print(f"🏆 최고 수익률: {results['total_return'].max():.2%}")
            print(f"🎲 평균 승률: {results['win_rate'].mean():.1%}")
            
            # 성과 분석
            positive_strategies = len(results[results['total_return'] > 0])
            excellent_strategies = len(results[results['total_return'] > 0.1])  # 10% 이상
            
            print(f"\n📊 성과 분석:")
            print(f"   🟢 수익 전략: {positive_strategies}개 ({positive_strategies/len(results)*100:.1f}%)")
            print(f"   🌟 우수 전략 (10%+): {excellent_strategies}개")
            print(f"   📉 손실 전략: {len(results[results['total_return'] < 0])}개")
            
            # 상위 5개 전략 상세 출력
            top_5 = results.nlargest(5, 'total_return')
            print(f"\n🥇 상위 5개 전략 상세:")
            print("-" * 60)
            for i, (_, row) in enumerate(top_5.iterrows(), 1):
                print(f"{i}. {row['stock_name']}({row['stock_code']}) - {row['strategy']}")
                print(f"   💰 수익률: {row['total_return']:.2%} | 승률: {row['win_rate']:.1%}")
                print(f"   📊 거래수: {row['total_trades']}회 | 샤프: {row['sharpe_ratio']:.2f}")
                print()
            
            # 최적 포트폴리오 생성
            print("🎯 최적 포트폴리오 생성 중...")
            create_portfolio_from_backtest("enhanced_backtest_results.json")
            
        else:
            print("❌ 백테스트 결과가 없습니다.")
            print("   - 모든 종목에서 데이터 조회에 실패했습니다.")
            print("   - API 연결 상태와 종목 코드를 확인해주세요.")
            
    except KeyboardInterrupt:
        print("\n⚠️ 사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"❌ 백테스트 실행 중 오류 발생: {e}")
        print("   상세 오류 내용은 logs/enhanced_backtest.log 파일을 확인해주세요.")
    
    print(f"\n✅ 프로그램 종료")
    print(f"📁 생성된 파일:")
    print(f"   - enhanced_backtest_results.json: 전체 백테스트 결과")
    print(f"   - optimal_portfolio.json: 최적 포트폴리오 구성")
    print(f"   - logs/enhanced_backtest.log: 상세 실행 로그")
