"""
개별 종목 기반 업종 모멘텀 분석 모듈 (대안 버전)
- 업종지수 API가 작동하지 않는 경우 대안
- 개별 종목들의 평균 수익률로 업종 모멘텀 계산
- 네이버 금융 API 활용
"""
import requests
import time
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class SectorMomentumAnalyzerV2:
    """개별 종목 기반 업종 모멘텀 분석 클래스"""
    
    # 네이버 금융 업종 코드
    NAVER_SECTOR_CODES = {
        "0": "음식료품",
        "1": "섬유의복",
        "2": "종이목재",
        "3": "화학",
        "4": "의약품",
        "5": "비금속광물",
        "6": "철강금속",
        "7": "기계",
        "8": "전기전자",
        "9": "의료정밀",
        "10": "운수장비",
        "11": "유통업",
        "12": "전기가스업",
        "13": "건설업",
        "14": "운수창고",
        "15": "통신업",
        "16": "금융업",
        "17": "은행",
        "18": "증권",
        "19": "보험",
        "20": "서비스업",
        "21": "제조업"
    }
    
    def __init__(self, api_client):
        """
        Args:
            api_client: KIS API 클라이언트 인스턴스
        """
        self.api_client = api_client
        self.app_key = api_client.app_key
        self.app_secret = api_client.app_secret
    
    def get_sector_stocks_from_naver(self, sector_code: str) -> List[Dict]:
        """
        네이버 금융에서 특정 업종의 종목 리스트 조회
        
        Args:
            sector_code: 네이버 업종 코드 (0~21)
            
        Returns:
            List[Dict]: 종목 정보 리스트
        """
        try:
            url = f"https://finance.naver.com/sise/sise_group_detail.naver?type=upjong&no={sector_code}"
            headers = {"User-Agent": "Mozilla/5.0"}
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 종목 테이블 찾기
            table = soup.select_one("table.type_5")
            if not table:
                logger.warning(f"업종 {sector_code}: 테이블을 찾을 수 없음")
                return []
            
            stocks = []
            rows = table.select("tr")
            
            for row in rows:
                cols = row.select("td")
                if len(cols) < 7:
                    continue
                
                try:
                    # 종목명과 종목코드
                    name_tag = cols[1].select_one("a")
                    if not name_tag:
                        continue
                    
                    stock_name = name_tag.text.strip()
                    stock_href = name_tag.get("href", "")
                    stock_code = stock_href.split("code=")[-1] if "code=" in stock_href else ""
                    
                    if not stock_code:
                        continue
                    
                    # 현재가
                    current_price_text = cols[2].text.strip().replace(",", "")
                    current_price = int(current_price_text) if current_price_text else 0
                    
                    # 등락률
                    change_rate_text = cols[3].text.strip().replace("%", "").replace("+", "")
                    change_rate = float(change_rate_text) if change_rate_text else 0
                    
                    # 거래량
                    volume_text = cols[6].text.strip().replace(",", "")
                    volume = int(volume_text) if volume_text else 0
                    
                    if current_price > 0:
                        stock_info = {
                            'code': stock_code,
                            'name': stock_name,
                            'current_price': current_price,
                            'change_rate': change_rate,
                            'volume': volume
                        }
                        stocks.append(stock_info)
                        
                except (ValueError, IndexError, AttributeError) as e:
                    continue
            
            logger.info(f"업종 {sector_code}: {len(stocks)}개 종목 수집")
            return stocks
            
        except Exception as e:
            logger.error(f"네이버 금융 업종 {sector_code} 조회 오류: {e}")
            return []
    
    def get_stock_recent_performance(self, stock_code: str, days: int = 2) -> float:
        """
        개별 종목의 최근 N일 수익률 계산 (KIS API 사용)
        
        Args:
            stock_code: 종목 코드
            days: 조회 일수
            
        Returns:
            float: N일 수익률 (%)
        """
        try:
            # KIS API로 일봉 데이터 조회
            url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_client.get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST03010100"
            }
            
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
            
            params = {
                "fid_cond_mrkt_div_code": "J",  # J: 주식
                "fid_input_iscd": stock_code,
                "fid_input_date_1": start_date,
                "fid_input_date_2": end_date,
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "0"
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('rt_cd') == '0' and data.get('output2'):
                df = pd.DataFrame(data['output2'])
                df['close'] = pd.to_numeric(df['stck_clpr'], errors='coerce')
                df = df.dropna(subset=['close'])
                
                if len(df) >= days + 1:
                    recent_close = df.iloc[-1]['close']
                    past_close = df.iloc[-(days + 1)]['close']
                    
                    return_pct = ((recent_close - past_close) / past_close) * 100
                    return return_pct
            
            return 0.0
            
        except Exception as e:
            logger.debug(f"종목 {stock_code} 수익률 계산 오류: {e}")
            return 0.0
    
    def analyze_sector_momentum(self, min_days: int = 2, sample_size: int = 10) -> List[Dict]:
        """
        업종별 모멘텀 분석 (개별 종목 기반)
        
        Args:
            min_days: 최소 연속 상승 일수
            sample_size: 업종당 샘플링할 종목 수
            
        Returns:
            List[Dict]: 모멘텀이 높은 업종 정보
        """
        sector_performance = []
        
        logger.info(f"📊 {min_days}일 연속 상승 업종 분석 시작 (개별 종목 기반)...")
        
        for sector_code, sector_name in self.NAVER_SECTOR_CODES.items():
            try:
                # 1. 네이버에서 업종 종목 수집
                stocks = self.get_sector_stocks_from_naver(sector_code)
                
                if len(stocks) < 5:
                    logger.debug(f"업종 {sector_name}: 종목 수 부족")
                    continue
                
                # 2. 시가총액 상위 종목 샘플링 (거래량 기준 정렬)
                stocks.sort(key=lambda x: x['volume'], reverse=True)
                sample_stocks = stocks[:sample_size]
                
                # 3. 각 종목의 N일 수익률 계산
                returns = []
                for stock in sample_stocks:
                    return_pct = self.get_stock_recent_performance(stock['code'], days=min_days)
                    if return_pct != 0.0:
                        returns.append(return_pct)
                    time.sleep(0.1)  # API 호출 제한
                
                if len(returns) < 3:
                    logger.debug(f"업종 {sector_name}: 유효 데이터 부족")
                    continue
                
                # 4. 업종 평균 수익률 계산
                avg_return = sum(returns) / len(returns)
                
                # 5. 상승 종목 비율
                rising_ratio = sum(1 for r in returns if r > 0) / len(returns)
                
                # 6. 연속 상승 조건 (평균 수익률 > 0 & 상승 종목 비율 > 60%)
                if avg_return > 0 and rising_ratio >= 0.6:
                    sector_info = {
                        'code': sector_code,
                        'name': sector_name,
                        'consecutive_days': min_days,
                        'period_return': avg_return,
                        'rising_ratio': rising_ratio * 100,
                        'sample_size': len(returns),
                        'top_stocks': sample_stocks[:5]  # 상위 5개 종목
                    }
                    
                    sector_performance.append(sector_info)
                    logger.info(f"✅ {sector_name}: {min_days}일 평균 수익률 {avg_return:.2f}% "
                              f"(상승 비율 {rising_ratio*100:.1f}%)")
                
                time.sleep(0.5)  # 업종간 간격
                
            except Exception as e:
                logger.warning(f"⚠️ {sector_name} 분석 오류: {e}")
                continue
        
        # 수익률 기준 정렬
        sector_performance.sort(key=lambda x: x['period_return'], reverse=True)
        
        logger.info(f"🎯 모멘텀 상승 업종: {len(sector_performance)}개 발견")
        
        return sector_performance
    
    def get_top_stocks_from_rising_sectors(self, min_consecutive_days: int = 2,
                                          top_n_sectors: int = 5,
                                          top_n_stocks: int = 2) -> List[Dict]:
        """
        모멘텀 업종의 시가총액 상위 종목 추출
        
        Args:
            min_consecutive_days: 최소 연속 상승 일수
            top_n_sectors: 상위 N개 업종 선택
            top_n_stocks: 업종당 상위 N개 종목 선택
            
        Returns:
            List[Dict]: 추천 종목 리스트
        """
        logger.info("=" * 60)
        logger.info("🚀 업종 모멘텀 기반 종목 선정 시작 (V2)")
        logger.info("=" * 60)
        
        # 1. 업종 모멘텀 분석
        rising_sectors = self.analyze_sector_momentum(min_consecutive_days)
        
        if not rising_sectors:
            logger.warning(f"⚠️ 모멘텀 상승 업종이 없습니다.")
            return []
        
        # 2. 상위 N개 업종 선택
        selected_sectors = rising_sectors[:top_n_sectors]
        
        logger.info(f"\n📌 선정된 상위 {len(selected_sectors)}개 업종:")
        for i, sector in enumerate(selected_sectors, 1):
            logger.info(f"  {i}. {sector['name']}: "
                       f"{sector['consecutive_days']}일 평균 +{sector['period_return']:.2f}% "
                       f"(상승 {sector['rising_ratio']:.0f}%)")
        
        # 3. 각 업종의 상위 종목 추출
        recommended_stocks = []
        
        for sector in selected_sectors:
            logger.info(f"\n🔍 {sector['name']} 업종 종목:")
            
            top_stocks = sector['top_stocks'][:top_n_stocks]
            
            for rank, stock in enumerate(top_stocks, 1):
                # 개별 종목 수익률 재계산
                stock_return = self.get_stock_recent_performance(
                    stock['code'], days=min_consecutive_days
                )
                
                stock_data = {
                    'sector_code': sector['code'],
                    'sector_name': sector['name'],
                    'sector_return': sector['period_return'],
                    'sector_consecutive_days': sector['consecutive_days'],
                    'rank_in_sector': rank,
                    'stock_code': stock['code'],
                    'stock_name': stock['name'],
                    'current_price': stock['current_price'],
                    'change_rate': stock_return,  # 실제 수익률
                    'volume': stock['volume']
                }
                
                recommended_stocks.append(stock_data)
                
                logger.info(f"  ✅ #{rank} {stock['name']}({stock['code']}): "
                          f"현재가 {stock['current_price']:,}원 "
                          f"({stock_return:+.2f}%)")
                
                time.sleep(0.1)
        
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
        message_lines.append("🚀 **[업종 모멘텀 기반 추천 종목 V2]**")
        message_lines.append("💡 *개별 종목 분석 기반 상승 업종의 대표주*\n")
        
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
            
            message_lines.append(f"**📊 {sector_name} 업종** ({consecutive_days}일 평균 +{sector_return:.2f}%)")
            
            for stock in sector_stocks:
                message_lines.append(
                    f"  {stock['rank_in_sector']}위. **{stock['stock_name']} ({stock['stock_code']})**"
                )
                message_lines.append(
                    f"      💰 현재가: {stock['current_price']:,}원 ({stock['change_rate']:+.2f}%)"
                )
            
            message_lines.append("")  # 빈 줄
        
        message_lines.append("⏰ 전략: 매수 후 1주일 보유")
        message_lines.append(f"📅 분석시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        return "\n".join(message_lines)
