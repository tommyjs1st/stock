"""
포지션 관리 모듈
"""
import json
import os
from datetime import datetime, timedelta, date
from typing import Dict, Tuple, List


class PositionManager:
    """종목별 포지션 관리 클래스"""
    
    def __init__(self, logger, max_purchases_per_symbol=2, max_quantity_per_symbol=200, 
                 min_holding_period_hours=24, purchase_cooldown_hours=24,
                 max_total_holdings=5):
        self.logger = logger
        self.position_history_file = "position_history.json"
        self.position_history = {}
        
        # 설정값들
        self.max_purchases_per_symbol = max_purchases_per_symbol
        self.max_quantity_per_symbol = max_quantity_per_symbol
        self.min_holding_period_hours = min_holding_period_hours
        self.purchase_cooldown_hours = purchase_cooldown_hours
        self.max_total_holdings = max_total_holdings
        
        self.load_position_history()
    
    def load_position_history(self):
        """포지션 이력 로드"""
        try:
            if os.path.exists(self.position_history_file):
                with open(self.position_history_file, 'r', encoding='utf-8') as f:
                    self.position_history = json.load(f)
                self.logger.info(f"📋 포지션 이력 로드: {len(self.position_history)}개 종목")
        except Exception as e:
            self.logger.error(f"포지션 이력 로드 실패: {e}")
            self.position_history = {}
    
    def save_position_history(self):
        """포지션 이력 저장"""
        try:
            with open(self.position_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.position_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"포지션 이력 저장 실패: {e}")
    
    def record_purchase(self, symbol: str, quantity: int, price: float, strategy: str):
        """매수 기록"""
        now = datetime.now()
        
        if symbol not in self.position_history:
            self.position_history[symbol] = {
                'total_quantity': 0,
                'purchase_count': 0,
                'purchases': [],
                'last_purchase_time': None,
                'first_purchase_time': None
            }
        
        purchase_record = {
            'timestamp': now.isoformat(),
            'quantity': quantity,
            'price': price,
            'strategy': strategy,
            'order_type': 'BUY'
        }
        
        self.position_history[symbol]['purchases'].append(purchase_record)
        self.position_history[symbol]['total_quantity'] += quantity
        self.position_history[symbol]['purchase_count'] += 1
        self.position_history[symbol]['last_purchase_time'] = now.isoformat()
        
        if not self.position_history[symbol]['first_purchase_time']:
            self.position_history[symbol]['first_purchase_time'] = now.isoformat()
        
        self.save_position_history()
        
        self.logger.info(f"📝 매수 기록: {symbol} {quantity}주 @ {price:,}원 "
                        f"(누적: {self.position_history[symbol]['total_quantity']}주)")
    
    def record_sale(self, symbol: str, quantity: int, price: float, reason: str):
        """매도 기록"""
        now = datetime.now()
        
        if symbol in self.position_history:
            sale_record = {
                'timestamp': now.isoformat(),
                'quantity': quantity,
                'price': price,
                'reason': reason,
                'order_type': 'SELL'
            }
            
            self.position_history[symbol]['purchases'].append(sale_record)
            self.position_history[symbol]['total_quantity'] -= quantity
            
            if self.position_history[symbol]['total_quantity'] <= 0:
                self.position_history[symbol]['total_quantity'] = 0
                self.position_history[symbol]['position_closed_time'] = now.isoformat()
            
            self.save_position_history()
            
            self.logger.info(f"📝 매도 기록: {symbol} {quantity}주 @ {price:,}원 "
                           f"사유: {reason} (잔여: {self.position_history[symbol]['total_quantity']}주)")
    
    def can_purchase_symbol(self, symbol: str, current_quantity: int = 0,
                            total_holdings_count: int = 0) -> Tuple[bool, str]:
        """종목 매수 가능 여부 확인"""
        actual_holdings = total_holdings_count
    
        if current_quantity == 0 and actual_holdings >= self.max_total_holdings:
            return False, f"최대 보유 종목 수 초과 ({actual_holdings}/{self.max_total_holdings}개)"

        # 현재 보유 수량 확인
        if current_quantity >= self.max_quantity_per_symbol:
            return False, f"최대 보유 수량 초과 ({current_quantity}/{self.max_quantity_per_symbol}주)"
        
        # 매수 횟수 제한 확인
        history = self.position_history.get(symbol, {})
        purchase_count = history.get('purchase_count', 0)
        
        if purchase_count >= self.max_purchases_per_symbol:
            return False, f"최대 매수 횟수 초과 ({purchase_count}/{self.max_purchases_per_symbol}회)"
        
        today = date.today().strftime('%Y-%m-%d')
        trades_file = "daily_trades.json"
        if os.path.exists(trades_file):
            with open(trades_file, 'r', encoding='utf-8') as f:
                all_trades = json.load(f)
        
            # 오늘 해당 종목 매도 내역 확인
            today_sells = [t for t in all_trades 
                          if (t.get('symbol') == symbol and 
                              t.get('action') == 'SELL' and 
                              t.get('timestamp', '').startswith(today))]
        
            if today_sells:
                sell_time = today_sells[-1]['timestamp'][-8:-3]  # HH:MM 형식
                return False, f"당일 매도 종목 재매수 금지 (매도시간: {sell_time})"

        # 재매수 금지 기간 확인
        last_purchase_time = history.get('last_purchase_time')
        if last_purchase_time:
            last_time = datetime.fromisoformat(last_purchase_time)
            time_since_last = datetime.now() - last_time
        
            if time_since_last < timedelta(hours=self.purchase_cooldown_hours):
                remaining_hours = self.purchase_cooldown_hours - time_since_last.total_seconds() / 3600
            
                # 🆕 매도 후 재매수인지 확인
                recent_sales = self._get_recent_sales(symbol)
                if recent_sales:
                    last_sale = recent_sales[-1]
                    sale_price = last_sale['price']
                    sale_time = datetime.fromisoformat(last_sale['timestamp'])
                    
                    return False, (f"재매수 금지 기간 중 (남은: {remaining_hours:.1f}시간) "
                                 f"- 최근매도: {sale_price:,}원 ({sale_time.strftime('%m/%d %H:%M')})")
                else:
                    return False, f"재매수 금지 기간 중 (남은 시간: {remaining_hours:.1f}시간)"
    
        return True, "매수 가능"

    def _get_recent_sales(self, symbol: str) -> List[Dict]:
        """최근 매도 내역 조회 - 파일에서 읽기"""
        try:
            trades_file = "trades.json"  # 또는 실제 거래 로그 파일 경로
            if not os.path.exists(trades_file):
                return []
            
            with open(trades_file, 'r', encoding='utf-8') as f:
                all_trades = json.load(f)
            
            # 해당 종목의 매도 내역만 필터링
            recent_sales = []
            for trade in all_trades:
                if (trade.get('symbol') == symbol and 
                    trade.get('action') == 'SELL'):
                    recent_sales.append(trade)
            
            # 최근 순으로 정렬
            return sorted(recent_sales, key=lambda x: x['timestamp'], reverse=True)
            
        except Exception as e:
            self.logger.error(f"매도 기록 조회 실패 ({symbol}): {e}")
            return []

    def can_sell_symbol(self, symbol: str, current_quantity: int = 0) -> Tuple[bool, str]:
        """종목 매도 가능 여부 확인"""
        
        # 보유 여부 확인
        if current_quantity <= 0:
            return False, "보유 포지션 없음"
        
        # 최소 보유 기간 확인
        history = self.position_history.get(symbol, {})
        first_purchase_time = history.get('first_purchase_time')
        
        if first_purchase_time:
            first_time = datetime.fromisoformat(first_purchase_time)
            holding_time = datetime.now() - first_time
            
            if holding_time < timedelta(hours=self.min_holding_period_hours):
                remaining_hours = self.min_holding_period_hours - holding_time.total_seconds() / 3600
                return False, f"최소 보유 기간 미충족 (남은 시간: {remaining_hours:.1f}시간)"
        
        return True, "매도 가능"
    
    def get_position_summary(self, symbol: str) -> Dict:
        """종목별 포지션 요약 정보"""
        history = self.position_history.get(symbol, {})
        
        return {
            'total_quantity': history.get('total_quantity', 0),
            'purchase_count': history.get('purchase_count', 0),
            'first_purchase_time': history.get('first_purchase_time'),
            'last_purchase_time': history.get('last_purchase_time'),
            'is_position_closed': history.get('position_closed_time') is not None
        }
