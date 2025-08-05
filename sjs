    # KISAutoTrader 클래스 안에 추가할 메서드들:
    
    def get_market_status_info(self, current_time=None):
        """장 상태 정보 반환"""
        if current_time is None:
            current_time = datetime.now()
        
        is_open = self.is_market_open(current_time)
        
        if is_open:
            today_close = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
            time_to_close = today_close - current_time
            
            return {
                'status': 'OPEN',
                'message': f'장 시간 중 (마감까지 {str(time_to_close).split(".")[0]})',
                'next_change': today_close,
                'is_trading_time': True
            }
        else:
            # 다음 개장 시간 계산
            next_day = current_time + timedelta(days=1)
            while next_day.weekday() >= 5:
                next_day += timedelta(days=1)
            
            next_open = next_day.replace(hour=9, minute=0, second=0, microsecond=0)
            
            if current_time.weekday() >= 5:
                message = f'주말 휴장 (다음 개장: {next_open.strftime("%m/%d %H:%M")})'
            elif current_time.hour < 9:
                message = f'장 시작 전 (개장: 09:00)'
            else:
                message = f'장 마감 후 (다음 개장: {next_open.strftime("%m/%d %H:%M")})'
            
            return {
                'status': 'CLOSED',
                'message': message,
                'next_change': next_open,
                'is_trading_time': False
            }
    
    def is_market_open(self, current_time=None):
        """한국 증시 개장 시간 확인"""
        if current_time is None:
            current_time = datetime.now()
        
        weekday = current_time.weekday()
        if weekday >= 5:
            return False
        
        hour = current_time.hour
        minute = current_time.minute
        
        if hour < 9:
            return False
        
        if hour > 15 or (hour == 15 and minute > 30):
            return False
        
        return True
    
    def update_all_positions(self):
        """모든 보유 종목 포지션 업데이트"""
        try:
            all_holdings = self.get_all_holdings()
            
            self.positions = {}
            for symbol in getattr(self, 'symbols', []):
                if symbol in all_holdings:
                    self.positions[symbol] = all_holdings[symbol]
            
            self.all_positions = all_holdings
            
            self.logger.info(f"💼 포지션 업데이트: 거래대상 {len(self.positions)}개, 전체 {len(self.all_positions)}개")
            
        except Exception as e:
            self.logger.error(f"포지션 업데이트 실패: {e}")
    
    def process_sell_signals(self):
        """매도 신호 처리"""
        if not hasattr(self, 'all_positions') or not self.all_positions:
            return
        
        positions_to_process = dict(self.all_positions)
        
        for symbol, position in positions_to_process.items():
            try:
                if symbol not in self.all_positions:
                    continue
                    
                self.process_sell_for_symbol(symbol, position)
                time.sleep(0.5)
            except Exception as e:
                self.logger.error(f"{symbol} 매도 처리 오류: {e}")
    
    def notify_error(self, error_type: str, error_msg: str):
        """오류 알림"""
        if not self.notify_on_error:
            return
    
        title = f"⚠️ 시스템 오류: {error_type}"
        message = f"""
    **오류 내용**: {error_msg}
    **시간**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
    
        self.send_discord_notification(title, message, 0xff0000)
