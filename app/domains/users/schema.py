# app/domains/users/schema.py
from pydantic import BaseModel, EmailStr, ConfigDict

# --- Request DTOs ---
class UserCreateRequest(BaseModel):
    email: EmailStr
    password: str
    nickname: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

# --- Response DTOs ---
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