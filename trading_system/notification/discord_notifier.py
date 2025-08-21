"""
디스코드 알림 모듈
"""
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List 


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
    
    def notify_daily_summary(self, summary: Dict, trend_analysis: Dict = None):
        """일일 요약 알림 - 거래 내역이 없어도 보유 종목 현황 전송"""
        if not self.notify_on_daily_summary or not self.webhook_url:
            return
        
        total_profit_loss = summary.get('total_profit_loss', 0)
        total_return_pct = summary.get('total_return_pct', 0)
        total_assets = summary.get('total_assets', 0)
        cash = summary.get('cash', 0)
        stock_value = summary.get('stock_value', 0)
        has_holdings = summary.get('has_holdings', False)
        program_trade_only = summary.get('program_trade_only', True)
        
        # 수익/손실에 따른 색상 및 이모지
        if total_profit_loss > 0:
            color = 0x00ff00  # 녹색
            profit_emoji = "📈"
        elif total_profit_loss < 0:
            color = 0xff0000  # 빨간색
            profit_emoji = "📉" 
        else:
            color = 0xffff00  # 노란색
            profit_emoji = "➖"
        
        title = f"{profit_emoji} 일일 포트폴리오 현황 ({summary.get('date')})"
        
        # 🆕 기본 정보 (보유 자산이 있으면 표시)
        if has_holdings:
            message = f"""
    💰 **총 자산**: {total_assets:,.0f}원
    💵 **현금**: {cash:,.0f}원
    📊 **주식평가액**: {stock_value:,.0f}원
    
    📈 **평가손익**: {total_profit_loss:+,.0f}원 ({total_return_pct:+.2f}%)
    📋 **보유종목**: {summary.get('position_count', 0)}개
    """
        else:
            message = f"""
    💰 **총 자산**: {total_assets:,.0f}원
    💵 **현금**: {cash:,.0f}원
    
    📋 **보유종목**: 없음
    """
        
        # 당일 거래 정보
        today_trades = summary.get('today_trades', [])
        if today_trades:
            buy_trades = [t for t in today_trades if t['action'] == 'BUY']
            sell_trades = [t for t in today_trades if t['action'] == 'SELL']
            
            # 거래 종목 리스트
            traded_stocks = list(set([t.get('stock_name', t['symbol']) for t in today_trades]))
            
            # 총 거래 금액
            total_buy_amount = sum(t['amount'] for t in buy_trades)
            total_sell_amount = sum(t['amount'] for t in sell_trades)
            
            message += f"\n**🔄 오늘 프로그램 거래**\n"
            message += f"📊 **거래종목**: {len(set([t['symbol'] for t in today_trades]))}개\n"
            message += f"🛒 **매수**: {len(buy_trades)}건 ({total_buy_amount:,.0f}원)\n"
            message += f"💸 **매도**: {len(sell_trades)}건 ({total_sell_amount:,.0f}원)\n"
            
            # 거래 내역 (최근 5건만)
            if len(today_trades) <= 5:
                message += f"\n**📝 거래 내역**\n"
            else:
                message += f"\n**📝 거래 내역** (최근 5건)\n"
            
            sorted_trades = sorted(today_trades, key=lambda x: x['timestamp'], reverse=True)
            
            for trade in sorted_trades[:5]:
                action_emoji = "🛒" if trade['action'] == 'BUY' else "💸"
                time_str = trade['timestamp'].split('T')[1][:5]
                stock_display = trade.get('stock_name', trade['symbol'])
                reason = trade.get('reason', '')
                
                message += f"{action_emoji} `{time_str}` **{stock_display}** {trade['quantity']}주 @ {trade['price']:,.0f}원"
                if reason:
                    message += f" ({reason})"
                message += "\n"
        
        else:
            # 🆕 거래 내역이 없는 경우
            if has_holdings:
                message += f"\n**🔄 오늘 프로그램 거래**: 없음 (기존 보유 종목만 유지)\n"
            else:
                message += f"\n**🔄 오늘 프로그램 거래**: 없음\n"
        
        # 🆕 보유 종목 현황 (거래가 없어도 표시)
        positions = summary.get('position_details', [])
        if positions:
            sorted_positions = sorted(positions, key=lambda x: x['profit_loss_pct'], reverse=True)
            
            message += f"\n**📊 현재 보유종목** ({len(positions)}개)\n"
            for i, pos in enumerate(sorted_positions):
                pnl_emoji = "📈" if pos['profit_loss_pct'] > 0 else "📉" if pos['profit_loss_pct'] < 0 else "➖"
                
                if i < 8:  # 최대 8개까지 표시
                    message += f"{pnl_emoji} **{pos['stock_name']}** {pos['quantity']}주 {pos['profit_loss']:+,.0f}원 ({pos['profit_loss_pct']:+.1f}%)\n"
                elif i == 8 and len(positions) > 8:
                    message += f"... 외 {len(positions) - 8}개 종목\n"
                    break
        
        # 트렌드 분석
        if trend_analysis and trend_analysis.get('total_days', 0) > 0:
            winning_rate = (trend_analysis.get('winning_days', 0) / 
                           max(trend_analysis.get('total_days', 1), 1) * 100)
            
            message += f"\n**📊 최근 7일 트렌드**\n"
            message += f"수익일: {trend_analysis.get('winning_days', 0)}/{trend_analysis.get('total_days', 0)}일 ({winning_rate:.1f}%)\n"
            message += f"평균수익률: {trend_analysis.get('avg_return', 0):+.2f}%\n"
            message += f"최고수익일: {trend_analysis.get('best_day', 0):+.2f}%\n"
            message += f"자산증감: {trend_analysis.get('asset_growth', 0):+,.0f}원\n"
        
        # 🆕 상태 메시지 추가
        if program_trade_only and has_holdings:
            message += f"\n💡 *오늘은 프로그램 거래가 없었지만 기존 보유 종목의 현재 상황을 알려드립니다.*\n"
        elif not has_holdings:
            message += f"\n💡 *현재 보유 종목이 없습니다. 내일 좋은 매수 기회를 찾아보겠습니다.*\n"
        
        message += f"\n⏰ 요약시간: {datetime.now().strftime('%H:%M:%S')}"
        
        return self.send_notification(title, message, color)

    # 🆕 거래가 많은 날을 위한 간소화된 요약 (선택사항)
    def notify_daily_summary_compact(self, summary: Dict, trend_analysis: Dict = None):
        """간소화된 일일 요약 (거래가 많을 때 사용)"""
        if not self.notify_on_daily_summary or not self.webhook_url:
            return
        
        total_profit_loss = summary.get('total_profit_loss', 0)
        total_return_pct = summary.get('total_return_pct', 0)
        
        color = 0x00ff00 if total_profit_loss > 0 else 0xff0000 if total_profit_loss < 0 else 0xffff00
        profit_emoji = "📈" if total_profit_loss > 0 else "📉" if total_profit_loss < 0 else "➖"
        
        title = f"{profit_emoji} 일일 요약 ({summary.get('date')})"
        
        today_trades = summary.get('today_trades', [])
        buy_count = len([t for t in today_trades if t['action'] == 'BUY'])
        sell_count = len([t for t in today_trades if t['action'] == 'SELL'])
        traded_symbols = len(set([t['symbol'] for t in today_trades]))
        
        message = f"""
    💰 **자산**: {summary.get('total_assets', 0):,.0f}원
    📈 **손익**: {total_profit_loss:+,.0f}원 ({total_return_pct:+.2f}%)
    
    🔄 **거래**: {len(today_trades)}건 ({traded_symbols}개 종목)
    🛒 매수 {buy_count}건 | 💸 매도 {sell_count}건
    📋 **보유**: {summary.get('position_count', 0)}개 종목
    """
        
        return self.send_notification(title, message, color)
    
    def notify_system_stop(self, reason: str = "사용자 종료"):
        """시스템 종료 알림 - 강제 실행"""
        title = "⏹️ 자동매매 시스템 종료"
        message = f"""
    종료 사유: {reason}
    종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
    """
        # 웹훅 URL이 있으면 강제로 알림 전송
        if self.webhook_url and self.webhook_url.strip():
            result = self.send_notification(title, message, 0xff6600)
            if self.logger:
                if result:
                    self.logger.info("✅ Discord 종료 알림 전송 성공")
                else:
                    self.logger.error("❌ Discord 종료 알림 전송 실패")
            return result
        else:
            if self.logger:
                self.logger.warning("⚠️ Discord 웹훅 URL이 설정되지 않음")
            return False

    
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
