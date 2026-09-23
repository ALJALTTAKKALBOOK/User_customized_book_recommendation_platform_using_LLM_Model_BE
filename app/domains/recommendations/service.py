import json
import logging
import numpy as np
from typing import Dict, TypedDict, List, AsyncGenerator, Any, Union, cast
from typing_extensions import NotRequired 
from pydantic import BaseModel, Field     
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, case

from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig 

from app.domains.users.model import User, MockUser
from app.domains.books.model import Book
from app.core.constants import GENRES, ALL_SUB_CATEGORIES
from app.core.llm_helper import llm_analyzer, llm_creator, embeddings_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 설정값: 거리 임계값 및 재시도 상한
# pgvector 코사인 거리 = 1 - cosine_similarity (0에 가까울수록 유사)
# -0.15 보정 후 최상위 1위 도서의 거리가 0.65를 초과하면 유사도 부족(Low Confidence)으로 판단
# ---------------------------------------------------------
MAX_RETRIES = 1
DISTANCE_CONFIDENCE_THRESHOLD = 0.65

# ---------------------------------------------------------
# 0. 시맨틱 라우팅 유틸리티 (메모리 캐싱)
# ---------------------------------------------------------
CATEGORY_EMBEDDING_CACHE: Dict[str, np.ndarray] = {}

def calculate_cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    return float(np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2)))

CATEGORY_DESCRIPTIONS = {
    "컴퓨터공학": "컴퓨터공학 기초 이론서. 자료구조, 알고리즘, 컴퓨터 구조, 이산수학, 운영체제 원리, 컴파일러 등 학부 전공서. 컴퓨터 역사 및 기술 발전사 교양서 포함.",
    "IT일반": "비전공자를 위한 IT 교양서. 디지털 리터러시, IT 산업 트렌드, 빅테크 비즈니스 모델, AI/챗GPT 교양서, IT 용어 해설, 개발자와 비개발자 간 소통.",
    "OS": "운영체제 전문서. 프로세스 관리, 멀티스레딩, 동시성 제어, 데드락, 메모리 관리, 스케줄링, 파일 시스템, 리눅스 커널 분석.",
    "네트워크": "컴퓨터 네트워크 전문서. TCP/IP, OSI 7계층, 소켓 프로그래밍, 라우팅, 패킷 교환, 네트워크 프로토콜.",
    "보안/해킹": "정보보안 및 해킹 전문서. 웹 취약점(XSS, SQL Injection), 침투 테스트, 리버스 엔지니어링, 악성코드 분석, 암호학.",
    "데이터베이스": "데이터베이스 전문서. RDBMS, SQL, 쿼리 튜닝, 인덱스 최적화, 실행 계획 분석, NoSQL(Redis, MongoDB), 데이터 모델링.",
    "개발방법론": "소프트웨어 개발 프로세스. 애자일, 스크럼, TDD, 리팩토링, 클린 코드, 디자인 패턴, Git 브랜치 전략, CI/CD, 데브옵스, 프로젝트 관리.",
    "웹프로그래밍": "웹 애플리케이션 개발서. 백엔드(스프링 부트, Node.js, Django), 프론트엔드(React, Vue, TypeScript), REST API, MSA, 대용량 트래픽 처리.",
    "프로그래밍 언어": "특정 프로그래밍 언어 자체의 문법과 원리. 파이썬, 자바, C/C++, JavaScript 등의 언어 입문서 및 심화서. 객체지향 원리, 메모리 관리, 모던 문법.",
    "모바일프로그래밍": "모바일 앱 개발서. iOS(Swift, RxSwift, MVVM), Android(Kotlin), 크로스플랫폼(Flutter, React Native) 네이티브 앱 개발.",
}

async def get_or_embed_categories() -> Dict[str, np.ndarray]:
    global CATEGORY_EMBEDDING_CACHE
    if not CATEGORY_EMBEDDING_CACHE:
        for category in ALL_SUB_CATEGORIES:
            description = CATEGORY_DESCRIPTIONS.get(category, category)
            text_to_embed = f"{category}: {description}"
            vector = await embeddings_client.aembed_query(text_to_embed)
            CATEGORY_EMBEDDING_CACHE[category] = np.array(vector)
    return CATEGORY_EMBEDDING_CACHE

