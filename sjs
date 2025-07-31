    # 일봉 데이터 컬럼명 수정 및 MACD 완전 구현
    
    def get_daily_data_fixed(self, symbol: str, days: int = 100) -> pd.DataFrame:
        """수정된 일봉 데이터 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010100"
        }
    
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol,
            "fid_input_date_1": start_date,
            "fid_input_date_2": end_date,
            "fid_period_div_code": "D",
            "fid_org_adj_prc": "0"
        }
    
        try:
            self.logger.info(f"📅 {symbol} 일봉 데이터 조회: {days}일간")
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
    
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                
                # 일봉 데이터 컬럼명 확인 및 출력
                self.logger.debug(f"일봉 데이터 컬럼: {df.columns.tolist()}")
                
                # 날짜 순으로 정렬
                if 'stck_bsop_date' in df.columns:
                    df = df.sort_values('stck_bsop_date').reset_index(drop=True)
                
                # 컬럼명 매핑 (일봉 → 분봉 형식으로 통일)
                column_mapping = {
                    'stck_clpr': 'stck_prpr',    # 종가 → 현재가
                    'stck_oprc': 'stck_oprc',    # 시가 (동일)
                    'stck_hgpr': 'stck_hgpr',    # 고가 (동일)
                    'stck_lwpr': 'stck_lwpr',    # 저가 (동일)
                    'acml_vol': 'cntg_vol',      # 누적거래량 → 거래량
                    'acml_tr_pbmn': 'acml_tr_pbmn'  # 누적거래대금
                }
                
                # 컬럼명 변경
                for old_col, new_col in column_mapping.items():
                    if old_col in df.columns:
                        df[new_col] = df[old_col]
                
                # 숫자형 변환
                numeric_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'cntg_vol']
                for col in numeric_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                
                # NaN 제거
                df = df.dropna(subset=['stck_prpr'])
                
                self.logger.info(f"✅ {symbol} 일봉 데이터 {len(df)}개 조회 완료")
                self.logger.debug(f"가격 범위: {df['stck_prpr'].min():,} ~ {df['stck_prpr'].max():,}")
                
                return df
            else:
                self.logger.warning(f"❌ {symbol} 일봉 데이터 없음")
                
        except Exception as e:
            self.logger.error(f"일봉 데이터 조회 실패 ({symbol}): {e}")
    
        return pd.DataFrame()
    
    def debug_daily_data_columns(self, symbol: str):
        """일봉 데이터 컬럼 구조 확인"""
        print(f"🔍 {symbol} 일봉 데이터 구조 분석")
        
        try:
            url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
            headers = {
                "content-type": "application/json",
                "authorization": f"Bearer {self.get_access_token()}",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "tr_id": "FHKST03010100"
            }
    
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
            params = {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": symbol,
                "fid_input_date_1": start_date,
                "fid_input_date_2": end_date,
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "0"
            }
    
            response = requests.get(url, headers=headers, params=params, timeout=15)
            data = response.json()
    
            print(f"📊 API 응답 구조:")
            print(f"  - rt_cd: {data.get('rt_cd')}")
            print(f"  - msg1: {data.get('msg1', 'N/A')}")
            
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                print(f"  - 데이터 개수: {len(df)}개")
                print(f"  - 컬럼 목록: {df.columns.tolist()}")
                
                if len(df) > 0:
                    print(f"\n📈 첫 번째 행 데이터:")
                    first_row = df.iloc[0]
                    for col in df.columns:
                        print(f"  {col}: {first_row[col]}")
                    
                    # 가격 관련 컬럼 찾기
                    price_cols = [col for col in df.columns if 'pr' in col.lower() or 'prc' in col.lower()]
                    print(f"\n💰 가격 관련 컬럼: {price_cols}")
                    
                    volume_cols = [col for col in df.columns if 'vol' in col.lower()]
                    print(f"📊 거래량 관련 컬럼: {volume_cols}")
            else:
                print("❌ output2 데이터 없음")
                
        except Exception as e:
            print(f"❌ 디버깅 실패: {e}")
    
    def test_macd_with_fixed_daily_data(self):
        """수정된 일봉 데이터로 MACD 테스트"""
        print("🧪 수정된 일봉 데이터로 MACD 테스트")
        print("="*60)
        
        for symbol in self.symbols:
            stock_name = self.get_stock_name(symbol)
            print(f"\n📊 {symbol}({stock_name}) 분석:")
            
            # 1. 컬럼 구조 먼저 확인
            print("🔍 컬럼 구조 확인:")
            self.debug_daily_data_columns(symbol)
            
            # 2. 수정된 일봉 데이터 조회
            print("\n📅 수정된 일봉 데이터 조회:")
            df = self.get_daily_data_fixed(symbol, days=100)
            
            if df.empty:
                print("❌ 일봉 데이터를 가져올 수 없습니다")
                continue
            
            print(f"✅ 일봉 데이터: {len(df)}일")
            print(f"가격 범위: {df['stck_prpr'].min():,} ~ {df['stck_prpr'].max():,}")
            print(f"최근 가격: {df['stck_prpr'].iloc[-1]:,}원")
            print(f"고유가격 수: {df['stck_prpr'].nunique()}개")
            
            if len(df) >= 35:
                # 3. MACD 계산
                print("\n📈 MACD 계산:")
                try:
                    df_with_macd = self.calculate_macd(df)
                    
                    # MACD 데이터 확인
                    if 'macd_line' in df_with_macd.columns:
                        print(f"✅ MACD 계산 성공")
                        
                        # 최근 5일 데이터 출력
                        print(f"\n📊 최근 5일 MACD 데이터:")
                        recent = df_with_macd.tail(5)
                        for i, row in recent.iterrows():
                            date = row.get('stck_bsop_date', f'Day{i}')
                            price = row['stck_prpr']
                            macd_line = row.get('macd_line', 0)
                            macd_signal = row.get('macd_signal', 0)
                            macd_hist = row.get('macd_histogram', 0)
                            cross = row.get('macd_cross', 0)
                            
                            cross_icon = ""
                            if cross == 1:
                                cross_icon = "🌟골든"
                            elif cross == -1:
                                cross_icon = "💀데드"
                            
                            print(f"  {date}: {price:,}원, MACD={macd_line:.4f}, Signal={macd_signal:.4f}, Hist={macd_hist:.4f} {cross_icon}")
                        
                        # 4. 골든크로스 분석
                        print(f"\n🎯 골든크로스 분석:")
                        macd_analysis = self.detect_macd_golden_cross(df_with_macd)
                        
                        for key, value in macd_analysis.items():
                            print(f"  {key}: {value}")
                        
                        # 5. 종합 신호 (만약 함수가 있다면)
                        if hasattr(self, 'calculate_enhanced_momentum_signals'):
                            print(f"\n🎯 종합 신호:")
                            try:
                                signals = self.calculate_enhanced_momentum_signals(df_with_macd)
                                print(f"  신호: {signals['signal']}")
                                print(f"  강도: {signals['strength']:.2f}")
                                if 'signal_components' in signals:
                                    print(f"  구성요소: {signals['signal_components']}")
                            except Exception as e:
                                print(f"  ❌ 종합 신호 계산 실패: {e}")
                    else:
                        print(f"❌ MACD 계산 실패 - macd_line 컬럼 없음")
                        
                except Exception as e:
                    print(f"❌ MACD 계산 오류: {e}")
                    import traceback
                    traceback.print_exc()
            else:
                print(f"❌ 데이터 부족: {len(df)} < 35일")
    
    def simple_macd_implementation(self, df: pd.DataFrame, price_col: str = 'stck_prpr') -> pd.DataFrame:
        """간단하고 안전한 MACD 구현"""
        try:
            if len(df) < 35 or price_col not in df.columns:
                return df
            
            # 가격 데이터 정리
            prices = df[price_col].astype(float).fillna(method='ffill')
            
            # EMA 계산
            ema12 = prices.ewm(span=12, adjust=False).mean()
            ema26 = prices.ewm(span=26, adjust=False).mean()
            
            # MACD 지표 계산
            df['macd_line'] = ema12 - ema26
            df['macd_signal'] = df['macd_line'].ewm(span=9, adjust=False).mean()
            df['macd_histogram'] = df['macd_line'] - df['macd_signal']
            
            # 골든크로스/데드크로스 감지
            df['macd_cross'] = 0
            for i in range(1, len(df)):
                current_macd = df['macd_line'].iloc[i]
                current_signal = df['macd_signal'].iloc[i]
                prev_macd = df['macd_line'].iloc[i-1]
                prev_signal = df['macd_signal'].iloc[i-1]
                
                if current_macd > current_signal and prev_macd <= prev_signal:
                    df.iloc[i, df.columns.get_loc('macd_cross')] = 1  # 골든크로스
                elif current_macd < current_signal and prev_macd >= prev_signal:
                    df.iloc[i, df.columns.get_loc('macd_cross')] = -1  # 데드크로스
            
            print(f"✅ MACD 계산 완료: {len(df)}개 데이터")
            return df
            
        except Exception as e:
            print(f"❌ MACD 계산 실패: {e}")
            return df
    
    def analyze_macd_signals_simple(self, df: pd.DataFrame) -> Dict:
        """간단한 MACD 신호 분석"""
        try:
            if 'macd_cross' not in df.columns or len(df) < 10:
                return {
                    'golden_cross': False,
                    'signal_strength': 0,
                    'current_trend': 'neutral'
                }
            
            # 최근 5일 내 골든크로스 확인
            recent_crosses = df['macd_cross'].tail(5)
            golden_cross = any(recent_crosses == 1)
            dead_cross = any(recent_crosses == -1)
            
            # 현재 상태
            latest = df.iloc[-1]
            macd_above_signal = latest['macd_line'] > latest['macd_signal']
            macd_above_zero = latest['macd_line'] > 0
            
            # 신호 강도 계산
            signal_strength = 0
            current_trend = 'neutral'
            
            if golden_cross:
                signal_strength = 2.0
                current_trend = 'bullish'
                
                if macd_above_zero:
                    signal_strength += 1.0
                
                # 골든크로스 발생 시점 확인
                cross_age = 999
                for i in range(len(df)-1, max(0, len(df)-6), -1):
                    if df['macd_cross'].iloc[i] == 1:
                        cross_age = len(df) - i - 1
                        break
                
                if cross_age <= 2:  # 최근 2일 내
                    signal_strength += 0.5
                    
            elif dead_cross:
                current_trend = 'bearish'
                signal_strength = -1.0
            elif macd_above_signal and macd_above_zero:
                current_trend = 'bullish'
                signal_strength = 1.0
            elif not macd_above_signal and not macd_above_zero:
                current_trend = 'bearish'
                signal_strength = -0.5
            
            return {
                'golden_cross': golden_cross,
                'signal_strength': signal_strength,
                'current_trend': current_trend,
                'macd_above_zero': macd_above_zero,
                'macd_above_signal': macd_above_signal,
                'recent_cross_age': cross_age if golden_cross else 999
            }
            
        except Exception as e:
            print(f"❌ MACD 신호 분석 실패: {e}")
            return {
                'golden_cross': False,
                'signal_strength': 0,
                'current_trend': 'neutral'
            }
    
    def complete_macd_test(self):
        """완전한 MACD 테스트"""
        print("🚀 완전한 MACD 시스템 테스트")
        print("="*60)
        
        for symbol in self.symbols:
            stock_name = self.get_stock_name(symbol)
            print(f"\n📊 {symbol}({stock_name}) 완전 분석:")
            
            # 1. 일봉 데이터 조회
            df = self.get_daily_data_fixed(symbol, days=100)
            
            if df.empty:
                print("❌ 데이터 조회 실패")
                continue
            
            print(f"📅 데이터: {len(df)}일, 가격 범위: {df['stck_prpr'].min():,}~{df['stck_prpr'].max():,}")
            
            if len(df) < 35:
                print(f"❌ 데이터 부족: {len(df)} < 35")
                continue
            
            # 2. MACD 계산
            df_with_macd = self.simple_macd_implementation(df)
            
            # 3. 신호 분석
            signals = self.analyze_macd_signals_simple(df_with_macd)
            
            print(f"🎯 MACD 분석 결과:")
            print(f"  골든크로스: {signals['golden_cross']}")
            print(f"  신호 강도: {signals['signal_strength']:.1f}")
            print(f"  현재 추세: {signals['current_trend']}")
            print(f"  MACD > 0: {signals['macd_above_zero']}")
            print(f"  MACD > Signal: {signals['macd_above_signal']}")
            
            if signals['golden_cross']:
                print(f"  🌟 골든크로스 {signals['recent_cross_age']}일 전 발생!")
            
            # 4. 투자 권고
            if signals['signal_strength'] >= 2.0:
                print(f"  💰 투자 권고: 강한 매수 신호")
            elif signals['signal_strength'] >= 1.0:
                print(f"  📈 투자 권고: 약한 매수 신호")
            elif signals['signal_strength'] <= -1.0:
                print(f"  📉 투자 권고: 매도 신호")
            else:
                print(f"  ⏸️ 투자 권고: 관망")
    
