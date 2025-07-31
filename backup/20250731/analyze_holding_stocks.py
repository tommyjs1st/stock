import os
import sys
import time
import json
import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime, timedelta
from dotenv import load_dotenv
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional
from dotenv import load_dotenv
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 환경 변수 로드
load_dotenv()

# API 설정
APP_KEY = os.getenv("KIS_APP_KEY")
APP_SECRET = os.getenv("KIS_APP_SECRET")
ACCOUNT_NO = os.getenv("KIS_ACCOUNT_NO")
ACCOUNT_PW = os.getenv("KIS_ACCOUNT_PW")
CUSTTYPE = os.getenv("KIS_CUSTTYPE")
BASE_URL = os.getenv("KIS_ACCESS_URL")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
TOKEN_FILE = "token.json"

# ========================== 토큰 관리 ==========================
def request_new_token():
    """새 토큰 요청"""
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    data = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    res = requests.post(url, headers=headers, data=json.dumps(data)).json()
    res["requested_at"] = int(time.time())
    with open(TOKEN_FILE, "w") as f:
        json.dump(res, f)
    return res["access_token"]

def load_token():
    """토큰 로드 및 유효성 검사"""
    if not os.path.exists(TOKEN_FILE):
        return request_new_token()
    
    with open(TOKEN_FILE, "r") as f:
        token_data = json.load(f)

    now = int(time.time())
    issued_at = token_data.get("requested_at", 0)
    expires_in = int(token_data.get("expires_in", 0))
    
    if now - issued_at >= expires_in - 3600:
        return request_new_token()
    else:
        return token_data["access_token"]

# ========================== 보유 주식 조회 ==========================
def get_holdings():
    """보유 주식 조회"""
    token = load_token()
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "TTTC8434R",
    }
    params = {
        "CANO": ACCOUNT_NO[:8],
        "ACNT_PRDT_CD": ACCOUNT_NO[8:],
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "SORT_SQN": "ASC",
        "INQR_STRT_POS": "0",
        "INQR_MAX_LINE": "100",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": "",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01"
    }
    
    url = f"{BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance"
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        logger.error(f"보유 주식 조회 실패: {e}")
        raise e

    data = response.json()
    if data["rt_cd"] != "0":
        raise Exception(f"조회 실패: {data['msg1']}")

    stocks = data["output1"]
    if not stocks:
        logger.info("보유 종목이 없습니다.")
        return pd.DataFrame(columns=["code", "name", "quantity", "avg_price", "eval_profit"])

    df = pd.DataFrame(stocks)
    df = df[df["hldg_qty"].astype(float) > 0]
    df = df[["pdno", "prdt_name", "hldg_qty", "pchs_avg_pric", "evlu_pfls_amt"]]
    df.columns = ["code", "name", "quantity", "avg_price", "eval_profit"]
    
    return df

# ========================== OHLCV 데이터 조회 ==========================
def get_ohlcv(stock_code, adjust_price=True, start_date=None, end_date=None):
    """주식 OHLCV 데이터 조회"""
    token = load_token()

    if end_date is None:
        end_dt = datetime.today()
        end_date = end_dt.strftime("%Y%m%d")
    else:
        end_dt = datetime.strptime(end_date, "%Y%m%d")

    if start_date is None:
        start_dt = end_dt - timedelta(days=140)
        start_date = start_dt.strftime("%Y%m%d")

    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"

    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": "FHKST03010100",
        "custtype": CUSTTYPE or "P"
    }

    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code.zfill(6),
        "fid_input_date_1": start_date,
        "fid_input_date_2": end_date,
        "fid_period_div_code": "D",
        "fid_org_adj_prc": "1" if adjust_price else "0"
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get("rt_cd") != "0":
            raise Exception(f"조회 실패: {data.get('msg1', 'Unknown error')}")

        output = data.get("output2", [])
        if not output:
            raise Exception("받은 OHLCV 데이터가 없습니다.")

        df = pd.DataFrame(output)
        df = df[[
            "stck_bsop_date", "stck_oprc", "stck_hgpr", "stck_lwpr", "stck_clpr", "acml_vol"
        ]].rename(columns={
            "stck_bsop_date": "date",
            "stck_oprc": "open",
            "stck_hgpr": "high",
            "stck_lwpr": "low",
            "stck_clpr": "close",
            "acml_vol": "volume"
        })

        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        numeric_cols = ["open", "high", "low", "close", "volume"]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
        df = df.dropna().sort_values("date").reset_index(drop=True)

        return df
    except Exception as e:
        logger.error(f"OHLCV 데이터 조회 실패 ({stock_code}): {str(e)}")
        return None

