# 1. 자원을 최소한으로 쓰는 초경량 파이썬 3.12 슬림 버전을 기반 이미지로 사용
FROM python:3.12-slim
WORKDIR /app

# 2. 패키지 설치를 위해 requirements.txt 파일을 먼저 복사하고 설치 (빌드 캐시 활용!) [1.1.4]
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3. 나머지 내 FastAPI 백엔드 소스 코드를 컨테이너 내부로 통체로 복사
COPY . .

# 4. FastAPI 서비스를 구동 (Nginx가 내부에서 8000포트로 접속할 수 있도록 포트 오픈)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]