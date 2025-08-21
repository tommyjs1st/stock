# trading_system/monitoring/__init__.py
"""
모니터링 패키지
"""

# trading_system/monitoring/daily_performance.py
"""
일일 성과 추적 모듈
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class DailyPerformanceTracker:
    """일일 성과 추적 클래스"""
    
    def __init__(self, api_client, logger):
        self.api_client = api_client
        self.logger = logger
        self.performance_file = "daily_performance.json"
        self.trades_file = "daily_trades.json"
        
    def calculate_daily_summary(self) -> Dict:
        """일일 수익률 요약 계산 - 기존 보유 종목 포함"""
        try:
            # 현재 포트폴리오 상태
            holdings = self.api_client.get_all_holdings()
            account_data = self.api_client.get_account_balance()
            
            if not account_data:
                return {}
            
            output = account_data.get('output', {})
            cash = float(output.get('ord_psbl_cash', 0))
            
            # 보유 주식 평가
            total_stock_value = 0
            total_purchase_amount = 0
            total_profit_loss = 0
            position_details = []
            
            for symbol, position in holdings.items():
                stock_value = position['total_value']
                purchase_value = position['purchase_amount']
                profit_loss = stock_value - purchase_value
                profit_loss_pct = (profit_loss / purchase_value * 100) if purchase_value > 0 else 0
                
                total_stock_value += stock_value
                total_purchase_amount += purchase_value
                total_profit_loss += profit_loss
                
                position_details.append({
                    'symbol': symbol,
                    'stock_name': position['stock_name'],
                    'quantity': position['quantity'],
                    'avg_price': position['avg_price'],
                    'current_price': position['current_price'],
                    'total_value': stock_value,
                    'profit_loss': profit_loss,
                    'profit_loss_pct': profit_loss_pct
                })
            
            # 총 자산 및 수익률
            total_assets = cash + total_stock_value
            total_return_pct = (total_profit_loss / total_purchase_amount * 100) if total_purchase_amount > 0 else 0
            
            # 🆕 오늘 거래 내역 (프로그램 실행 중 + 기존 보유 정보)
            today_trades = self.get_today_trades()
            
            # 🆕 거래 내역이 없어도 기본 요약 생성
            summary = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'timestamp': datetime.now().isoformat(),
                'total_assets': total_assets,
                'cash': cash,
                'stock_value': total_stock_value,
                'total_profit_loss': total_profit_loss,
                'total_return_pct': total_return_pct,
                'position_count': len(holdings),
                'position_details': position_details,
                'today_trades': today_trades,
                'has_holdings': len(holdings) > 0,  # 보유 종목 존재 여부
                'program_trade_only': len(today_trades) == 0  # 프로그램 거래만 있는지
            }
            
            # 저장
            self.save_daily_performance(summary)
            
            return summary
            
        except Exception as e:
            self.logger.error(f"일일 요약 계산 실패: {e}")
            return {}
    
    def get_estimated_daily_trades_from_holdings(self, holdings: Dict) -> List[Dict]:
        """보유 종목으로부터 추정 거래 내역 생성 (참고용)"""
        try:
            estimated_trades = []
            today = datetime.now().strftime('%Y-%m-%d')
            
            for symbol, position in holdings.items():
                # 기존 보유 종목을 "참고용 거래"로 표시
                estimated_trades.append({
                    'timestamp': f"{today}T09:00:00",  # 장 시작 시간으로 가정
                    'symbol': symbol,
                    'stock_name': position['stock_name'],
                    'action': 'HOLD',  # 보유 중
                    'quantity': position['quantity'],
                    'price': position['avg_price'],
                    'amount': position['purchase_amount'],
                    'reason': '기존보유'
                })
            
            return estimated_trades
            
        except Exception as e:
            self.logger.error(f"추정 거래 내역 생성 실패: {e}")
            return []
    
    def get_today_trades(self) -> List[Dict]:
        """오늘 거래 내역 조회"""
        try:
            if not os.path.exists(self.trades_file):
                return []
            
            with open(self.trades_file, 'r', encoding='utf-8') as f:
                all_trades = json.load(f)
            
            today = datetime.now().strftime('%Y-%m-%d')
            today_trades = [trade for trade in all_trades 
                           if trade.get('timestamp', '').startswith(today)]
            
            return today_trades
            
        except Exception as e:
            self.logger.error(f"오늘 거래 내역 조회 실패: {e}")
            return []
    
    def record_trade(self, symbol: str, action: str, quantity: int, 
                    price: float, reason: str, stock_name: str = ""):
        """거래 기록"""
        trade_record = {
            'timestamp': datetime.now().isoformat(),
            'symbol': symbol,
            'stock_name': stock_name,
            'action': action,
            'quantity': quantity,
            'price': price,
            'amount': quantity * price,
            'reason': reason
        }
        
        try:
            trades = []
            if os.path.exists(self.trades_file):
                with open(self.trades_file, 'r', encoding='utf-8') as f:
                    trades = json.load(f)
            
            trades.append(trade_record)
            
            with open(self.trades_file, 'w', encoding='utf-8') as f:
                json.dump(trades, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            self.logger.error(f"거래 기록 실패: {e}")
    
    def save_daily_performance(self, summary: Dict):
        """일일 성과 저장"""
        try:
            performances = []
            if os.path.exists(self.performance_file):
                with open(self.performance_file, 'r', encoding='utf-8') as f:
                    performances = json.load(f)
            
            # 같은 날짜 데이터가 있으면 업데이트, 없으면 추가
            today = summary['date']
            updated = False
            
            for i, perf in enumerate(performances):
                if perf.get('date') == today:
                    performances[i] = summary
                    updated = True
                    break
            
            if not updated:
                performances.append(summary)
            
            # 최근 90일만 유지
            performances = performances[-90:]
            
            with open(self.performance_file, 'w', encoding='utf-8') as f:
                json.dump(performances, f, ensure_ascii=False, indent=2)
                
        except Exception as e:
            self.logger.error(f"일일 성과 저장 실패: {e}")
    
    def get_trend_analysis(self, days: int = 7) -> Dict:
        """수익률 트렌드 분석"""
        try:
            if not os.path.exists(self.performance_file):
                return {}
            
            with open(self.performance_file, 'r', encoding='utf-8') as f:
                performances = json.load(f)
            
            recent_performances = performances[-days:] if len(performances) >= days else performances
            
            if len(recent_performances) < 2:
                return {}
            
            # 트렌드 계산
            returns = [perf.get('total_return_pct', 0) for perf in recent_performances]
            assets = [perf.get('total_assets', 0) for perf in recent_performances]
            
            return {
                'avg_return': sum(returns) / len(returns),
                'best_day': max(returns),
                'worst_day': min(returns),
                'asset_growth': assets[-1] - assets[0] if len(assets) >= 2 else 0,
                'winning_days': len([r for r in returns if r > 0]),
                'total_days': len(returns)
            }
            
        except Exception as e:
            self.logger.error(f"트렌드 분석 실패: {e}")
            return {}

    def get_today_trade_summary(self) -> Dict:
        """당일 거래 요약 분석"""
        try:
            today_trades = self.get_today_trades()
            
            if not today_trades:
                return {
                    'total_trades': 0,
                    'buy_count': 0,
                    'sell_count': 0,
                    'traded_symbols': 0,
                    'traded_stocks': [],
                    'total_buy_amount': 0,
                    'total_sell_amount': 0,
                    'net_amount': 0
                }
            
            buy_trades = [t for t in today_trades if t['action'] == 'BUY']
            sell_trades = [t for t in today_trades if t['action'] == 'SELL']
            
            # 거래 종목 분석
            traded_symbols = list(set([t['symbol'] for t in today_trades]))
            traded_stocks = list(set([t.get('stock_name', t['symbol']) for t in today_trades]))
            
            # 거래 금액 분석
            total_buy_amount = sum(t['amount'] for t in buy_trades)
            total_sell_amount = sum(t['amount'] for t in sell_trades)
            
            return {
                'total_trades': len(today_trades),
                'buy_count': len(buy_trades),
                'sell_count': len(sell_trades),
                'traded_symbols': len(traded_symbols),
                'traded_stocks': traded_stocks,
                'total_buy_amount': total_buy_amount,
                'total_sell_amount': total_sell_amount,
                'net_amount': total_sell_amount - total_buy_amount,
                'trade_details': today_trades
            }
            
        except Exception as e:
            self.logger.error(f"당일 거래 요약 분석 실패: {e}")
            return {}

    def calculate_trade_performance(self, holdings: Dict) -> Dict:
        """당일 거래 성과 분석"""
        try:
            today_trades = self.get_today_trades()
            sell_trades = [t for t in today_trades if t['action'] == 'SELL']
            
            if not sell_trades:
                return {}
            
            profitable_trades = 0
            total_profit = 0
            
            for sell_trade in sell_trades:
                symbol = sell_trade['symbol']
                sell_price = sell_trade['price']
                quantity = sell_trade['quantity']
                
                # 현재 보유 종목에서 평균 매수가 찾기
                if symbol in holdings:
                    avg_buy_price = holdings[symbol].get('avg_price', 0)
                    trade_profit = (sell_price - avg_buy_price) * quantity
                    total_profit += trade_profit
                    
                    if sell_price > avg_buy_price:
                        profitable_trades += 1
            
            win_rate = (profitable_trades / len(sell_trades)) * 100 if sell_trades else 0
            
            return {
                'sell_count': len(sell_trades),
                'profitable_trades': profitable_trades,
                'win_rate': win_rate,
                'total_profit': total_profit
            }
            
        except Exception as e:
            self.logger.error(f"거래 성과 분석 실패: {e}")
            return {}
