from pydantic import BaseModel, ConfigDict, field_validator

# --------------- Request DTOs ------------------
class RecommendRequest(BaseModel):
    query: str

    @field_validator('query')
    @classmethod
    def validate_query(cls, value: str):
        stripped_value = value.strip()
        if len(stripped_value) < 5:
            raise ValueError("질문은 최소 5글자 이상 입력해주세요.")
        if len(stripped_value) > 500:
            raise ValueError("질문이 너무 깁니다. 핵심만 간결하게 적어주세요.")
        return stripped_value

# --------------- Response DTOs ------------------
class RecommendationResponse(BaseModel):
    id: int
    user_id: int
    book_id: int
    reason: str  # AI 에이전트가 작성한 스트리밍 답변의 최종 완성본

    # Service 단에서 SQLAlchemy 모델을 바로 리턴해도 Pydantic이 변환해줌
    model_config = ConfigDict(from_attributes=True)