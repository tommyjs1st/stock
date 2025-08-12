"""
주문 관리 모듈
"""
from typing import Dict


class OrderManager:
    """주문 실행 및 관리 클래스"""
    
    def __init__(self, api_client, logger, max_position_ratio=0.4):
        self.api_client = api_client
        self.logger = logger
        self.max_position_ratio = max_position_ratio
    
    def calculate_position_size(self, current_price: float, signal_strength: float) -> int:
        """포지션 크기 계산"""
        try:
            account_data = self.api_client.get_account_balance()
            if not account_data:
                return 0

            output = account_data.get('output', {})
            available_cash = float(output.get('ord_psbl_cash', 0))
            
            if available_cash == 0:
                return 0
                
            # 최대 투자 가능 금액
            max_investment = available_cash * self.max_position_ratio
            
            # 신호 강도에 따른 조정
            if signal_strength < 0.5:
                return 0
            elif signal_strength < 1.0:
                position_ratio = 0.2
            elif signal_strength < 2.0:
                position_ratio = 0.4
            elif signal_strength < 3.0:
                position_ratio = 0.6
            elif signal_strength < 4.0:
                position_ratio = 0.8
            else:
                position_ratio = 1.0

            adjusted_investment = max_investment * position_ratio
            
            # 최소 투자 금액 체크
            min_investment = 100000
            if adjusted_investment < min_investment:
                if available_cash >= min_investment:
                    adjusted_investment = min_investment
                else:
                    return 0

            quantity = int(adjusted_investment / current_price)
            
            self.logger.info(f"📊 포지션 계산: {quantity}주 (투자금액: {adjusted_investment:,}원)")
            
            return max(quantity, 0)

        except Exception as e:
            self.logger.error(f"포지션 크기 계산 실패: {e}")
            return 0
    
    def adjust_to_price_unit(self, price: float) -> int:
        """한국 주식 호가단위에 맞게 가격 조정"""
        
        if price <= 0:
            return 1
        
        if price < 1000:
            return int(price)
        elif price < 5000:
            return int(price // 5) * 5
        elif price < 10000:
            return int(price // 10) * 10
        elif price < 50000:
            return int(price // 50) * 50
        elif price < 100000:
            return int(price // 100) * 100
        elif price < 500000:
            return int(price // 500) * 500
        else:
            return int(price // 1000) * 1000
    
    def get_min_price_unit(self, price: float) -> int:
        """가격대별 최소 호가단위"""
        if price < 1000:
            return 1
        elif price < 5000:
            return 5
        elif price < 10000:
            return 10
        elif price < 50000:
            return 50
        elif price < 100000:
            return 100
        elif price < 500000:
            return 500
        else:
            return 1000
    
    def calculate_smart_limit_price(self, symbol: str, side: str, urgency: str = "normal") -> int:
        """스마트 지정가 계산"""
        
        # 호가 정보 조회
        bid_ask = self.api_client.get_current_bid_ask(symbol)
        
        if not bid_ask:
            # 호가 조회 실패 시 현재가 기반
            try:
                current_price_data = self.api_client.get_current_price(symbol)
                if current_price_data and current_price_data.get('output'):
                    current_price = float(current_price_data['output'].get('stck_prpr', 0))
                    
                    if current_price > 0:
                        if side == "BUY":
                            raw_price = current_price * 1.003
                        else:
                            raw_price = current_price * 0.997
                        
                        return self.adjust_to_price_unit(raw_price)
            except:
                pass
            
            raise Exception("현재가 정보를 가져올 수 없습니다")
        
        current_price = bid_ask['current_price']
        bid_price = bid_ask['bid_price']
        ask_price = bid_ask['ask_price']
        spread = bid_ask['spread']
        
        if side == "BUY":
            if urgency == "urgent":
                raw_price = ask_price
            elif urgency == "aggressive":
                raw_price = ask_price + max(spread // 4, self.get_min_price_unit(ask_price))
            else:
                if spread <= self.get_min_price_unit(current_price) * 5:
                    raw_price = ask_price
                else:
                    raw_price = (current_price + ask_price) / 2
        else:
            if urgency == "urgent":
                raw_price = bid_price
            elif urgency == "aggressive":
                raw_price = bid_price - max(spread // 4, self.get_min_price_unit(bid_price))
            else:
                if spread <= self.get_min_price_unit(current_price) * 5:
                    raw_price = bid_price
                else:
                    raw_price = (current_price + bid_price) / 2
        
        limit_price = self.adjust_to_price_unit(raw_price)
        limit_price = max(limit_price, 1)
        
        self.logger.info(f"💰 {symbol} {side} 지정가: {limit_price:,}원 (긴급도: {urgency})")
        
        return limit_price
    
    def place_order_with_strategy(self, symbol: str, side: str, quantity: int, strategy: str = "limit") -> Dict:
        """전략적 주문 실행"""
        
        if strategy == "market":
            return self.api_client.place_order(symbol, side, quantity, price=0)
        
        elif strategy in ["limit", "aggressive_limit", "patient_limit", "urgent"]:
            urgency_map = {
                "limit": "normal",
                "aggressive_limit": "aggressive", 
                "patient_limit": "normal",
                "urgent": "urgent"
            }
            urgency = urgency_map.get(strategy, "normal")
            
            try:
                limit_price = self.calculate_smart_limit_price(symbol, side, urgency)
                return self.api_client.place_order(symbol, side, quantity, price=limit_price)
            except Exception as e:
                self.logger.warning(f"지정가 계산 실패, 시장가로 변경: {e}")
                return self.api_client.place_order(symbol, side, quantity, price=0)
        
        else:
            return self.api_client.place_order(symbol, side, quantity, price=0)
