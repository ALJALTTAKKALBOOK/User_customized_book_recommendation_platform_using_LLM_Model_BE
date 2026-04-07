import json
import logging
from typing import Dict, Any
from openai import AsyncOpenAI
#  LangChain 전용 임포트 추가
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

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
       
        if not raw_content:
            logger.warning("[LLM Helper] 빈 응답이 반환되었습니다.")
            return {}
            
        return json.loads(raw_content)

    except json.JSONDecodeError as e:
        logger.error(f"[LLM Helper] JSON 파싱 실패: {e}")
        return {}
    except Exception as e:
        logger.error(f"[LLM Helper] LLM API 에러: {e}")
        return {}
    
    

# =====================================================================
# 2. LangChain 전용 객체 및 팩토리 (Agent, RAG, Node 등에서 공용 사용)
# =====================================================================

#  [공용 객체 1] 분석용 LLM (환각 방지, 일관성 유지용 / 온도 0)
# - 사용처: Context 분석(Node 1), 유저 의도 파악 등 정확해야 할 때
llm_analyzer = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0,
    api_key = SecretStr(settings.OPENAI_API_KEY)
)

#  [공용 객체 2] 창작용 LLM (유창한 문장, 추천 사유 생성용 / 온도 0.7)
# - 사용처: 가상 책 생성(HyDE), 유저에게 추천 이유 설명할 때
llm_creator = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.7,
    api_key = SecretStr(settings.OPENAI_API_KEY)
)

#  [팩토리 함수] 특수한 설정(예: 스트리밍)이 필요할 때 찍어내는 함수
def get_langchain_llm(
    model: str = "gpt-4o-mini", 
    temperature: float = 0.0, 
    streaming: bool = False
) -> ChatOpenAI:
    """
    필요할 때마다 LangChain ChatOpenAI 객체를 생성해서 반환합니다.
    특히, SSE 스트리밍 응답을 할 때는 streaming=True로 호출해서 쓰세요.
    """
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key = SecretStr(settings.OPENAI_API_KEY),
        streaming=streaming
    )
    
embeddings_client = OpenAIEmbeddings(
    model="text-embedding-3-small",
    api_key=SecretStr(settings.OPENAI_API_KEY)  
)
    