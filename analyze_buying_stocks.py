import requests
import json
import time
import pandas as pd
from bs4 import BeautifulSoup
import pandas_ta as ta
import logging
from logging.handlers import TimedRotatingFileHandler
import os
from datetime import datetime
from dotenv import load_dotenv
import numpy as np


load_dotenv()
TOKEN_FILE = "token.json"

def get_early_signal_analysis(df, name, code, app_key, app_secret, access_token):
    """
    고점 매수를 방지하는 조기 신호 분석
    """
    try:
        if df is None or df.empty or len(df) < 60:
            return 0, []
            
        current_price = df.iloc[-1]["stck_clpr"]
        
        # 1. 가격 위치 분석 (핵심 개선)
        price_position_score = analyze_price_position(df, current_price)
        
        # 2. 조기 기술적 신호
        early_technical_score = analyze_early_technical_signals(df)
        
        # 3. 시장 대비 상대적 강도
        relative_strength_score = analyze_relative_strength(df)
        
        # 4. 거래량 패턴 (사전 징후)
        volume_pattern_score = analyze_early_volume_patterns(df)
        
        # 5. 기관/외국인 흐름 (누적 기준)
        institutional_flow_score = analyze_institutional_accumulation(
            code, app_key, app_secret, access_token
        )
        
        total_score = (
            price_position_score * 0.35 +      # 가격 위치가 가장 중요
            early_technical_score * 0.25 +
            relative_strength_score * 0.15 +
            volume_pattern_score * 0.15 +
            institutional_flow_score * 0.10
        )
        
        signals = []
        if price_position_score >= 3: signals.append("저점권진입")
        if early_technical_score >= 3: signals.append("조기기술신호")
        if relative_strength_score >= 3: signals.append("상대적강세")
        if volume_pattern_score >= 3: signals.append("거래량선행")
        if institutional_flow_score >= 3: signals.append("기관누적매수")
        
        return total_score, signals
        
    except Exception as e:
        logger.error(f"❌ {name}: 조기 신호 분석 오류: {e}")
        return 0, []



def analyze_price_position(df, current_price):
    """
    가격 위치 분석 - 고점 매수 방지의 핵심
    """
    score = 0
    
    # 최근 52주 고점/저점 대비 위치
    high_52w = df["stck_hgpr"].tail(252).max() if len(df) >= 252 else df["stck_hgpr"].max()
    low_52w = df["stck_lwpr"].tail(252).min() if len(df) >= 252 else df["stck_lwpr"].min()
    
    if high_52w > low_52w:
        position_ratio = (current_price - low_52w) / (high_52w - low_52w)
        
        # 저점권에서 가산점 (고점 매수 방지)
        if position_ratio <= 0.3:  # 하위 30% 구간
            score += 4
        elif position_ratio <= 0.5:  # 하위 50% 구간  
            score += 3
        elif position_ratio <= 0.7:  # 중간 구간
            score += 1
        else:  # 상위 30% 구간 - 감점
            score -= 3  # 강한 감점으로 고점 매수 방지
    
    # 최근 조정폭 분석
    recent_high = df["stck_hgpr"].tail(20).max()
    if recent_high > 0:
        correction_ratio = (recent_high - current_price) / recent_high
        
        # 적절한 조정 후 매수
        if 0.1 <= correction_ratio <= 0.25:  # 10-25% 조정
            score += 3
        elif 0.05 <= correction_ratio < 0.1:   # 5-10% 조정
            score += 2
        elif correction_ratio > 0.25:          # 25% 이상 조정
            score += 1
        elif correction_ratio < 0.02:          # 2% 미만 조정 - 고점 위험
            score -= 2
    
    return max(score, 0)  # 음수 방지



