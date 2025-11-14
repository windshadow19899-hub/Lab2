# BioStar2 Attendance Gateway

이 저장소는 Suprema BioStar2 API를 이용하여 사내 출퇴근/부재 데이터를 수집하고
제공하기 위한 간단한 FastAPI 기반 웹 서비스를 포함합니다.

## 구성 요소

- `biostar2_client.py` – BioStar2 REST API에 접근하기 위한 최소한의 파이썬 클라이언트.
  - `/v2/login` 엔드포인트를 호출해 세션 토큰을 발급받고 자동으로 재사용합니다.
  - `/v2/attendance/events` 와 `/v2/attendance/leaves` 엔드포인트를 호출하여
    출퇴근 이벤트와 부재(휴가) 기록을 페이징 처리하면서 수집합니다.
- `app.py` – FastAPI 애플리케이션.
  - `/attendance` – 특정 기간의 출퇴근 이벤트를 JSON으로 반환합니다.
  - `/leaves` – 특정 기간의 부재(휴가) 정보를 반환합니다.
- `requirements.txt` – 필요한 파이썬 의존성 목록.

## 실행 방법

1. **의존성 설치**

   ```bash
   pip install -r requirements.txt
   ```

2. **환경 변수 설정**

   ```bash
   export BIOSTAR2_BASE_URL="https://<biostar2-host>"
   export BIOSTAR2_USERNAME="api-user"
   export BIOSTAR2_PASSWORD="your-password"
   # 필요 시 SSL 검증 비활성화
   export BIOSTAR2_VERIFY_SSL=false
   ```

   `.env` 파일을 사용하려면 `BIOSTAR2_ENV_FILE` 환경 변수에 경로를 지정하면 됩니다.

3. **서버 실행**

   ```bash
   uvicorn app:app --reload --host 0.0.0.0 --port 8000
   ```

4. **API 사용 예시**

   ```bash
   curl "http://localhost:8000/attendance?start=2024-01-01T00:00:00&end=2024-01-01T23:59:59"
   curl "http://localhost:8000/leaves?start=2024-01-01&end=2024-01-31&user_ids=100001,100002"
   ```

## 참고 사항

- BioStar2 서버의 실제 응답 구조가 다를 경우 `BioStar2Client` 의 `token_path`
  옵션을 이용하거나 `_extract_token` 메서드를 확장하면 됩니다.
- 대량 데이터를 가져올 경우 API의 페이지 크기(`limit`)를 적절하게 조절하거나
  야간 배치 작업을 활용하여 서버 부하를 줄이십시오.
- 개인정보 보호 규정을 준수하기 위해 HTTPS, 접근 제어, 감사 로그 등을 필수로 고려해야 합니다.
