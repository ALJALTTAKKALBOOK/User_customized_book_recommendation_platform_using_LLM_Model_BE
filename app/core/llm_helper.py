import json
import logging
from openai import AsyncOpenAI, APIError, RateLimitError
from app.core.config import settings

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# 💡 프롬프트 수정: 텍스트 퀄리티와 '체감 난이도'를 종합적으로 판단하도록 지시합니다.
SYSTEM_PROMPT = """너는 사용자의 독서 근력을 평가하는 '독서 수준 평가 전문가'야. 
사용자가 작성한 [독후감 내용]과 본인이 느낀 [체감 난이도(1~5)]를 종합하여 순수한 JSON 객체로 응답해.

1. "domain": 독후감의 핵심 분야 (예: 경제, 소설, 과학, 철학, IT 등. 10자 이내 단답형)
2. "change": 사용자의 이해도 성장 수치 (-5 ~ +5 정수)

[입체적 채점 가이드]
* 체감 난이도가 높음 (4~5): 어려운 책을 끝까지 읽어낸 끈기를 칭찬해야 해. 
  - 후기가 짧거나 투박해도("어려웠지만 겨우 다 읽었다") +1 ~ +2점의 기본 보상을 줘.
  - 후기에 깊은 통찰까지 담겨있다면 +3 ~ +5점의 높은 가산점을 줘.
* 체감 난이도가 보통/쉬움 (1~3): 책이 쉽다고 느꼈으므로 글의 퀄리티를 조금 더 엄격하게 봐.
  - 내용을 잘 요약하고 배운 점이 명확하면 +1 ~ +3점을 줘.
  - "재밌었다" 등 너무 짧고 성의가 없으면 0점을 줘.
* 무조건 감점 (-1 ~ -5): 난이도와 상관없이 책의 내용을 완전히 왜곡했거나, 욕설, 의미 없는 자음/모음 남발(ㅋㅋ, ㅎㅎ), 표절 의심 문장이라면 가차 없이 마이너스 점수를 부여해.

출력 형식 예시:
{"domain": "역사", "change": 2}
"""

# 💡 함수 파라미터 변경: felt_difficulty 를 추가로 받습니다.
async def analyze_review_with_llm(content: str, felt_difficulty: int) -> dict:
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                # 💡 유저 메시지 변경: LLM에게 난이도와 후기를 함께 묶어서 던져줍니다.
                {
                    "role": "user", 
                    "content": f"[체감 난이도]: {felt_difficulty} / 5\n[독후감 내용]:\n{content}"
                }
            ],
            response_format={"type": "json_object"}, 
            temperature=0.3, 
            max_tokens=100 
        )
        
        raw_content = response.choices[0].message.content
        logger.info(f"LLM Raw Response (Difficulty: {felt_difficulty}): {raw_content}")
        
        result = json.loads(raw_content)
        domain = str(result.get("domain", "기타")).strip()
        
        try:
            change = int(result.get("change", 0))
            # LLM 폭주 방지 방어 로직 (그대로 유지)
            change = max(-5, min(5, change)) 
        except ValueError:
            change = 0
            
        return {"domain": domain, "change": change}

    except json.JSONDecodeError as e:
        logger.error(f"JSON 파싱 실패: {e}")
        return {"domain": "기타", "change": 0}
    except Exception as e:
        logger.error(f"LLM API 에러: {e}")
        return {"domain": "기타", "change": 0}