def analyze_early_technical_signals(df):
    """
    조기 기술적 신호 - 후행지표 대신 선행지표 중심
    """
    score = 0
    
    # 1. 스토캐스틱 %K가 과매도에서 반등 시작
    if len(df) >= 14:
        # 스토캐스틱 계산
        low_14 = df["stck_lwpr"].rolling(14).min()
        high_14 = df["stck_hgpr"].rolling(14).max()
        k_percent = 100 * (df["stck_clpr"] - low_14) / (high_14 - low_14)
        
        recent_k = k_percent.tail(3).tolist()
        if len(recent_k) >= 3:
            # 과매도에서 반등 시작
            if recent_k[-3] < 25 and recent_k[-1] > recent_k[-2] > recent_k[-3]:
                score += 3
    
    # 2. 볼린저밴드 하단에서 반등
    if len(df) >= 20:
        bb_middle = df["stck_clpr"].rolling(20).mean()
        bb_std = df["stck_clpr"].rolling(20).std()
        bb_lower = bb_middle - (2 * bb_std)
        
        # 하단 터치 후 상승
        if (df["stck_lwpr"].iloc[-2] <= bb_lower.iloc[-2] and 
            df["stck_clpr"].iloc[-1] > bb_lower.iloc[-1]):
            score += 3
    
    # 3. RSI 30 아래에서 35 위로 반등
    if len(df) >= 14:
        delta = df["stck_clpr"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        if rsi.iloc[-2] < 30 and rsi.iloc[-1] > 35:
            score += 2
    
    # 4. 이격도 분석 (과도한 하락 후 반등)
    if len(df) >= 20:
        ma20 = df["stck_clpr"].rolling(20).mean()
        deviation = (df["stck_clpr"] / ma20 - 1) * 100
        
        # -15% 이하 이격 후 반등
        if deviation.iloc[-2] < -15 and deviation.iloc[-1] > deviation.iloc[-2]:
            score += 2
    
    return min(score, 5)


def analyze_early_volume_patterns(df):
    """
    거래량 선행 패턴 분석
    """
    score = 0
    
    if len(df) < 20:
        return 0
    
    # 1. 저점에서 거래량 증가 (먼저 거래량이 증가하고 가격이 따라옴)
    vol_ma20 = df["acml_vol"].rolling(20).mean()
    recent_vol = df["acml_vol"].iloc[-1]
    prev_vol = df["acml_vol"].iloc[-2]
    
    # 평균 대비 거래량 증가이면서 가격은 아직 큰 상승 없음
    price_change = (df["stck_clpr"].iloc[-1] / df["stck_clpr"].iloc[-5] - 1) * 100
    
    if (recent_vol > vol_ma20.iloc[-1] * 1.5 and 
        recent_vol > prev_vol * 1.2 and 
        -5 <= price_change <= 5):  # 가격은 횡보
        score += 4
    
    # 2. 연속된 거래량 증가 패턴
    vol_trend = []
    for i in range(3):
        vol_trend.append(df["acml_vol"].iloc[-(i+1)])
    
    if vol_trend[0] > vol_trend[1] > vol_trend[2]:  # 3일 연속 증가
        score += 2
    
    # 3. 상대적 거래량 강도
    vol_60_avg = df["acml_vol"].tail(60).mean()
    if recent_vol > vol_60_avg * 2:
        score += 1
    
    return min(score, 5)


def analyze_institutional_accumulation(code, app_key, app_secret, access_token):
    """
    기관/외국인 누적 매수 분석 (단기 흐름이 아닌 장기 누적)
    """
    score = 0
    
    try:
        # 최근 10일 누적 데이터
        foreign_list, foreign_trend = get_foreign_netbuy_trend_kis(
            code, app_key, app_secret, access_token, days=10
        )
        institution_list, institution_trend = get_institution_netbuy_trend_kis(
            code, app_key, app_secret, access_token, days=10
        )
        
        # 장기 누적 매수 여부 (단순 연속이 아닌 누적)
        if len(foreign_list) >= 10:
            foreign_accumulation = sum(foreign_list)
            if foreign_accumulation > 0:
                score += 2
        
        if len(institution_list) >= 10:
            institution_accumulation = sum(institution_list)
            if institution_accumulation > 0:
                score += 2
        
        # 최근 3일 연속 매수는 여전히 의미있음
        if foreign_trend == "steady_buying":
            score += 1
        if institution_trend == "steady_buying":
            score += 1
            
    except Exception as e:
        logger.error(f"기관 누적 분석 오류: {e}")
        
    return min(score, 5)


def improved_timing_analysis(df, symbol, target_signal):
    """
    개선된 타이밍 분석 - 고점 매수 방지
    """
    try:
        if df.empty or len(df) < 20:
            return {'execute': False, 'reason': '분봉 데이터 부족'}
        
        current_price = float(df['stck_prpr'].iloc[-1])
        
        # 1. 과매수 상태 체크 (고점 매수 방지)
        if len(df) >= 14:
            delta = df['stck_prpr'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi = 100 - (100 / (1 + gain / loss))
            
            current_rsi = rsi.iloc[-1]
            
            # RSI 70 이상이면 과매수로 매수 금지
            if current_rsi > 70:
                return {'execute': False, 'reason': f'과매수 상태 RSI: {current_rsi:.1f}'}
        
        # 2. 급등 직후 매수 금지
        price_change_5min = (current_price / df['stck_prpr'].iloc[-6] - 1) * 100
        if price_change_5min > 3:  # 5분간 3% 이상 급등
            return {'execute': False, 'reason': f'급등 직후 {price_change_5min:.1f}%'}
        
        # 3. 적절한 매수 타이밍 조건
        timing_score = 0
        reasons = []
        
        # 단기 조정 후 반등
        if -2 <= price_change_5min <= 1:
            timing_score += 2
            reasons.append("적절한조정")
        
        # 거래량 확인
        if len(df) >= 20:
            vol_avg = df['cntg_vol'].rolling(20).mean().iloc[-1]
            current_vol = df['cntg_vol'].iloc[-1]
            
            if current_vol > vol_avg * 1.2:
                timing_score += 1
                reasons.append("거래량증가")
        
        # RSI 적정 수준
        if 'current_rsi' in locals() and 40 <= current_rsi <= 60:
            timing_score += 2
            reasons.append("RSI적정")
        
        execute = timing_score >= 3
        
        return {
            'execute': execute,
            'timing_score': timing_score,
            'reasons': reasons,
            'current_price': current_price,
            'rsi': current_rsi if 'current_rsi' in locals() else None,
            'price_change': price_change_5min
        }
        
    except Exception as e:
        return {'execute': False, 'reason': f'분석 오류: {str(e)}'}



def calculate_buy_signal_score_improved(df, name, code, app_key, app_secret, access_token, foreign_trend=None):
    """
    개선된 매수 신호 점수 계산 - 고점 매수 방지
    """
    try:
        if df is None or df.empty:
            return 0, []
            
        current_price = df.iloc[-1]["stck_clpr"]
        
        # 1. 가격 위치 분석 (가장 중요 - 40% 가중치)
        price_position_score = analyze_price_position(df, current_price)
        
        # 2. 기존 기술적 신호들 (30% 가중치)
        original_score, original_signals = calculate_buy_signal_score(
            df, name, code, app_key, app_secret, access_token, foreign_trend
        )
        
        # 3. 조기 기술적 신호 (30% 가중치)
        early_signals = []
        early_score = 0
        
        # RSI 과매도 반등
        if is_rsi_oversold_recovery(df):
            early_score += 2
            early_signals.append("RSI과매도반등")
        
        # 볼린저밴드 반등
        if is_bollinger_rebound(df):
            early_score += 2
            early_signals.append("볼린저반등")
        
        # 스토캐스틱 과매도 반등
        if is_stochastic_oversold_recovery(df):
            early_score += 1
            early_signals.append("스토캐스틱반등")
        
        # 최종 점수 계산
        final_score = (price_position_score * 0.4) + (original_score * 0.3) + (early_score * 0.3)
        
        # 고점 필터링 - 강화
        recent_high = df["stck_hgpr"].tail(20).max()
        if current_price > recent_high * 0.9:  # 최근 고점 90% 이상이면 강한 감점
            final_score *= 0.3  # 70% 감점
            early_signals.append("고점위험")
        
        # 급등 필터링 - 추가
        if len(df) >= 5:
            price_change_5d = (current_price / df["stck_clpr"].iloc[-6] - 1) * 100
            if price_change_5d > 10:  # 5일간 10% 이상 급등
                final_score *= 0.5
                early_signals.append("급등위험")
        
        all_signals = original_signals + early_signals
        
        return final_score, all_signals
        
    except Exception as e:
        logger.error(f"❌ {name}: 개선된 매수 신호 계산 오류: {e}")
        return 0, []


def get_early_signal_analysis(df, name, code, app_key, app_secret, access_token):
    """
    고점 매수를 방지하는 조기 신호 분석
    """
    try:
        if df is None or df.empty or len(df) < 60:
            return 0, []
            
        current_price = df.iloc[-1]["stck_clpr"]
        
        # 1. 가격 위치 분석 (핵심 개선)
        price_position_score = analyze_price_position(df, current_price)
        
        # 2. 조기 기술적 신호
        early_technical_score = analyze_early_technical_signals(df)
        
        # 3. 시장 대비 상대적 강도
        relative_strength_score = analyze_relative_strength(df)
        
        # 4. 거래량 패턴 (사전 징후)
        volume_pattern_score = analyze_early_volume_patterns(df)
        
        # 5. 기관/외국인 흐름 (누적 기준)
        institutional_flow_score = analyze_institutional_accumulation(
            code, app_key, app_secret, access_token
        )
        
        total_score = (
            price_position_score * 0.35 +      # 가격 위치가 가장 중요
            early_technical_score * 0.25 +
            relative_strength_score * 0.15 +
            volume_pattern_score * 0.15 +
            institutional_flow_score * 0.10
        )
        
        signals = []
        if price_position_score >= 3: signals.append("저점권진입")
        if early_technical_score >= 3: signals.append("조기기술신호")
        if relative_strength_score >= 3: signals.append("상대적강세")
        if volume_pattern_score >= 3: signals.append("거래량선행")
        if institutional_flow_score >= 3: signals.append("기관누적매수")
        
        return total_score, signals
        
    except Exception as e:
        logger.error(f"❌ {name}: 조기 신호 분석 오류: {e}")
        return 0, []


def analyze_price_position(df, current_price):
    """
    가격 위치 분석 - 고점 매수 방지의 핵심
    """
    score = 0
    
    # 최근 52주 고점/저점 대비 위치
    high_52w = df["stck_hgpr"].tail(252).max() if len(df) >= 252 else df["stck_hgpr"].max()
    low_52w = df["stck_lwpr"].tail(252).min() if len(df) >= 252 else df["stck_lwpr"].min()
    
    if high_52w > low_52w:
        position_ratio = (current_price - low_52w) / (high_52w - low_52w)
        
        # 저점권에서 가산점 (고점 매수 방지)
        if position_ratio <= 0.3:  # 하위 30% 구간
            score += 4
        elif position_ratio <= 0.5:  # 하위 50% 구간  
            score += 3
        elif position_ratio <= 0.7:  # 중간 구간
            score += 1
        else:  # 상위 30% 구간 - 감점
            score -= 2
    
    # 최근 조정폭 분석
    recent_high = df["stck_hgpr"].tail(20).max()
    if recent_high > 0:
        correction_ratio = (recent_high - current_price) / recent_high
        
        # 적절한 조정 후 매수
        if 0.1 <= correction_ratio <= 0.25:  # 10-25% 조정
            score += 3
        elif 0.05 <= correction_ratio < 0.1:   # 5-10% 조정
            score += 2
        elif correction_ratio > 0.25:          # 25% 이상 조정
            score += 1
    
    return min(score, 5)


def analyze_early_technical_signals(df):
    """
    조기 기술적 신호 - 후행지표 대신 선행지표 중심
    """
    score = 0
    
    # 1. 스토캐스틱 %K가 과매도에서 반등 시작
    if len(df) >= 14:
        # 스토캐스틱 계산
        low_14 = df["stck_lwpr"].rolling(14).min()
        high_14 = df["stck_hgpr"].rolling(14).max()
        k_percent = 100 * (df["stck_clpr"] - low_14) / (high_14 - low_14)
        
        recent_k = k_percent.tail(3).tolist()
        if len(recent_k) >= 3:
            # 과매도에서 반등 시작
            if recent_k[-3] < 25 and recent_k[-1] > recent_k[-2] > recent_k[-3]:
                score += 3
    
    # 2. 볼린저밴드 하단에서 반등
    if len(df) >= 20:
        bb_middle = df["stck_clpr"].rolling(20).mean()
        bb_std = df["stck_clpr"].rolling(20).std()
        bb_lower = bb_middle - (2 * bb_std)
        
        # 하단 터치 후 상승
        if (df["stck_lwpr"].iloc[-2] <= bb_lower.iloc[-2] and 
            df["stck_clpr"].iloc[-1] > bb_lower.iloc[-1]):
            score += 3
    
    # 3. RSI 30 아래에서 35 위로 반등
    if len(df) >= 14:
        delta = df["stck_clpr"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        if rsi.iloc[-2] < 30 and rsi.iloc[-1] > 35:
            score += 2
    
    # 4. 이격도 분석 (과도한 하락 후 반등)
    if len(df) >= 20:
        ma20 = df["stck_clpr"].rolling(20).mean()
        deviation = (df["stck_clpr"] / ma20 - 1) * 100
        
        # -15% 이하 이격 후 반등
        if deviation.iloc[-2] < -15 and deviation.iloc[-1] > deviation.iloc[-2]:
            score += 2
    
    return min(score, 5)


def analyze_early_volume_patterns(df):
    """
    거래량 선행 패턴 분석
    """
    score = 0
    
    if len(df) < 20:
        return 0
    
    # 1. 저점에서 거래량 증가 (먼저 거래량이 증가하고 가격이 따라옴)
    vol_ma20 = df["acml_vol"].rolling(20).mean()
    recent_vol = df["acml_vol"].iloc[-1]
    prev_vol = df["acml_vol"].iloc[-2]
    
    # 평균 대비 거래량 증가이면서 가격은 아직 큰 상승 없음
    price_change = (df["stck_clpr"].iloc[-1] / df["stck_clpr"].iloc[-5] - 1) * 100
    
    if (recent_vol > vol_ma20.iloc[-1] * 1.5 and 
        recent_vol > prev_vol * 1.2 and 
        -5 <= price_change <= 5):  # 가격은 횡보
        score += 4
    
    # 2. 연속된 거래량 증가 패턴
    vol_trend = []
    for i in range(3):
        vol_trend.append(df["acml_vol"].iloc[-(i+1)])
    
    if vol_trend[0] > vol_trend[1] > vol_trend[2]:  # 3일 연속 증가
        score += 2
    
    # 3. 상대적 거래량 강도
    vol_60_avg = df["acml_vol"].tail(60).mean()
    if recent_vol > vol_60_avg * 2:
        score += 1
    
    return min(score, 5)


def analyze_institutional_accumulation(code, app_key, app_secret, access_token):
    """
    기관/외국인 누적 매수 분석 (단기 흐름이 아닌 장기 누적)
    """
    score = 0
    
    try:
        # 최근 10일 누적 데이터
        foreign_list, foreign_trend = get_foreign_netbuy_trend_kis(
            code, app_key, app_secret, access_token, days=10
        )
        institution_list, institution_trend = get_institution_netbuy_trend_kis(
            code, app_key, app_secret, access_token, days=10
        )
        
        # 장기 누적 매수 여부 (단순 연속이 아닌 누적)
        if len(foreign_list) >= 10:
            foreign_accumulation = sum(foreign_list)
            if foreign_accumulation > 0:
                score += 2
        
        if len(institution_list) >= 10:
            institution_accumulation = sum(institution_list)
            if institution_accumulation > 0:
                score += 2
        
        # 최근 3일 연속 매수는 여전히 의미있음
        if foreign_trend == "steady_buying":
            score += 1
        if institution_trend == "steady_buying":
            score += 1
            
    except Exception as e:
        logger.error(f"기관 누적 분석 오류: {e}")
        
    return min(score, 5)


def improved_timing_analysis(df, symbol, target_signal):
    """
    개선된 타이밍 분석 - 고점 매수 방지
    """
    try:
        if df.empty or len(df) < 20:
            return {'execute': False, 'reason': '분봉 데이터 부족'}
        
        current_price = float(df['stck_prpr'].iloc[-1])
        
        # 1. 과매수 상태 체크 (고점 매수 방지)
        if len(df) >= 14:
            delta = df['stck_prpr'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rsi = 100 - (100 / (1 + gain / loss))
            
            current_rsi = rsi.iloc[-1]
            
            # RSI 70 이상이면 과매수로 매수 금지
            if current_rsi > 70:
                return {'execute': False, 'reason': f'과매수 상태 RSI: {current_rsi:.1f}'}
        
        # 2. 급등 직후 매수 금지
        price_change_5min = (current_price / df['stck_prpr'].iloc[-6] - 1) * 100
        if price_change_5min > 3:  # 5분간 3% 이상 급등
            return {'execute': False, 'reason': f'급등 직후 {price_change_5min:.1f}%'}
        
        # 3. 적절한 매수 타이밍 조건
        timing_score = 0
        reasons = []
        
        # 단기 조정 후 반등
        if -2 <= price_change_5min <= 1:
            timing_score += 2
            reasons.append("적절한조정")
        
        # 거래량 확인
        if len(df) >= 20:
            vol_avg = df['cntg_vol'].rolling(20).mean().iloc[-1]
            current_vol = df['cntg_vol'].iloc[-1]
            
            if current_vol > vol_avg * 1.2:
                timing_score += 1
                reasons.append("거래량증가")
        
        # RSI 적정 수준
        if 'current_rsi' in locals() and 40 <= current_rsi <= 60:
            timing_score += 2
            reasons.append("RSI적정")
        
        execute = timing_score >= 3
        
        return {
            'execute': execute,
            'timing_score': timing_score,
            'reasons': reasons,
            'current_price': current_price,
            'rsi': current_rsi if 'current_rsi' in locals() else None,
            'price_change': price_change_5min
        }
        
    except Exception as e:
        return {'execute': False, 'reason': f'분석 오류: {str(e)}'}

def get_institution_netbuy_trend_kis(stock_code, app_key, app_secret, access_token, days=3):
    """
    최근 N일 기관 순매수량 리스트와 추세 판단 결과 반환
    """
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010900"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json().get("output", [])

        netbuy_list = []
        for row in data[:days]:
            # 기관 순매수량 (기관계)
            qty = row.get("orgn_ntby_qty", "").replace(",", "").strip()
            if qty != "":
                netbuy_list.append(int(qty))

        # 추세 분석
        trend = "neutral"
        if len(netbuy_list) >= 3:
            pos_days = sum(1 for x in netbuy_list if x > 0)
            if pos_days == days:
                trend = "steady_buying"  # ✅ 전일 모두 순매수
            elif pos_days >= days * 0.6:
                trend = "accumulating"  # 순매수 우세
            elif pos_days <= days * 0.2:
                trend = "distributing"  # 순매도 우세
            else:
                trend = "mixed"

        return netbuy_list, trend

    except Exception as e:
        logger.error(f"❌ KIS API 기관 추세 분석 오류: {e}")
        return [], "unknown"


def get_period_price_data_alternative(access_token, app_key, app_secret, stock_code, days=60, max_retries=3):
    """
    대안 API: 주식현재가 일자별 API를 사용한 데이터 조회
    더 안정적일 수 있음
    """
    from datetime import datetime, timedelta
    
    # 오늘부터 역산해서 영업일 기준으로 계산
    end_date = datetime.now()
    # 주말과 공휴일을 고려해 실제 달력일로는 더 많이 빼기
    start_date = end_date - timedelta(days=int(days * 1.4))  # 영업일 고려해 1.4배
    
    start_date_str = start_date.strftime("%Y%m%d")
    end_date_str = end_date.strftime("%Y%m%d")
    
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-price"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": app_key,
        "appSecret": app_secret,
        "tr_id": "FHKST01010400"
    }
    
    # 여러 번에 나누어 조회 (API 제한 때문)
    all_data = []
    current_end = end_date
    
    for i in range(3):  # 최대 3번 나누어 조회 (각각 30일씩)
        current_start = current_end - timedelta(days=30)
        if current_start < start_date:
            current_start = start_date
            
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
            "fid_input_date_1": current_start.strftime("%Y%m%d"),
            "fid_input_date_2": current_end.strftime("%Y%m%d"),
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "0"
        }
        
        for attempt in range(max_retries):
            try:
                time.sleep(0.2)  # API 호출 간격
                response = requests.get(url, headers=headers, params=params, timeout=10)
                response.raise_for_status()
                data = response.json().get("output", [])
                
                if data:
                    all_data.extend(data)
                    logger.info(f"📊 {stock_code}: {current_start.strftime('%Y%m%d')}~{current_end.strftime('%Y%m%d')} {len(data)}건 조회")
                break
                
            except Exception as e:
                logger.error(f"❌ 구간 조회 오류 (시도 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                continue
        
        current_end = current_start - timedelta(days=1)
        if current_end <= start_date:
            break
    
    if not all_data:
        logger.error(f"❌ {stock_code} 대안 API 데이터 조회 실패")
        return None
    
    # DataFrame 생성 및 중복 제거
    df = pd.DataFrame(all_data)
    df = df.drop_duplicates(subset=['stck_bsop_date']).reset_index(drop=True)
    
    # 데이터 타입 변환
    df["stck_clpr"] = pd.to_numeric(df["stck_clpr"], errors="coerce")
    df["stck_hgpr"] = pd.to_numeric(df["stck_hgpr"], errors="coerce") 
    df["stck_lwpr"] = pd.to_numeric(df["stck_lwpr"], errors="coerce")
    df["acml_vol"] = pd.to_numeric(df["acml_vol"], errors="coerce")
    
    df = df.dropna(subset=["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"])
    df = df.sort_values(by="stck_bsop_date").reset_index(drop=True)
    
    logger.info(f"✅ {stock_code}: 대안 API로 총 {len(df)}일 데이터 조회 완료")
    return df


def get_period_price_data(access_token, app_key, app_secret, stock_code, days=60, period="D", max_retries=3):
    """
    국내주식기간별시세 API를 사용해 더 긴 기간 데이터 조회
    days: 조회할 일수 (기본 60일)
    period: "D"(일), "W"(주), "M"(월), "Y"(년)
    """
    from datetime import datetime, timedelta
    
    # 시작일과 종료일 계산
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days + 20)  # 여유분 20일 추가 (휴장일 고려)
    
    start_date_str = start_date.strftime("%Y%m%d")
    end_date_str = end_date.strftime("%Y%m%d")
    
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": app_key,
        "appSecret": app_secret,
        "tr_id": "FHKST03010100"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code,
        "fid_input_date_1": start_date_str,  # 시작일 명시
        "fid_input_date_2": end_date_str,    # 종료일 명시
        "fid_period_div_code": period,       # "D":일, "W":주, "M":월, "Y":년
        "fid_org_adj_prc": "0"              # 0:수정주가, 1:원주가
    }
    
    logger.debug("📅 {stock_code}: {start_date_str} ~ {end_date_str} 데이터 조회 시작")
    
    # 데이터 조회 (재시도)
    df = None
    for attempt in range(max_retries):
        try:
            time.sleep(0.1)
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json().get("output2", [])  # output2가 실제 데이터
            df = pd.DataFrame(data)
            break
        except requests.exceptions.ConnectionError as e:
            logger.error(f"❌ 기간별 데이터 연결 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
        except Exception as e:
            logger.error(f"❌ 기간별 데이터 조회 오류 (시도 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                time.sleep(1)
            continue
    
    if df is None or df.empty:
        logger.error(f"❌ {stock_code} 기간별 데이터 조회 실패")
        return None
    
    # 데이터 타입 변환 및 컬럼명 통일
    df = df.rename(columns={
        'stck_bsop_date': 'stck_bsop_date',  # 영업일자
        'stck_clpr': 'stck_clpr',           # 종가
        'stck_oprc': 'stck_oprc',           # 시가
        'stck_hgpr': 'stck_hgpr',           # 고가
        'stck_lwpr': 'stck_lwpr',           # 저가
        'acml_vol': 'acml_vol'              # 누적거래량
    })
    
    # 숫자 변환
    df["stck_clpr"] = pd.to_numeric(df["stck_clpr"], errors="coerce")
    df["stck_hgpr"] = pd.to_numeric(df["stck_hgpr"], errors="coerce")
    df["stck_lwpr"] = pd.to_numeric(df["stck_lwpr"], errors="coerce")
    df["acml_vol"] = pd.to_numeric(df["acml_vol"], errors="coerce")
    
    # 결측치 제거
    df = df.dropna(subset=["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"])
    
    # 날짜순 정렬 (과거 → 현재)
    df = df.sort_values(by="stck_bsop_date").reset_index(drop=True)
    
    logger.debug(f"✅ {stock_code}: {len(df)}일 데이터 조회 완료")
    return df


def get_daily_price_data_with_realtime(access_token, app_key, app_secret, stock_code, days=60, max_retries=3):
    """
    개선된 일봉 데이터 + 실시간 현재가 결합
    기간별시세 API를 사용해 지정한 일수만큼 데이터 확보
    days: 조회할 일수 (기본 60일, MACD용으로 충분)
    """
    # 먼저 기간별시세 API로 충분한 과거 데이터 조회
    df = get_period_price_data(access_token, app_key, app_secret, stock_code, days=days, period="D", max_retries=max_retries)
    
    # 기본 API가 실패하면 대안 API 시도
    if df is None or len(df) < 30:
        logger.info(f"⚠️ {stock_code}: 기본 API 실패, 대안 API 시도...")
        df = get_period_price_data_alternative(access_token, app_key, app_secret, stock_code, days=days, max_retries=max_retries)
    
    if df is None or df.empty:
        logger.error(f"❌ {stock_code} 기간별 데이터 조회 실패")
        return None
    
    # MACD 계산 가능 여부 확인
    if len(df) < 35:
        logger.info(f"⚠️ {stock_code}: 데이터 부족 ({len(df)}일) - MACD 분석에는 최소 35일 필요")
    elif len(df) < 50:
        logger.info(f"⚠️ {stock_code}: 데이터 부족 ({len(df)}일) - MACD 정확도를 위해 50일 이상 권장")
    else:
        logger.debug(f"✅ {stock_code}: {len(df)}일 데이터로 MACD 분석 가능")
    
    # 실시간 현재가 조회해서 최신 데이터 업데이트
    current_price, current_volume = get_current_price(access_token, app_key, app_secret, stock_code)
    
    if current_price and current_volume:
        today = datetime.now().strftime("%Y%m%d")
        
        # 최신 데이터가 오늘 데이터인지 확인
        if len(df) > 0 and df.iloc[-1]["stck_bsop_date"] == today:
            # 오늘 데이터를 실시간 가격으로 업데이트
            df.loc[df.index[-1], "stck_clpr"] = current_price
            df.loc[df.index[-1], "acml_vol"] = current_volume
            logger.debug(f"📈 {stock_code}: 오늘 데이터를 실시간 가격으로 업데이트")
        else:
            # 오늘 데이터 새로 추가
            new_row = {
                "stck_bsop_date": today,
                "stck_clpr": current_price,
                "stck_hgpr": current_price,
                "stck_lwpr": current_price,
                "acml_vol": current_volume
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            logger.debug(f"📈 {stock_code}: 오늘 실시간 데이터 추가")
    
    return df


def is_macd_golden_cross(df):
    """
    개선된 MACD 골든크로스 신호 감지 (충분한 데이터로 정확도 향상)
    """
    if len(df) < 35:  # 최소 35일 필요
        return False
    
    try:
        close_prices = df['stck_clpr'].copy()
        
        if close_prices.isnull().any():
            return False
        
        # 표준 MACD 계산 (12일 EMA - 26일 EMA)
        ema_12 = close_prices.ewm(span=12, adjust=False).mean()
        ema_26 = close_prices.ewm(span=26, adjust=False).mean()
        ema_05 = close_prices.ewm(span=5, adjust=False).mean()
        
        # MACD Line 계산
        macd_line = ema_12 - ema_26
        #macd_line = ema_05 - ema_12
        
        # Signal Line 계산 (MACD의 9일 EMA)
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        if len(macd_line) < 2:
            return False
        
        # 오늘과 어제의 MACD, Signal 값
        today_macd = macd_line.iloc[-1]
        today_signal = signal_line.iloc[-1]
        yesterday_macd = macd_line.iloc[-2]
        yesterday_signal = signal_line.iloc[-2]
        
        # 골든크로스 조건 (매수 신호만)
        # 1. 어제는 MACD가 Signal 아래에 있었음
        # 2. 오늘은 MACD가 Signal 위로 돌파
        # 3. MACD가 상승 추세
        golden_cross_today = (
            yesterday_macd <= yesterday_signal and  # 어제는 아래
            today_macd > today_signal and          # 오늘은 위로 돌파
            today_macd > yesterday_macd            # MACD가 상승 추세
        )
        
        # 추가 필터: 매수 시점만 감지 (0선 근처 이하에서만 유효)
        valid_cross = today_signal <= 0.2  # Signal이 0선 근처 또는 아래
        
        # 충분한 데이터가 있을 때만 추가 검증
        if len(df) >= 50:
            # 거래량 증가 확인 (선택사항)
            volume_surge = df.iloc[-1]["acml_vol"] > df["acml_vol"].tail(10).mean() * 1.1
            return golden_cross_today and valid_cross and volume_surge
        else:
            return golden_cross_today and valid_cross
        
    except Exception as e:
        logger.error(f"MACD 계산 오류: {e}")
        return False


def is_macd_near_golden_cross(df):
    """
    개선된 MACD 골든크로스 근접 신호 감지
    """
    if len(df) < 35:
        return False
    
    try:
        close_prices = df['stck_clpr'].copy()
        
        if close_prices.isnull().any():
            return False
        
        # 표준 MACD 계산
        ema_12 = close_prices.ewm(span=12, adjust=False).mean()
        ema_26 = close_prices.ewm(span=26, adjust=False).mean()
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        
        if len(macd_line) < 5:
            return False
        
        current_macd = macd_line.iloc[-1]
        current_signal = signal_line.iloc[-1]
        
        # 1. MACD가 Signal 아래에 있어야 함
        if current_macd >= current_signal:
            return False
        
        # 2. 차이가 매우 작음 (근접 상태)
        diff = abs(current_macd - current_signal)
        signal_abs = abs(current_signal)
        is_close = (diff / max(signal_abs, 0.01) <= 0.05) or (diff <= 0.03)
        
        # 3. MACD 상승 추세 확인
        macd_trend_up = False
        if len(macd_line) >= 3:
            macd_trend_up = (
                macd_line.iloc[-1] > macd_line.iloc[-2] and 
                macd_line.iloc[-2] >= macd_line.iloc[-3]
            )
        
        # 4. 히스토그램 개선 추세
        histogram_improving = False
        if len(macd_line) >= 3:
            hist_today = current_macd - current_signal
            hist_yesterday = macd_line.iloc[-2] - signal_line.iloc[-2]
            hist_2days_ago = macd_line.iloc[-3] - signal_line.iloc[-3]
            
            histogram_improving = (
                hist_today > hist_yesterday and 
                hist_yesterday > hist_2days_ago
            )
        
        # 5. 매수 구간에서만 유효
        valid_position = current_signal <= 0.3
        
        return (is_close and 
                (macd_trend_up or histogram_improving) and 
                valid_position)
        
    except Exception as e:
        logger.error(f"MACD 근접 계산 오류: {e}")
        return False


def get_current_price(access_token, app_key, app_secret, stock_code):
    """
    실시간 현재가 조회
    """
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appKey": app_key,
        "appSecret": app_secret,
        "tr_id": "FHKST01010100"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json().get("output", {})
        
        current_price = float(data.get("stck_prpr", 0))
        current_volume = int(data.get("acml_vol", 0))
        
        return current_price, current_volume
    except Exception as e:
        logger.error(f"현재가 조회 오류: {e}")
        return None, None


def is_institution_consecutive_buying(stock_code, app_key, app_secret, access_token, days=5):
    """
    기관의 긍정적 매수 추세 확인 (유연한 기준)
    """
    try:
        netbuy_list, trend = get_institution_netbuy_trend_kis(
            stock_code, app_key, app_secret, access_token, days
        )
        
        # 유연한 기준: steady_buying(100% 순매수) 또는 accumulating(60% 이상 순매수)
        return trend == "steady_buying"
    except Exception as e:
        logger.error(f"❌ {stock_code}: 기관 매수 추세 확인 중 오류: {e}")
        return False

def is_institution_positive_trend(stock_code, app_key, app_secret, access_token, days=3):
    """
    기관의 긍정적 매수 추세 확인
    - steady_buying: 모든 날짜에서 순매수 (100%)
    - accumulating: 60% 이상 날짜에서 순매수
    """
    try:
        netbuy_list, trend = get_institution_netbuy_trend_kis(
            stock_code, app_key, app_secret, access_token, days
        )
        
        return trend in ("steady_buying", "accumulating")
    except Exception as e:
        logger.error(f"❌ {stock_code}: 기관 매수 추세 확인 중 오류: {e}")
        return False

def get_foreign_netbuy_trend_kis(stock_code, app_key, app_secret, access_token, days=5):
    """
    최근 N일 외국인 순매수량 리스트와 추세 판단 결과 반환
    """
    url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
    headers = {
        "Content-Type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010900"
    }
    params = {
        "fid_cond_mrkt_div_code": "J",
        "fid_input_iscd": stock_code
    }

    try:
        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json().get("output", [])

        netbuy_list = []
        for row in data[:days]:
            qty = row.get("frgn_ntby_qty", "").replace(",", "").strip()
            if qty != "":
                netbuy_list.append(int(qty))

        # 추세 분석
        trend = "neutral"
        if len(netbuy_list) >= 3:
            pos_days = sum(1 for x in netbuy_list if x > 0)
            if pos_days == days:
                trend = "steady_buying"  # ✅ 전일 모두 순매수
            elif pos_days >= days * 0.6:
                trend = "accumulating"  # 순매수 우세
            elif pos_days <= days * 0.2:
                trend = "distributing"  # 순매도 우세
            else:
                trend = "mixed"

        return netbuy_list, trend

    except Exception as e:
        logger.error(f"❌ KIS API 외국인 추세 분석 오류: {e}")
        return [], "unknown"


def get_foreign_net_buy_kis(stock_code, app_key, app_secret, access_token, days=3):
    """
    KIS API를 사용해 최근 N일간 외국인 순매수량 합계 반환
    """
    try:
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-investor"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "FHKST01010900"
        }
        params = {
            "fid_cond_mrkt_div_code": "J",        # 'J' = 코스피, 'Q' = 코스닥
            "fid_input_iscd": stock_code
        }

        res = requests.get(url, headers=headers, params=params)
        res.raise_for_status()
        data = res.json().get("output", [])

        total_net_buy = 0
        count = 0

        for row in data:
            qty_str = row.get("frgn_ntby_qty", "").replace(",", "").strip()
            if qty_str == "":
                continue

            total_net_buy += int(qty_str)
            count += 1
            if count >= days:
                break

        return total_net_buy

    except Exception as e:
        logger.error(f"❌ KIS API 외국인 순매수 조회 오류: {e}")
        return 0


def get_fundamental_data_from_naver(stock_code):
    """
    네이버에서 기본적 분석 데이터 추출 (에러 처리 강화)
    """
    try:
        url = f"https://finance.naver.com/item/main.nhn?code={stock_code}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        def extract_number(label):
            try:
                element = soup.find(string=lambda s: s and label in s)
                if not element:
                    return None
                td = element.find_next("td")
                if not td:
                    return None
                text = td.text.replace(",", "").replace("%", "").replace("배", "").strip()
                return float(text) if text else None
            except:
                return None

        return {
            "PER": extract_number("PER"),
            "PBR": extract_number("PBR"),
            "ROE": extract_number("ROE"),
            "부채비율": extract_number("부채비율")
        }
    except Exception as e:
        logger.error(f"❌ {stock_code}: 기본적 분석 데이터 조회 오류: {e}")
        return {"PER": None, "PBR": None, "ROE": None, "부채비율": None}


def passes_fundamental_filters(data):
    """
    기본적 분석 필터 통과 여부 (None 값 처리 강화)
    """
    try:
        per = data.get("PER")
        roe = data.get("ROE")
        debt_ratio = data.get("부채비율")
        
        # None 값이 있으면 해당 조건은 무시
        conditions = []
        if per is not None:
            conditions.append(per < 80)
        if roe is not None:
            conditions.append(roe > 1)
        if debt_ratio is not None:
            conditions.append(debt_ratio < 500)
        
        # 최소 하나 이상의 조건이 있고 모두 통과해야 함
        return len(conditions) > 0 and all(conditions)
    except Exception:
        return False


def setup_logger(log_dir="logs", log_filename="buying_stocks.log", when="midnight", backup_count=7):
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_filename)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    if logger.hasHandlers():
        logger.handlers.clear()

    handler = TimedRotatingFileHandler(
        log_path, when=when, interval=1, backupCount=backup_count, encoding='utf-8'
    )
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger

def load_keys():
    app_key = os.getenv("KIS_APP_KEY")
    app_secret = os.getenv("KIS_APP_SECRET")
    if not app_key or not app_secret:
        raise ValueError("환경변수 KIS_APP_KEY 또는 KIS_APP_SECRET이 설정되지 않았습니다.")
    return app_key, app_secret

def request_new_token():
    app_key, app_secret = load_keys()
    url = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"
    headers = {"Content-Type": "application/json"}
    data = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    res = requests.post(url, headers=headers, data=json.dumps(data)).json()
    res["requested_at"] = int(time.time())
    with open(TOKEN_FILE, "w") as f:
        json.dump(res, f)
    return res["access_token"]

def load_token():
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

def get_top_200_stocks():
    """
    시가총액 상위 200개 종목 조회 (에러 처리 강화)
    """
    stocks = {}
    exclude_keywords = ["KODEX","TIGER", "PLUS", "ACE", "ETF", "ETN", "리츠", "우", "스팩"]

    try:
        for page in range(1, 11):
            url = f"https://finance.naver.com/sise/sise_market_sum.nhn?sosok=0&page={page}"
            headers = {"User-Agent": "Mozilla/5.0"}
            res = requests.get(url, headers=headers, timeout=10)
            res.raise_for_status()
            soup = BeautifulSoup(res.text, "html.parser")
            rows = soup.select("table.type_2 tr")

            for row in rows:
                try:
                    link = row.select_one("a.tltle")
                    if link:
                        name = link.text.strip()
                        href = link["href"]
                        code = href.split("=")[-1]
                        
                        if any(keyword in name for keyword in exclude_keywords):
                            continue
                        
                        stocks[name] = code
                except Exception as e:
                    continue  # 개별 행 파싱 오류는 건너뛰기
            
            time.sleep(0.1)  # 요청 간격 조절
    except Exception as e:
        logger.error(f"❌ 종목 리스트 조회 중 오류: {e}")
    
    return stocks


def get_daily_price_data(access_token, app_key, app_secret, stock_code):
    """
    일봉 데이터 조회 (에러 처리 강화)
    """
    try:
        url = "https://openapi.koreainvestment.com:9443/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = {
            "Content-Type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appKey": app_key,
            "appSecret": app_secret,
            "tr_id": "FHKST01010400"
        }
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "0"
        }
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json().get("output", [])
        
        if not data:
            return None
            
        df = pd.DataFrame(data)
        
        # 필수 컬럼 확인
        required_cols = ["stck_clpr", "stck_hgpr", "stck_lwpr", "acml_vol"]
        if not all(col in df.columns for col in required_cols):
            return None
            
        # 데이터 타입 변환
        for col in required_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            
        df = df.dropna(subset=required_cols)
        
        if df.empty:
            return None
            
        return df.sort_values(by="stck_bsop_date").reset_index(drop=True)
    except Exception as e:
        logger.error(f"❌ {stock_code}: 일봉 데이터 조회 오류: {e}")
        return None

