"""
한국 주식시장 운영시간 및 공휴일 체크 모듈
"""
import requests
import json
from datetime import datetime, time, timedelta
import logging
import os
from typing import Tuple
from config.config_manager import ConfigManager

class KoreanMarketSchedule:
    def __init__(self, config_path: str = "config.yaml"):
        self.logger = logging.getLogger(__name__)

        config_manager = ConfigManager(config_path)
        openapi_config = config_manager.get_openapi_config()
        self.openapi_decoding_key = openapi_config['decoding_key']
        
        # 한국 주식시장 운영시간
        self.market_open_time = time(9, 0)      # 09:00
        self.market_close_time = time(15, 30)   # 15:30 (실제 거래 종료)
        self.after_hours_limit = time(16, 0)    # 16:00 (분석 프로그램 종료 시간)
        
        # 공휴일 API URL (공공데이터포털)
        self.holiday_api_key = os.getenv("HOLIDAY_API_KEY")  # 선택사항
        
        # 2025년 한국 공휴일 (하드코딩 백업)
        self.korean_holidays_2025 = {
            "01-01": "신정",
            "01-28": "설날 연휴",
            "01-29": "설날",
            "01-30": "설날 연휴",
            "03-01": "삼일절",
            "05-05": "어린이날",
            "05-26": "부처님오신날",
            "06-06": "현충일",
            "08-15": "광복절",
            "10-03": "개천절",
            "10-09": "한글날",
            "12-25": "성탄절"
        }
        
        # 2026년 한국 공휴일 (미리 추가)
        self.korean_holidays_2026 = {
            "01-01": "신정",
            "02-16": "설날 연휴",
            "02-17": "설날",
            "02-18": "설날 연휴",
            "03-01": "삼일절",
            "05-05": "어린이날",
            "05-14": "부처님오신날",
            "06-06": "현충일",
            "08-15": "광복절",
            "09-28": "추석 연휴",
            "09-29": "추석",
            "09-30": "추석 연휴",
            "10-03": "개천절",
            "10-09": "한글날",
            "12-25": "성탄절"
        }

    def get_holidays_from_api(self, year: int) -> dict:
        """
        공공데이터포털 API에서 공휴일 정보 조회
        API 키가 없거나 실패하면 하드코딩된 데이터 사용
        """
        if not self.holiday_api_key:
            self.logger.info("공휴일 API 키가 없어 하드코딩된 데이터를 사용합니다.")
            return self._get_hardcoded_holidays(year)
        
        # API 키가 'your_holiday_api_key_here' 같은 placeholder인 경우
        if self.holiday_api_key in ['your_holiday_api_key_here', 'your_api_key_here']:
            self.logger.info("공휴일 API 키가 placeholder 값입니다. 하드코딩된 데이터를 사용합니다.")
            return self._get_hardcoded_holidays(year)
        
        try:
            # 공휴일 정보 조회 API 사용 (국경일 + 공휴일 통합)
            url = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getHoliDeInfo"
            params = {
                'serviceKey': self.openapi_decoding_key,
                'pageNo': '1',
                'numOfRows': '50',
                'solYear': str(year),
                # 'solMonth': '',  # 월을 지정하지 않으면 전년도 조회
            }
            
            self.logger.debug(f"API 요청 URL: {url}")
            self.logger.debug(f"API 요청 파라미터: {params}")
            
            response = requests.get(url, params=params, timeout=15)
            
            # 응답 상태 체크
            self.logger.debug(f"응답 상태코드: {response.status_code}")
            self.logger.debug(f"응답 헤더: {dict(response.headers)}")
            self.logger.debug(f"응답 내용 (처음 500자): {response.text[:500]}")
            
            response.raise_for_status()
            
            # 빈 응답 체크
            if not response.text.strip():
                raise ValueError("빈 응답을 받았습니다")
            
            # 오류 응답 체크 (XML 오류 메시지 처리)
            if response.text.strip().startswith('<OpenAPI_ServiceResponse>'):
                # XML 오류 응답 파싱
                try:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(response.text, 'xml')
                    err_msg = soup.find('errMsg')
                    return_auth_msg = soup.find('returnAuthMsg')
                    return_reason_code = soup.find('returnReasonCode')
                    
                    error_details = []
                    if err_msg:
                        error_details.append(f"오류: {err_msg.text}")
                    if return_auth_msg:
                        error_details.append(f"인증오류: {return_auth_msg.text}")
                    if return_reason_code:
                        error_details.append(f"코드: {return_reason_code.text}")
                    
                    error_message = " | ".join(error_details)
                    
                    # 특정 오류에 대한 안내
                    if "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in response.text:
                        self.logger.error("❌ API 키가 해당 서비스에 등록되지 않았습니다.")
                        self.logger.error("💡 해결방법: https://www.data.go.kr 에서 '특일 정보' API 활용신청 필요")
                    elif "SERVICE_KEY_IS_NOT_REGISTERED" in response.text:
                        self.logger.error("❌ 유효하지 않은 API 키입니다.")
                    
                    raise ValueError(f"API 서비스 오류: {error_message}")
                    
                except ImportError:
                    raise ValueError("XML 오류 응답을 받았으나 BeautifulSoup이 없어 파싱할 수 없습니다")
                except Exception:
                    raise ValueError(f"API 서비스 오류: {response.text}")
            
            # JSON 파싱 시도
            try:
                data = response.json()
            except json.JSONDecodeError as json_error:
                # XML 응답인 경우 처리 (오류 로그 생략)
                if response.text.strip().startswith('<'):
                    self.logger.debug("XML 응답을 받았습니다. XML 파싱을 시도합니다.")
                    return self._parse_xml_response(response.text, year)
                else:
                    self.logger.error(f"JSON 파싱 실패: {json_error}")
                    self.logger.error(f"응답 내용: {response.text}")
                    raise json_error
            
            # API 응답 구조 확인
            self.logger.debug(f"API 응답 구조: {data}")
            
            # 오류 응답 체크
            header = data.get('response', {}).get('header', {})
            result_code = header.get('resultCode', '')
            result_msg = header.get('resultMsg', '')
            
            if result_code != '00':
                raise ValueError(f"API 오류: 코드={result_code}, 메시지={result_msg}")
            
            holidays = {}
            body = data.get('response', {}).get('body', {})
            items = body.get('items', {})
            
            # items가 None이거나 빈 경우 처리
            if not items:
                self.logger.warning(f"{year}년 공휴일 데이터가 없습니다.")
                return self._get_hardcoded_holidays(year)
            
            # item이 단일 객체인 경우와 리스트인 경우 모두 처리
            item_list = items.get('item', [])
            if isinstance(item_list, dict):
                item_list = [item_list]
            elif not isinstance(item_list, list):
                item_list = []
            
            for item in item_list:
                date_str = str(item.get('locdate', ''))
                name = item.get('dateName', '')
                is_holiday = item.get('isHoliday', 'N')
                
                # 공공기관 휴일만 선택
                if date_str and name and is_holiday == 'Y' and len(date_str) == 8:
                    try:
                        date_formatted = f"{date_str[4:6]}-{date_str[6:8]}"
                        holidays[date_formatted] = name
                    except (IndexError, ValueError):
                        continue
            
            if holidays:
                self.logger.info(f"API에서 {year}년 공휴일 {len(holidays)}개 조회 완료")
                return holidays
            else:
                self.logger.warning(f"API에서 {year}년 공휴일 데이터를 찾을 수 없습니다.")
                return self._get_hardcoded_holidays(year)
            
        except requests.exceptions.Timeout:
            self.logger.warning("공휴일 API 요청 시간 초과, 하드코딩된 데이터 사용")
            return self._get_hardcoded_holidays(year)
        except requests.exceptions.RequestException as e:
            self.logger.warning(f"공휴일 API 네트워크 오류: {e}, 하드코딩된 데이터 사용")
            return self._get_hardcoded_holidays(year)
        except Exception as e:
            self.logger.warning(f"공휴일 API 조회 실패: {e}, 하드코딩된 데이터 사용")
            return self._get_hardcoded_holidays(year)

    def _parse_xml_response(self, xml_text: str, year: int) -> dict:
        """XML 응답 파싱 (BeautifulSoup 사용)"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(xml_text, 'xml')
            
            holidays = {}
            items = soup.find_all('item')
            
            for item in items:
                locdate = item.find('locdate')
                dateName = item.find('dateName')
                isHoliday = item.find('isHoliday')
                
                if locdate and dateName and isHoliday:
                    date_str = locdate.text.strip()
                    name = dateName.text.strip()
                    is_holiday = isHoliday.text.strip()
                    
                    if date_str and name and is_holiday == 'Y' and len(date_str) == 8:
                        try:
                            date_formatted = f"{date_str[4:6]}-{date_str[6:8]}"
                            holidays[date_formatted] = name
                        except (IndexError, ValueError):
                            continue
            
            if holidays:
                self.logger.info(f"XML API에서 {year}년 공휴일 {len(holidays)}개 파싱 완료")
                return holidays
            else:
                return self._get_hardcoded_holidays(year)
                
        except ImportError:
            self.logger.warning("BeautifulSoup이 설치되지 않아 XML 파싱할 수 없습니다. pip install beautifulsoup4 lxml")
            return self._get_hardcoded_holidays(year)
        except Exception as e:
            self.logger.warning(f"XML 파싱 실패: {e}")
            return self._get_hardcoded_holidays(year)

    def _get_hardcoded_holidays(self, year: int) -> dict:
        """하드코딩된 공휴일 데이터 반환"""
        if year == 2025:
            return self.korean_holidays_2025
        elif year == 2026:
            return self.korean_holidays_2026
        else:
            self.logger.warning(f"{year}년 공휴일 데이터가 없습니다. 2025년 데이터를 사용합니다.")
            return self.korean_holidays_2025

    def is_holiday(self, target_date: datetime = None) -> Tuple[bool, str]:
        """
        지정된 날짜가 공휴일인지 확인
        
        Args:
            target_date: 확인할 날짜 (None이면 오늘)
            
        Returns:
            Tuple[bool, str]: (공휴일 여부, 공휴일명)
        """
        if target_date is None:
            target_date = datetime.now()
        
        # 주말 확인
        weekday = target_date.weekday()
        if weekday == 5:  # 토요일
            return True, "토요일"
        elif weekday == 6:  # 일요일
            return True, "일요일"
        
        # 공휴일 확인
        holidays = self.get_holidays_from_api(target_date.year)
        date_key = target_date.strftime("%m-%d")
        
        if date_key in holidays:
            return True, holidays[date_key]
        
        return False, ""

    def is_market_hours(self, target_time: datetime = None) -> bool:
        """
        주식시장 운영시간인지 확인
        
        Args:
            target_time: 확인할 시간 (None이면 현재 시간)
            
        Returns:
            bool: 시장 운영시간 여부
        """
        if target_time is None:
            target_time = datetime.now()
        
        current_time = target_time.time()
        return self.market_open_time <= current_time <= self.market_close_time

    def should_terminate_program(self, target_time: datetime = None) -> Tuple[bool, str]:
        """
        프로그램을 종료해야 하는지 판단
        
        Args:
            target_time: 확인할 시간 (None이면 현재 시간)
            
        Returns:
            Tuple[bool, str]: (종료 여부, 종료 사유)
        """
        if target_time is None:
            target_time = datetime.now()
        
        # 1. 공휴일 체크
        is_holiday_result, holiday_name = self.is_holiday(target_time)
        if is_holiday_result:
            return True, f"오늘은 {holiday_name}입니다. 주식시장이 휴장합니다."
        
        # 2. 시간 체크 (16시 이후)
        current_time = target_time.time()
        if current_time >= self.after_hours_limit:
            return True, f"장 마감 후 시간입니다. (현재: {current_time.strftime('%H:%M')})"
        
        # 3. 너무 이른 시간 체크 (6시 이전)
        early_limit = time(6, 0)
        if current_time < early_limit:
            return True, f"너무 이른 시간입니다. (현재: {current_time.strftime('%H:%M')})"
        
        return False, ""

    def get_market_status(self, target_time: datetime = None) -> dict:
        """
        시장 상태 종합 정보 반환
        
        Args:
            target_time: 확인할 시간 (None이면 현재 시간)
            
        Returns:
            dict: 시장 상태 정보
        """
        if target_time is None:
            target_time = datetime.now()
        
        is_holiday_result, holiday_name = self.is_holiday(target_time)
        is_market_time = self.is_market_hours(target_time)
        should_terminate, terminate_reason = self.should_terminate_program(target_time)
        
        # 다음 거래일 계산
        next_trading_day = self._get_next_trading_day(target_time)
        
        return {
            "current_time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
            "is_holiday": is_holiday_result,
            "holiday_name": holiday_name,
            "is_market_hours": is_market_time,
            "should_terminate": should_terminate,
            "terminate_reason": terminate_reason,
            "next_trading_day": next_trading_day.strftime("%Y-%m-%d") if next_trading_day else None,
            "market_open_time": self.market_open_time.strftime("%H:%M"),
            "market_close_time": self.market_close_time.strftime("%H:%M"),
            "program_stop_time": self.after_hours_limit.strftime("%H:%M")
        }

    def _get_next_trading_day(self, current_date: datetime) -> datetime:
        """다음 거래일 계산"""
        next_day = current_date + timedelta(days=1)
        
        # 최대 10일까지만 확인 (무한루프 방지)
        for _ in range(10):
            is_holiday_result, _ = self.is_holiday(next_day)
            if not is_holiday_result:
                return next_day
            next_day += timedelta(days=1)
        
        return None

    def wait_until_market_hours(self, check_interval: int = 300) -> bool:
        """
        시장 개장시간까지 대기
        
        Args:
            check_interval: 체크 간격 (초)
            
        Returns:
            bool: 정상적으로 시장 개장시간에 도달했는지 여부
        """
        import time
        
        while True:
            should_terminate, reason = self.should_terminate_program()
            if should_terminate:
                self.logger.info(f"대기 중 종료 조건 발생: {reason}")
                return False
            
            if self.is_market_hours():
                self.logger.info("시장 개장시간에 도달했습니다.")
                return True
            
            current_time = datetime.now()
            self.logger.info(f"시장 개장 대기 중... (현재: {current_time.strftime('%H:%M')})")
            time.sleep(check_interval)


def check_market_schedule_and_exit():
    """
    시장 스케줄을 체크하고 필요시 프로그램 종료
    분석 프로그램 시작 시 호출하는 함수
    """
    market_checker = KoreanMarketSchedule()
    market_status = market_checker.get_market_status()
    
    logger = logging.getLogger(__name__)
    
    # 상태 정보 로깅
    logger.info("=" * 60)
    logger.info("📅 한국 주식시장 스케줄 체크")
    logger.info("=" * 60)
    logger.info(f"🕐 현재 시간: {market_status['current_time']}")
    logger.info(f"📊 시장 운영시간: {market_status['market_open_time']} ~ {market_status['market_close_time']}")
    logger.info(f"⏰ 프로그램 종료시간: {market_status['program_stop_time']} 이후")
    
    if market_status['is_holiday']:
        logger.info(f"🏖️ 공휴일: {market_status['holiday_name']}")
    else:
        logger.info("💼 정상 거래일")
    
    if market_status['is_market_hours']:
        logger.info("🟢 현재 시장 운영시간 중")
    else:
        logger.info("🔴 현재 시장 운영시간 외")
    
    if market_status['next_trading_day']:
        logger.info(f"📅 다음 거래일: {market_status['next_trading_day']}")
    
    # 종료 조건 체크
    if market_status['should_terminate']:
        logger.info("=" * 60)
        logger.info("🛑 프로그램 종료 조건 충족")
        logger.info(f"📝 종료 사유: {market_status['terminate_reason']}")
        logger.info("=" * 60)
        
        # Discord 알림 (선택사항)
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if webhook_url:
            try:
                import requests
                message = f"🛑 **[프로그램 자동 종료]**\n📅 {market_status['current_time']}\n📝 {market_status['terminate_reason']}"
                requests.post(webhook_url, json={"content": message}, timeout=10)
            except Exception as e:
                logger.warning(f"Discord 알림 전송 실패: {e}")
        
        # 프로그램 종료
        logger.info("프로그램을 종료합니다.")
        print("장 운영시간이 아닙니다. 프로그램을 종료합니다.")
        exit(0)
    else:
        logger.info("✅ 프로그램 실행 조건 충족")
        logger.info("=" * 60)
        return True


def test_holiday_api():
    """공휴일 API 연결 테스트"""
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    api_key = os.getenv("HOLIDAY_API_KEY")
    
    print("=" * 60)
    print("🔍 공휴일 API 연결 테스트")
    print("=" * 60)
    
    if not api_key:
        print("❌ HOLIDAY_API_KEY가 .env 파일에 설정되지 않았습니다.")
        print("💡 .env 파일에 다음과 같이 추가하세요:")
        print("HOLIDAY_API_KEY=your_actual_api_key_here")
        return False
    
    if api_key in ['your_holiday_api_key_here', 'your_api_key_here']:
        print("❌ HOLIDAY_API_KEY가 placeholder 값입니다.")
        print("💡 실제 API 키로 변경해주세요.")
        return False
    
    print(f"✅ API 키 확인됨: {api_key[:10]}...")
    
    # API 테스트
    try:
        url = "http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService/getHoliDeInfo"
        params = {
            'serviceKey': api_key,
            'pageNo': '1',
            'numOfRows': '5',
            'solYear': '2025',
        }
        
        print("📡 API 요청 중...")
        response = requests.get(url, params=params, timeout=10)
        
        print(f"📊 응답 상태: {response.status_code}")
        print(f"📄 응답 길이: {len(response.text)} bytes")
        print(f"🔍 응답 미리보기:")
        print(response.text[:300] + "..." if len(response.text) > 300 else response.text)
        
        if response.status_code == 200:
            # 응답 내용 확인
            if "SERVICE_KEY_IS_NOT_REGISTERED_ERROR" in response.text:
                print("❌ API 키가 해당 서비스에 등록되지 않았습니다!")
                print("💡 해결방법:")
                print("   1. https://www.data.go.kr 접속")
                print("   2. '특일 정보' 또는 '한국천문연구원' 검색") 
                print("   3. '한국천문연구원_특일 정보' 클릭")
                print("   4. '활용신청' 버튼 클릭하여 신청")
                print("   5. 승인 후 새로운 인증키 확인")
                return False
            elif "SERVICE ERROR" in response.text:
                print("❌ API 서비스 오류가 발생했습니다.")
                print(f"오류 내용: {response.text}")
                return False
            else:
                print("✅ API 연결 성공!")
                return True
        else:
            print(f"❌ API 오류: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"❌ API 테스트 실패: {e}")
        return False


if __name__ == "__main__":
    # 테스트 코드
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # 1. API 연결 테스트
    print("🧪 공휴일 API 테스트를 먼저 실행합니다...")
    api_test_result = test_holiday_api()
    print()
    
    # 2. 시장 스케줄 체크
    market_checker = KoreanMarketSchedule()
    
    # 현재 상태 체크
    status = market_checker.get_market_status()
    print("현재 시장 상태:")
    for key, value in status.items():
        print(f"  {key}: {value}")
    
    # 특정 날짜 테스트
    test_dates = [
        datetime(2025, 1, 1),   # 신정
        datetime(2025, 1, 29),  # 설날
        datetime(2025, 8, 18),  # 평일
        datetime(2025, 8, 17),  # 토요일
    ]
    
    print("\n날짜별 테스트:")
    for test_date in test_dates:
        is_holiday, holiday_name = market_checker.is_holiday(test_date)
        should_terminate, reason = market_checker.should_terminate_program(test_date)
        print(f"  {test_date.strftime('%Y-%m-%d %A')}: 공휴일={is_holiday}({holiday_name}), 종료={should_terminate}({reason})")
    
    # API 테스트 결과에 따른 권장사항
    print("\n" + "=" * 60)
    if api_test_result:
        print("🎉 API가 정상 작동합니다! 실시간 공휴일 데이터를 사용할 수 있습니다.")
    else:
        print("⚠️ API 연결에 문제가 있지만, 하드코딩된 데이터로 정상 작동합니다.")
        print("💡 공휴일 API 키 발급 방법:")
        print("   1. https://www.data.go.kr 접속")
        print("   2. 회원가입 후 로그인")
        print("   3. '특일 정보' 검색")
        print("   4. '활용신청' 버튼 클릭")
        print("   5. 발급받은 키를 .env 파일에 추가")
    print("=" * 60)
