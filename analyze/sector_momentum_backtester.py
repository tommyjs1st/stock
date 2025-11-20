"""
업종 모멘텀 전략 백테스트 모듈
과거 데이터로 전략 검증
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class SectorMomentumBacktester:
    """업종 모멘텀 전략 백테스트 클래스"""
    
    def __init__(self, api_client, sector_analyzer):
        """
        Args:
            api_client: KIS API 클라이언트
            sector_analyzer: SectorMomentumAnalyzer 인스턴스
        """
        self.api_client = api_client
        self.sector_analyzer = sector_analyzer
        
    def get_stock_price_data(self, stock_code: str, days: int = 30) -> pd.DataFrame:
        """
        종목 가격 데이터 조회
        
        Args:
            stock_code: 종목 코드
            days: 조회 일수
            
        Returns:
            DataFrame: 가격 데이터
        """
        try:
            url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_client.get_access_token()}",
                "appkey": self.api_client.app_key,
                "appsecret": self.api_client.app_secret,
                "tr_id": "FHKST03010100"
            }
            
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
            
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": stock_code,
                "fid_input_date_1": start_date,
                "fid_input_date_2": end_date,
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "0"
            }
            
            import time
            time.sleep(0.1)
            
            import requests
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                
                df['date'] = pd.to_datetime(df['stck_bsop_date'], format='%Y%m%d')
                df['close'] = pd.to_numeric(df['stck_clpr'], errors='coerce')
                df['open'] = pd.to_numeric(df['stck_oprc'], errors='coerce')
                df['high'] = pd.to_numeric(df['stck_hgpr'], errors='coerce')
                df['low'] = pd.to_numeric(df['stck_lwpr'], errors='coerce')
                df['volume'] = pd.to_numeric(df['acml_vol'], errors='coerce')
                
                df = df[['date', 'close', 'open', 'high', 'low', 'volume']]
                df = df.sort_values('date').reset_index(drop=True)
                
                return df
            
            return pd.DataFrame()
            
        except Exception as e:
            logger.error(f"종목 {stock_code} 가격 데이터 조회 오류: {e}")
            return pd.DataFrame()
    
    def simulate_holding_period(self, stock_code: str, stock_name: str, 
                                entry_date: datetime, holding_days: int = 7) -> Dict:
        """
        보유 기간 시뮬레이션
        
        Args:
            stock_code: 종목 코드
            stock_name: 종목명
            entry_date: 진입 날짜
            holding_days: 보유 일수
            
        Returns:
            Dict: 시뮬레이션 결과
        """
        try:
            # 가격 데이터 조회
            df = self.get_stock_price_data(stock_code, days=holding_days + 10)
            
            if df.empty:
                return {
                    'success': False,
                    'reason': '데이터 없음'
                }
            
            # 진입일 찾기
            entry_idx = None
            for idx, row in df.iterrows():
                if row['date'] >= entry_date:
                    entry_idx = idx
                    break
            
            if entry_idx is None or entry_idx >= len(df) - 1:
                return {
                    'success': False,
                    'reason': '진입일 데이터 없음'
                }
            
            # 진입가 (다음날 시가)
            if entry_idx + 1 < len(df):
                entry_price = df.iloc[entry_idx + 1]['open']
                entry_actual_date = df.iloc[entry_idx + 1]['date']
            else:
                return {
                    'success': False,
                    'reason': '진입가 데이터 없음'
                }
            
            # 청산일 찾기 (영업일 기준)
            exit_idx = min(entry_idx + 1 + holding_days, len(df) - 1)
            exit_price = df.iloc[exit_idx]['close']
            exit_date = df.iloc[exit_idx]['date']
            
            # 수익률 계산
            return_pct = ((exit_price - entry_price) / entry_price) * 100
            
            # 기간 내 최고가/최저가
            period_df = df.iloc[entry_idx + 1:exit_idx + 1]
            max_price = period_df['high'].max()
            min_price = period_df['low'].min()
            max_return = ((max_price - entry_price) / entry_price) * 100
            max_drawdown = ((min_price - entry_price) / entry_price) * 100
            
            return {
                'success': True,
                'stock_code': stock_code,
                'stock_name': stock_name,
                'entry_date': entry_actual_date.strftime('%Y-%m-%d'),
                'exit_date': exit_date.strftime('%Y-%m-%d'),
                'entry_price': entry_price,
                'exit_price': exit_price,
                'return_pct': return_pct,
                'max_return': max_return,
                'max_drawdown': max_drawdown,
                'holding_days': (exit_date - entry_actual_date).days
            }
            
        except Exception as e:
            logger.error(f"종목 {stock_code} 보유 시뮬레이션 오류: {e}")
            return {
                'success': False,
                'reason': f'오류: {e}'
            }
    
    def backtest_current_recommendations(self, recommendations: List[Dict], 
                                        holding_days: int = 7) -> Dict:
        """
        현재 추천 종목에 대한 백테스트 (가상 진입)
        
        Args:
            recommendations: 추천 종목 리스트
            holding_days: 보유 일수
            
        Returns:
            Dict: 백테스트 결과
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"📈 백테스트 시작 (보유기간: {holding_days}영업일)")
        logger.info(f"{'='*60}")
        
        results = []
        entry_date = datetime.now()
        
        for rec in recommendations:
            stock_code = rec['stock_code']
            stock_name = rec['stock_name']
            sector_name = rec['sector_name']
            
            logger.info(f"\n🔍 {stock_name}({stock_code}) - {sector_name} 업종")
            
            result = self.simulate_holding_period(
                stock_code, stock_name, entry_date, holding_days
            )
            
            if result['success']:
                result['sector_name'] = sector_name
                result['sector_return'] = rec['sector_return']
                results.append(result)
                
                logger.info(f"  📅 {result['entry_date']} 진입 ({result['entry_price']:,}원) "
                          f"→ {result['exit_date']} 청산 ({result['exit_price']:,}원)")
                logger.info(f"  💰 수익률: {result['return_pct']:+.2f}% "
                          f"(최고 {result['max_return']:+.2f}%, 최저 {result['max_drawdown']:+.2f}%)")
            else:
                logger.warning(f"  ⚠️ 시뮬레이션 실패: {result.get('reason', 'Unknown')}")
        
        # 통계 계산
        if results:
            returns = [r['return_pct'] for r in results]
            winning_trades = [r for r in results if r['return_pct'] > 0]
            
            stats = {
                'total_trades': len(results),
                'winning_trades': len(winning_trades),
                'win_rate': len(winning_trades) / len(results) * 100,
                'avg_return': np.mean(returns),
                'median_return': np.median(returns),
                'best_return': max(returns),
                'worst_return': min(returns),
                'std_return': np.std(returns),
                'total_return': sum(returns),
                'avg_max_return': np.mean([r['max_return'] for r in results]),
                'avg_max_drawdown': np.mean([r['max_drawdown'] for r in results]),
                'trades': results
            }
            
            logger.info(f"\n{'='*60}")
            logger.info("📊 백테스트 결과 요약")
            logger.info(f"{'='*60}")
            logger.info(f"총 거래 수: {stats['total_trades']}개")
            logger.info(f"승률: {stats['win_rate']:.1f}% ({stats['winning_trades']}/{stats['total_trades']})")
            logger.info(f"평균 수익률: {stats['avg_return']:+.2f}%")
            logger.info(f"중간값 수익률: {stats['median_return']:+.2f}%")
            logger.info(f"최고 수익률: {stats['best_return']:+.2f}%")
            logger.info(f"최악 수익률: {stats['worst_return']:+.2f}%")
            logger.info(f"수익률 표준편차: {stats['std_return']:.2f}%")
            logger.info(f"누적 수익률: {stats['total_return']:+.2f}%")
            logger.info(f"평균 최고 수익: {stats['avg_max_return']:+.2f}%")
            logger.info(f"평균 최대 손실: {stats['avg_max_drawdown']:+.2f}%")
            
            return stats
        else:
            logger.warning("⚠️ 백테스트할 데이터가 없습니다.")
            return {
                'total_trades': 0,
                'win_rate': 0,
                'avg_return': 0
            }
    
    def format_backtest_report(self, stats: Dict) -> str:
        """
        백테스트 리포트 포맷팅
        
        Args:
            stats: 백테스트 통계
            
        Returns:
            str: 포맷된 리포트
        """
        if stats['total_trades'] == 0:
            return "📭 백테스트 데이터가 없습니다."
        
        lines = []
        lines.append("📈 **[업종 모멘텀 전략 백테스트 결과]**\n")
        
        # 전체 통계
        lines.append("**📊 전체 통계**")
        lines.append(f"• 총 거래: {stats['total_trades']}개")
        lines.append(f"• 승률: **{stats['win_rate']:.1f}%** ({stats['winning_trades']}/{stats['total_trades']})")
        lines.append(f"• 평균 수익률: **{stats['avg_return']:+.2f}%**")
        lines.append(f"• 중간값: {stats['median_return']:+.2f}%")
        lines.append(f"• 최고/최악: {stats['best_return']:+.2f}% / {stats['worst_return']:+.2f}%")
        lines.append(f"• 변동성(σ): {stats['std_return']:.2f}%")
        lines.append(f"• 누적 수익: **{stats['total_return']:+.2f}%**\n")
        
        # 리스크 지표
        lines.append("**⚠️ 리스크 지표**")
        lines.append(f"• 평균 최고 수익: +{stats['avg_max_return']:.2f}%")
        lines.append(f"• 평균 최대 손실: {stats['avg_max_drawdown']:.2f}%\n")
        
        # 개별 거래 (상위 5개)
        lines.append("**🏆 상위 5개 거래**")
        sorted_trades = sorted(stats['trades'], key=lambda x: x['return_pct'], reverse=True)
        for i, trade in enumerate(sorted_trades[:5], 1):
            lines.append(
                f"{i}. {trade['stock_name']} ({trade['stock_code']}): "
                f"**{trade['return_pct']:+.2f}%** "
                f"({trade['sector_name']} 업종)"
            )
        
        # 하위 3개 거래
        if len(sorted_trades) > 5:
            lines.append("\n**📉 하위 3개 거래**")
            for i, trade in enumerate(sorted_trades[-3:], 1):
                lines.append(
                    f"{i}. {trade['stock_name']} ({trade['stock_code']}): "
                    f"{trade['return_pct']:+.2f}% "
                    f"({trade['sector_name']} 업종)"
                )
        
        lines.append(f"\n⏰ 보유기간: 약 {stats['trades'][0]['holding_days']}영업일")
        lines.append(f"📅 백테스트 일시: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        return "\n".join(lines)


def test_backtest():
    """백테스트 테스트 함수"""
    import sys
    sys.path.insert(0, '/Volumes/SSD/RESTAPI/analyze')
    from sector_momentum_analyzer import SectorMomentumAnalyzer
    
    # 간단한 더미 데이터로 테스트
    dummy_recommendations = [
        {
            'stock_code': '005930',
            'stock_name': '삼성전자',
            'sector_name': '전기전자',
            'sector_return': 3.5
        }
    ]
    
    print("백테스트 모듈 로드 완료")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    test_backtest()