# 기존 지표들 (에러 처리 강화)
def is_golden_cross(df):
    """골든크로스 신호 감지"""
    try:
        if df is None or df.empty or len(df) < 21:
            return False
        if 'stck_clpr' not in df.columns:
            return False
            
        df = df.copy()
        df["ma5"] = df["stck_clpr"].rolling(window=5).mean()
        df["ma20"] = df["stck_clpr"].rolling(window=20).mean()
        
        if len(df) < 2:
            return False
            
        today = df.iloc[-1]
        yesterday = df.iloc[-2]
        
        return (not pd.isna(today["ma5"]) and not pd.isna(today["ma20"]) and
                not pd.isna(yesterday["ma5"]) and not pd.isna(yesterday["ma20"]) and
                yesterday["ma5"] < yesterday["ma20"] and today["ma5"] > today["ma20"])
    except Exception as e:
        logger.error(f"❌ 골든크로스 계산 오류: {e}")
        return False

def is_bollinger_rebound(df):
    """볼린저밴드 반등 신호"""
    try:
        if df is None or df.empty or len(df) < 21:
            return False
        if 'stck_clpr' not in df.columns:
            return False
            
        df = df.copy()
        df["ma20"] = df["stck_clpr"].rolling(window=20).mean()
        df["stddev"] = df["stck_clpr"].rolling(window=20).std()
        df["lower_band"] = df["ma20"] - 2 * df["stddev"]

        if len(df) < 2:
            return False
            
        today = df.iloc[-1]
        yesterday = df.iloc[-2]

        return (not pd.isna(yesterday["lower_band"]) and not pd.isna(today["lower_band"]) and
                yesterday["stck_clpr"] < yesterday["lower_band"] and
                today["stck_clpr"] > today["lower_band"])
    except Exception as e:
        logger.error(f"❌ 볼린저밴드 계산 오류: {e}")
        return False