# ========================== 신호 분석 시스템 ==========================
@dataclass
class SignalResult:
    """신호 결과를 담는 데이터 클래스"""
    signal_name: str
    signal_value: bool
    confidence: float
    metadata: Dict

class DataValidator:
    """데이터 검증 클래스"""
    
    @staticmethod
    def validate_ohlcv_data(df: pd.DataFrame, min_rows: int = 26) -> pd.DataFrame:
        """OHLCV 데이터 검증 및 전처리"""
        if df is None or df.empty:
            raise ValueError("데이터가 비어있습니다.")
        
        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        missing_cols = [col for col in required_columns if col not in df.columns]
        if missing_cols:
            raise ValueError(f"필수 컬럼이 누락되었습니다: {missing_cols}")
        
        df = df.copy()
        df['date'] = pd.to_datetime(df['date'])
        
        numeric_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        
        df = df.dropna(subset=numeric_cols)
        
        if len(df) < min_rows:
            raise ValueError(f"기술적 분석을 위해 최소 {min_rows}개의 데이터가 필요합니다. 현재: {len(df)}개")
        
        df = df.sort_values('date').reset_index(drop=True)
        return df

class BaseSignalDetector(ABC):
    """신호 감지기 기본 클래스"""
    
    def __init__(self, name: str):
        self.name = name
    
    @abstractmethod
    def detect(self, df: pd.DataFrame) -> SignalResult:
        pass

class MACDCrossDownDetector(BaseSignalDetector):
    """MACD 하향 교차 감지기"""
    
    def __init__(self, fast=12, slow=26, signal=9):
        super().__init__("MACD Cross Down")
        self.fast = fast
        self.slow = slow
        self.signal = signal
    
    def detect(self, df: pd.DataFrame) -> SignalResult:
        try:
            df_work = df.copy().reset_index(drop=True)
            
            # MACD 계산
            ema_fast = df_work['close'].ewm(span=self.fast).mean()
            ema_slow = df_work['close'].ewm(span=self.slow).mean()
            macd_line = ema_fast - ema_slow
            signal_line = macd_line.ewm(span=self.signal).mean()
            
            df_work['macd'] = macd_line
            df_work['signal'] = signal_line
            df_work = df_work.dropna(subset=['macd', 'signal'])
            
            if len(df_work) < 2:
                return SignalResult(self.name, False, 0.0, {"error": "계산 가능한 데이터 부족"})
            
            # 교차 판별 (MACD가 시그널 아래로 내려가는 경우)
            current_cross = (df_work['macd'].iloc[-1] < df_work['signal'].iloc[-1])
            prev_cross = (df_work['macd'].iloc[-2] > df_work['signal'].iloc[-2])
            cross_down = current_cross and prev_cross
            
            # 신뢰도 계산
            if len(df_work) >= 5:
                recent_diff = abs(df_work['macd'].iloc[-5:] - df_work['signal'].iloc[-5:])
                confidence = min(1.0, recent_diff.mean() / df_work['close'].iloc[-1] * 1000)
            else:
                confidence = 0.5
            
            return SignalResult(
                self.name, 
                cross_down, 
                confidence,
                {
                    "current_macd": df_work['macd'].iloc[-1],
                    "current_signal": df_work['signal'].iloc[-1],
                    "cross_down": cross_down
                }
            )
            
        except Exception as e:
            logger.error(f"MACD 계산 오류: {str(e)}")
            return SignalResult(self.name, False, 0.0, {"error": str(e)})

