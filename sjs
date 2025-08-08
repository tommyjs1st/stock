    
    def is_market_open(self, current_time=None):
        """한국 증시 개장 시간 확인 (수정된 버전)"""
        if current_time is None:
            current_time = datetime.now()
        
        # 주말 체크
        weekday = current_time.weekday()  # 0=월, 6=일
        if weekday >= 5:  # 토요일(5), 일요일(6)
            return False
        
        # 시간 체크
        hour = current_time.hour
        minute = current_time.minute
        current_time_minutes = hour * 60 + minute
        
        # 개장: 09:00 (540분), 마감: 15:30 (930분)
        market_open_minutes = 9 * 60  # 540
        market_close_minutes = 15 * 60 + 30  # 930
        
        return market_open_minutes <= current_time_minutes <= market_close_minutes
    
    def get_market_status_info(self, current_time=None):
        """장 상태 정보 반환 (수정된 버전)"""
        if current_time is None:
            current_time = datetime.now()
        
        is_open = self.is_market_open(current_time)
        
        if is_open:
            # 장이 열려있는 경우
            today_close = current_time.replace(hour=15, minute=30, second=0, microsecond=0)
            time_to_close = today_close - current_time
            
            hours, remainder = divmod(time_to_close.total_seconds(), 3600)
            minutes, _ = divmod(remainder, 60)
            
            return {
                'status': 'OPEN',
                'message': f'장 시간 중 (마감까지 {int(hours)}시간 {int(minutes)}분)',
                'next_change': today_close,
                'is_trading_time': True
            }
        else:
            # 장이 닫혀있는 경우
            weekday = current_time.weekday()
            
            if weekday >= 5:  # 주말
                # 다음 월요일 09:00 계산
                days_until_monday = 7 - weekday  # 토요일이면 2일, 일요일이면 1일
                next_open = current_time + timedelta(days=days_until_monday)
                next_open = next_open.replace(hour=9, minute=0, second=0, microsecond=0)
                message = f'주말 휴장 (다음 개장: {next_open.strftime("%m/%d %H:%M")})'
            
            elif current_time.hour < 9:
                # 장 시작 전
                next_open = current_time.replace(hour=9, minute=0, second=0, microsecond=0)
                time_to_open = next_open - current_time
                hours, remainder = divmod(time_to_open.total_seconds(), 3600)
                minutes, _ = divmod(remainder, 60)
                message = f'장 시작 전 (개장까지 {int(hours)}시간 {int(minutes)}분)'
            
            else:
                # 장 마감 후
                next_day = current_time + timedelta(days=1)
                # 다음날이 주말이면 월요일로
                while next_day.weekday() >= 5:
                    next_day += timedelta(days=1)
                
                next_open = next_day.replace(hour=9, minute=0, second=0, microsecond=0)
                message = f'장 마감 후 (다음 개장: {next_open.strftime("%m/%d %H:%M")})'
            
            return {
                'status': 'CLOSED',
                'message': message,
                'next_change': next_open if 'next_open' in locals() else current_time + timedelta(hours=12),
                'is_trading_time': False
            }