def is_macd_signal_cross(df):
    """MACD 신호선 교차"""
    try:
        if df is None or df.empty or len(df) < 35:
            return False
        if 'stck_clpr' not in df.columns:
            return False
        
        close = df["stck_clpr"]
        macd_result = ta.macd(close, fast=12, slow=26, signal=9)
        
        if macd_result is None or macd_result.isna().any().any():
            return False
        
        macd = macd_result["MACD_12_26_9"]
        signal = macd_result["MACDs_12_26_9"]

        if len(macd) < 2:
            return False
            
        return (macd.iloc[-2] < signal.iloc[-2] and macd.iloc[-1] > signal.iloc[-1])
    except Exception as e:
        logger.error(f"❌ MACD 계산 오류: {e}")
        return False

# 🆕 추가 기술적 지표들 (에러 처리 강화)
def is_rsi_oversold_recovery(df, period=14, oversold_threshold=30, recovery_threshold=35):
    """RSI 과매도 구간에서 회복 신호"""
    try:
        if df is None or df.empty or len(df) < period + 2:
            return False
        if 'stck_clpr' not in df.columns:
            return False
        
        rsi = ta.rsi(df["stck_clpr"], length=period)
        
        if rsi is None or rsi.isna().any() or len(rsi) < 2:
            return False
        
        # 전날 RSI가 과매도 구간이고, 오늘 회복 신호
        return (rsi.iloc[-2] < oversold_threshold and 
                rsi.iloc[-1] > recovery_threshold)
    except Exception as e:
        logger.error(f"❌ RSI 계산 오류: {e}")
        return False

