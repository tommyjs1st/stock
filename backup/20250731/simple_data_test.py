import requests
import json
import yaml
from datetime import datetime, timedelta

def test_daily_data():
    """일봉 데이터 조회 테스트"""
    
    # config.yaml에서 설정 로드
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    app_key = config['kis']['app_key']
    app_secret = config['kis']['app_secret']
    base_url = config['kis']['base_url']
    
    # token.json에서 토큰 로드
    with open('token.json', 'r', encoding='utf-8') as f:
        token_data = json.load(f)
    access_token = token_data['access_token']
    
    # 여러 API 방식 테스트
    test_apis = [
        {
            "name": "일봉 차트 (FHKST03010100)",
            "url": f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "tr_id": "FHKST03010100",
            "params": {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": "005930",
                "fid_input_date_1": "20250701",
                "fid_input_date_2": "20250728",
                "fid_period_div_code": "D"
            }
        },
        {
            "name": "일봉 차트 (FHKST03010100) - 다른 파라미터",
            "url": f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
            "tr_id": "FHKST03010100",
            "params": {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": "005930",
                "fid_input_date_1": "20250701",
                "fid_input_date_2": "20250728",
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "0"
            }
        },
        {
            "name": "일봉 차트 (FHKST01010400)",
            "url": f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-daily-price",
            "tr_id": "FHKST01010400",
            "params": {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": "005930",
                "fid_period_div_code": "D",
                "fid_org_adj_prc": "1"
            }
        },
        {
            "name": "현재가 조회 (확인용)",
            "url": f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price",
            "tr_id": "FHKST01010100",
            "params": {
                "fid_cond_mrkt_div_code": "J",
                "fid_input_iscd": "005930"
            }
        }
    ]
    
    for api_test in test_apis:
        print(f"\n{'='*60}")
        print(f"테스트: {api_test['name']}")
        print(f"URL: {api_test['url']}")
        print(f"TR_ID: {api_test['tr_id']}")
        print("-" * 60)
        
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": api_test['tr_id']
        }
        
        try:
            response = requests.get(api_test['url'], headers=headers, params=api_test['params'])
            data = response.json()
            
            print(f"HTTP 상태: {response.status_code}")
            print(f"API 응답 코드: '{data.get('rt_cd')}'")
            print(f"API 메시지: '{data.get('msg1')}'")
            
            if data.get('rt_cd') == '0':
                print("✅ API 호출 성공!")
                
                # output 데이터 확인
                for key in ['output', 'output1', 'output2']:
                    if key in data:
                        output_data = data[key]
                        if isinstance(output_data, list):
                            print(f"{key}: {len(output_data)}건의 데이터")
                            if output_data:
                                print(f"  첫 번째 항목 컬럼: {list(output_data[0].keys())}")
                        elif isinstance(output_data, dict):
                            print(f"{key}: {output_data}")
                        else:
                            print(f"{key}: {output_data}")
                
                # 성공한 API가 있으면 상세 정보 출력
                if 'output2' in data and data['output2']:
                    print("\n📊 상세 데이터 (첫 3개):")
                    for i, item in enumerate(data['output2'][:3]):
                        print(f"  {i+1}. {item}")
                    break
                elif 'output' in data and data['output']:
                    print(f"\n📊 상세 데이터: {data['output']}")
                    break
            
            elif data.get('rt_cd'):
                print(f"❌ API 오류: {data.get('rt_cd')} - {data.get('msg1')}")
            else:
                print("❌ 빈 응답")
                print(f"전체 응답: {json.dumps(data, indent=2, ensure_ascii=False)}")
                
        except Exception as e:
            print(f"❌ 요청 오류: {e}")
    
    print(f"\n{'='*60}")
    print("테스트 완료")

def test_simple_current_price():
    """간단한 현재가 조회 테스트"""
    print(f"\n{'='*60}")
    print("추가 테스트: 현재가 조회")
    print("-" * 60)
    
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    app_key = config['kis']['app_key']
    app_secret = config['kis']['app_secret']
    base_url = config['kis']['base_url']
    
    with open('token.json', 'r', encoding='utf-8') as f:
        token_data = json.load(f)
    access_token = token_data['access_token']
    
    url = f"{base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "FHKST01010100"
    }
    params = {"fid_cond_mrkt_div_code": "J", "fid_input_iscd": "005930"}
    
    response = requests.get(url, headers=headers, params=params)
    data = response.json()
    
    print(f"현재가 조회 결과: {data.get('rt_cd')} - {data.get('msg1')}")
    if data.get('rt_cd') == '0':
        output = data.get('output', {})
        print(f"삼성전자 현재가: {output.get('stck_prpr', 'N/A')}원")

if __name__ == "__main__":
    test_daily_data()
    test_simple_current_price()
