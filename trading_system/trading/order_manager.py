"""
주문 관리 모듈 (종목명 로그 개선)
"""
from typing import Dict, Callable


class OrderManager:
    """주문 실행 및 관리 클래스"""
    
    def __init__(self, api_client, logger, max_position_ratio=0.4, get_stock_name_func=None):
        self.api_client = api_client
        self.logger = logger
        self.max_position_ratio = max_position_ratio
        self.get_stock_name = get_stock_name_func or (lambda code: code)
    
    def calculate_position_size(self, current_price: float, signal_strength: float, symbol: str = None) -> int:
        """포지션 크기 계산"""
        try:
            account_data = self.api_client.get_account_balance()
            if not account_data:
                if symbol:
                    stock_name = self.get_stock_name(symbol)
                    self.logger.error(f"❌ {stock_name}({symbol}) 계좌 정보 조회 실패")
                return 0

            output = account_data.get('output', {})
            available_cash = float(output.get('ord_psbl_cash', 0))
            
            if available_cash == 0:
                if symbol:
                    stock_name = self.get_stock_name(symbol)
                    self.logger.warning(f"⚠️ {stock_name}({symbol}) 매수 가능 현금 없음")
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
                    if symbol:
                        stock_name = self.get_stock_name(symbol)
                        self.logger.warning(f"⚠️ {stock_name}({symbol}) 최소 투자금액 부족: {available_cash:,}원")
                    return 0

            quantity = int(adjusted_investment / current_price)
            
            # 종목명 포함 로그
            if symbol:
                stock_name = self.get_stock_name(symbol)
                self.logger.info(f"📊 {stock_name}({symbol}) 포지션 계산: {quantity}주 "
                               f"(투자금액: {adjusted_investment:,}원, 신호강도: {signal_strength:.2f})")
            else:
                self.logger.info(f"📊 포지션 계산: {quantity}주 (투자금액: {adjusted_investment:,}원)")
            
            return max(quantity, 0)

        except Exception as e:
            if symbol:
                stock_name = self.get_stock_name(symbol)
                self.logger.error(f"❌ {stock_name}({symbol}) 포지션 크기 계산 실패: {e}")
            else:
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
            """스마트 지정가 계산 (버그 수정 버전)"""
            stock_name = self.get_stock_name(symbol)
            
            self.logger.info(f"🔍 {symbol}({stock_name}) {side} 지정가 계산 시작 (긴급도: {urgency})")
            
            # 호가 정보 조회
            bid_ask = self.api_client.get_current_bid_ask(symbol)
            
            if not bid_ask or bid_ask.get('current_price', 0) == 0:
                self.logger.warning(f"⚠️ {symbol}({stock_name}) 호가 조회 실패, 현재가 기준으로 계산")
                
                # 호가 조회 실패 시 현재가 기반
                try:
                    current_price_data = self.api_client.get_current_price(symbol)
                    if current_price_data and current_price_data.get('output'):
                        current_price = float(current_price_data['output'].get('stck_prpr', 0))
                        
                        if current_price > 0:
                            if side == "BUY":
                                raw_price = current_price * 1.003  # 0.3% 위
                            else:
                                raw_price = current_price * 0.997  # 0.3% 아래
                            
                            limit_price = self.adjust_to_price_unit(raw_price)
                            self.logger.info(f"💰 {symbol}({stock_name}) {side} 지정가(현재가기준): {limit_price:,}원 "
                                           f"(현재가: {current_price:,}원)")
                            return limit_price
                except Exception as e:
                    self.logger.error(f"❌ {symbol}({stock_name}) 현재가 조회도 실패: {e}")
                
                raise Exception(f"{symbol}({stock_name}) 가격 정보를 가져올 수 없습니다")
            
            current_price = bid_ask['current_price']
            bid_price = bid_ask['bid_price']
            ask_price = bid_ask['ask_price']
            spread = bid_ask['spread']
            
            self.logger.info(f"📊 {symbol}({stock_name}) 호가 정보:")
            self.logger.info(f"  현재가: {current_price:,}원")
            self.logger.info(f"  매수호가: {bid_price:,}원, 매도호가: {ask_price:,}원")
            self.logger.info(f"  스프레드: {spread:,}원")
            
            # 호가가 0이거나 비정상적인 경우 현재가 기준으로 처리
            if bid_price == 0 or ask_price == 0 or ask_price <= bid_price:
                self.logger.warning(f"⚠️ {symbol}({stock_name}) 비정상적인 호가, 현재가 기준으로 계산")
                if side == "BUY":
                    raw_price = current_price * 1.003
                else:
                    raw_price = current_price * 0.997
            else:
                # 정상적인 호가 기반 계산
                if side == "BUY":
                    if urgency == "urgent":
                        raw_price = ask_price  # 매도호가로 즉시 체결
                    elif urgency == "aggressive":
                        # 매도호가 + 스프레드의 1/4 (더 공격적)
                        raw_price = ask_price + max(spread // 4, self.get_min_price_unit(ask_price))
                    else:  # normal, patient
                        if spread <= self.get_min_price_unit(current_price) * 5:
                            # 스프레드가 작으면 매도호가
                            raw_price = ask_price
                        else:
                            # 스프레드가 크면 현재가와 매도호가의 중간
                            raw_price = (current_price + ask_price) / 2
                else:  # SELL
                    if urgency == "urgent":
                        raw_price = bid_price  # 매수호가로 즉시 체결
                    elif urgency == "aggressive":
                        # 매수호가 - 스프레드의 1/4 (더 공격적)
                        raw_price = bid_price - max(spread // 4, self.get_min_price_unit(bid_price))
                    else:  # normal, patient
                        if spread <= self.get_min_price_unit(current_price) * 5:
                            # 스프레드가 작으면 매수호가
                            raw_price = bid_price
                        else:
                            # 스프레드가 크면 현재가와 매수호가의 중간
                            raw_price = (current_price + bid_price) / 2
            
            limit_price = self.adjust_to_price_unit(raw_price)
            limit_price = max(limit_price, 1)
            
            # 가격 검증
            if side == "BUY":
                # 매수 시 현재가의 30% 이상 차이나면 비정상
                if limit_price > current_price * 1.3:
                    self.logger.warning(f"⚠️ {symbol}({stock_name}) 매수 지정가가 너무 높음, 현재가 +1%로 조정")
                    limit_price = self.adjust_to_price_unit(current_price * 1.01)
                elif limit_price < current_price * 0.7:
                    self.logger.warning(f"⚠️ {symbol}({stock_name}) 매수 지정가가 너무 낮음, 현재가 -1%로 조정")
                    limit_price = self.adjust_to_price_unit(current_price * 0.99)
            else:  # SELL
                # 매도 시 현재가의 30% 이상 차이나면 비정상
                if limit_price < current_price * 0.7:
                    self.logger.warning(f"⚠️ {symbol}({stock_name}) 매도 지정가가 너무 낮음, 현재가 -1%로 조정")
                    limit_price = self.adjust_to_price_unit(current_price * 0.99)
                elif limit_price > current_price * 1.3:
                    self.logger.warning(f"⚠️ {symbol}({stock_name}) 매도 지정가가 너무 높음, 현재가 +1%로 조정")
                    limit_price = self.adjust_to_price_unit(current_price * 1.01)
            
            self.logger.info(f"💰 {symbol}({stock_name}) {side} 최종 지정가: {limit_price:,}원 "
                            f"(긴급도: {urgency}, 현재가 대비: {((limit_price/current_price-1)*100):+.2f}%)")
            
            return limit_price
    
    def place_order_with_strategy(self, symbol: str, side: str, quantity: int, strategy: str = "limit") -> Dict:
        """전략적 주문 실행"""
        stock_name = self.get_stock_name(symbol)
        
        self.logger.info(f"📝 {stock_name}({symbol}) {side} 주문 실행 시작: {quantity}주, 전략: {strategy}")
        
        if strategy == "market":
            result = self.api_client.place_order(symbol, side, quantity, price=0)
        
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
                result = self.api_client.place_order(symbol, side, quantity, price=limit_price)
            except Exception as e:
                self.logger.warning(f"⚠️ {stock_name}({symbol}) 지정가 계산 실패, 시장가로 변경: {e}")
                result = self.api_client.place_order(symbol, side, quantity, price=0)
        
        else:
            result = self.api_client.place_order(symbol, side, quantity, price=0)
        
        # 결과 로그
        if result.get('success'):
            executed_price = result.get('limit_price', 0)
            order_no = result.get('order_no', 'Unknown')
            total_amount = quantity * executed_price if executed_price > 0 else 0
            
            self.logger.info(f"✅ {stock_name}({symbol}) {side} 주문 성공: "
                           f"{quantity}주 @ {executed_price:,}원 "
                           f"(총액: {total_amount:,}원, 주문번호: {order_no})")
        else:
            error_msg = result.get('error', 'Unknown error')
            self.logger.error(f"❌ {stock_name}({symbol}) {side} 주문 실패: {error_msg}")
        
        return result

    def place_order_with_tracking(self, symbol: str, side: str, quantity: int, 
                                 strategy: str = "limit", order_tracker=None) -> Dict:
        """추적 기능이 포함된 주문 실행"""
        stock_name = self.get_stock_name(symbol)
        
        self.logger.info(f"📝 {symbol}({stock_name}) {side} 주문 실행 시작: {quantity}주, 전략: {strategy}")
        
        # 기존 주문 로직
        if strategy == "market":
            result = self.api_client.place_order(symbol, side, quantity, price=0)
            limit_price = 0
        else:
            try:
                limit_price = self.calculate_smart_limit_price(symbol, side, 
                                                             "urgent" if strategy == "urgent" else "normal")
                result = self.api_client.place_order(symbol, side, quantity, price=limit_price)
                result['limit_price'] = limit_price
            except Exception as e:
                self.logger.warning(f"⚠️ {symbol}({stock_name}) 지정가 계산 실패, 시장가로 변경: {e}")
                result = self.api_client.place_order(symbol, side, quantity, price=0)
                limit_price = 0
        
        # 결과 처리
        if result.get('success'):
            order_no = result.get('order_no', 'Unknown')
            
            if limit_price > 0 and order_tracker:
                # 지정가 주문인 경우 추적 대상에 추가
                order_tracker.add_pending_order(
                    order_no=order_no,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    limit_price=limit_price,
                    strategy=strategy,
                    stock_name=stock_name
                )
                
                self.logger.info(f"⏳ {symbol}({stock_name}) {side} 지정가 주문 접수: "
                               f"{quantity}주 @ {limit_price:,}원 (주문번호: {order_no})")
            else:
                # 시장가 주문은 즉시 체결로 간주
                self.logger.info(f"✅ {symbol}({stock_name}) {side} 시장가 주문 완료: "
                               f"{quantity}주 (주문번호: {order_no})")
        else:
            error_msg = result.get('error', 'Unknown error')
            self.logger.error(f"❌ {symbol}({stock_name}) {side} 주문 실패: {error_msg}")
        
        return result