def is_stochastic_oversold_recovery(df, k_period=14, d_period=3, oversold_threshold=20):
    """스토캐스틱 과매도 구간에서 회복 신호"""
    try:
        if df is None or df.empty or len(df) < k_period + d_period + 2:
            return False
        required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
        if not all(col in df.columns for col in required_cols):
            return False
        
        stoch = ta.stoch(df["stck_hgpr"], df["stck_lwpr"], df["stck_clpr"], 
                         k=k_period, d=d_period)
        
        if stoch is None or stoch.isna().any().any():
            return False
        
        stoch_k = stoch[f"STOCHk_{k_period}_{d_period}_3"]
        stoch_d = stoch[f"STOCHd_{k_period}_{d_period}_3"]
        
        if len(stoch_k) < 2:
            return False
        
        # %K가 %D를 상향 돌파하면서 과매도 구간에서 벗어날 때
        return (stoch_k.iloc[-2] < stoch_d.iloc[-2] and 
                stoch_k.iloc[-1] > stoch_d.iloc[-1] and
                stoch_k.iloc[-1] < oversold_threshold + 10)
    except Exception as e:
        logger.error(f"❌ 스토캐스틱 계산 오류: {e}")
        return False

def is_volume_breakout(df, volume_period=20, volume_multiplier=2.0):
    """거래량 급증 신호"""
    try:
        if df is None or df.empty or len(df) < volume_period + 1:
            return False
        if 'acml_vol' not in df.columns:
            return False
        
        avg_volume = df["acml_vol"].rolling(window=volume_period).mean()
        today_volume = df["acml_vol"].iloc[-1]
        avg_volume_today = avg_volume.iloc[-1]
        
        if pd.isna(avg_volume_today) or avg_volume_today == 0:
            return False
        
        # 오늘 거래량이 평균의 2배 이상
        return today_volume > avg_volume_today * volume_multiplier
    except Exception as e:
        logger.error(f"❌ 거래량 계산 오류: {e}")
        return False

