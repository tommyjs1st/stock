"""
업종 모멘텀 분석 모듈
2일 연속 상승 업종의 시가총액 상위 종목 추출
"""
import requests
import time
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class SectorMomentumAnalyzer:
    """업종 모멘텀 분석 클래스"""
    
    # 한국 업종 코드 매핑 (KOSPI 주요 업종)
    SECTOR_CODES = {
        "G10": "음식료품",
        "G15": "섬유의복", 
        "G20": "종이목재",
        "G25": "화학",
        "G30": "의약품",
        "G35": "비금속광물",
        "G40": "철강금속",
        "G45": "기계",
        "G50": "전기전자",
        "G55": "의료정밀",
        "G56": "운수장비",
        "G57": "운수창고",
        "G60": "유통업",
        "G65": "통신업",
        "G70": "금융업",
        "G75": "은행",
        "G80": "증권",
        "G85": "보험",
        "G90": "서비스업",
        "G93": "건설업",
        "G94": "기타제조"
    }
    
    def __init__(self, api_client):
        """
        Args:
            api_client: KIS API 클라이언트 인스턴스
        """
        self.api_client = api_client
        self.app_key = api_client.app_key
        self.app_secret = api_client.app_secret
        self.access_token = None
        
    def _get_access_token(self):
        """액세스 토큰 가져오기"""
        if not self.access_token:
            self.access_token = self.api_client.get_access_token()
        return self.access_token
    
    def get_sector_price_data(self, sector_code: str, days: int = 5) -> pd.DataFrame:
        """
        업종 지수 일별 가격 데이터 조회
        
        Args:
            sector_code: 업종 코드 (예: G50)
            days: 조회할 일수
            
        Returns:
            DataFrame: 업종 지수 데이터
        """
        try:
            url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self._get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKUP03500100"  # 업종 기간별 시세 조회
            }
            
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
            
            params = {
                "FID_COND_MRKT_DIV_CODE": "U",  # 업종
                "FID_INPUT_ISCD": sector_code,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": end_date,
                "FID_PERIOD_DIV_CODE": "D",  # 일봉
                "FID_ORG_ADJ_PRC": "0"
            }
            
            time.sleep(0.2)  # API 호출 제한
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                
                # 필요한 컬럼만 추출 및 변환
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
            logger.error(f"업종 {sector_code} 가격 데이터 조회 오류: {e}")
            return pd.DataFrame()
    
    def get_consecutive_rising_sectors(self, min_days: int = 2) -> List[Dict]:
        """
        N일 연속 상승한 업종 찾기
        
        Args:
            min_days: 최소 연속 상승 일수
            
        Returns:
            List[Dict]: 연속 상승 업종 정보 리스트
        """
        rising_sectors = []
        
        logger.info(f"📊 {min_days}일 연속 상승 업종 분석 시작...")
        
        for sector_code, sector_name in self.SECTOR_CODES.items():
            try:
                # 업종 데이터 조회
                df = self.get_sector_price_data(sector_code, days=10)
                
                if df.empty or len(df) < min_days + 1:
                    continue
                
                # 최근 N일 연속 상승 확인
                recent_data = df.tail(min_days + 1)
                
                # 종가 기준 연속 상승 체크
                is_consecutive_rising = True
                for i in range(len(recent_data) - min_days, len(recent_data)):
                    if recent_data.iloc[i]['close'] <= recent_data.iloc[i-1]['close']:
                        is_consecutive_rising = False
                        break
                
                if is_consecutive_rising:
                    # 수익률 계산
                    period_return = ((recent_data.iloc[-1]['close'] / recent_data.iloc[-min_days-1]['close']) - 1) * 100
                    daily_returns = []
                    
                    for i in range(len(recent_data) - min_days, len(recent_data)):
                        daily_return = ((recent_data.iloc[i]['close'] / recent_data.iloc[i-1]['close']) - 1) * 100
                        daily_returns.append(daily_return)
                    
                    sector_info = {
                        'code': sector_code,
                        'name': sector_name,
                        'consecutive_days': min_days,
                        'period_return': period_return,
                        'daily_returns': daily_returns,
                        'current_price': recent_data.iloc[-1]['close'],
                        'avg_daily_return': sum(daily_returns) / len(daily_returns)
                    }
                    
                    rising_sectors.append(sector_info)
                    logger.info(f"✅ {sector_name}({sector_code}): {min_days}일 연속 상승, "
                              f"누적 수익률 {period_return:.2f}%")
                
                time.sleep(0.1)  # API 호출 간격
                
            except Exception as e:
                logger.warning(f"⚠️ {sector_name}({sector_code}) 분석 오류: {e}")
                continue
        
        # 수익률 기준 정렬
        rising_sectors.sort(key=lambda x: x['period_return'], reverse=True)
        
        logger.info(f"🎯 {min_days}일 연속 상승 업종: {len(rising_sectors)}개 발견")
        
        return rising_sectors
    
    def get_sector_stocks(self, sector_code: str) -> List[Dict]:
        """
        특정 업종의 종목 리스트 조회
        
        Args:
            sector_code: 업종 코드
            
        Returns:
            List[Dict]: 종목 정보 리스트
        """
        try:
            url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-sector-stock"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self._get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKUP03500200"  # 업종별 종목 시세
            }
            
            params = {
                "FID_COND_MRKT_DIV_CODE": "U",
                "FID_INPUT_ISCD": sector_code
            }
            
            time.sleep(0.2)
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('output'):
                stocks = []
                for item in data['output']:
                    stock_info = {
                        'code': item.get('stck_shrn_iscd', ''),
                        'name': item.get('hts_kor_isnm', ''),
                        'current_price': float(item.get('stck_prpr', 0)),
                        'change_rate': float(item.get('prdy_ctrt', 0)),
                        'market_cap': float(item.get('lstg_stqt', 0)) * float(item.get('stck_prpr', 0)),  # 상장주식수 * 현재가
                        'volume': int(item.get('acml_vol', 0))
                    }
                    
                    if stock_info['code'] and stock_info['market_cap'] > 0:
                        stocks.append(stock_info)
                
                # 시가총액 기준 정렬
                stocks.sort(key=lambda x: x['market_cap'], reverse=True)
                
                return stocks
            
            return []
            
        except Exception as e:
            logger.error(f"업종 {sector_code} 종목 리스트 조회 오류: {e}")
            return []
    
    def get_top_stocks_from_rising_sectors(self, min_consecutive_days: int = 2, 
                                          top_n_sectors: int = 5, 
                                          top_n_stocks: int = 2) -> List[Dict]:
        """
        연속 상승 업종의 시가총액 상위 종목 추출
        
        Args:
            min_consecutive_days: 최소 연속 상승 일수
            top_n_sectors: 상위 N개 업종 선택
            top_n_stocks: 업종당 상위 N개 종목 선택
            
        Returns:
            List[Dict]: 추천 종목 리스트
        """
        logger.info("=" * 60)
        logger.info("🚀 업종 모멘텀 기반 종목 선정 시작")
        logger.info("=" * 60)
        
        # 1. 연속 상승 업종 찾기
        rising_sectors = self.get_consecutive_rising_sectors(min_consecutive_days)
        
        if not rising_sectors:
            logger.warning(f"⚠️ {min_consecutive_days}일 연속 상승 업종이 없습니다.")
            return []
        
        # 2. 상위 N개 업종 선택
        selected_sectors = rising_sectors[:top_n_sectors]
        
        logger.info(f"\n📌 선정된 상위 {len(selected_sectors)}개 업종:")
        for i, sector in enumerate(selected_sectors, 1):
            logger.info(f"  {i}. {sector['name']}({sector['code']}): "
                       f"{sector['consecutive_days']}일 연속 상승, "
                       f"누적 +{sector['period_return']:.2f}%")
        
        # 3. 각 업종의 시가총액 상위 종목 추출
        recommended_stocks = []
        
        for sector in selected_sectors:
            logger.info(f"\n🔍 {sector['name']} 업종 종목 분석 중...")
            
            stocks = self.get_sector_stocks(sector['code'])
            
            if not stocks:
                logger.warning(f"  ⚠️ {sector['name']} 업종 종목 조회 실패")
                continue
            
            # 상위 N개 종목 선택
            top_stocks = stocks[:top_n_stocks]
            
            for rank, stock in enumerate(top_stocks, 1):
                stock_data = {
                    'sector_code': sector['code'],
                    'sector_name': sector['name'],
                    'sector_return': sector['period_return'],
                    'sector_consecutive_days': sector['consecutive_days'],
                    'rank_in_sector': rank,
                    'stock_code': stock['code'],
                    'stock_name': stock['name'],
                    'current_price': stock['current_price'],
                    'change_rate': stock['change_rate'],
                    'market_cap': stock['market_cap'],
                    'market_cap_billion': stock['market_cap'] / 100000000,  # 억원 단위
                    'volume': stock['volume']
                }
                
                recommended_stocks.append(stock_data)
                
                logger.info(f"  ✅ #{rank} {stock['name']}({stock['code']}): "
                          f"시가총액 {stock_data['market_cap_billion']:.0f}억원, "
                          f"현재가 {stock['current_price']:,}원 ({stock['change_rate']:+.2f}%)")
            
            time.sleep(0.2)
        
        logger.info(f"\n🎯 최종 추천 종목: {len(recommended_stocks)}개")
        logger.info("=" * 60)
        
        return recommended_stocks
    
    def format_recommendations_message(self, stocks: List[Dict]) -> str:
        """
        추천 종목 메시지 포맷팅
        
        Args:
            stocks: 추천 종목 리스트
            
        Returns:
            str: 포맷된 메시지
        """
        if not stocks:
            return "📭 추천할 종목이 없습니다."
        
        message_lines = []
        message_lines.append("🚀 **[업종 모멘텀 기반 추천 종목]**")
        message_lines.append("💡 *2일 연속 상승 업종의 시가총액 상위주*\n")
        
        # 업종별로 그룹화
        sectors = {}
        for stock in stocks:
            sector_name = stock['sector_name']
            if sector_name not in sectors:
                sectors[sector_name] = []
            sectors[sector_name].append(stock)
        
        for sector_name, sector_stocks in sectors.items():
            sector_return = sector_stocks[0]['sector_return']
            consecutive_days = sector_stocks[0]['sector_consecutive_days']
            
            message_lines.append(f"**📊 {sector_name} 업종** ({consecutive_days}일 연속 +{sector_return:.2f}%)")
            
            for stock in sector_stocks:
                message_lines.append(
                    f"  {stock['rank_in_sector']}위. **{stock['stock_name']} ({stock['stock_code']})**"
                )
                message_lines.append(
                    f"      💰 시가총액: {stock['market_cap_billion']:.0f}억원 | "
                    f"현재가: {stock['current_price']:,}원 ({stock['change_rate']:+.2f}%)"
                )
            
            message_lines.append("")  # 빈 줄
        
        message_lines.append("⏰ 전략: 매수 후 1주일 보유")
        message_lines.append(f"📅 분석시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        return "\n".join(message_lines)


def test_sector_momentum():
    """테스트 함수"""
    import sys
    import os
    from dotenv import load_dotenv
    
    # analyze 디렉토리의 kis_api_client 사용
    sys.path.append('/Volumes/SSD/RESTAPI/analyze')
    from kis_api_client import KISAPIClient
    
    load_dotenv()
    
    # API 클라이언트 초기화
    api_client = KISAPIClient()
    
    # 업종 모멘텀 분석기 생성
    analyzer = SectorMomentumAnalyzer(api_client)
    
    # 2일 연속 상승 업종의 시가총액 상위 2개 종목 추출
    recommendations = analyzer.get_top_stocks_from_rising_sectors(
        min_consecutive_days=2,
        top_n_sectors=5,
        top_n_stocks=2
    )
    
    # 결과 출력
    if recommendations:
        print("\n" + "=" * 60)
        print(analyzer.format_recommendations_message(recommendations))
        print("=" * 60)
    else:
        print("\n⚠️ 추천할 종목이 없습니다.")


if __name__ == "__main__":
    # 로깅 설정
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )
    
    test_sector_momentum()
