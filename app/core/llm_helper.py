import json
import logging
from typing import Dict, Any
from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

async def generate_json_with_llm(
    system_prompt: str, 
    user_prompt: str, 
    temperature: float = 0.3
) -> Dict[str, Any]:
    """
    범용적인 LLM JSON 응답 생성 함수입니다.
    어느 도메인이든 프롬프트만 넘겨주면 API를 호출해서 파이썬 딕셔너리(dict)로 돌려줍니다.

    [필수 주의사항!]
    OpenAI의 JSON 모드를 사용하므로, `system_prompt` 텍스트 안에 
    반드시 "JSON으로 응답해", "JSON 형식" 같은 단어가 포함되어야 에러가 안 납니다!

    [사용 예시]
    ```python
    SYSTEM_PROMPT = \"\"\"너는 번역기야. 입력된 과일 이름을 한국어로 번역해서 순수한 JSON으로 반환해.
    출력 예시: {"korean_name": "사과"} \"\"\"
    USER_PROMPT = "apple"

    # 1. 함수 호출
    result_dict = await generate_json_with_llm(SYSTEM_PROMPT, USER_PROMPT)

    # 2. 에러 방어 및 데이터 사용
    if not result_dict:
        return "번역 실패" # 에러 시 빈 딕셔너리 {} 반환됨
    
    return result_dict.get("korean_name", "알수없음") # 출력: "사과"
    ```

    :param system_prompt: LLM의 역할과 출력 포맷(JSON)을 지시하는 프롬프트
    :param user_prompt: LLM이 실제로 처리할 데이터 (예: 유저 작성 글)
    :param temperature: 창의성 조절 (0.0: 일관됨 ~ 1.0: 창의적 / 기본값 0.3)
    :return: 파싱이 완료된 JSON 딕셔너리 (실패 시 빈 딕셔너리 {} 반환)
    """
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"}, 
            temperature=temperature,
        )
        
        raw_content = response.choices[0].message.content
        logger.info(f"[LLM Helper] Raw Response: {raw_content}")
        
        return json.loads(raw_content)

    except json.JSONDecodeError as e:
        logger.error(f"[LLM Helper] JSON 파싱 실패: {e}")
        return {}
    except Exception as e:
        logger.error(f"[LLM Helper] LLM API 에러: {e}")
        return {}