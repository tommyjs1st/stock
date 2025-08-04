    
    def get_stock_data_with_debug(self, stock_code: str, period: str = "D", count: int = 100) -> pd.DataFrame:
        """
        디버깅이 포함된 주식 데이터 조회 메서드
        """
        print(f"🚀 주식 데이터 조회 시작 - 종목: {stock_code}")
        
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010100"
        }
    
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
            "fid_input_date_1": "",
            "fid_input_date_2": "",
            "fid_period_div_code": period,
            "fid_org_adj_prc": "0"
        }
    
        print(f"📡 요청 정보:")
        print(f"  URL: {url}")
        print(f"  Headers: {json.dumps(headers, indent=2, ensure_ascii=False)}")
        print(f"  Params: {json.dumps(params, indent=2, ensure_ascii=False)}")
    
        try:
            print(f"📞 API 호출 중...")
            response = requests.get(url, headers=headers, params=params)
            
            # 모든 응답 정보 로깅
            log_api_response_detailed(response, "stock_data", stock_code)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    
                    print(f"✅ API 호출 성공!")
                    print(f"📊 응답 데이터 키들: {list(data.keys()) if isinstance(data, dict) else '딕셔너리가 아님'}")
                    
                    if 'output2' in data and data['output2']:
                        print(f"📈 차트 데이터 개수: {len(data['output2'])}")
                        
                        df = pd.DataFrame(data['output2'])
                        print(f"📋 DataFrame 생성 완료 - 크기: {df.shape}")
                        print(f"📋 컬럼들: {list(df.columns)}")
                        
                        # 데이터 처리 과정 상세 로깅
                        print(f"🔄 데이터 처리 시작...")
                        
                        # 컬럼명 변경 및 데이터 타입 변환
                        df = df.rename(columns={
                            'stck_bsop_date': 'date',
                            'stck_oprc': 'open',
                            'stck_hgpr': 'high',
                            'stck_lwpr': 'low',
                            'stck_clpr': 'close',
                            'acml_vol': 'volume'
                        })
                        print(f"✅ 컬럼명 변경 완료")
    
                        # 필요한 컬럼만 선택
                        required_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
                        missing_columns = [col for col in required_columns if col not in df.columns]
                        
                        if missing_columns:
                            print(f"❌ 필수 컬럼 누락: {missing_columns}")
                            print(f"📋 현재 컬럼들: {list(df.columns)}")
                            return pd.DataFrame()
                        
                        df = df[required_columns].copy()
                        print(f"✅ 필수 컬럼 선택 완료")
    
                        # 데이터 타입 변환
                        print(f"🔄 데이터 타입 변환 중...")
                        for col in ['open', 'high', 'low', 'close', 'volume']:
                            before_type = df[col].dtype
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                            after_type = df[col].dtype
                            print(f"  {col}: {before_type} → {after_type}")
    
                        df['date'] = pd.to_datetime(df['date'])
                        df = df.sort_values('date').reset_index(drop=True)
    
                        # 최근 count개만 선택
                        original_length = len(df)
                        df = df.tail(count).reset_index(drop=True)
                        final_length = len(df)
                        
                        print(f"✅ 데이터 처리 완료!")
                        print(f"📊 처리 결과: {original_length}개 → {final_length}개")
                        print(f"📅 데이터 기간: {df['date'].min()} ~ {df['date'].max()}")
                        
                        # 샘플 데이터 출력
                        print(f"📋 최근 3일 데이터:")
                        print(df.tail(3).to_string())
    
                        return df
                    else:
                        print(f"❌ output2 데이터가 없거나 비어있음")
                        if 'output2' in data:
                            print(f"📊 output2 타입: {type(data['output2'])}")
                            print(f"📊 output2 길이: {len(data['output2']) if isinstance(data['output2'], list) else 'N/A'}")
                        return pd.DataFrame()
                        
                except json.JSONDecodeError as e:
                    print(f"❌ JSON 파싱 오류: {e}")
                    return pd.DataFrame()
                except Exception as e:
                    print(f"❌ 데이터 처리 오류: {e}")
                    return pd.DataFrame()
            else:
                print(f"❌ API 호출 실패 - 상태코드: {response.status_code}")
                return pd.DataFrame()
    
        except Exception as e:
            print(f"❌ 전체 프로세스 오류: {e}")
            return pd.DataFrame()
