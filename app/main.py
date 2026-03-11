from fastapi import FastAPI
from app.domains.users.router import router as user_router

# FastAPI 앱 생성
app = FastAPI(title="알잘딱깔북 API 서버", version="1.0")

# 컨트롤러(라우터) 조립하기
app.include_router(user_router, prefix="/api/users", tags=["Users"])

@app.get("/")
def health_check():
    return {"status": "서버가 정상적으로 켜졌습니다!"}