# ---------------------------------------------------------
# 1. State 및 Pydantic 정의
# ---------------------------------------------------------
class AgentState(TypedDict):
    query: str
    domain_levels: dict[str, int]
    
    hyde_target_genre: NotRequired[str]  
    hyde_target_category: NotRequired[str]      
    hyde_difficulty_level: NotRequired[int]
    
    hyde_summary: NotRequired[str]
    hyde_keyword: NotRequired[list[str]]
    
    recommended_books: NotRequired[List[dict[str, Any]]]
    top_distance: NotRequired[float]          
    final_answer: NotRequired[str]
    
    retry_count: NotRequired[int]             
    is_broadening_mode: NotRequired[bool]   

class ContextAnalysisOutput(BaseModel):
    target_genre: str = Field(description="가장 적합한 장르(대분류)")
    target_sub_category: str = Field(
        description="질문의 핵심 주제를 묘사하는 짧고 명확한 가상 카테고리명 (예: 'OS', '프로그래밍언어')"
    )
    calculated_difficulty: int = Field(description="계산된 난이도 (0~10)")

class HydeOutput(BaseModel):
    summary: str = Field(
        description="가상 도서 핵심 요약 (100자 이내, 주제+대상+접근법 한 문장)"
    )
    keywords: list[str] = Field(
        description="키워드 5개: topic 2개 + approach 1~2개 + target 1~2개",
        min_length=5,
        max_length=5,
    )

# ---------------------------------------------------------
# 2. Node 함수들
# ---------------------------------------------------------

# Node 1: 컨텍스트 분석 (1회만 수행)
async def analyze_context_node(state: AgentState) -> dict[str, Any]:
    prompt = ChatPromptTemplate.from_messages([
        ("system",
            f"너는 도서 추천을 위한 컨텍스트 분석기야. 아래 규칙을 엄격히 따라 분석해.\n"
            f"[허용된 장르(대분류)]: {', '.join(GENRES)}\n\n"
            "1. 유저의 질문을 분석해서, 어떤 IT 분야/주제의 책을 찾는지 가장 잘 묘사하는 "
            "**가상의 카테고리명을 자유롭게 생성**해. 핵심 키워드가 2~4개 포함되는 1줄로 작성해.\n"
            "2. [허용된 장르(대분류)] 중 가장 적합한 장르 하나를 선택해.\n"
            "3. 질문에 '기초, 처음, 쉬운' 등이 있으면 유저 숙련도(domain_levels)의 해당 분야 레벨을 기준으로 -1 하향해.\n"
            "4. '심화, 실전, 어려운' 등이 있으면 난이도 +2 상향해.\n"
            "5. 만약 질문한 분야가 유저 숙련도(domain_levels)에 아예 없다면 기본 난이도를 1로 설정해."
        ),
        ("user", "내 숙련도: {domain_levels}\n내 질문: {query}")
    ])

    structured_llm = llm_analyzer.with_structured_output(ContextAnalysisOutput)
    chain = prompt | structured_llm
    
    raw_result = await chain.ainvoke({"domain_levels": state["domain_levels"], "query": state["query"]})
    result = cast(ContextAnalysisOutput, raw_result)

    description_vector = np.array(
        await embeddings_client.aembed_query(result.target_sub_category)
    )

    category_cache = await get_or_embed_categories()
    
    best_category = ""
    highest_score = -1.0

    for category_name, category_vector in category_cache.items():
        score = calculate_cosine_similarity(description_vector, category_vector)
        if score > highest_score:
            highest_score = score
            best_category = category_name

    logger.info(f"[Node 1] 시맨틱 라우팅 완료: '{best_category}' (유사도: {highest_score:.4f})")

    return {
        "hyde_target_genre": result.target_genre,
        "hyde_target_category": best_category,
        "hyde_difficulty_level": result.calculated_difficulty
    }