def is_williams_r_oversold_recovery(df, period=14, oversold_threshold=-80, recovery_threshold=-70):
    """Williams %R 과매도 구간에서 회복 신호"""
    try:
        if df is None or df.empty or len(df) < period + 2:
            return False
        required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
        if not all(col in df.columns for col in required_cols):
            return False
        
        willr = ta.willr(df["stck_hgpr"], df["stck_lwpr"], df["stck_clpr"], length=period)
        
        if willr is None or willr.isna().any() or len(willr) < 2:
            return False
        
        # 전날 과매도 구간이고 오늘 회복 신호
        return (willr.iloc[-2] < oversold_threshold and 
                willr.iloc[-1] > recovery_threshold)
    except Exception as e:
        logger.error(f"❌ Williams %R 계산 오류: {e}")
        return False

def is_double_bottom_pattern(df, lookback=20, tolerance=0.02):
    """이중바닥 패턴 감지"""
    try:
        if df is None or df.empty or len(df) < lookback * 2:
            return False
        if 'stck_lwpr' not in df.columns or 'stck_clpr' not in df.columns:
            return False
        
        # 최근 구간에서 저점 찾기
        recent_data = df.tail(lookback * 2)
        
        # 저점들 찾기 (local minima)
        lows = []
        for i in range(1, len(recent_data) - 1):
            if (recent_data.iloc[i]["stck_lwpr"] < recent_data.iloc[i-1]["stck_lwpr"] and 
                recent_data.iloc[i]["stck_lwpr"] < recent_data.iloc[i+1]["stck_lwpr"]):
                lows.append((i, recent_data.iloc[i]["stck_lwpr"]))
        
        if len(lows) < 2:
            return False
        
        # 마지막 두 저점 비교
        last_two_lows = lows[-2:]
        low1_price = last_two_lows[0][1]
        low2_price = last_two_lows[1][1]
        
        # 두 저점이 비슷한 수준이고, 현재 가격이 상승 중
        price_diff = abs(low1_price - low2_price) / low1_price
        current_price = df.iloc[-1]["stck_clpr"]
        
        return (price_diff < tolerance and 
                current_price > max(low1_price, low2_price) * 1.02)
    except Exception as e:
        logger.error(f"❌ 이중바닥 패턴 계산 오류: {e}")
        return False