class RSIOverboughtDetector(BaseSignalDetector):
    """RSI 과매수 감지기"""
    
    def __init__(self, period=14, threshold=70):
        super().__init__("RSI Overbought")
        self.period = period
        self.threshold = threshold
    
    def detect(self, df: pd.DataFrame) -> SignalResult:
        try:
            df_work = df.copy().reset_index(drop=True)
            
            # RSI 계산
            delta = df_work['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=self.period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=self.period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            current_rsi = rsi.iloc[-1]
            overbought = current_rsi > self.threshold
            
            confidence = min(1.0, (current_rsi - self.threshold) / (100 - self.threshold)) if overbought else 0.0
            
            return SignalResult(
                self.name, 
                overbought, 
                confidence,
                {"current_rsi": current_rsi, "threshold": self.threshold}
            )
            
        except Exception as e:
            logger.error(f"RSI 계산 오류: {str(e)}")
            return SignalResult(self.name, False, 0.0, {"error": str(e)})

class BollingerBandDetector(BaseSignalDetector):
    """볼린저 밴드 돌파 감지기"""
    
    def __init__(self, period=20, std_dev=2):
        super().__init__("Bollinger Band Break")
        self.period = period
        self.std_dev = std_dev
    
    def detect(self, df: pd.DataFrame) -> SignalResult:
        try:
            df_work = df.copy().reset_index(drop=True)
            
            # 볼린저 밴드 계산
            sma = df_work['close'].rolling(window=self.period).mean()
            std = df_work['close'].rolling(window=self.period).std()
            upper_band = sma + (std * self.std_dev)
            
            current_price = df_work['close'].iloc[-1]
            current_upper = upper_band.iloc[-1]
            
            break_upper = current_price > current_upper
            
            confidence = max(0.0, min(1.0, (current_price - current_upper) / current_upper * 10)) if break_upper else 0.0
            
            return SignalResult(
                self.name, 
                break_upper, 
                confidence,
                {
                    "current_price": current_price,
                    "upper_band": current_upper,
                    "break_upper": break_upper
                }
            )
            
        except Exception as e:
            logger.error(f"볼린저 밴드 계산 오류: {str(e)}")
            return SignalResult(self.name, False, 0.0, {"error": str(e)})

class TradingSignalSystem:
    """거래 신호 시스템"""
    
    def __init__(self):
        self.validator = DataValidator()
        self.detectors = [
            MACDCrossDownDetector(),
            RSIOverboughtDetector(),
            BollingerBandDetector()
        ]
    
    def analyze(self, df: pd.DataFrame, strategy: str = "any") -> Dict:
        """전체 분석 실행"""
        try:
            # 데이터 검증
            validated_df = self.validator.validate_ohlcv_data(df)
            
            # 신호 감지
            signal_results = {}
            for detector in self.detectors:
                result = detector.detect(validated_df)
                signal_results[detector.name] = result
            
            # 결합 신호 계산
            if strategy == "all":
                combined_signal = all(result.signal_value for result in signal_results.values())
                combined_confidence = np.mean([result.confidence for result in signal_results.values()])
            elif strategy == "any":
                combined_signal = any(result.signal_value for result in signal_results.values())
                combined_confidence = max([result.confidence for result in signal_results.values()])
            else:
                combined_signal = False
                combined_confidence = 0.0
            
            # 결과 정리
            latest_data = validated_df.iloc[-1]
            
            return {
                "status": "success",
                "data": {
                    "latest_date": latest_data['date'].strftime('%Y-%m-%d'),
                    "latest_price": latest_data['close'],
                    "individual_signals": {name: {
                        "signal": result.signal_value,
                        "confidence": result.confidence,
                        "metadata": result.metadata
                    } for name, result in signal_results.items()},
                    "combined_signal": {
                        "signal": combined_signal,
                        "confidence": combined_confidence,
                        "strategy": strategy
                    }
                }
            }
            
        except Exception as e:
            logger.error(f"분석 중 오류: {str(e)}")
            return {
                "status": "error",
                "error": str(e)
            }

# ========================== 메인 분석 함수 ==========================
def analyze_holding_stocks(strategy="any", delay_seconds=1):
    """보유 주식들의 매도 시점 분석"""
    
    print("=" * 60)
    print("📊 보유 주식 매도 시점 분석 시작")
    print("=" * 60)
    
    try:
        # 보유 주식 조회
        print("\n1️⃣ 보유 주식 조회 중...")
        holdings_df = get_holdings()
        
        if holdings_df.empty:
            print("❌ 보유 주식이 없습니다.")
            return
        
        print(f"✅ 보유 주식 {len(holdings_df)}개 발견")
        print(holdings_df[['code', 'name', 'quantity', 'avg_price', 'eval_profit']])
        
        # 신호 분석 시스템 초기화
        signal_system = TradingSignalSystem()
        
        # 각 주식별 분석
        print(f"\n2️⃣ 각 주식별 매도 신호 분석 중... (전략: {strategy})")
        print("-" * 60)
        
        sell_recommendations = []
        
        for idx, stock in holdings_df.iterrows():
            code = stock['code']
            name = stock['name']
            quantity = int(stock['quantity'])
            avg_price = float(stock['avg_price'])
            eval_profit = float(stock['eval_profit'])
            
            print(f"\n📈 [{code}] {name} 분석 중...")
            
            # API 호출 간격 조절
            if idx > 0:
                time.sleep(delay_seconds)
            
            # OHLCV 데이터 조회
            ohlcv_df = get_ohlcv(code)
            
            if ohlcv_df is None:
                print(f"❌ {name} 데이터 조회 실패")
                continue
            
            # 신호 분석
            result = signal_system.analyze(ohlcv_df, strategy=strategy)
            
            if result["status"] == "success":
                data = result["data"]
                current_price = data['latest_price']
                
                print(f"   💰 현재가: {current_price:,}원")
                print(f"   📊 매수가: {avg_price:,}원")
                print(f"   📈 수익률: {(eval_profit/abs(eval_profit)*100) if eval_profit != 0 else 0:.1f}%")
                
                # 개별 신호 출력
                signals_str = []
                for signal_name, signal_info in data["individual_signals"].items():
                    status = "🔴" if signal_info["signal"] else "🟢"
                    signals_str.append(f"{signal_name}: {status}")
                
                print(f"   📡 개별신호: {' | '.join(signals_str)}")
                
                # 최종 매도 신호
                if data["combined_signal"]["signal"]:
                    print(f"   🚨 매도 신호 발생! (신뢰도: {data['combined_signal']['confidence']:.2f})")
                    sell_recommendations.append({
                        'code': code,
                        'name': name,
                        'current_price': current_price,
                        'quantity': quantity,
                        'avg_price': avg_price,
                        'eval_profit': eval_profit,
                        'confidence': data['combined_signal']['confidence'],
                        'signals': data["individual_signals"]
                    })
                else:
                    print(f"   ✅ 매도 신호 없음")
            else:
                print(f"❌ {name} 분석 실패: {result['error']}")
        
        # 최종 결과 출력
        msg = []
        print("\n" + "=" * 60)
        print("📋 매도 추천 종목 요약")
        print("=" * 60)
        
        if sell_recommendations:
            msg.append(f"\n🚨 매도 신호 발생 종목: {len(sell_recommendations)}개")
            
            for i, rec in enumerate(sell_recommendations, 1):
                msg.append(f"\n{i}. [{rec['code']}] {rec['name']}")
                msg.append(f"   현재가: {rec['current_price']:,}원")
                msg.append(f"   보유수량: {rec['quantity']:,}주")
                msg.append(f"   평균단가: {rec['avg_price']:,}원")
                msg.append(f"   평가손익: {rec['eval_profit']:+,}원")
                msg.append(f"   신뢰도: {rec['confidence']:.2f}")
                
                # 발생한 신호들만 표시
                triggered_signals = [name for name, info in rec['signals'].items() if info['signal']]
                msg.append(f"   발생신호: {', '.join(triggered_signals)}")

            final_msg = '\n'.join(msg)
            print(final_msg);
            send_discord_message(final_msg)

        else:
            print("\n✅ 현재 매도 신호가 발생한 종목이 없습니다.")
            print("   모든 보유 종목을 계속 보유하세요.")
        
        print("\n" + "=" * 60)
        print("✅ 분석 완료!")
        print("=" * 60)

        
    except Exception as e:
        print(f"❌ 분석 중 오류 발생: {str(e)}")
        logger.error(f"분석 중 오류: {str(e)}")

def send_discord_message(message):
    MAX_LENGTH = 2000
    chunks = [message[i:i+MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]
    
    for chunk in chunks:
        data = {"content": chunk}
        try:
            response = requests.post(WEBHOOK_URL, json=data)
            response.raise_for_status()
        except Exception as e:
            print(f"❌ 디스코드 전송 실패: {e}")
        time.sleep(0.5)  # 전송 간 간격 (안정성)

if __name__ == "__main__":
    # 사용법 안내
    print("🔧 사용 가능한 전략:")
    print("  - 'all': 모든 신호가 발생해야 매도 추천")
    print("  - 'any': 하나의 신호라도 발생하면 매도 추천")
    

    # 분석 실행 (기본값: any 전략)
    analyze_holding_stocks(strategy="any", delay_seconds=1)
