"""
디스코드 알림 모듈
"""
import requests
from datetime import datetime, timedelta
from typing import Optional


class DiscordNotifier:
    """디스코드 웹훅 알림 클래스"""
    
    def __init__(self, webhook_url: str, notify_on_trade: bool = True, 
                 notify_on_error: bool = True, notify_on_daily_summary: bool = True, 
                 logger=None):
        self.webhook_url = webhook_url
        self.notify_on_trade = notify_on_trade
        self.notify_on_error = notify_on_error
        self.notify_on_daily_summary = notify_on_daily_summary
        self.logger = logger
    
    def send_notification(self, title: str, message: str, color: int = 0x00ff00) -> bool:
        """디스코드 웹훅으로 알림 전송"""
        if not self.webhook_url:
            return False

        try:
            korea_now = datetime.now()
            utc_time = korea_now - timedelta(hours=9)
            embed = {
                "title": title,
                "description": message,
                "color": color,
                "timestamp": utc_time.isoformat() + "Z",
                "footer": {
                    "text": "하이브리드 자동매매 시스템"
                }
            }

            data = {"embeds": [embed]}

            response = requests.post(
                self.webhook_url,
                json=data,
                timeout=10
            )

            return response.status_code == 204

        except Exception as e:
            if self.logger:
                self.logger.error(f"디스코드 알림 오류: {e}")
            return False
    
    def notify_trade_success(self, action: str, symbol: str, quantity: int, 
                           price: int, order_no: str, stock_name: str = ""):
        """매매 성공 알림"""
        if not self.notify_on_trade:
            return

        action_emoji = "🛒" if action == "BUY" else "💸"
        color = 0x00ff00 if action == "BUY" else 0xff6600

        title = f"{action_emoji} {action} 주문 체결!"
        message = f"""
종목: {symbol} ({stock_name})
수량: {quantity}주
가격: {price:,}원
총액: {quantity * price:,}원
주문번호: {order_no}
시간: {datetime.now().strftime('%H:%M:%S')}
"""
        self.send_notification(title, message, color)
    
    def notify_trade_failure(self, action: str, symbol: str, error_msg: str, stock_name: str = ""):
        """매매 실패 알림"""
        if not self.notify_on_error:
            return

        title = f"❌ {action} 주문 실패"
        message = f"""
종목: {symbol} ({stock_name})
오류: {error_msg}
시간: {datetime.now().strftime('%H:%M:%S')}
"""
        self.send_notification(title, message, 0xff0000)
    
    def notify_daily_summary(self, total_trades: int, profit_loss: float, 
                           successful_trades: int, symbol_list: list = None):
        """일일 요약 알림"""
        if not self.notify_on_daily_summary:
            return

        title = "📊 일일 거래 요약"
        color = 0x00ff00 if profit_loss >= 0 else 0xff0000

        symbol_text = ""
        if symbol_list:
            symbol_text = f"거래 종목: {', '.join(symbol_list)}\n"

        message = f"""
총 거래 횟수: {total_trades}회
성공한 거래: {successful_trades}회
일일 수익률: {profit_loss:.2%}
{symbol_text}날짜: {datetime.now().strftime('%Y-%m-%d')}
"""
        self.send_notification(title, message, color)
    
    def notify_error(self, error_type: str, error_msg: str):
        """오류 알림"""
        if not self.notify_on_error:
            return

        title = f"⚠️ 시스템 오류: {error_type}"
        message = f"""
오류 내용: {error_msg}
시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_notification(title, message, 0xff0000)
    
    def notify_system_start(self, strategy_type: str, check_interval: int, symbols: list = None):
        """시스템 시작 알림"""
        symbol_text = ""
        if symbols:
            symbol_text = f"\n대상 종목: {', '.join(symbols)}"
        
        title = "🚀 자동매매 시스템 시작"
        message = f"""
전략: {strategy_type}
체크 간격: {check_interval}분{symbol_text}
시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_notification(title, message, 0x00ff00)
    
    def notify_system_stop(self, reason: str = "사용자 종료"):
        """시스템 종료 알림"""
        title = "⏹️ 자동매매 시스템 종료"
        message = f"""
종료 사유: {reason}
종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
        self.send_notification(title, message, 0xff6600)
    
    def notify_symbol_changes(self, added: set, removed: set, get_stock_name_func=None):
        """종목 변경 알림"""
        if not added and not removed:
            return
        
        message_parts = []
        
        if added:
            if get_stock_name_func:
                added_list = [f"{s}({get_stock_name_func(s)})" for s in added]
            else:
                added_list = list(added)
            message_parts.append(f"➕ 추가: {', '.join(added_list)}")
        
        if removed:
            if get_stock_name_func:
                removed_list = [f"{s}({get_stock_name_func(s)})" for s in removed]
            else:
                removed_list = list(removed)
            message_parts.append(f"➖ 제거: {', '.join(removed_list)}")
        
        if message_parts:
            title = "🔄 거래 종목 업데이트"
            message = f"""
백테스트 결과 업데이트로 인한 종목 변경

{chr(10).join(message_parts)}

시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
            self.send_notification(title, message, 0x0099ff)
