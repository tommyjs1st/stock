"""
주문 추적 및 체결 확인 시스템
trading_system/trading/order_tracker.py
"""
import json
import os
import time
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Optional


class OrderTracker:
    """주문 추적 및 관리 클래스"""
    
    def __init__(self, api_client, logger):
        self.api_client = api_client
        self.logger = logger
        self.pending_orders_file = "pending_orders.json"
        self.pending_orders = {}
        self.load_pending_orders()
    
    def load_pending_orders(self):
        """미체결 주문 로드"""
        try:
            if os.path.exists(self.pending_orders_file):
                with open(self.pending_orders_file, 'r', encoding='utf-8') as f:
                    self.pending_orders = json.load(f)
                self.logger.info(f"📋 미체결 주문 로드: {len(self.pending_orders)}개")
        except Exception as e:
            self.logger.error(f"미체결 주문 로드 실패: {e}")
            self.pending_orders = {}
    
    def save_pending_orders(self):
        """미체결 주문 저장"""
        try:
            with open(self.pending_orders_file, 'w', encoding='utf-8') as f:
                json.dump(self.pending_orders, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"미체결 주문 저장 실패: {e}")
    
    def add_pending_order(self, order_no: str, symbol: str, side: str, quantity: int, 
                         limit_price: int, strategy: str, stock_name: str = ""):
        """미체결 주문 추가 (Unknown 주문 번호 처리 개선)"""
        
        # Unknown 주문 번호인 경우 추적하지 않음
        if not order_no or order_no.lower() == 'unknown' or order_no == '':
            self.logger.warning(f"⚠️ {symbol}({stock_name}) 유효하지 않은 주문번호로 추적 제외: {order_no}")
            return
        
        order_info = {
            'order_no': order_no,
            'symbol': symbol,
            'stock_name': stock_name,
            'side': side,
            'quantity': quantity,
            'limit_price': limit_price,
            'strategy': strategy,
            'order_time': datetime.now().isoformat(),
            'check_count': 0,
            'last_check': None
        }
        
        self.pending_orders[order_no] = order_info
        self.save_pending_orders()
        
        self.logger.info(f"📝 미체결 주문 등록: {symbol}({stock_name}) {side} {quantity}주 @ {limit_price:,}원")
    
    
    def check_order_execution(self, order_no: str) -> Dict:
        """개별 주문 체결 상태 확인"""
        try:
            # KIS API 주문 체결 조회
            url = f"{self.api_client.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
            
            is_mock = "vts" in self.api_client.base_url.lower()
            tr_id = "VTTC8001R" if is_mock else "TTTC8001R"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_client.get_access_token()}",
                "appkey": self.api_client.app_key,
                "appsecret": self.api_client.app_secret,
                "tr_id": tr_id
            }
            
            # 오늘 날짜
            today = datetime.now().strftime("%Y%m%d")
            
            params = {
                "CANO": self.api_client.account_no.split('-')[0],
                "ACNT_PRDT_CD": self.api_client.account_no.split('-')[1],
                "INQR_STRT_DT": today,
                "INQR_END_DT": today,
                "SLL_BUY_DVSN_CD": "00",  # 전체
                "INQR_DVSN": "01",       # 일반조회
                "PDNO": "",              # 전체 종목
                "CCLD_DVSN": "01",       # 체결
                "ORD_GNO_BRNO": "",
                "ODNO": order_no,        # 특정 주문번호
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('rt_cd') == '0':
                    orders = data.get('output1', [])
                    
                    for order in orders:
                        if order.get('odno') == order_no:
                            # 체결 상태 확인
                            ccld_qty = int(order.get('tot_ccld_qty', 0))  # 총 체결수량
                            ord_qty = int(order.get('ord_qty', 0))        # 주문수량
                            ccld_amt = int(order.get('tot_ccld_amt', 0))  # 총 체결금액
                            
                            if ccld_qty > 0:
                                avg_price = ccld_amt // ccld_qty if ccld_qty > 0 else 0
                                
                                return {
                                    'status': 'executed' if ccld_qty == ord_qty else 'partial',
                                    'executed_qty': ccld_qty,
                                    'remaining_qty': ord_qty - ccld_qty,
                                    'avg_price': avg_price,
                                    'total_amount': ccld_amt
                                }
                            else:
                                return {'status': 'pending', 'executed_qty': 0}
                    
                    # 주문을 찾을 수 없는 경우 (취소되었거나 만료)
                    return {'status': 'not_found'}
                
        except Exception as e:
            self.logger.error(f"주문 {order_no} 체결 확인 오류: {e}")
        
        return {'status': 'error'}
    
    def check_all_pending_orders(self, position_manager, get_stock_name_func=None):
        """모든 미체결 주문 확인 (Unknown 처리 개선)"""
        if not self.pending_orders:
            return
        
        self.logger.info(f"🔍 미체결 주문 {len(self.pending_orders)}개 확인 중...")
        
        completed_orders = []
        
        for order_no, order_info in self.pending_orders.items():
            try:
                symbol = order_info['symbol']
                stock_name = order_info.get('stock_name', '') or (get_stock_name_func(symbol) if get_stock_name_func else symbol)
                
                # Unknown 주문 번호인 경우 바로 제거
                if not order_no or order_no.lower() == 'unknown' or order_no == '':
                    self.logger.warning(f"❌ {symbol}({stock_name}) 유효하지 않은 주문번호 제거: {order_no}")
                    completed_orders.append(order_no)
                    continue
                
                # 체결 확인
                result = self.check_order_execution(order_no)
                order_info['check_count'] += 1
                order_info['last_check'] = datetime.now().isoformat()
                
                if result['status'] == 'executed':
                    # 완전 체결
                    executed_qty = result['executed_qty']
                    avg_price = result['avg_price']
                    
                    self.logger.info(f"✅ {symbol}({stock_name}) 주문 체결 완료: "
                                   f"{executed_qty}주 @ {avg_price:,}원")
                    
                    # 포지션에 기록
                    if order_info['side'] == 'BUY':
                        position_manager.record_purchase(symbol, executed_qty, avg_price, order_info['strategy'])
                    else:
                        position_manager.record_sale(symbol, executed_qty, avg_price, order_info['strategy'])
                    
                    completed_orders.append(order_no)
                
                elif result['status'] == 'partial':
                    # 부분 체결
                    executed_qty = result['executed_qty']
                    remaining_qty = result['remaining_qty']
                    avg_price = result['avg_price']
                    
                    self.logger.info(f"⚡ {symbol}({stock_name}) 부분 체결: "
                                   f"{executed_qty}주 체결, {remaining_qty}주 미체결")
                    
                    # 체결된 부분만 포지션에 기록
                    if order_info['side'] == 'BUY':
                        position_manager.record_purchase(symbol, executed_qty, avg_price, order_info['strategy'])
                    else:
                        position_manager.record_sale(symbol, executed_qty, avg_price, order_info['strategy'])
                    
                    # 미체결 수량으로 주문 정보 업데이트
                    order_info['quantity'] = remaining_qty
                
                elif result['status'] == 'not_found':
                    # 주문이 취소되었거나 만료됨 (더 자세한 로그)
                    self.logger.warning(f"❌ {symbol}({stock_name}) 주문 취소/만료: {order_no} "
                                      f"(확인횟수: {order_info['check_count']})")
                    completed_orders.append(order_no)
                
                elif result['status'] == 'error':
                    # API 오류 발생
                    order_info['check_count'] += 1
                    if order_info['check_count'] >= 10:  # 10번 실패하면 포기
                        self.logger.error(f"❌ {symbol}({stock_name}) 주문 확인 포기: {order_no} "
                                        f"(10회 연속 실패)")
                        completed_orders.append(order_no)
                
                # 오래된 미체결 주문 취소 (24시간 경과)
                order_time = datetime.fromisoformat(order_info['order_time'])
                if datetime.now() - order_time > timedelta(hours=24):
                    self.logger.warning(f"⏰ {symbol}({stock_name}) 24시간 경과 주문 취소 시도")
                    self.cancel_order(order_no, symbol, stock_name)
                    completed_orders.append(order_no)
                
                time.sleep(0.2)  # API 호출 간격
                
            except Exception as e:
                self.logger.error(f"주문 {order_no} 확인 중 오류: {e}")
                # 5번 연속 오류 발생시 해당 주문 제거
                order_info['check_count'] += 1
                if order_info['check_count'] >= 5:
                    self.logger.error(f"❌ {symbol}({stock_name}) 주문 확인 오류로 제거: {order_no}")
                    completed_orders.append(order_no)
        
        # 완료된 주문 제거
        for order_no in completed_orders:
            if order_no in self.pending_orders:
                del self.pending_orders[order_no]
        
        if completed_orders:
            self.save_pending_orders()
            self.logger.info(f"🗂️ {len(completed_orders)}개 주문 완료 처리")
    
    def cancel_order(self, order_no: str, symbol: str, stock_name: str = "") -> bool:
        """주문 취소"""
        try:
            url = f"{self.api_client.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"
            
            is_mock = "vts" in self.api_client.base_url.lower()
            tr_id = "VTTC0803U" if is_mock else "TTTC0803U"
            
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.api_client.get_access_token()}",
                "appkey": self.api_client.app_key,
                "appsecret": self.api_client.app_secret,
                "tr_id": tr_id
            }
            
            data = {
                "CANO": self.api_client.account_no.split('-')[0],
                "ACNT_PRDT_CD": self.api_client.account_no.split('-')[1],
                "KRX_FWDG_ORD_ORGNO": "",
                "ORGN_ODNO": order_no,
                "ORD_DVSN": "00",
                "RVSE_CNCL_DVSN_CD": "02",  # 취소
                "ORD_QTY": "0",
                "ORD_UNPR": "0",
                "QTY_ALL_ORD_YN": "Y"
            }
            
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('rt_cd') == '0':
                    self.logger.info(f"✅ {symbol}({stock_name}) 주문 취소 성공: {order_no}")
                    return True
                else:
                    error_msg = result.get('msg1', 'Unknown error')
                    self.logger.error(f"❌ {symbol}({stock_name}) 주문 취소 실패: {error_msg}")
            
        except Exception as e:
            self.logger.error(f"❌ {symbol}({stock_name}) 주문 취소 오류: {e}")
        
        return False
    
    def get_pending_orders_summary(self) -> Dict:
        """미체결 주문 요약"""
        if not self.pending_orders:
            return {'total': 0, 'buy_orders': 0, 'sell_orders': 0}
        
        buy_count = sum(1 for order in self.pending_orders.values() if order['side'] == 'BUY')
        sell_count = len(self.pending_orders) - buy_count
        
        return {
            'total': len(self.pending_orders),
            'buy_orders': buy_count,
            'sell_orders': sell_count,
            'orders': list(self.pending_orders.values())
        }
