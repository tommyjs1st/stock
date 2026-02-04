"""
기술적 지표 강화 함수 - Phase 1 추가분
괴리율 계산 및 투자자 조건 검증
"""
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def calculate_ma20_divergence(df):
    """
    20일 이동평균선 대비 괴리율 계산
    
    Args:
        df: 주가 데이터프레임 (stck_clpr, MA20 필요)
        
    Returns:
        dict: {
            'divergence_pct': float - 괴리율 (%)
            'category': str - 구간 분류 (mild/moderate/strong)
            'current_price': float - 현재가
            'ma20': float - 20일 이동평균
        }
    """
    try:
        if df is None or df.empty or len(df) < 20:
            return {
                'divergence_pct': None,
                'category': 'unknown',
                'current_price': None,
                'ma20': None
            }
        
        # MA20 계산 (없는 경우)
        if 'MA20' not in df.columns:
            df['MA20'] = df['stck_clpr'].rolling(window=20).mean()
        
        current_price = df['stck_clpr'].iloc[-1]
        ma20 = df['MA20'].iloc[-1]
        
        if pd.isna(ma20) or ma20 == 0:
            return {
                'divergence_pct': None,
                'category': 'unknown',
                'current_price': current_price,
                'ma20': None
            }
        
        # 괴리율 계산: (현재가 - MA20) / MA20 * 100
        divergence_pct = ((current_price - ma20) / ma20) * 100
        
        # 구간 분류
        if -5 <= divergence_pct <= 0:
            category = 'mild'        # 약조정
        elif -10 <= divergence_pct < -5:
            category = 'moderate'    # 중간조정
        elif divergence_pct < -10:
            category = 'strong'      # 강조정
        else:
            category = 'above_ma20'  # 20일선 위 (절대조건 미달)
        
        logger.debug(f"📊 괴리율: {divergence_pct:.2f}% ({category}), 현재가: {current_price:,}, MA20: {ma20:.2f}")
        
        return {
            'divergence_pct': round(divergence_pct, 2),
            'category': category,
            'current_price': current_price,
            'ma20': round(ma20, 2)
        }
        
    except Exception as e:
        logger.error(f"❌ 괴리율 계산 오류: {e}")
        return {
            'divergence_pct': None,
            'category': 'error',
            'current_price': None,
            'ma20': None
        }


def get_divergence_bonus(divergence_info, config):
    """
    괴리율에 따른 보너스 점수 계산
    
    Args:
        divergence_info: calculate_ma20_divergence 결과
        config: 설정 딕셔너리 (ma20_divergence 섹션)
        
    Returns:
        float: 보너스 점수
    """
    try:
        if not config or not config.get('enabled', False):
            return 0.0
        
        category = divergence_info.get('category', 'unknown')
        bonus_scores = config.get('bonus_scores', {})
        
        bonus = bonus_scores.get(category, 0.0)
        
        if bonus > 0:
            logger.debug(f"🎁 괴리율 보너스: +{bonus}점 ({category})")
        
        return bonus
        
    except Exception as e:
        logger.error(f"❌ 보너스 점수 계산 오류: {e}")
        return 0.0


def check_institution_consecutive_buying(institution_netbuy_list, consecutive_days=2):
    """
    기관 최근 연속 매수 확인
    
    Args:
        institution_netbuy_list: 기관 순매수 리스트 (최신순)
        consecutive_days: 요구되는 연속 매수 일수
        
    Returns:
        dict: {
            'meets_condition': bool - 조건 만족 여부
            'consecutive_days': int - 실제 연속 매수 일수
            'reason': str - 판단 근거
            'volumes': list - 해당 기간 거래량
        }
    """
    try:
        if not institution_netbuy_list or len(institution_netbuy_list) < consecutive_days:
            return {
                'meets_condition': False,
                'consecutive_days': 0,
                'reason': f'데이터 부족 (최소 {consecutive_days}일 필요)',
                'volumes': []
            }
        
        # 최근 N일 데이터 확인
        recent_days = institution_netbuy_list[:consecutive_days]
        
        # 연속 매수일 카운트
        consecutive_count = 0
        for volume in recent_days:
            if volume > 0:
                consecutive_count += 1
            else:
                break
        
        logger.debug(f"🏛️ 기관 최근 데이터: {recent_days[:3]}, 연속매수일: {consecutive_count}")
        
        # 조건 판단
        meets_condition = consecutive_count >= consecutive_days
        
        if meets_condition:
            reason = f'최근 {consecutive_count}일 연속 순매수'
        else:
            reason = f'연속 매수 {consecutive_count}일 (최소 {consecutive_days}일 필요)'
        
        return {
            'meets_condition': meets_condition,
            'consecutive_days': consecutive_count,
            'reason': reason,
            'volumes': recent_days
        }
        
    except Exception as e:
        logger.error(f"❌ 기관 매수 체크 오류: {e}")
        return {
            'meets_condition': False,
            'consecutive_days': 0,
            'reason': f'오류 발생: {str(e)}',
            'volumes': []
        }