def is_ichimoku_bullish_signal(df):
    """일목균형표 매수 신호"""
    try:
        if df is None or df.empty or len(df) < 52:
            return False
        required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
        if not all(col in df.columns for col in required_cols):
            return False
        
        # 일목균형표 계산
        high = df["stck_hgpr"]
        low = df["stck_lwpr"]
        close = df["stck_clpr"]
        
        # 전환선 (9일)
        conversion_line = (high.rolling(9).max() + low.rolling(9).min()) / 2
        
        # 기준선 (26일)
        base_line = (high.rolling(26).max() + low.rolling(26).min()) / 2
        
        # 선행스팬A
        span_a = ((conversion_line + base_line) / 2).shift(26)
        
        # 선행스팬B
        span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
        
        # 후행스팬
        lagging_span = close.shift(-26)
        
        current_price = close.iloc[-1]
        current_conversion = conversion_line.iloc[-1]
        current_base = base_line.iloc[-1]
        
        if pd.isna(current_conversion) or pd.isna(current_base):
            return False
        
        # 구름 위에 있고, 전환선이 기준선을 상향 돌파
        cloud_top = max(span_a.iloc[-1], span_b.iloc[-1]) if not pd.isna(span_a.iloc[-1]) and not pd.isna(span_b.iloc[-1]) else None
        
        if cloud_top is None or pd.isna(cloud_top):
            return False
        
        return (current_price > cloud_top and 
                len(conversion_line) >= 2 and len(base_line) >= 2 and
                conversion_line.iloc[-2] < base_line.iloc[-2] and 
                current_conversion > current_base)
    except Exception as e:
        logger.error(f"❌ 일목균형표 계산 오류: {e}")
        return False

def is_cup_handle_pattern(df, cup_depth=0.1, handle_depth=0.05, min_periods=30):
    """컵앤핸들 패턴 감지 (간단한 버전)"""
    try:
        if df is None or df.empty or len(df) < min_periods:
            return False
        required_cols = ['stck_hgpr', 'stck_lwpr', 'stck_clpr']
        if not all(col in df.columns for col in required_cols):
            return False
        
        # 최근 30일 데이터
        recent_data = df.tail(min_periods)
        
        # 컵 패턴: 고점 -> 저점 -> 고점 형태
        max_price = recent_data["stck_hgpr"].max()
        min_price = recent_data["stck_lwpr"].min()
        current_price = recent_data["stck_clpr"].iloc[-1]
        
        if max_price == 0:
            return False
        
        # 컵의 깊이 체크
        cup_depth_actual = (max_price - min_price) / max_price
        
        # 현재 고점 근처까지 회복했는지 체크
        recovery_ratio = current_price / max_price
        
        return (cup_depth_actual > cup_depth and 
                recovery_ratio > 0.90 and 
                len(recent_data) >= 6 and
                current_price > recent_data["stck_clpr"].iloc[-5])  # 최근 5일 상승
    except Exception as e:
        logger.error(f"❌ 컵앤핸들 패턴 계산 오류: {e}")
        return False


def calculate_buy_signal_score(df, name, code, app_key, app_secret, access_token):
    """
    개선된 매수 신호 점수 계산 - 고점 매수 방지
    """
    if df is None or df.empty:
        return 0, []
    
    # 기존 후행지표들은 가중치 축소
    legacy_score, legacy_signals = calculate_buy_signal_score(
        df, name, code, app_key, app_secret, access_token
    )
    
    # 새로운 조기 신호 분석
    early_score, early_signals = get_early_signal_analysis(
        df, name, code, app_key, app_secret, access_token
    )
    
    # 조합 점수 (조기 신호에 더 높은 가중치)
    final_score = (legacy_score * 0.3) + (early_score * 0.7)
    
    # 고점 필터링
    current_price = df.iloc[-1]["stck_clpr"]
    recent_high = df["stck_hgpr"].tail(20).max()
    
    if current_price > recent_high * 0.95:  # 최근 고점 95% 이상이면 감점
        final_score *= 0.5
        early_signals.append("고점권주의")
    
    all_signals = legacy_signals + early_signals
    
    return final_score, all_signals

def send_discord_message(message, webhook_url):
    """디스코드 메시지 전송 (에러 처리 강화)"""
    if not webhook_url:
        logger.error("❌ Discord webhook URL이 설정되지 않았습니다.")
        return
        
    logger.info(message)
    MAX_LENGTH = 2000
    chunks = [message[i:i+MAX_LENGTH] for i in range(0, len(message), MAX_LENGTH)]
    
    for chunk in chunks:
        data = {"content": chunk}
        try:
            response = requests.post(webhook_url, json=data, timeout=10)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"❌ 디스코드 전송 실패: {e}")
        time.sleep(0.5)

def format_multi_signal_message(grade, stocks):
    """다중신호 종목 메시지 포맷팅"""
    if not stocks:
        return ""
    
    grade_info = {
        "ultra_strong": {"icon": "🚀", "name": "초강력 매수신호", "desc": "5점 이상"},
        "strong": {"icon": "🔥", "name": "강력 매수신호", "desc": "4점"},
        "moderate": {"icon": "⭐", "name": "보통 매수신호", "desc": "3점"},
        "weak": {"icon": "⚡", "name": "약한 매수신호", "desc": "2점"},
        "single": {"icon": "💡", "name": "단일 매수신호", "desc": "1점"}
    }
    
    info = grade_info[grade]
    header = f"{info['icon']} **[{info['name']} ({info['desc']})]**\n"
    
    stock_lines = []
    for stock in sorted(stocks, key=lambda x: x['score'], reverse=True):
        signals_text = ", ".join(stock['signals'])
        price_text = f"{stock['price']:,}원"
        volume_text = f"{stock['volume']:,}"
        
        line = f"- {stock['name']} ({stock['code']}) - {stock['score']}점\n"
        line += f"  📊 [{signals_text}]"
        #line += f"  💰 {price_text} | 📈 {volume_text}주"
        if ('외국인매수추세' in stock['signals']):
            line += f"\n  💰 외국인: {stock['foreign']}"
        stock_lines.append(line)
    
    return header + "\n".join(stock_lines)

def format_signal_combination_message(combinations):
    """신호 조합 패턴 메시지 포맷팅"""
    if not combinations:
        return ""
    
    header = "🔍 **[인기 신호 조합 패턴]**\n"
    combo_lines = []
    
    # 조합별 종목 수로 정렬
    sorted_combos = sorted(combinations.items(), key=lambda x: len(x[1]), reverse=True)
    
    for combo, stocks in sorted_combos[:10]:  # 상위 10개 조합만
        if len(stocks) >= 2:  # 2개 이상 종목에서 나타나는 조합만
            combo_lines.append(f"• **{combo}** ({len(stocks)}개 종목)")
            combo_lines.append(f"  → {', '.join(stocks[:5])}")  # 최대 5개 종목만 표시
            if len(stocks) > 5:
                combo_lines.append(f"  → 외 {len(stocks)-5}개 종목")
    
    return header + "\n".join(combo_lines) if combo_lines else ""


