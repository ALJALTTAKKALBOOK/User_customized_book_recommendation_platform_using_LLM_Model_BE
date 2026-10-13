# app/domains/users/schema.py
from pydantic import BaseModel, EmailStr, ConfigDict
from pydantic import BaseModel, field_validator
from app.core.constants import ALL_SUB_CATEGORIES


# --------------- Request DTOs ------------------
class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str
    nickname: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    
class OnboardingRequest(BaseModel):
    # 유저가 선택한 세부 카테고리와 숙련도 점수 (예: {"Spring": 3, "Python": 5})
    proficiencies: dict[str, int]

    #  Spring의 @Valid + Custom Validator 역할
    @field_validator('proficiencies')
    @classmethod
    def validate_categories(cls, proficiencies: dict[str, int]):
        for key, score in proficiencies.items():
            # 1. 키 검증: 우리가 허락한 카테고리 안에 있는가?
            if key not in ALL_SUB_CATEGORIES:
                raise ValueError(f"허용되지 않은 카테고리입니다: {key}")
            # 2. 점수 검증: 0 ~ 10점 사이인가?
            if not (0 <= score <= 10):
                raise ValueError(f"점수는 0에서 10 사이여야 합니다: {key}={score}")
        return proficiencies

# --------------- Response DTOs ------------------
class UserResponse(BaseModel):
    id: int
    email: str
    nickname: str
    domain_levels: dict[str, int]  # JSONB 데이터가 파이썬 dict로 예쁘게 나옵니다.

    # model_validate 함수가 작동시 객체의 해시맵을 뒤지는것이 아닌 객체의 속성을 뒤지도록함
    model_config = ConfigDict(from_attributes=True)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"