def check_investor_condition(foreign_list, institution_list, condition_type, consecutive_days=2):
    """
    투자자 매수 조건 통합 체크
    
    Args:
        foreign_list: 외국인 순매수 리스트
        institution_list: 기관 순매수 리스트
        condition_type: 조건 타입
            - 'foreign_only': 외국인만
            - 'institution_only': 기관만
            - 'both': 외국인 AND 기관 모두 연속 매수
            - 'either': 외국인 OR 기관 중 하나라도 연속 매수
        consecutive_days: 연속 매수 일수
        
    Returns:
        dict: {
            'meets_condition': bool - 조건 만족 여부
            'reason': str - 판단 근거
            'foreign_check': dict - 외국인 체크 결과
            'institution_check': dict - 기관 체크 결과
        }
    """
    try:
        # 기존 check_foreign_consecutive_buying 함수 import 필요
        from technical_indicators import check_foreign_consecutive_buying
        
        # 외국인 체크
        foreign_check = check_foreign_consecutive_buying(foreign_list) if foreign_list else {
            'meets_condition': False,
            'consecutive_days': 0,
            'reason': '외국인 데이터 없음',
            'volumes': []
        }
        
        # 기관 체크
        institution_check = check_institution_consecutive_buying(institution_list, consecutive_days) if institution_list else {
            'meets_condition': False,
            'consecutive_days': 0,
            'reason': '기관 데이터 없음',
            'volumes': []
        }
        
        # 조건별 판단
        if condition_type == 'foreign_only':
            meets_condition = foreign_check['meets_condition']
            reason = f"외국인: {foreign_check['reason']}"
            
        elif condition_type == 'institution_only':
            meets_condition = institution_check['meets_condition']
            reason = f"기관: {institution_check['reason']}"
            
        elif condition_type == 'both':
            meets_condition = foreign_check['meets_condition'] and institution_check['meets_condition']
            reason = f"외국인: {foreign_check['reason']}, 기관: {institution_check['reason']}"
            
        elif condition_type == 'either':
            meets_condition = foreign_check['meets_condition'] or institution_check['meets_condition']
            if foreign_check['meets_condition'] and institution_check['meets_condition']:
                reason = "외국인+기관 모두 연속 매수"
            elif foreign_check['meets_condition']:
                reason = f"외국인: {foreign_check['reason']}"
            else:
                reason = f"기관: {institution_check['reason']}"
        else:
            meets_condition = False
            reason = f"알 수 없는 조건 타입: {condition_type}"
        
        logger.debug(f"👥 투자자 조건({condition_type}): {meets_condition} - {reason}")
        
        return {
            'meets_condition': meets_condition,
            'reason': reason,
            'foreign_check': foreign_check,
            'institution_check': institution_check
        }
        
    except Exception as e:
        logger.error(f"❌ 투자자 조건 체크 오류: {e}")
        return {
            'meets_condition': False,
            'reason': f'오류 발생: {str(e)}',
            'foreign_check': {},
            'institution_check': {}
        }


def check_trading_value(df, min_trading_value=100000000):
    """
    거래대금 체크 (거래량 × 현재가)
    
    Args:
        df: 주가 데이터프레임
        min_trading_value: 최소 거래대금 (기본 1억원)
        
    Returns:
        dict: {
            'meets_condition': bool - 조건 만족 여부
            'trading_value': int - 당일 거래대금
            'reason': str - 판단 근거
        }
    """
    try:
        if df is None or df.empty:
            return {
                'meets_condition': False,
                'trading_value': 0,
                'reason': '데이터 없음'
            }
        
        current_price = df['stck_clpr'].iloc[-1]
        volume_col = 'acml_vol' if 'acml_vol' in df.columns else 'cntg_vol'
        current_volume = df[volume_col].iloc[-1]
        
        trading_value = int(current_price * current_volume)
        meets_condition = trading_value >= min_trading_value
        
        if meets_condition:
            reason = f'거래대금 {trading_value:,}원 (기준: {min_trading_value:,}원)'
        else:
            reason = f'거래대금 부족 {trading_value:,}원 < {min_trading_value:,}원'
        
        logger.debug(f"💰 거래대금 체크: {meets_condition} - {reason}")
        
        return {
            'meets_condition': meets_condition,
            'trading_value': trading_value,
            'reason': reason
        }
        
    except Exception as e:
        logger.error(f"❌ 거래대금 체크 오류: {e}")
        return {
            'meets_condition': False,
            'trading_value': 0,
            'reason': f'오류 발생: {str(e)}'
        }