# Node 2: 가상 도서(HyDE) 생성 (Broadening 재시도 지원)
async def generate_hyde_node(state: AgentState) -> dict[str, Any]:
    query = state["query"]
    target_category = state.get("hyde_target_category", "IT")
    target_level = state.get("hyde_difficulty_level", 5)
    is_broadening = state.get("is_broadening_mode", False)

    retry_instruction = ""
    if is_broadening:
        retry_instruction = (
            f"\n[ 검색 신뢰도 부족에 따른 가상 도서 재생성 지침]\n"
            f"- 이전 가상 도서의 줄거리가 너무 지엽적이어서 DB 내 도서들과 의미적 거리가 멀었습니다.\n"
            f"- 특정 마이너 라이브러리나 좁은 용어에 집중하지 마세요.\n"
            f"- '{target_category}' 분야의 표준적인 핵심 개념 중심으로 "
            f"검색 풀을 넓힐 수 있도록 줄거리를 포괄적인 톤으로 작성하세요.\n"
        )

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         f"너는 도서 큐레이터야. 유저의 질문과 타겟 정보를 바탕으로, "
         f"DB 벡터 검색에 사용할 '이상적인 가상 도서'를 생성해.\n"
         f"{retry_instruction}\n"
         "[줄거리 작성 규칙]\n"
         "- 분량: 100자 이내, 한 문장.\n"
         "- 다음 3가지를 반드시 포함:\n"
         "  1. 주제 (어떤 기술/개념)\n"
         "  2. 대상 (누구를 위한 — 입문자/실무자/연구자/비전공자 등)\n"
         "  3. 접근법 (어떻게 — 사례 중심/실습 중심/이론 중심/역사적 관점/튜토리얼 등)\n"
         "- 난이도별 어휘 선택:\n"
         "  · 0~2: \"비전공자에게\", \"~를 처음 접하는 사람에게\", \"기초부터 단계별로\"\n"
         "  · 3~5: \"실무에서 자주 마주치는 ~를 단계별로\", \"입문자에게 실습 중심으로\"\n"
         "  · 6~8: \"~의 내부 동작 원리를 심화 분석한\", \"실무자에게 딥다이브로\"\n"
         "  · 9~10: \"최신 연구 동향과 ~를 분석한\", \"연구자/전문가에게 심화 학습서로\"\n"
         "- 타겟 카테고리의 핵심 개념을 1~2개 자연스럽게 포함하라.\n"
         "- 유저 질문의 의도를 반드시 줄거리에 반영하라.\n"
         "- 마케팅 문구 및 추상적 표현 금지.\n\n"
         "[키워드 추출 규칙]\n"
         "정확히 5개의 키워드를 아래 3개 축으로 추출하라.\n"
         "1. 주제 (topic) — 2개\n"
         "2. 접근방식 (approach) — 1~2개 [\"역사적 관점\", \"사례 중심\", \"이론 중심\", \"실습 중심\", \"개념 정리\", \"튜토리얼\", \"레퍼런스\", \"프로젝트 기반\", \"비교 분석\", \"시각적 설명\", \"딥다이브\", \"문제 해결 중심\"]\n"
         "3. 대상/성격 (target) — 1~2개 [\"비전공자 교양서\", \"입문자용\", \"중급자용\", \"실무자용\", \"연구자용\", \"수험서\", \"참고서\", \"기초 학습서\", \"심화 학습서\"]\n"
         "- 5개 키워드를 라벨 없이 하나의 리스트로 합쳐서 반환하라."
        ),
        ("user", "유저 질문: {query}\n타겟 카테고리: {category}\n타겟 난이도: {level}")
    ])

    structured_llm = llm_creator.with_structured_output(HydeOutput)
    chain = prompt | structured_llm
    
    raw_result = await chain.ainvoke({"query": query, "category": target_category, "level": target_level})
    result = cast(HydeOutput, raw_result)
    
    return {
        "hyde_summary": result.summary,
        "hyde_keyword": result.keywords
    }