def convert_numpy_types(obj):
    """numpy 타입을 JSON 직렬화 가능한 타입으로 변환"""
    if isinstance(obj, np.integer):
        return int(obj)
    elif isinstance(obj, np.floating):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, dict):
        return {key: convert_numpy_types(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [convert_numpy_types(item) for item in obj]
    else:
        return obj

if __name__ == "__main__":
    try:
        app_key = os.getenv("KIS_APP_KEY")
        app_secret = os.getenv("KIS_APP_SECRET")
        access_token = load_token()
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        logger = setup_logger()
        
        logger.info("📊 시가총액 상위 200개 종목 분석 시작...")
        stock_list = get_top_200_stocks()
        backtest_candidates = []  # score 2 이상 종목들을 저장할 리스트
        
        if not stock_list:
            logger.error("❌ 종목 리스트를 가져올 수 없습니다.")
            exit(1)

        # 각 신호별 종목 리스트
        signal_lists = {
            "골든크로스": [],
            "볼린저밴드복귀": [],
            "MACD상향돌파": [],
            "RSI과매도회복": [],
            "스토캐스틱회복": [],
            "거래량급증": [],
            "Williams%R회복": [],
            "이중바닥": [],
            "일목균형표": [],
            "컵앤핸들": [],
            "MACD골든크로스": [],
            "외국인매수추세": [] ,
            "기관연속매수": []   
        }
        
        # 다중신호 종목 분류
        multi_signal_stocks = {
            "ultra_strong": [],    # 5점 이상 - 매우 강한 신호
            "strong": [],          # 4점 - 강한 신호
            "moderate": [],        # 3점 - 보통 신호
            "weak": [],           # 2점 - 약한 신호
            "single": []          # 1점 - 단일 신호
        }
        
        # 신호 조합 분석
        signal_combinations = {}
        
        # 성공적으로 분석된 종목 수 추적
        analyzed_count = 0
        error_count = 0


        for name, code in stock_list.items():
            try:
                # 외국인 순매수 확인
                foreign_net_buy = get_foreign_net_buy_kis(code, app_key, app_secret, access_token, days=3)
                netbuy_list, trend = get_foreign_netbuy_trend_kis(code, app_key, app_secret, access_token)
                
                # 외국인 매도 추세면 제외
                if trend == "distributing":
                    continue

                df = get_daily_price_data_with_realtime(access_token, app_key, app_secret, code)
                if df is None or df.empty:
                    continue

                # 개선된 종합 점수 계산 사용
                score, active_signals = calculate_buy_signal_score_improved(
                    df, name, code, app_key, app_secret, access_token, foreign_trend=trend
                )
                
                # 현재 가격 정보
                current_price = df.iloc[-1]["stck_clpr"]
                volume = df.iloc[-1]["acml_vol"]
                
                # 개별 신호 체크
                if is_golden_cross(df):
                    signal_lists["골든크로스"].append(f"- {name} ({code})")
                if is_bollinger_rebound(df):
                    signal_lists["볼린저밴드복귀"].append(f"- {name} ({code})")
                if is_macd_signal_cross(df):
                    signal_lists["MACD상향돌파"].append(f"- {name} ({code})")
                if is_rsi_oversold_recovery(df):
                    signal_lists["RSI과매도회복"].append(f"- {name} ({code})")
                if is_stochastic_oversold_recovery(df):
                    signal_lists["스토캐스틱회복"].append(f"- {name} ({code})")
                #if is_volume_breakout(df):
                    #signal_lists["거래량급증"].append(f"- {name} ({code})")
                if is_williams_r_oversold_recovery(df):
                    signal_lists["Williams%R회복"].append(f"- {name} ({code})")
                if is_double_bottom_pattern(df):
                    signal_lists["이중바닥"].append(f"- {name} ({code})")
                if is_ichimoku_bullish_signal(df):
                    signal_lists["일목균형표"].append(f"- {name} ({code})")
                if is_cup_handle_pattern(df):
                    signal_lists["컵앤핸들"].append(f"- {name} ({code})")
                if is_macd_golden_cross(df):
                    signal_lists["MACD골든크로스"].append(f"- {name} ({code})")
                if trend == "steady_buying":
                    signal_lists["외국인매수추세"].append(f"- {name} ({code})")
                #if is_institution_consecutive_buying(code, app_key, app_secret, access_token):
                #    signal_lists["기관연속매수"].append(f"- {name} ({code})") 
                if is_institution_positive_trend(code, app_key, app_secret, access_token):
                    signal_lists["기관매수추세"].append(f"- {name} ({code})")

                

                if score >= 3.0:  # 기존보다 높은 기준
                    current_price = df.iloc[-1]["stck_clpr"]
                    volume = df.iloc[-1]["acml_vol"]
                    
                    stock_info = {
                        "name": name, "code": code, "score": score, 
                        "signals": active_signals, "price": current_price, "volume": volume,
                        "foreign": netbuy_list 
                    }
                    
                    # 점수별 분류도 더 엄격하게
                    if score >= 6:
                        multi_signal_stocks["ultra_strong"].append(stock_info)
                    elif score >= 5:
                        multi_signal_stocks["strong"].append(stock_info)
                    elif score >= 4:
                        multi_signal_stocks["moderate"].append(stock_info)
                    else:
                        multi_signal_stocks["weak"].append(stock_info)
                    
                    # 백테스트 후보도 더 엄격하게
                    if score >= 4.0:  # 기존 3.0 → 4.0
                        backtest_candidates.append({
                            "code": code,
                            "name": name,
                            "score": score,
                            "signals": active_signals,
                            "price": current_price,
                            "volume": volume,
                            "foreign_netbuy": netbuy_list,
                            "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })

                analyzed_count += 1
                if analyzed_count % 50 == 0:
                    logger.info(f"진행 상황: {analyzed_count}개 종목 분석 완료")

            except Exception as e:
                logger.error(f"⚠️ {name} 분석 오류: {e}")
                error_count += 1
            
            time.sleep(0.5)  # API 호출 제한 고려

        logger.info(f"분석 완료: 성공 {analyzed_count}개, 오류 {error_count}개")

        # 결과 전송
        # 1. 다중신호 종목 우선순위별 전송
        priority_order = ["ultra_strong", "strong", "moderate", "weak"]
        
        for grade in priority_order:
            if multi_signal_stocks[grade]:
                msg = format_multi_signal_message(grade, multi_signal_stocks[grade])
                if msg:
                    send_discord_message(msg, webhook_url)
                    logger.info(f"{grade} 종목: {len(multi_signal_stocks[grade])}개")
        
        # 2. 신호 조합 패턴 분석 결과 전송
        if signal_combinations:
            combo_msg = format_signal_combination_message(signal_combinations)
            if combo_msg:
                send_discord_message(combo_msg, webhook_url)
                logger.info(f"신호 조합 패턴: {len(signal_combinations)}개")
        
        # 3. 요약 통계 전송
        total_multi_signals = sum(len(stocks) for grade, stocks in multi_signal_stocks.items() if grade != "single")
        summary_msg = f"📈 **[다중신호 종목 요약]**\n"
        summary_msg += f"🚀 초강력 신호: {len(multi_signal_stocks['ultra_strong'])}개\n"
        summary_msg += f"🔥 강력 신호: {len(multi_signal_stocks['strong'])}개\n"
        summary_msg += f"⭐ 보통 신호: {len(multi_signal_stocks['moderate'])}개\n"
        summary_msg += f"⚡ 약한 신호: {len(multi_signal_stocks['weak'])}개\n"
        summary_msg += f"💡 단일 신호: {len(multi_signal_stocks['single'])}개\n"
        summary_msg += f"📊 **총 다중신호 종목: {total_multi_signals}개**\n"
        summary_msg += f"✅ 분석 성공: {analyzed_count}개 | ❌ 오류: {error_count}개"
        
        send_discord_message(summary_msg, webhook_url)

        # 4. 개별 신호 상세 (필요시)
        detail_mode = os.getenv("DETAIL_MODE", "false").lower() == "true"
        if detail_mode:
            for signal_type, signal_list in signal_lists.items():
                if signal_list:
                    icons = {
                        "골든크로스": "🟡", "볼린저밴드복귀": "🔵", "MACD상향돌파": "🟢",
                        "RSI과매도회복": "🟠", "스토캐스틱회복": "🟣", "거래량급증": "🔴",
                        "Williams%R회복": "🟤", "이중바닥": "⚫", "일목균형표": "🔘", "컵앤핸들": "🎯",
                        "MACD골든크로스": "⚡", "외국인매수추세": "🌍", "기관연속매수": "🏛️" 
                    }
                    icon = icons.get(signal_type, "📊")
                    msg = f"{icon} **[{signal_type} 발생 종목]**\n" + "\n".join(signal_list)
                    send_discord_message(msg, webhook_url)
                    logger.info(f"{signal_type}: {len(signal_list)}개")

        # 5. backtest_list.json 파일 저장
        try:

            # score 기준으로 내림차순 정렬 후 상위 10개만 선택
            backtest_candidates = sorted(backtest_candidates, key=lambda x: x['score'], reverse=True)[:20]
    
            logger.debug("저장할 데이터:", backtest_candidates)
            logger.debug(f"데이터 타입: {type(backtest_candidates)}")
            logger.debug(f"데이터 개수: {len(backtest_candidates)}")
            
            # numpy 타입 변환
            converted_data = convert_numpy_types(backtest_candidates)

            # 임시 파일에 먼저 저장
            temp_filename = "backtest_list_temp.json"
            final_filename = "backtest_list.json"
            
            with open(temp_filename, "w", encoding="utf-8") as f:
                json.dump(converted_data, f, ensure_ascii=False, indent=2)
            
            # 임시 파일이 정상적으로 생성되었는지 확인
            import os
            if os.path.exists(temp_filename):
                file_size = os.path.getsize(temp_filename)
                logger.debug(f"임시 파일 크기: {file_size} bytes")
                
                # 정상적으로 저장되었다면 원본 파일로 이동
                os.rename(temp_filename, final_filename)
                logger.info(f"✅ backtest_list.json 저장 완료: {len(backtest_candidates)}개 종목")
            else:
                raise Exception("임시 파일 생성 실패")
                
        except Exception as e:
            logger.error(f"❌ backtest_list.json 저장 실패: {e}")
            logger.error(f"상세 오류: {type(e).__name__}: {str(e)}")
            
            # 데이터 유효성 검사
            try:
                json.dumps(backtest_candidates, ensure_ascii=False)
            except Exception as json_error:
                logger.error(f"JSON 직렬화 오류: {json_error}")
            
            error_msg = f"❌ **[파일 저장 오류]**\nbacktest_list.json 저장 중 오류: {str(e)}"
            send_discord_message(error_msg, webhook_url)
        
        logger.info("✅ 모든 분석 및 전송 완료!")


    except Exception as e:
        logger.error(f"❌ 메인 프로세스 오류: {e}")
        print(f"❌ 심각한 오류 발생: {e}")
        if webhook_url:
            error_msg = f"❌ **[시스템 오류]**\n주식 분석 중 오류가 발생했습니다: {str(e)}"
            send_discord_message(error_msg, webhook_url)
