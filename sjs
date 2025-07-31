    def process_buy_for_symbol_fixed(self, symbol: str):
        """개선된 개별 종목 매수 처리"""
        stock_name = self.get_stock_name(symbol)
        
        # 현재 보유 여부 확인
        current_position = self.positions.get(symbol, {})
        has_position = current_position.get('quantity', 0) > 0
        
        self.logger.info(f"🔍 {symbol}({stock_name}) 매수 분석 시작")
        
        # 매수 가능 여부 확인 (보유 중이어도 추가 매수 가능한지 체크)
        can_buy, buy_reason = self.can_purchase_symbol(symbol)
        
        if not can_buy:
            self.logger.info(f"🚫 {symbol} - {buy_reason}")
            return
        
        if has_position:
            self.logger.info(f"📌 {symbol} - 이미 보유 중이지만 추가 매수 검토")
        
        # 분봉 데이터 조회
        df = self.get_minute_data(symbol)
        if df.empty:
            self.logger.warning(f"{symbol}({stock_name}) - 데이터 없음")
            return
        
        # 전략에 따른 신호 계산
        optimal_strategy = self.strategy_map.get(symbol, 'momentum')
        signals = self.calculate_signals_by_strategy(symbol, df, optimal_strategy)
        
        current_price = signals['current_price']
        
        self.logger.info(f"📊 {symbol}({stock_name}) 매수 분석 결과:")
        self.logger.info(f"  - 전략: {optimal_strategy}")
        self.logger.info(f"  - 신호: {signals['signal']}")
        self.logger.info(f"  - 강도: {signals['strength']:.2f}")
        self.logger.info(f"  - 현재가: {current_price:,}원")
        self.logger.info(f"  - 보유 여부: {'예' if has_position else '아니오'}")
        
        # 매수 신호 처리
        if signals['signal'] == 'BUY':
            quantity = self.calculate_position_size(symbol, current_price, signals['strength'])
            
            if quantity > 0:
                order_strategy = self.determine_order_strategy(signals['strength'], 'BUY')
                
                action_type = "추가 매수" if has_position else "신규 매수"
                self.logger.info(f"💰 {symbol} {action_type} 실행: {quantity}주 ({order_strategy})")
                
                result = self.place_order_with_strategy(symbol, 'BUY', quantity, order_strategy)
                
                if result['success']:
                    executed_price = result.get('limit_price', current_price)
                    self.position_manager.record_purchase(
                        symbol, quantity, executed_price, optimal_strategy
                    )
                    self.logger.info(f"✅ {symbol} {action_type} 완료: {quantity}주 @ {executed_price:,}원")
                    
                    # 포지션 업데이트
                    if has_position:
                        # 기존 보유량에 추가
                        old_quantity = current_position['quantity']
                        old_avg_price = current_position['avg_price']
                        new_total_quantity = old_quantity + quantity
                        new_avg_price = ((old_avg_price * old_quantity) + (executed_price * quantity)) / new_total_quantity
                        
                        self.positions[symbol]['quantity'] = new_total_quantity
                        self.positions[symbol]['avg_price'] = new_avg_price
                    else:
                        # 신규 포지션 생성
                        self.positions[symbol] = {
                            'quantity': quantity,
                            'avg_price': executed_price,
                            'current_price': current_price,
                            'profit_loss': 0
                        }
            else:
                self.logger.warning(f"⚠️ {symbol} - 매수 수량이 0입니다.")
        else:
            self.logger.info(f"📉 {symbol} - 매수 신호 없음 ({signals['signal']})")
    
    # 문제 2: process_buy_signals에서 로깅 부족
    def process_buy_signals_verbose(self):
        """상세 로깅이 포함된 매수 신호 처리"""
        self.logger.info("🛒 매수 신호 처리 시작")
        self.logger.info(f"📋 분석 대상 종목: {self.symbols}")
        
        if not self.symbols:
            self.logger.warning("❌ 분석할 종목이 없습니다")
            return
        
        for i, symbol in enumerate(self.symbols, 1):
            try:
                self.logger.info(f"🔍 [{i}/{len(self.symbols)}] {symbol} 매수 분석 중...")
                self.process_buy_for_symbol_fixed(symbol)
                time.sleep(0.5)  # API 호출 간격
            except Exception as e:
                self.logger.error(f"❌ {symbol} 매수 처리 오류: {e}")
        
        self.logger.info("✅ 매수 신호 처리 완료")
    
    # 문제 3: 거래 사이클에서 매수 처리가 제대로 호출되지 않을 수 있음
    def run_trading_cycle_improved_debug(self):
        """디버깅이 강화된 거래 사이클"""
        if not self.check_risk_management():
            self.logger.warning("리스크 관리 조건 위반 - 거래 중단")
            return
    
        self.logger.info("🔄 개선된 거래 사이클 시작")
        
        try:
            # 1. 모든 포지션 업데이트 (매도용)
            self.logger.info("1️⃣ 포지션 업데이트 중...")
            self.update_all_positions()
            
            # 2. 매도 처리 우선 (모든 보유 종목)
            self.logger.info("2️⃣ 매도 신호 처리 중...")
            if hasattr(self, 'all_positions') and self.all_positions:
                self.logger.info(f"   매도 분석 대상: {len(self.all_positions)}개 종목")
                self.process_sell_signals()
            else:
                self.logger.info("   보유 종목 없음 - 매도 처리 건너뛰기")
            
            # 3. 매수 처리 (백테스트 선정 종목) - 강화된 로깅
            self.logger.info("3️⃣ 매수 신호 처리 중...")
            self.logger.info(f"   매수 분석 대상: {self.symbols}")
            
            # 현재 상황 체크
            available_cash = self.get_available_cash()
            self.logger.info(f"   💵 현재 가용 자금: {available_cash:,}원")
            
            if available_cash <= 0:
                self.logger.warning("   ⚠️ 가용 자금 부족 - 매수 건너뛰기")
            else:
                self.process_buy_signals_verbose()
            
            # 4. 성과 데이터 저장
            self.logger.info("4️⃣ 성과 데이터 저장 중...")
            self.save_performance_data()
            
            self.logger.info("✅ 거래 사이클 완료")
            
        except Exception as e:
            self.logger.error(f"거래 사이클 실행 중 오류: {e}")
            import traceback
            self.logger.error(f"상세 오류:\n{traceback.format_exc()}")
    
    # 가용 자금 확인 함수 추가
    def get_available_cash(self) -> float:
        """가용 자금 조회"""
        try:
            account_data = self.get_account_balance()
            if account_data and account_data.get('output'):
                available_cash = float(account_data['output'].get('ord_psbl_cash', 0))
                return available_cash
        except Exception as e:
            self.logger.error(f"가용 자금 조회 실패: {e}")
        return 0
    
    # 문제 4: can_purchase_symbol 함수가 너무 엄격할 수 있음
    def can_purchase_symbol_debug(self, symbol: str) -> tuple[bool, str]:
        """디버깅이 강화된 종목 매수 가능 여부 확인"""
        
        self.logger.debug(f"🔍 {symbol} 매수 가능 여부 확인 중...")
        
        # 1. 현재 보유 수량 확인
        current_position = self.positions.get(symbol, {})
        current_quantity = current_position.get('quantity', 0)
        
        self.logger.debug(f"   현재 보유: {current_quantity}주 / 최대: {self.max_quantity_per_symbol}주")
        
        if current_quantity >= self.max_quantity_per_symbol:
            reason = f"최대 보유 수량 초과 ({current_quantity}/{self.max_quantity_per_symbol}주)"
            self.logger.debug(f"   ❌ {reason}")
            return False, reason
        
        # 2. 매수 횟수 제한 확인
        history = self.position_manager.position_history.get(symbol, {})
        purchase_count = history.get('purchase_count', 0)
        
        self.logger.debug(f"   매수 횟수: {purchase_count}회 / 최대: {self.max_purchases_per_symbol}회")
        
        if purchase_count >= self.max_purchases_per_symbol:
            reason = f"최대 매수 횟수 초과 ({purchase_count}/{self.max_purchases_per_symbol}회)"
            self.logger.debug(f"   ❌ {reason}")
            return False, reason
        
        # 3. 재매수 금지 기간 확인
        last_purchase_time = history.get('last_purchase_time')
        if last_purchase_time:
            last_time = datetime.fromisoformat(last_purchase_time)
            time_since_last = datetime.now() - last_time
            hours_since_last = time_since_last.total_seconds() / 3600
            
            self.logger.debug(f"   마지막 매수: {hours_since_last:.1f}시간 전 / 금지기간: {self.purchase_cooldown_hours}시간")
            
            if time_since_last < timedelta(hours=self.purchase_cooldown_hours):
                remaining_hours = self.purchase_cooldown_hours - hours_since_last
                reason = f"재매수 금지 기간 중 (남은 시간: {remaining_hours:.1f}시간)"
                self.logger.debug(f"   ❌ {reason}")
                return False, reason
        
        self.logger.debug(f"   ✅ 매수 가능")
        return True, "매수 가능"
    
    # 임시 테스트 함수
    def test_buy_analysis(self):
        """매수 분석 테스트"""
        self.logger.info("🧪 매수 분석 테스트 시작")
        
        for symbol in self.symbols:
            self.logger.info(f"\n{'='*50}")
            self.logger.info(f"🔍 {symbol} 테스트")
            self.logger.info(f"{'='*50}")
            
            # 1. 매수 가능 여부 확인
            can_buy, reason = self.can_purchase_symbol_debug(symbol)
            self.logger.info(f"매수 가능: {can_buy} - {reason}")
            
            # 2. 현재 포지션 확인
            position = self.positions.get(symbol, {})
            self.logger.info(f"현재 포지션: {position}")
            
            # 3. 분봉 데이터 확인
            df = self.get_minute_data(symbol)
            self.logger.info(f"분봉 데이터: {len(df)}개 봉")
            
            if not df.empty:
                # 4. 신호 계산
                strategy = self.strategy_map.get(symbol, 'momentum')
                signals = self.calculate_signals_by_strategy(symbol, df, strategy)
                self.logger.info(f"신호: {signals}")
                
                # 5. 매수 시뮬레이션
                if signals['signal'] == 'BUY':
                    quantity = self.calculate_position_size(symbol, signals['current_price'], signals['strength'])
                    self.logger.info(f"계산된 매수 수량: {quantity}주")
    
    # 실제 적용을 위한 함수 교체
    def apply_buy_analysis_fix(self):
        """매수 분석 수정사항 적용"""
        
        # 기존 함수들을 수정된 버전으로 교체
        self.process_buy_for_symbol = self.process_buy_for_symbol_fixed
        self.process_buy_signals = self.process_buy_signals_verbose
        self.can_purchase_symbol = self.can_purchase_symbol_debug
        self.run_trading_cycle_improved = self.run_trading_cycle_improved_debug
        
        self.logger.info("✅ 매수 분석 수정사항 적용 완료")
    
