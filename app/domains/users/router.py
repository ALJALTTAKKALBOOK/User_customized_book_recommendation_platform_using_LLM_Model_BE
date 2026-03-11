from fastapi import APIRouter

# 도메인별 라우터 생성 (Spring의 @RestController 역할)
router = APIRouter()

@router.get("/test")
def get_user_test():
    return {"message": "유저 도메인 API 통신 성공!"}