# Node 3: 벡터 검색 및 가중 거리(Weighted Distance) 산출
async def retrieve_books_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    configurable_data = config.get("configurable", {})
    db_session = configurable_data.get("db_session")
    
    if not db_session:
        logger.error("DB 세션이 주입되지 않았습니다!")
        return {"recommended_books": [], "top_distance": 2.0}
    
    hyde_target_category = state.get("hyde_target_category")
    hyde_difficulty_level = state.get("hyde_difficulty_level")
    hyde_summary = state.get("hyde_summary")
    hyde_keyword = state.get("hyde_keyword", [])
    
    if not hyde_summary:
        return {"recommended_books": [], "top_distance": 2.0}

    keyword_str = ", ".join(hyde_keyword)
    hyde_text_to_embed = f"난이도: {hyde_difficulty_level}\n키워드: {keyword_str}\n줄거리: {hyde_summary}"
    
    query_vector = await embeddings_client.aembed_query(hyde_text_to_embed)
    raw_distance = Book.embedding.cosine_distance(query_vector)

    # 카테고리 일치 도서에 -0.15 감쇄 부여
    weighted_distance = raw_distance - case(
        (Book.sub_category == hyde_target_category, 0.15),
        else_=0.0
    )
        
    # 도서 객체와 함께 계산된 weighted_distance 컬럼도 함께 select
    stmt = select(Book, weighted_distance.label("calc_dist")).order_by(weighted_distance).limit(3)
    result = await db_session.execute(stmt)
    rows = result.all()

    if not rows:
        return {"recommended_books": [], "top_distance": 2.0}

    # 최상위 도서의 보정 거리 확인
    top_distance = float(rows[0].calc_dist)

    recommended_books_list = [{
        "book_id": book.id,
        "title": book.title,
        "author": book.author,
        "difficulty": book.difficulty,
        "summary": book.summary,
        "cover_url": book.cover_url,
        "sub_category": book.sub_category,
        "distance": round(float(dist), 4)
    } for book, dist in rows]
            
    return {
        "recommended_books": recommended_books_list,
        "top_distance": top_distance
    }

# ---------------------------------------------------------
# 3. 라우팅 판단 및 상태 갱신 노드
# ---------------------------------------------------------

def evaluate_retrieval_confidence(state: AgentState) -> str:
    """
    최상위 책의 보정 거리가 임계값(0.65)을 초과하면 검색 신뢰도가 낮다고 판단,
    Node 2(HyDE)로 돌아가 더 넓은 범위로 가상 도서를 재생성합니다.
    """
    top_distance = state.get("top_distance", 2.0)
    retry_count = state.get("retry_count", 0)

    logger.info(f"[신뢰도 평가] 1위 도서 보정 거리: {top_distance:.4f} (임계값: {DISTANCE_CONFIDENCE_THRESHOLD})")

    # 거리가 멀어 신뢰도가 떨어지고, 재시도 횟수가 남아있는 경우
    if top_distance > DISTANCE_CONFIDENCE_THRESHOLD and retry_count < MAX_RETRIES:
        logger.warning(f"검색 거리가 너무 멉니다({top_distance:.4f} > {DISTANCE_CONFIDENCE_THRESHOLD}). HyDE 재생성 모드로 전환합니다.")
        return "retry_hyde"

    return "proceed"

# 재시도 카운트 및 확장 모드 활성화 노드
def prepare_broadening_node(state: AgentState) -> dict[str, Any]:
    return {
        "retry_count": state.get("retry_count", 0) + 1,
        "is_broadening_mode": True
    }

# Node 4: 최종 답변 생성
async def generate_answer_node(state: AgentState) -> dict[str, Any]:
    query = state["query"]
    domain_levels = state["domain_levels"]
    recommended_books = state.get("recommended_books", [])
    
    if not recommended_books:
        return {"final_answer": "죄송합니다. 현재 회원님의 조건에 맞는 적합한 도서를 찾지 못했습니다."}
        
    books_context = ""
    for idx, book in enumerate(recommended_books, 1):
        books_context += (
            f"[{idx}번 책]\n제목: {book['title']}\n저자: {book['author']}\n"
            f"분야: {book.get('sub_category', 'IT')}\n난이도: {book['difficulty']}/10\n"
            f"줄거리: {book['summary']}\n\n"
        )

    prompt = ChatPromptTemplate.from_messages([
        ("system", 
         "너는 친절하고 전문적인 IT 도서 추천 비서야.\n"
         "유저의 [질문]과 [현재 숙련도]를 분석해서, 내가 제공한 [추천 도서 목록]의 책들이 왜 유저에게 맞는지 설명해 줘.\n\n"
         "[절대 규칙]\n"
         "1. 제공된 [추천 도서 목록]의 책은 단 한 권도 빠짐없이 각각 언급하고 추천 사유를 작성하라.\n"
         "2. 책 제목을 명확히 적고, 그 책이 유저의 난이도와 질문 의도에 부합하는 이유를 1~2줄로 핵심만 설명하라.\n"
         "3. 없는 책을 지어내거나 누락하지 마라."
        ),
        ("user", "내 숙련도: {domain_levels}\n내 질문: {query}\n\n[추천 도서 목록]\n{books_context}")
    ])

    chain = prompt | llm_creator
    response = await chain.ainvoke({"domain_levels": domain_levels, "query": query, "books_context": books_context})
    
    return {"final_answer": str(response.content)}

