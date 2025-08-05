    def get_minute_data(self, symbol: str, minutes: int = 240) -> pd.DataFrame:
        """분봉 데이터 조회"""
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice"
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_access_token()}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010200"
        }
    
        end_time = datetime.now().strftime("%H%M%S")
        params = {
            "fid_etc_cls_code": "",
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": symbol,
            "fid_input_hour_1": end_time,
            "fid_pw_data_incu_yn": "Y"
        }
    
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
    
            if data.get('output2'):
                df = pd.DataFrame(data['output2'])
                if not df.empty and 'stck_cntg_hour' in df.columns:
                    df['stck_cntg_hour'] = pd.to_datetime(df['stck_cntg_hour'], format='%H%M%S', errors='coerce')
                    numeric_cols = ['stck_prpr', 'stck_oprc', 'stck_hgpr', 'stck_lwpr', 'cntg_vol']
                    for col in numeric_cols:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors='coerce')
                    
                    # NaN 제거
                    df = df.dropna(subset=['stck_prpr'])
                    
                    if not df.empty:
                        self.logger.info(f"✅ {symbol} 분봉 데이터 {len(df)}개 조회 완료")
                        return df.sort_values('stck_cntg_hour').reset_index(drop=True)
                    else:
                        self.logger.warning(f"⚠️ {symbol} 분봉 데이터가 비어있음")
                else:
                    self.logger.warning(f"⚠️ {symbol} 분봉 데이터 구조 이상")
    
        except Exception as e:
            self.logger.error(f"분봉 데이터 조회 실패 ({symbol}): {e}")
    
        return pd.DataFrame()
