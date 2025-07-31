import requests
import json
import time
from datetime import datetime
import yaml

class CompleteTradingTest:
    def __init__(self, config_path: str = "config.yaml"):
        """⚠️ 실전투자 환경 테스트 - 실제 돈이 거래됩니다!"""
        print("⚠️  경고: 실전투자 환경 테스트입니다!")
        print("⚠️  실제 돈이 거래되므로 매우 주의하세요!")
        print("=" * 60)
        
        confirm = input("실전투자 환경에서 테스트하시겠습니까? (YES 입력 필요): ")
        if confirm != "YES":
            print("테스트를 취소했습니다.")
            exit(0)
        
        print("📋 설정 파일 로드 중...")
        self.load_config(config_path)
        print("🔑 토큰 로드 중...")
        self.load_token()
    
    def load_config(self, config_path: str):
        """설정 파일 로드"""
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        self.app_key = config['kis']['app_key']
        self.app_secret = config['kis']['app_secret'] 
        self.base_url = config['kis']['base_url']
        self.account_no = config['kis']['account_no']
        
        # 실전투자 환경 확인
        self.is_real = "openapi.koreainvestment.com" in self.base_url
        
        if not self.is_real:
            print("❌ 실전투자 URL이 아닙니다!")
            print("config.yaml에서 다음으로 변경하세요:")
            print("base_url: 'https://openapi.koreainvestment.com:9443'")
            exit(1)
        
        print(f"✅ 설정 로드 완료")
        print(f"서버: {self.base_url}")
        print(f"환경: 🔴 실전투자")
        print(f"계좌: {self.account_no}")
        
        # 최종 확인
        final_confirm = input("\n마지막 확인: 실전 계좌로 거래하시겠습니까? (YES): ")
        if final_confirm != "YES":
            print("테스트를 취소했습니다.")
            exit(0)
    
    def load_token(self):
        """토큰 로드"""
        with open('token.json', 'r', encoding='utf-8') as f:
            token_data = json.load(f)
        
        self.access_token = token_data.get('access_token')
        expire_time_str = token_data.get('access_token_token_expired', '')
        print(f"✅ 토큰 로드 완료 (만료: {expire_time_str})")
    
    def choose_order_type(self, action: str, current_price: int):
        """주문 방식 선택 (시장가 vs 지정가)"""
        print(f"\n📋 {action} 주문 방식 선택")
        print("-" * 40)
        print("1. 시장가 주문 (즉시 체결)")
        print("   - 장점: 빠른 체결, 확실한 거래")
        print("   - 단점: 가격 변동 위험")
        print("2. 지정가 주문 (원하는 가격 지정)")
        print("   - 장점: 원하는 가격에 거래")
        print("   - 단점: 체결 안될 수 있음")
        print("3. 최유리 주문 (가장 유리한 가격)")
        print("   - 장점: 시장가보다 유리한 가격")
        print("   - 단점: 체결 확률 중간")
        print(f"\n현재가: {current_price:,}원")
        
        while True:
            choice = input("주문 방식을 선택하세요 (1-3): ")
            
            if choice == "1":
                # 시장가
                return {
                    'type': 'market',
                    'code': '01',
                    'price': '0',
                    'name': '시장가'
                }
            elif choice == "2":
                # 지정가
                if action == "매수":
                    suggested_price = current_price - 100  # 현재가보다 100원 낮게 제안
                    print(f"제안가격: {suggested_price:,}원 (현재가 -100원)")
                else:
                    suggested_price = current_price + 100  # 현재가보다 100원 높게 제안
                    print(f"제안가격: {suggested_price:,}원 (현재가 +100원)")
                
                while True:
                    try:
                        price_input = input(f"지정가를 입력하세요 (엔터: {suggested_price:,}원): ").strip()
                        if price_input == "":
                            order_price = suggested_price
                        else:
                            order_price = int(price_input)
                        
                        if order_price <= 0:
                            print("❌ 가격은 0보다 커야 합니다.")
                            continue
                        
                        return {
                            'type': 'limit',
                            'code': '00',
                            'price': str(order_price),
                            'name': f'지정가 {order_price:,}원'
                        }
                    except ValueError:
                        print("❌ 올바른 숫자를 입력해주세요.")
            
            elif choice == "3":
                # 최유리
                return {
                    'type': 'best',
                    'code': '03',
                    'price': '0',
                    'name': '최유리'
                }
            else:
                print("❌ 1, 2, 3 중에서 선택해주세요.")
    
    def get_current_price(self, symbol: str):
        """현재가 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100"
        }
        params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": symbol}
        
        try:
            response = requests.get(url, headers=headers, params=params, timeout=10)
            data = response.json()
            
            if data.get('rt_cd') == '0':
                current_price = int(data['output']['stck_prpr'])
                return current_price
            else:
                print(f"❌ 현재가 조회 실패: {data.get('msg1')}")
                return None
                
        except Exception as e:
            print(f"❌ 현재가 조회 오류: {e}")
            return None
    
    def get_account_balance(self):
        """실전투자 계좌 조회"""
        print(f"\n💰 실전투자 계좌 조회")
        print("-" * 50)
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "TTTC8434R"  # 실전투자용
        }
        
        # 실전투자용 파라미터
        params = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "AFHR_FLPR_YN": "N",        # 시간외단일가여부
            "OFL_YN": "",               # 오프라인여부
            "INQR_DVSN": "02",          # 조회구분
            "UNPR_DVSN": "01",          # 단가구분
            "FUND_STTL_ICLD_YN": "N",   # 펀드결제분포함여부
            "FNCG_AMT_AUTO_RDPT_YN": "N", # 융자금액자동상환여부
            "PRCS_DVSN": "01",          # 처리구분
            "CTX_AREA_FK100": "",       # 연속조회검색조건100
            "CTX_AREA_NK100": ""        # 연속조회키100
        }
        
        try:
            print(f"요청: TTTC8434R - {self.account_no}")
            response = requests.get(url, headers=headers, params=params, timeout=15)
            data = response.json()
            
            print(f"HTTP 상태: {response.status_code}")
            print(f"응답 코드: {data.get('rt_cd', 'Unknown')}")
            print(f"응답 메시지: {data.get('msg1', 'No message')}")
            
            if data.get('rt_cd') == '0':
                print("✅ 계좌 조회 성공!")
                
                # 예수금 정보
                output2 = data.get('output2', [])
                if output2:
                    cash_info = output2[0]
                    available_cash = int(cash_info.get('dnca_tot_amt', 0))
                    total_eval = int(cash_info.get('tot_evlu_amt', 0))
                    print(f"💰 예수금: {available_cash:,}원")
                    print(f"💎 총 평가금액: {total_eval:,}원")
                
                # 보유 종목 정보
                output1 = data.get('output1', [])
                holdings = [item for item in output1 if int(item.get('hldg_qty', 0)) > 0]
                
                if holdings:
                    print(f"📊 보유 종목 ({len(holdings)}개):")
                    total_profit = 0
                    for item in holdings:
                        symbol = item.get('pdno', '')
                        name = item.get('prdt_name', '')
                        qty = int(item.get('hldg_qty', 0))
                        avg_price = float(item.get('pchs_avg_pric', 0))
                        current_price = float(item.get('prpr', 0))
                        profit_rate = float(item.get('evlu_pfls_rt', 0))
                        profit_loss = int(item.get('evlu_pfls_amt', 0))
                        
                        print(f"  {symbol} ({name}): {qty}주")
                        print(f"    평균: {avg_price:,.0f}원 → 현재: {current_price:,.0f}원")
                        print(f"    손익: {profit_loss:,}원 ({profit_rate:+.2f}%)")
                        total_profit += profit_loss
                    
                    print(f"💹 총 손익: {total_profit:,}원")
                else:
                    print("📊 보유 종목 없음")
                
                return {
                    'success': True,
                    'available_cash': available_cash if output2 else 0,
                    'holdings': holdings
                }
            else:
                print(f"❌ 계좌 조회 실패: {data.get('msg1')}")
                return {'success': False, 'error': data.get('msg1')}
                
        except Exception as e:
            print(f"❌ 계좌 조회 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    def buy_order(self, symbol: str, test_amount: int = 50000):
        """🔴 실전투자 매수 주문 - 실제 돈이 거래됩니다!"""
        print(f"\n🔴 실전투자 매수 주문 - 실제 돈이 거래됩니다!")
        print("-" * 60)
        print(f"⚠️  주의: 이것은 실제 거래입니다!")
        print(f"⚠️  실제 돈 {test_amount:,}원이 사용됩니다!")
        print("-" * 60)
        
        # 1. 현재가 조회
        current_price = self.get_current_price(symbol)
        if not current_price:
            print("❌ 현재가 조회 실패")
            return False
        
        # 2. 주문 방식 선택
        order_info = self.choose_order_type("매수", current_price)
        
        # 3. 주문 수량 계산
        if order_info['type'] == 'limit':
            order_price = int(order_info['price'])
        else:
            order_price = current_price  # 시장가/최유리는 현재가 기준으로 계산
        
        quantity = test_amount // order_price
        if quantity == 0:
            print(f"❌ 주문 가능 수량 없음 (주문가: {order_price:,}원)")
            return False
        
        actual_amount = quantity * order_price
        print(f"\n📋 주문 정보:")
        print(f"   종목: {symbol}")
        print(f"   수량: {quantity}주")
        print(f"   주문방식: {order_info['name']}")
        if order_info['type'] == 'limit':
            print(f"   지정가: {order_price:,}원")
            print(f"   현재가: {current_price:,}원")
        print(f"   예상금액: {actual_amount:,}원")
        
        # 4. 3단계 확인
        print(f"\n🚨 실제 돈이 거래됩니다! 🚨")
        confirm1 = input("1단계 확인 - 실제 매수하시겠습니까? (YES): ")
        if confirm1 != 'YES':
            print("주문을 취소했습니다.")
            return False
        
        confirm2 = input(f"2단계 확인 - {symbol} {quantity}주를 {order_info['name']}으로 매수? (YES): ")
        if confirm2 != 'YES':
            print("주문을 취소했습니다.")
            return False
        
        confirm3 = input("3단계 최종확인 - 정말 실제 주문을 실행하시겠습니까? (CONFIRM): ")
        if confirm3 != 'CONFIRM':
            print("주문을 취소했습니다.")
            return False
        
        # 5. 실전투자 매수 주문
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "TTTC0802U"  # 실전투자 매수
        }
        
        data = {
            "CANO": self.account_no.split('-')[0],
            "ACNT_PRDT_CD": self.account_no.split('-')[1],
            "PDNO": symbol,
            "ORD_DVSN": order_info['code'],
            "ORD_QTY": str(quantity),
            "ORD_UNPR": order_info['price']
        }
        
        try:
            print(f"🔴 실제 주문 실행 중... ({order_info['name']})")
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=15)
            result = response.json()
            
            print(f"HTTP 상태: {response.status_code}")
            print(f"응답 코드: {result.get('rt_cd', 'Unknown')}")
            print(f"응답 메시지: {result.get('msg1', 'No message')}")
            
            if result.get('rt_cd') == '0':
                order_no = result.get('output', {}).get('odno', 'Unknown')
                print(f"✅ 실제 매수 주문 성공!")
                print(f"🔴 실제 돈이 사용되었습니다!")
                print(f"   주문번호: {order_no}")
                print(f"   종목: {symbol}")
                print(f"   수량: {quantity}주")
                print(f"   주문방식: {order_info['name']}")
                if order_info['type'] == 'limit':
                    print(f"   지정가: {order_price:,}원")
                return True
            else:
                print(f"❌ 매수 주문 실패: {result.get('msg1')}")
                return False
                
        except Exception as e:
            print(f"❌ 주문 실행 오류: {e}")
            return False
    
    def sell_order(self):
        """🔴 실전투자 매도 주문 - 실제 거래됩니다!"""
        print(f"\n🔴 실전투자 매도 주문 - 실제 거래됩니다!")
        print("-" * 60)
        
        # 1. 계좌 조회로 보유 종목 확인
        account_data = self.get_account_balance()
        if not account_data['success'] or not account_data['holdings']:
            print("❌ 매도할 보유 종목이 없습니다.")
            return False
        
        holdings = account_data['holdings']
        print(f"\n보유 종목 목록:")
        for i, item in enumerate(holdings, 1):
            symbol = item.get('pdno', '')
            name = item.get('prdt_name', '')
            qty = int(item.get('hldg_qty', 0))
            profit_rate = float(item.get('evlu_pfls_rt', 0))
            print(f"{i}. {symbol} ({name}): {qty}주 ({profit_rate:+.2f}%)")
        
        try:
            choice = int(input(f"매도할 종목 번호 (1-{len(holdings)}): ")) - 1
            if choice < 0 or choice >= len(holdings):
                print("❌ 잘못된 선택입니다.")
                return False
                
            selected = holdings[choice]
            symbol = selected.get('pdno', '')
            name = selected.get('prdt_name', '')
            quantity = int(selected.get('hldg_qty', 0))
            
            # 2. 현재가 조회
            current_price = self.get_current_price(symbol)
            if not current_price:
                return False
            
            # 3. 주문 방식 선택
            order_info = self.choose_order_type("매도", current_price)
            
            expected_amount = quantity * current_price
            print(f"\n📋 매도 정보:")
            print(f"   종목: {symbol} ({name})")
            print(f"   수량: {quantity}주")
            print(f"   현재가: {current_price:,}원")
            print(f"   주문방식: {order_info['name']}")
            if order_info['type'] == 'limit':
                order_price = int(order_info['price'])
                expected_amount = quantity * order_price
                print(f"   지정가: {order_price:,}원")
            print(f"   예상 수령액: 약 {expected_amount:,}원")
            
            # 4. 3단계 확인
            print(f"\n🚨 실제 주식이 매도됩니다! 🚨")
            confirm1 = input("1단계 확인 - 실제 매도하시겠습니까? (YES): ")
            if confirm1 != 'YES':
                print("매도를 취소했습니다.")
                return False
            
            confirm2 = input(f"2단계 확인 - {symbol} {quantity}주를 {order_info['name']}으로 매도? (YES): ")
            if confirm2 != 'YES':
                print("매도를 취소했습니다.")
                return False
            
            confirm3 = input("3단계 최종확인 - 정말 실제 매도를 실행하시겠습니까? (CONFIRM): ")
            if confirm3 != 'CONFIRM':
                print("매도를 취소했습니다.")
                return False
            
            # 5. 실전투자 매도 주문
            url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.access_token}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "TTTC0801U"  # 실전투자 매도
            }
            
            data = {
                "CANO": self.account_no.split('-')[0],
                "ACNT_PRDT_CD": self.account_no.split('-')[1],
                "PDNO": symbol,
                "ORD_DVSN": order_info['code'],
                "ORD_QTY": str(quantity),
                "ORD_UNPR": order_info['price']
            }
            
            print(f"🔴 실제 매도 주문 실행 중... ({order_info['name']})")
            response = requests.post(url, headers=headers, data=json.dumps(data), timeout=15)
            result = response.json()
            
            if result.get('rt_cd') == '0':
                order_no = result.get('output', {}).get('odno', 'Unknown')
                print(f"✅ 실제 매도 주문 성공!")
                print(f"🔴 실제 주식이 매도되었습니다!")
                print(f"   주문번호: {order_no}")
                print(f"   주문방식: {order_info['name']}")
                return True
            else:
                print(f"❌ 매도 주문 실패: {result.get('msg1')}")
                return False
                
        except Exception as e:
            print(f"❌ 매도 테스트 오류: {e}")
            return False
    
    def run_trading_test(self):
        """🔴 실전투자 매매 기능 테스트"""
        print("🔴 실전투자 매매 기능 테스트")
        print("⚠️  주의: 실제 돈과 주식이 거래됩니다!")
        print("=" * 60)
        
        # 1. 계좌 조회
        account_data = self.get_account_balance()
        if not account_data['success']:
            print("❌ 계좌 조회 실패로 테스트 중단")
            return
        
        # 2. 현재가 조회 테스트
        print(f"\n📈 현재가 조회 테스트")
        print("-" * 30)
        symbols = ['005930', '062040', '000660']
        for symbol in symbols:
            price = self.get_current_price(symbol)
            if price:
                print(f"✅ {symbol}: {price:,}원")
        
        # 3. 매매 테스트 메뉴
        while True:
            print(f"\n🔴 실전투자 매매 테스트 메뉴")
            print("⚠️  실제 돈이 거래됩니다!")
            print("-" * 40)
            print("1. 🔴 실제 매수 주문 (소액)")
            print("2. 🔴 실제 매도 주문")
            print("3. 💰 계좌 정보 조회")
            print("4. 🚪 종료")
            
            try:
                choice = input("선택하세요 (1-4): ")
                
                if choice == '1':
                    symbol = input("매수할 종목코드 (예: 005930): ")
                    amount = int(input("투자 금액 (예: 50000): "))
                    self.buy_order(symbol, amount)
                    
                elif choice == '2':
                    self.sell_order()
                    
                elif choice == '3':
                    self.get_account_balance()
                    
                elif choice == '4':
                    print("테스트를 종료합니다.")
                    break
                    
                else:
                    print("잘못된 선택입니다.")
                    
            except KeyboardInterrupt:
                print("\n테스트를 중단합니다.")
                break
            except Exception as e:
                print(f"❌ 오류: {e}")

if __name__ == "__main__":
    try:
        tester = CompleteTradingTest()
        tester.run_trading_test()
        
    except KeyboardInterrupt:
        print("\n\n사용자가 테스트를 중단했습니다.")
    except Exception as e:
        print(f"\n❌ 테스트 초기화 실패: {e}")
