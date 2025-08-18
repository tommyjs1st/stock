import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import requests
import json
import time
import os
from datetime import datetime
from dotenv import load_dotenv
from typing import Dict, List, Tuple
import logging
import warnings
warnings.filterwarnings('ignore')

load_dotenv()


def log_api_response_detailed(response, api_name, stock_code=None, save_to_file=True):
    """
    KIS API 응답을 상세히 로깅하는 함수 (백테스트용)
    
    Args:
        response: requests.Response 객체
        api_name: API 이름 (예: "stock_data", "token")
        stock_code: 종목코드 (선택사항)
        save_to_file: 파일로 저장할지 여부
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    print("🔍" + "="*70)
    print(f"📡 KIS API 응답 상세 분석 - {api_name}")
    print(f"🕐 시간: {timestamp}")
    if stock_code:
        print(f"📈 종목코드: {stock_code}")
    print("="*70)
    
    # 1. 기본 응답 정보
    print("📊 [기본 응답 정보]")
    print(f"  ✅ 상태코드: {response.status_code}")
    print(f"  🌐 요청 URL: {response.url}")
    print(f"  ⏱️ 응답시간: {response.elapsed.total_seconds():.3f}초")
    print(f"  📦 응답크기: {len(response.content):,} bytes")
    print(f"  🔤 인코딩: {response.encoding}")
    
    # 2. 요청 헤더 정보
    print("\n📋 [요청 헤더 정보]")
    request_headers = response.request.headers
    for key, value in request_headers.items():
        # 민감한 정보는 마스킹
        if key.lower() in ['authorization', 'appkey', 'appsecret']:
            masked_value = value[:10] + "***" if len(value) > 10 else "***"
            print(f"  {key}: {masked_value}")
        else:
            print(f"  {key}: {value}")
    
    # 3. 응답 헤더 정보
    print("\n📨 [응답 헤더 정보]")
    for key, value in response.headers.items():
        print(f"  {key}: {value}")
    
    # 4. Raw 응답 본문
    print("\n📄 [Raw 응답 본문]")
    print("-" * 50)
    try:
        raw_text = response.text
        print(f"응답 길이: {len(raw_text)}자")
        
        # 처음 1000자만 표시
        if len(raw_text) <= 1000:
            print(raw_text)
        else:
            print(raw_text[:1000])
            print(f"\n... (총 {len(raw_text)}자 중 1000자만 표시됨)")
            
        # 한글이 포함되어 있는지 확인
        korean_chars = sum(1 for c in raw_text if ord(c) >= 0xAC00 and ord(c) <= 0xD7A3)
        if korean_chars > 0:
            print(f"📝 한글 문자 {korean_chars}개 포함됨")
            
    except Exception as e:
        print(f"❌ Raw 텍스트 읽기 오류: {e}")
    
    # 5. JSON 파싱 및 분석
    print("\n🔍 [JSON 파싱 결과]")
    print("-" * 50)
    try:
        json_data = response.json()
        
        # JSON 기본 구조
        print(f"📊 JSON 타입: {type(json_data)}")
        
        if isinstance(json_data, dict):
            print(f"📋 최상위 키들: {list(json_data.keys())}")
            
            # 각 키별 상세 정보
            for key, value in json_data.items():
                print(f"\n🔑 키: '{key}'")
                print(f"   타입: {type(value)}")
                
                if isinstance(value, list):
                    print(f"   리스트 길이: {len(value)}")
                    if value and isinstance(value[0], dict):
                        print(f"   첫 번째 항목 키들: {list(value[0].keys())}")
                elif isinstance(value, dict):
                    print(f"   딕셔너리 키들: {list(value.keys())}")
                else:
                    # 문자열이나 숫자인 경우 값 표시
                    str_value = str(value)
                    if len(str_value) <= 100:
                        print(f"   값: {value}")
                    else:
                        print(f"   값: {str_value[:100]}... (길이: {len(str_value)})")
        
        # 예쁘게 포맷된 JSON 출력
        print(f"\n📝 [포맷된 JSON 출력]")
        print("-" * 50)
        formatted_json = json.dumps(json_data, indent=2, ensure_ascii=False)
        
        if len(formatted_json) <= 2000:
            print(formatted_json)
        else:
            print(formatted_json[:2000])
            print(f"\n... (총 {len(formatted_json)}자 중 2000자만 표시됨)")
        
        # KIS API 특화 분석
        print(f"\n🎯 [KIS API 특화 분석]")
        print("-" * 50)
        
        # rt_cd 확인 (응답 코드)
        if 'rt_cd' in json_data:
            rt_cd = json_data['rt_cd']
            print(f"📊 응답코드(rt_cd): {rt_cd}")
            if rt_cd == "0":
                print("   ✅ 성공")
            else:
                print("   ❌ 실패")
        
        # 메시지 확인
        message_fields = ['msg1', 'msg_cd', 'message', 'error_description']
        for field in message_fields:
            if field in json_data:
                print(f"📝 {field}: {json_data[field]}")
        
        # output 데이터 분석
        if 'output' in json_data:
            output = json_data['output']
            print(f"📈 output 타입: {type(output)}")
            
            if isinstance(output, list):
                print(f"📊 output 리스트 길이: {len(output)}")
                if output:
                    print(f"📋 첫 번째 항목: {json.dumps(output[0], indent=2, ensure_ascii=False)}")
            elif isinstance(output, dict):
                print(f"📋 output 키들: {list(output.keys())}")
                print(f"📋 output 내용: {json.dumps(output, indent=2, ensure_ascii=False)}")
        
        # output2 데이터 분석 (차트 데이터용)
        if 'output2' in json_data:
            output2 = json_data['output2']
            print(f"📈 output2 타입: {type(output2)}")
            
            if isinstance(output2, list):
                print(f"📊 output2 리스트 길이: {len(output2)}")
                if output2:
                    print(f"📋 첫 번째 차트 데이터: {json.dumps(output2[0], indent=2, ensure_ascii=False)}")
    
    except json.JSONDecodeError as e:
        print(f"❌ JSON 파싱 실패: {e}")
        print("📄 응답이 JSON 형식이 아닙니다.")
        
        # HTML 응답인지 확인
        if response.text.strip().startswith('<'):
            print("🌐 HTML 응답으로 보입니다.")
            print("처음 500자:")
            print(response.text[:500])
    
    except Exception as e:
        print(f"❌ JSON 분석 중 오류: {e}")
    
    # 6. 파일 저장
    if save_to_file:
        try:
            log_dir = "api_debug_logs"
            os.makedirs(log_dir, exist_ok=True)
            
            if stock_code:
                filename = f"debug_{api_name}_{stock_code}_{timestamp}.json"
            else:
                filename = f"debug_{api_name}_{timestamp}.json"
            
            filepath = os.path.join(log_dir, filename)
            
            # 디버그 데이터 구성
            debug_data = {
                "timestamp": timestamp,
                "api_name": api_name,
                "stock_code": stock_code,
                "request": {
                    "method": response.request.method,
                    "url": str(response.request.url),
                    "headers": dict(response.request.headers),
                    "body": response.request.body
                },
                "response": {
                    "status_code": response.status_code,
                    "headers": dict(response.headers),
                    "response_time_seconds": response.elapsed.total_seconds(),
                    "content_length": len(response.content),
                    "encoding": response.encoding,
                    "raw_text": response.text
                }
            }
            
            # JSON 파싱 가능한 경우 추가
            try:
                debug_data["response"]["parsed_json"] = response.json()
            except:
                debug_data["response"]["parsed_json"] = None
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(debug_data, f, indent=2, ensure_ascii=False)
            
            print(f"\n💾 [파일 저장 완료]")
            print(f"   📁 경로: {filepath}")
            print(f"   📦 크기: {os.path.getsize(filepath):,} bytes")
            
        except Exception as e:
            print(f"❌ 파일 저장 실패: {e}")
    
    print("="*70)
    print()

class KISBacktester:
    def __init__(self, app_key: str, app_secret: str):
        """
        KIS API 백테스터 초기화

        Args:
            app_key: KIS API 앱 키
            app_secret: KIS API 앱 시크릿
            mock: 실전/모의 구분 (True: 모의, False: 실전)
        """
        self.app_key = app_key
        self.app_secret = app_secret
        self.base_url = "https://openapi.koreainvestment.com:9443"
        self.token_file = "token.json" 
        self.access_token = None
        self.setup_logging()

    def load_keys(self):
        app_key = os.getenv("KIS_APP_KEY")
        app_secret = os.getenv("KIS_APP_SECRET")
        if not app_key or not app_secret:
            raise ValueError("환경변수 KIS_APP_KEY 또는 KIS_APP_SECRET이 설정되지 않았습니다.")
        return app_key, app_secret

    def load_saved_token(self):
        """저장된 토큰 파일에서 토큰 로드 (기존 프로그램과 호환)"""
        try:
            if os.path.exists(self.token_file):
                with open(self.token_file, 'r', encoding='utf-8') as f:
                    token_data = json.load(f)

                # 기존 형식의 만료시간 파싱
                expire_time_str = token_data.get('access_token_token_expired', '')
                if expire_time_str:
                    expire_time = datetime.strptime(expire_time_str, '%Y-%m-%d %H:%M:%S')

                    # 토큰이 아직 유효한지 확인 (10분 여유 둠)
                    if datetime.now() < expire_time - timedelta(minutes=10):
                        self.access_token = token_data.get('access_token')
                        self.last_token_time = datetime.fromtimestamp(token_data.get('requested_at', 0))
                        self.logger.info(f"기존 토큰을 재사용합니다. (만료: {expire_time_str})")
                        return True
                    else:
                        self.logger.info(f"저장된 토큰이 만료되었습니다. (만료: {expire_time_str})")

        except Exception as e:
            self.logger.warning(f"토큰 파일 로드 실패: {e}")

        return False

    def save_token(self, token_response: dict):
        """토큰을 기존 프로그램과 호환되는 형식으로 저장"""
        try:
            current_time = int(time.time())
            expires_in = token_response.get('expires_in', 86400)
            expire_datetime = datetime.fromtimestamp(current_time + expires_in)

            token_data = {
                'access_token': token_response.get('access_token'),
                'access_token_token_expired': expire_datetime.strftime('%Y-%m-%d %H:%M:%S'),
                'token_type': token_response.get('token_type', 'Bearer'),
                'expires_in': expires_in,
                'requested_at': current_time
            }

            with open(self.token_file, 'w', encoding='utf-8') as f:
                json.dump(token_data, f, ensure_ascii=False, indent=2)

            self.logger.info(f"토큰이 저장되었습니다. (만료: {token_data['access_token_token_expired']})")

        except Exception as e:
            self.logger.error(f"토큰 저장 실패: {e}")


    def get_access_token(self) -> str:
        """KIS API 액세스 토큰 발급 또는 재사용 (기존 프로그램과 호환)"""
        # 메모리에 유효한 토큰이 있는지 확인
        if self.access_token and self.last_token_time:
            # 23시간 이내면 메모리 토큰 재사용
            if datetime.now() - self.last_token_time < timedelta(hours=23):
                return self.access_token
    
        # 저장된 토큰 재확인
        if self.load_saved_token():
            return self.access_token
    
        # 새 토큰 발급
        self.logger.info("새로운 액세스 토큰을 발급받습니다...")
    
        url = f"{self.base_url}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
    
        try:
            response = requests.post(url, headers=headers, data=json.dumps(data))
            response.raise_for_status()
    
            token_response = response.json()
            
            # 응답 구조 상세 로깅
            #self.logger.debug(f"토큰 API 응답: {token_response}")
            
            # 성공 조건 개선: access_token이 있으면 성공으로 판단
            access_token = token_response.get("access_token")
            
            if access_token:
                # 토큰이 있으면 성공
                self.access_token = access_token
                self.last_token_time = datetime.now()
    
                # 토큰을 기존 형식으로 파일에 저장
                self.save_token(token_response)
    
                self.logger.info("✅ 새로운 액세스 토큰 발급 완료")
                return self.access_token
            
            else:
                # 토큰이 없으면 실패 - rt_cd 기반 오류 처리
                rt_cd = token_response.get("rt_cd")
                
                if rt_cd and rt_cd != "0":
                    # rt_cd가 있고 실패인 경우
                    error_msg = token_response.get('msg1', 
                               token_response.get('message', 
                               token_response.get('error_description', 'Unknown error')))
                    error_code = token_response.get('msg_cd', token_response.get('error_code', 'Unknown'))
                    
                    self.logger.error(f"토큰 발급 실패 상세:")
                    self.logger.error(f"  - rt_cd: {rt_cd}")
                    self.logger.error(f"  - error_code: {error_code}")
                    self.logger.error(f"  - error_msg: {error_msg}")
                    
                    raise Exception(f"토큰 발급 실패 [{error_code}]: {error_msg}")
                else:
                    # access_token도 없고 rt_cd도 없는 경우
                    self.logger.error(f"예상치 못한 응답 형식: {token_response}")
                    raise Exception("토큰 응답에 access_token이 포함되지 않았습니다")
    
        except requests.exceptions.RequestException as e:
            self.logger.error(f"❌ 토큰 발급 네트워크 오류: {e}")
            raise
        except json.JSONDecodeError as e:
            self.logger.error(f"❌ 토큰 응답 JSON 파싱 오류: {e}")
            self.logger.error(f"응답 내용: {response.text if 'response' in locals() else 'N/A'}")
            raise
        except Exception as e:
            self.logger.error(f"❌ 토큰 발급 실패: {e}")
            raise

    def get_stock_data(self, stock_code: str, period: str = "D", count: int = 100) -> pd.DataFrame:
        """
        주식 데이터 조회

        Args:
            stock_code: 종목코드
            period: 기간 (D: 일봉, W: 주봉, M: 월봉)
            count: 조회할 데이터 개수
        """
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

        try:
            response = requests.get(url, headers=headers, params=params)
            if response.status_code == 200:
                data = response.json()
                if 'output2' in data and data['output2']:
                    df = pd.DataFrame(data['output2'])

                    # 컬럼명 변경 및 데이터 타입 변환
                    df = df.rename(columns={
                        'stck_bsop_date': 'date',
                        'stck_oprc': 'open',
                        'stck_hgpr': 'high',
                        'stck_lwpr': 'low',
                        'stck_clpr': 'close',
                        'acml_vol': 'volume'
                    })

                    # 필요한 컬럼만 선택
                    df = df[['date', 'open', 'high', 'low', 'close', 'volume']].copy()

                    # 데이터 타입 변환
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                    df['date'] = pd.to_datetime(df['date'])
                    df = df.sort_values('date').reset_index(drop=True)

                    # 최근 count개만 선택
                    df = df.tail(count).reset_index(drop=True)

                    return df
                else:
                    print(f"❌ 데이터 없음: {stock_code}")
                    return pd.DataFrame()
            else:
                print(f"❌ API 호출 실패: {response.status_code} - {response.text}")
                return pd.DataFrame()

        except Exception as e:
            print(f"❌ 데이터 조회 중 오류: {e}")
            return pd.DataFrame()

    
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


    def calculate_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """기술적 지표 계산"""
        if len(df) < 20:
            print("❌ 데이터가 부족합니다 (최소 20개 필요)")
            return df

        # 이동평균
        df['ma5'] = df['close'].rolling(window=5).mean()
        df['ma10'] = df['close'].rolling(window=10).mean()
        df['ma20'] = df['close'].rolling(window=20).mean()

        # 볼린저 밴드
        df['bb_middle'] = df['close'].rolling(window=20).mean()
        bb_std = df['close'].rolling(window=20).std()
        df['bb_upper'] = df['bb_middle'] + (bb_std * 2)
        df['bb_lower'] = df['bb_middle'] - (bb_std * 2)

        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # MACD
        exp1 = df['close'].ewm(span=12).mean()
        exp2 = df['close'].ewm(span=26).mean()
        df['macd'] = exp1 - exp2
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        # 거래량 비율 (현재 거래량 / 5일 평균 거래량)
        df['volume_ma5'] = df['volume'].rolling(window=5).mean()
        df['volume_ratio'] = df['volume'] / df['volume_ma5']

        # 가격 변화율
        df['price_change'] = df['close'].pct_change()
        df['price_change_5d'] = df['close'].pct_change(periods=5)

        # 변동성 (20일 표준편차)
        df['volatility'] = df['close'].rolling(window=20).std()

        return df

    def momentum_strategy(self, df: pd.DataFrame) -> pd.Series:
        """모멘텀 전략"""
        signals = pd.Series(0, index=df.index)

        # 조건: 5일선 > 20일선, RSI > 50, 거래량 증가
        buy_condition = (
            (df['ma5'] > df['ma20']) &
            (df['rsi'] > 50) &
            (df['volume_ratio'] > 1.2)
        )

        sell_condition = (
            (df['ma5'] < df['ma20']) |
            (df['rsi'] < 30)
        )

        signals[buy_condition] = 1
        signals[sell_condition] = -1

        return signals

    def mean_reversion_strategy(self, df: pd.DataFrame) -> pd.Series:
        """평균회귀 전략"""
        signals = pd.Series(0, index=df.index)

        # 조건: 가격이 볼린저 밴드 하한선 근처, RSI 과매도
        buy_condition = (
            (df['close'] <= df['bb_lower'] * 1.02) &
            (df['rsi'] < 35)
        )

        sell_condition = (
            (df['close'] >= df['bb_upper'] * 0.98) |
            (df['rsi'] > 65)
        )

        signals[buy_condition] = 1
        signals[sell_condition] = -1

        return signals

    def breakout_strategy(self, df: pd.DataFrame) -> pd.Series:
        """돌파 전략"""
        signals = pd.Series(0, index=df.index)

        # 조건: 20일 최고가 돌파, 거래량 급증
        df['high_20'] = df['high'].rolling(window=20).max()

        buy_condition = (
            (df['close'] > df['high_20'].shift(1)) &
            (df['volume_ratio'] > 2.0)
        )

        sell_condition = df['close'] < df['ma20']

        signals[buy_condition] = 1
        signals[sell_condition] = -1

        return signals

    def scalping_strategy(self, df: pd.DataFrame) -> pd.Series:
        """스캘핑 전략"""
        signals = pd.Series(0, index=df.index)

        # 조건: MACD 골든크로스, 단기 상승 추세
        buy_condition = (
            (df['macd'] > df['macd_signal']) &
            (df['macd'].shift(1) <= df['macd_signal'].shift(1)) &
            (df['close'] > df['ma5'])
        )

        sell_condition = (
            (df['macd'] < df['macd_signal']) |
            (df['close'] < df['ma5'] * 0.98)
        )

        signals[buy_condition] = 1
        signals[sell_condition] = -1

        return signals

    def backtest_strategy(self, df: pd.DataFrame, strategy_func, initial_capital: float = 1000000) -> Dict:
        """전략 백테스트"""
        if len(df) < 30:
            return {'error': '데이터 부족'}

        try:
            signals = strategy_func(df)

            # 포지션 계산
            positions = signals.replace(0, np.nan).fillna(method='ffill').fillna(0)

            # 수익률 계산
            returns = df['close'].pct_change()
            strategy_returns = positions.shift(1) * returns

            # 누적 수익률
            cumulative_returns = (1 + strategy_returns).cumprod()
            total_return = cumulative_returns.iloc[-1] - 1

            # 통계 계산
            winning_trades = len(strategy_returns[strategy_returns > 0])
            losing_trades = len(strategy_returns[strategy_returns < 0])
            total_trades = winning_trades + losing_trades

            win_rate = winning_trades / total_trades if total_trades > 0 else 0

            # 최대 낙폭 계산
            rolling_max = cumulative_returns.cummax()
            drawdown = (cumulative_returns - rolling_max) / rolling_max
            max_drawdown = drawdown.min()

            # 샤프 비율 (연간화)
            annual_return = total_return * (252 / len(df))
            annual_volatility = strategy_returns.std() * np.sqrt(252)
            sharpe_ratio = annual_return / annual_volatility if annual_volatility > 0 else 0

            return {
                'total_return': total_return,
                'annual_return': annual_return,
                'win_rate': win_rate,
                'total_trades': total_trades,
                'max_drawdown': max_drawdown,
                'sharpe_ratio': sharpe_ratio,
                'final_capital': initial_capital * (1 + total_return)
            }

        except Exception as e:
            return {'error': str(e)}

    def save_backtest_results(self, results_df: pd.DataFrame, stock_names: Dict[str, str], filename: str = "backtest_results.json"):
        """백테스트 결과를 JSON 파일로 저장"""
        if results_df.empty:
            print("저장할 결과가 없습니다.")
            return
        
        # 종목별 최고 전략 선택
        best_strategies = {}
        for stock_code in results_df['stock_code'].unique():
            stock_results = results_df[results_df['stock_code'] == stock_code]
            valid_results = stock_results[stock_results['total_trades'] >= 3]
            if valid_results.empty:
                best_row = stock_results.loc[stock_results['total_return'].idxmax()]
            else:
                best_row = valid_results.loc[valid_results['total_return'].idxmax()]
            
            best_strategies[stock_code] = {
                'symbol': stock_code,
                'name': stock_names.get(stock_code, stock_code),  # 종목명 추가
                'strategy': best_row['strategy'],
                'return': round(best_row['total_return'] * 100, 2),  # 백분율로 변환
                'win_rate': round(best_row['win_rate'], 3),
                'sharpe_ratio': round(best_row['sharpe_ratio'], 3),
                'max_drawdown': round(best_row['max_drawdown'], 3),
                'total_trades': int(best_row['total_trades']),
                'priority': 0,  # 나중에 계산
                'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        
        # 수익률 기준으로 우선순위 설정
        sorted_symbols = sorted(best_strategies.items(), 
                              key=lambda x: x[1]['return'], 
                              reverse=True)
        
        for i, (symbol, data) in enumerate(sorted_symbols):
            best_strategies[symbol]['priority'] = i + 1
        
        # 전체 결과 구성
        backtest_data = {
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'backtest_period': f"{len(results_df)} days",
            'verified_symbols': list(best_strategies.values()),
            'summary': {
                'total_symbols': len(best_strategies),
                'avg_return': round(results_df.groupby('stock_code')['total_return'].max().mean() * 100, 2),
                'best_symbol': sorted_symbols[0][0] if sorted_symbols else None,
                'best_return': sorted_symbols[0][1]['return'] if sorted_symbols else 0
            }
        }
        
        # JSON 파일로 저장
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(backtest_data, f, ensure_ascii=False, indent=2)
            print(f"\n✅ 백테스트 결과가 {filename}에 저장되었습니다.")
            
            # stock_names.json 별도 저장
            if os.path.exists('stock_names.json'):
                with open('stock_names.json', 'r', encoding='utf-8') as f:
                    existing_names = json.load(f)
            else:
                existing_names = {}
    
            # 기존 데이터와 새 데이터 병합
            merged_names = {**existing_names, **stock_names}
    
            # 병합된 데이터 저장
            with open('stock_names.json', 'w', encoding='utf-8') as f:
                json.dump(merged_names, f, ensure_ascii=False, indent=2)

            print(f"✅ 종목명 매핑이 stock_names.json에 저장되었습니다.")
            
        except Exception as e:
            print(f"❌ 결과 저장 실패: {e}")

    def run_comprehensive_backtest(self, stock_codes: List[str], stock_names: Dict[str, str] = None, days: int = 100):
        """종합 백테스트 실행"""
        print("🚀 KIS API 기반 시간단위 매매 백테스트 시작!")
        print("=" * 60)

        if stock_names is None:
            stock_names = {}

        strategies = {
            'momentum': self.momentum_strategy,
            'mean_reversion': self.mean_reversion_strategy,
            'breakout': self.breakout_strategy,
            'scalping': self.scalping_strategy
        }

        # 전략 조합
        strategy_combinations = [
            ['momentum'],
            ['mean_reversion'],
            ['breakout'],
            ['scalping'],
            ['momentum', 'breakout'],
            ['mean_reversion', 'scalping']
        ]

        all_results = []

        for stock_code in stock_codes:
            print(f"📊 {stock_code}({stock_names[stock_code]}) 종목 분석 중...")

            # 데이터 조회
            #df = self.get_stock_data_with_debug(stock_code, count=days)
            df = self.get_stock_data(stock_code, count=days)
            if df.empty:
                print(f"❌ {stock_code} - 데이터 조회 실패")
                continue

            # 기술적 지표 계산
            df = self.calculate_technical_indicators(df)

            # 각 전략 조합별 백테스트
            for combination in strategy_combinations:
                try:
                    if len(combination) == 1:
                        # 단일 전략
                        strategy_name = combination[0]
                        result = self.backtest_strategy(df, strategies[strategy_name])
                    else:
                        # 전략 조합 (신호 평균)
                        combined_signals = pd.Series(0, index=df.index)
                        for strategy_name in combination:
                            signals = strategies[strategy_name](df)
                            combined_signals += signals
                        combined_signals = combined_signals / len(combination)

                        # 임계값으로 신호 변환
                        final_signals = pd.Series(0, index=df.index)
                        final_signals[combined_signals > 0.5] = 1
                        final_signals[combined_signals < -0.5] = -1

                        def combined_strategy(df):
                            return final_signals

                        result = self.backtest_strategy(df, combined_strategy)

                    if 'error' in result:
                        print(f"❌ {stock_code} - {combination} 오류: {result['error']}")
                        continue

                    result['stock_code'] = stock_code
                    result['strategy'] = ' + '.join(combination)
                    all_results.append(result)

                    print(f"✅ {stock_code} - {combination}: 수익률 {result['total_return']:.2%}")

                except Exception as e:
                    print(f"❌ {stock_code} - {combination} 오류: {str(e)}")
                    continue

            # API 호출 제한 방지
            time.sleep(0.1)

        # 결과 정리 및 출력
        if all_results:
            results_df = pd.DataFrame(all_results)

            print("\n" + "=" * 60)
            print("📈 백테스트 결과 요약")
            print("=" * 60)

            # 전략별 평균 성과
            strategy_summary = results_df.groupby('strategy').agg({
                'total_return': 'mean',
                'win_rate': 'mean',
                'sharpe_ratio': 'mean',
                'max_drawdown': 'mean'
            }).round(4)

            print("\n🏆 전략별 평균 성과:")
            print(strategy_summary.to_string())

            # 종목별 최고 성과
            print(f"\n⭐ 종목별 최고 성과:")
            #best_by_stock = results_df.loc[results_df.groupby('stock_code')['total_return'].idxmax()]
            best_by_stock = results_df.loc[results_df.groupby('stock_code')['total_return'].idxmax()].sort_values(by='total_return', ascending=False)
            for _, row in best_by_stock.iterrows():
                stock_name = stock_names.get(row['stock_code'], row['stock_code'])
                print(f"{row['stock_code']}({stock_name}): {row['strategy']} - 수익률 {row['total_return']:.2%}")

            # 전체 최고 성과
            best_overall = results_df.loc[results_df['total_return'].idxmax()]
            print(f"\n🥇 전체 최고 성과:")
            print(f"종목: {best_overall['stock_code']}, 전략: {best_overall['strategy']}")
            print(f"수익률: {best_overall['total_return']:.2%}, 승률: {best_overall['win_rate']:.2%}")
            print(f"샤프비율: {best_overall['sharpe_ratio']:.3f}, 최대낙폭: {best_overall['max_drawdown']:.2%}")

            # JSON 파일로 저장
            self.save_backtest_results(results_df, stock_names)

            return results_df
        else:
            print("❌ 백테스트 결과가 없습니다.")
            return pd.DataFrame()

    def setup_logging(self):
        """로깅 설정 - 디버그 모드"""
        # 로그 레벨을 DEBUG로 변경
        logging.basicConfig(
            level=logging.INFO,  # INFO -> DEBUG로 변경
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('logs/backtest.log', encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

def load_stock_codes_from_file(file_path: str) -> Tuple[List[str], Dict[str, str]]:
    """
    파일에서 종목 코드와 종목명을 읽어오는 함수
    Returns:
        Tuple[List[str], Dict[str, str]]: (종목코드 리스트, {종목코드: 종목명} 딕셔너리)
    """
    if not os.path.exists(file_path):
        print(f"❌ 파일을 찾을 수 없습니다: {file_path}")
        return [], {}
    
    file_extension = os.path.splitext(file_path)[1].lower()
    stock_codes = []
    stock_names = {}  # 종목코드: 종목명 매핑
    
    try:
        if file_extension == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                if data and isinstance(data[0], dict):
                    # [{"code": "034020", "name": "두산에너빌리티", ...}, ...] 형태
                    if 'code' in data[0]:
                        for item in data:
                            if 'code' in item:
                                code = str(item['code']).zfill(6)
                                name = item.get('name', code)  # name이 없으면 코드를 사용
                                stock_codes.append(code)
                                stock_names[code] = name
                        print(f"✅ JSON 객체 배열에서 {len(stock_codes)}개 종목 코드 추출: {file_path}")
                    else:
                        print(f"❌ 객체에 'code' 필드가 없습니다.")
                        return [], {}
                else:
                    # ["062040", "278470", ...] 형태
                    stock_codes = [str(code).zfill(6) for code in data]
                    # 종목명이 없으므로 코드를 종목명으로 사용
                    stock_names = {code: code for code in stock_codes}
                    print(f"✅ JSON 배열에서 {len(stock_codes)}개 종목 로드: {file_path}")
                    
            elif isinstance(data, dict):
                # 기존 딕셔너리 처리 로직도 비슷하게 수정...
                # (생략 - 필요시 추가 구현)
                print(f"❌ 파일 읽기 오류 ({file_path}): {e}")
                return [], {}
                
        # 중복 제거 및 유효성 검사
        unique_codes = []
        unique_names = {}
        for code in stock_codes:
            if code and len(code) == 6 and code.isdigit():
                if code not in unique_codes:
                    unique_codes.append(code)
                    unique_names[code] = stock_names.get(code, code)
            else:
                print(f"⚠️ 유효하지 않은 종목코드 제외: {code}")
        
        print(f"📊 최종 {len(unique_codes)}개 종목 추가 로드 완료")
        
        return unique_codes, unique_names
        
    except Exception as e:
        print(f"❌ 파일 읽기 오류 ({file_path}): {e}")
        return [], {}


# 실행 코드
if __name__ == "__main__":
    APP_KEY = os.getenv("KIS_APP_KEY")
    APP_SECRET = os.getenv("KIS_APP_SECRET")
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    #from market_schedule_checker import check_market_schedule_and_exit
    #check_market_schedule_and_exit()

    # 백테스터 초기화 (모의투자 환경)
    backtester = KISBacktester(APP_KEY, APP_SECRET)

    # 분석할 종목 리스트
    base_stock_info = {
        "062040": "산일전기",
        "278470": "에이피알",
    }
    
    # 종목코드 리스트와 이름 딕셔너리 분리
    base_stock_list = list(base_stock_info.keys())
    base_stock_names = base_stock_info

    # backtest_list.json에서 종목 로드
    additional_codes, additional_names = load_stock_codes_from_file("backtest_list.json")
    
    # 종목 리스트와 이름 딕셔너리 합치기
    all_stock_codes = list(set(base_stock_list + additional_codes))
    all_stock_names = {**base_stock_names, **additional_names}
    
    print(f"📋 분석대상 목록: {', '.join([f'{code}({all_stock_names.get(code, code)})' for code in all_stock_codes[:5]])}{'...' if len(all_stock_codes) > 5 else ''}")
    
    # 백테스트 실행
    results = backtester.run_comprehensive_backtest(all_stock_codes, all_stock_names, days=100)

