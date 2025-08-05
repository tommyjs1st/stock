class PositionManager:
    def __init__(self, trader):
        self.trader = trader
        self.position_history_file = "position_history.json"
        self.position_history = {}
        self.load_position_history()
    
    def load_position_history(self):
        """포지션 이력 로드"""
        try:
            if os.path.exists(self.position_history_file):
                with open(self.position_history_file, 'r', encoding='utf-8') as f:
                    self.position_history = json.load(f)
                self.trader.logger.info(f"📋 포지션 이력 로드: {len(self.position_history)}개 종목")
        except Exception as e:
            self.trader.logger.error(f"포지션 이력 로드 실패: {e}")
            self.position_history = {}
    
    def save_position_history(self):
        """포지션 이력 저장"""
        try:
            with open(self.position_history_file, 'w', encoding='utf-8') as f:
                json.dump(self.position_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.trader.logger.error(f"포지션 이력 저장 실패: {e}")
    
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
        
        self.trader.logger.info(f"📝 매수 기록: {symbol} {quantity}주 @ {price:,}원 "
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
            
            self.trader.logger.info(f"📝 매도 기록: {symbol} {quantity}주 @ {price:,}원 "
                                   f"사유: {reason} (잔여: {self.position_history[symbol]['total_quantity']}주)")