# ---------------------------------------------------------
# 4. StateGraph 컴파일 (순환 그래프 구축)
# ---------------------------------------------------------
workflow = StateGraph(AgentState)

workflow.add_node("analyze_context", analyze_context_node)
workflow.add_node("generate_hyde", generate_hyde_node)
workflow.add_node("retrieve_books", retrieve_books_node)
workflow.add_node("prepare_broadening", prepare_broadening_node)
workflow.add_node("generate_answer", generate_answer_node)

# 기본 전진 엣지
workflow.set_entry_point("analyze_context")
workflow.add_edge("analyze_context", "generate_hyde")
workflow.add_edge("generate_hyde", "retrieve_books")

# 🌟 신뢰도 기반 조건부 엣지
workflow.add_conditional_edges(
    "retrieve_books",
    evaluate_retrieval_confidence,
    {
        "retry_hyde": "prepare_broadening",  # 거리가 멀면 확장 플래그 켜고
        "proceed": "generate_answer"        # 거리가 가까우면 바로 답변 생성
    }
)

# 🌟 Node 1로 가지 않고 Node 2로 바로 회귀 (비용/시간 절약)
workflow.add_edge("prepare_broadening", "generate_hyde")
workflow.add_edge("generate_answer", END)

agent_app = workflow.compile()

# =====================================================================
# 5. FastAPI SSE 스트리밍 서비스 함수
# =====================================================================

async def stream_book_recommendation_service(
    query: str, 
    current_user: User, 
    db: AsyncSession
) -> AsyncGenerator[str, None]:
    
    initial_state: AgentState = {
        "query": query,
        "domain_levels": current_user.domain_levels,
        "retry_count": 0,
        "is_broadening_mode": False
    }
    
    config: RunnableConfig = {"configurable": {"db_session": db}}
    last_retrieved_books: List[dict] = []
    
    async for event in agent_app.astream_events(initial_state, config=config, version="v1"):
        kind = event.get("event")
        metadata = event.get("metadata", {})
        node_name = metadata.get("langgraph_node")
        event_data = event.get("data", {})
        
        # 검색 결과 갱신
        if kind == "on_chain_end" and node_name == "retrieve_books":
            output_data = event_data.get("output", {})
            last_retrieved_books = output_data.get("recommended_books", [])

        # 재시도 루프 진입 시 사용자에게 상태 푸시
        elif kind == "on_chain_start" and node_name == "prepare_broadening":
            yield "event: status\ndata: 🔍 더 광범위한 연관 도서를 탐색하기 위해 검색 조건을 조정 중입니다...\n\n"

        # 답변 생성 노드 진입 시 확정된 책 리스트 전송
        elif kind == "on_chain_start" and node_name == "generate_answer":
            if last_retrieved_books:
                books_json = json.dumps(last_retrieved_books, ensure_ascii=False)
                yield f"event: books\ndata: {books_json}\n\n"

        # 토큰 스트리밍
        elif kind == "on_chat_model_stream" and node_name == "generate_answer":
            chunk = event_data.get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                text = str(chunk.content)
                sse_lines = text.split('\n')
                sse_data = "\n".join([f"data: {line}" for line in sse_lines])
                yield f"{sse_data}\n\n"

async def get_book_recommendation_service_test(
    query: str, 
    current_user: Union[MockUser, User],
    db: AsyncSession
) -> Dict[str, Any]:
    
    initial_state: AgentState = {
        "query": query,
        "domain_levels": current_user.domain_levels,
        "retry_count": 0,
        "is_broadening_mode": False
    }
    
    config: RunnableConfig = {"configurable": {"db_session": db}}
    final_state = await agent_app.ainvoke(initial_state, config=config)
    
    return {
        "final_category": final_state.get("hyde_target_category", ""),
        "top_distance": final_state.get("top_distance", 0.0),
        "retry_count": final_state.get("retry_count", 0),
        "is_broadening_mode": final_state.get("is_broadening_mode", False),
        "recommended_books": final_state.get("recommended_books", []),
        "final_answer": final_state.get("final_answer", "")
    }