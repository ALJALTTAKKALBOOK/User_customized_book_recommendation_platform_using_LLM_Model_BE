import json
import logging
import numpy as np
import time
from typing import Dict, TypedDict, List, AsyncGenerator, Any, Union, cast
from typing_extensions import NotRequired 
from pydantic import BaseModel, Field     
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy import case

from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig 

from app.domains.users.model import User
from app.domains.books.model import Book
from app.core.constants import GENRES, ALL_SUB_CATEGORIES
from app.core.llm_helper import llm_analyzer, llm_creator, embeddings_client
from app.domains.users.model import MockUser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 0. 시맨틱 라우팅 유틸리티 작성(최초 1회만 메모리에 캐싱)
# ---------------------------------------------------------
CATEGORY_EMBEDDING_CACHE = {}

def calculate_cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """두 벡터 간의 코사인 유사도를 계산합니다."""
    start_time = time.time()
    result = np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))
    end_time = time.time()
    print(f"코사인 유사도 계산 시간: {end_time - start_time}")
    return result

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

async def get_or_embed_categories():
    global CATEGORY_EMBEDDING_CACHE
    if not CATEGORY_EMBEDDING_CACHE:
        for category in ALL_SUB_CATEGORIES:
            description = CATEGORY_DESCRIPTIONS.get(category, category)
            text_to_embed = f"{category}: {description}"
            vector = await embeddings_client.aembed_query(text_to_embed)
            CATEGORY_EMBEDDING_CACHE[category] = np.array(vector)
    return CATEGORY_EMBEDDING_CACHE

# ---------------------------------------------------------
# 1. State 및 Pydantic 정의 (기존과 동일, db_session 없음)
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
    final_answer: NotRequired[str]

# ---------------------------------------------------------
# 2. 각 Node의 입출력 스키마 정의 (Pydantic 모델)
# ---------------------------------------------------------
class ContextAnalysisOutput(BaseModel):
    target_genre: str = Field(description="가장 적합한 장르(대분류)")
    target_sub_category: str = Field(  # | None 제거
        description="질문의 핵심 주제를 묘사하는 짧고 명확한 가상 카테고리명 (예: 'OS', '프로그래밍언어')"
    )
    calculated_difficulty: int = Field(description="계산된 난이도 (0~10)")

class HydeOutput(BaseModel):
    summary: str = Field(description="가상 도서 줄거리 (200~400자)")
    keywords: list[str] = Field(
        description="키워드 5개: topic 2개 + approach 1~2개 + target 1~2개",
        min_length=5,
        max_length=5,
    )

# ---------------------------------------------------------
# 3. 전역 Node 함수들 
# ---------------------------------------------------------

# node1
async def analyze_context_node(state: AgentState) -> dict[str, Any]:
    # ALL_SUB_CATEGORIES 노출 제거 — LLM이 직접 분류 결정을 하지 않도록 함
    prompt = ChatPromptTemplate.from_messages([
        ("system",
            f"너는 도서 추천을 위한 컨텍스트 분석기야. 아래 규칙을 엄격히 따라 분석해.\n"
            f"[허용된 장르(대분류)]: {', '.join(GENRES)}\n\n"
            "1. 유저의 질문을 분석해서, 어떤 IT 분야/주제의 책을 찾는지 가장 잘 묘사하는 "
            "**가상의 카테고리명을 자유롭게 생성**해. 카테고리 후보 목록을 보지 않고, "
            "핵심 키워드가 2~4개 포함되는 1줄로 작성해.\n"
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

    # 2. LLM이 생성한 '카테고리 묘사문'을 임베딩 (벡터화)
    description_vector = np.array(
        await embeddings_client.aembed_query(result.target_sub_category)
    )

    # 3. 사전에 임베딩된 카테고리들과 비교 (시맨틱 라우팅 핵심)
    category_cache = await get_or_embed_categories()
    
    best_category = ""
    highest_score = -1.0

    for category_name, category_vector in category_cache.items():
        score = calculate_cosine_similarity(description_vector, category_vector)
        if score > highest_score:
            highest_score = score
            best_category = category_name

    logger.info(f"LLM이 파악한 주제: {result.target_sub_category}")
    logger.info(f"시맨틱 라우팅 결과: '{best_category}'로 매핑됨 (유사도: {highest_score:.4f})")

    # 4. 강제 매핑된 best_category를 State로 넘겨줍니다.
    return {
        "hyde_target_genre": result.target_genre,
        "hyde_target_category": best_category, # 완벽하게 ALL_SUB_CATEGORIES 중 하나가 보장됨
        "hyde_difficulty_level": result.calculated_difficulty
    }
# node2
async def generate_hyde_node(state: AgentState) -> dict[str, Any]:
    query = state["query"]
    target_category = state.get("hyde_target_category")
    target_level = state.get("hyde_difficulty_level", 5)
    
    if not target_category:
        target_category = state.get("hyde_target_genre", "IT")
    
    # ⚠️ 키워드 스키마는 crawler/scripts/enrich_data.py의 SYSTEM_PROMPT와
    #    반드시 동일하게 유지할 것. 한 쪽 수정 시 다른 쪽도 같이 수정.
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "너는 도서 큐레이터야. 유저의 질문과 타겟 정보를 바탕으로, "
         "DB 벡터 검색에 사용할 '이상적인 가상 도서'를 생성해.\n\n"
         "[줄거리 작성 규칙]\n"
         "- 분량: 200~400자. 실제 도서 소개글처럼 자연스러운 한국어로.\n"
         "- 난이도 톤:\n"
         "  · 0~2: 입문자 톤 (\"~를 처음 접하는 사람도 이해할 수 있도록\")\n"
         "  · 3~5: 중급 톤 (\"실무에서 자주 마주치는 ~를 단계별로 학습\")\n"
         "  · 6~8: 심화 톤 (\"~의 내부 동작 원리와 설계 철학을 깊이 다룬다\")\n"
         "  · 9~10: 전문가 톤 (\"최신 연구 동향과 ~를 분석한 전문서\")\n"
         "- 타겟 카테고리의 핵심 개념을 1~2개 자연스럽게 포함하라.\n"
         "- 유저 질문의 의도(예: '쉬운', '실전', '역사', '그림으로')를 반드시 줄거리에 반영하라.\n\n"
         "[키워드 추출 규칙]\n"
         "정확히 5개의 키워드를 아래 3개 축으로 추출하라.\n\n"
         "1. 주제 (topic) — 2개: 책이 다루는 핵심 개념/기술/언어를 구체적으로.\n\n"
         "2. 접근방식 (approach) — 1~2개. 아래 어휘에서만 선택:\n"
         "   [\"역사적 관점\", \"사례 중심\", \"이론 중심\", \"실습 중심\", \"개념 정리\",\n"
         "    \"튜토리얼\", \"레퍼런스\", \"프로젝트 기반\", \"비교 분석\", \"시각적 설명\",\n"
         "    \"딥다이브\", \"문제 해결 중심\"]\n\n"
         "3. 대상/성격 (target) — 1~2개. 아래 어휘에서만 선택:\n"
         "   [\"비전공자 교양서\", \"입문자용\", \"중급자용\", \"실무자용\", \"연구자용\",\n"
         "    \"수험서\", \"참고서\", \"기초 학습서\", \"심화 학습서\"]\n\n"
         "[질문 의도 → 키워드 매핑 힌트]\n"
         "- \"쉬운/입문/처음/노베이스\" → target은 \"입문자용\" 또는 \"비전공자 교양서\".\n"
         "- \"심화/실전/실무/딥다이브\" → target은 \"실무자용\" 또는 \"심화 학습서\", approach는 \"딥다이브\".\n"
         "- \"역사/사례\" → approach에 \"역사적 관점\" 또는 \"사례 중심\".\n"
         "- \"그림/시각적/직관적\" → approach에 \"시각적 설명\".\n"
         "- \"튜토리얼/예제/단계별\" → approach에 \"튜토리얼\" 또는 \"실습 중심\".\n\n"
         "[중요]\n"
         "- approach/target은 반드시 위 어휘 목록 안에서만 선택. 새 표현 금지.\n"
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

# node3
async def retrieve_books_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    configurable_data = config.get("configurable", {})
    db_session = configurable_data.get("db_session")
    
    if not db_session:
        logger.error("DB 세션이 주입되지 않았습니다!")
        return {"recommended_books": []}
    
    hyde_target_genre = state.get("hyde_target_genre", "")
    hyde_target_category = state.get("hyde_target_category")
    
    hyde_difficulty_level = state.get("hyde_difficulty_level")
    hyde_summary = state.get("hyde_summary")
    hyde_keyword = state.get("hyde_keyword",[])
    
    if not hyde_summary:
        return {"recommended_books":[]}

    keyword_str = ", ".join(hyde_keyword)
    hyde_text_to_embed = f"난이도: {hyde_difficulty_level}\n키워드: {keyword_str}\n줄거리: {hyde_summary}"
    
    query_vector = await embeddings_client.aembed_query(hyde_text_to_embed)

    distance = Book.embedding.cosine_distance(query_vector)

    weighted_distance = distance - case(
    (Book.sub_category == hyde_target_category, 0.15),
    else_=0.0)
        
    stmt = select(Book).order_by(weighted_distance).limit(3)

    # 안전하게 가져온 DB 세션 사용
    result = await db_session.execute(stmt)
    real_books = result.scalars().all()

    recommended_books_list =[{
        "book_id": book.id,
        "title": book.title,
        "author": book.author,
        "difficulty": book.difficulty,
        "summary": book.summary,
        "cover_url": book.cover_url
    } for book in real_books]
            
    return {"recommended_books": recommended_books_list}

# node4
async def generate_answer_node(state: AgentState) -> dict[str, Any]:
    query = state["query"]
    domain_levels = state["domain_levels"]
    recommended_books = state.get("recommended_books",[])
    
    if not recommended_books:
        return {"final_answer": "죄송합니다. 현재 회원님의 수준에 딱 맞는 책을 찾지 못했습니다."}
        
    books_context = ""
    for idx, book in enumerate(recommended_books, 1):
        books_context += (
            f"[{idx}번 책]\n제목: {book['title']}\n저자: {book['author']}\n"
            f"난이도: {book['difficulty']}/10\n줄거리: {book['summary']}\n\n"
        )

    prompt = ChatPromptTemplate.from_messages([
        ("system", 
         "너는 친절하고 전문적인 IT 도서 추천 비서야.\n"
         "유저의 [질문]과 [현재 숙련도]를 분석해서, 내가 제공한 [추천 도서 목록]의 책들이 왜 유저에게 맞는지 설명해 줘.\n\n"
         " [절대 규칙 - 엄격히 준수할 것]\n"
         "1. 제공된 [추천 도서 목록]에 있는 책은 **무조건 모두, 단 한 권도 빠짐없이** 각각 언급하고 추천 사유를 작성해.\n"
         "2. 책 제목을 명확히 적고, 그 책이 유저의 난이도와 질문 의도에 왜 부합하는지 1~2줄로 핵심만 설명해.\n"
         "3. 없는 책을 지어내거나, 목록 중 일부 책의 설명을 생략하면 절대 안 돼."
        ),
        ("user", "내 숙련도: {domain_levels}\n내 질문: {query}\n\n[추천 도서 목록]\n{books_context}")
    ])

    chain = prompt | llm_creator
    response = await chain.ainvoke({"domain_levels": domain_levels, "query": query, "books_context": books_context})
    
    return {"final_answer": str(response.content)}


# ---------------------------------------------------------
# 3. 전역 컴파일 (애플리케이션이 뜰 때 단 한 번만 실행됨!)
# ---------------------------------------------------------
workflow = StateGraph(AgentState)
workflow.add_node("analyze_context", analyze_context_node)
workflow.add_node("generate_hyde", generate_hyde_node)
workflow.add_node("retrieve_books", retrieve_books_node)
workflow.add_node("generate_answer", generate_answer_node)

workflow.add_edge("analyze_context", "generate_hyde")
workflow.add_edge("generate_hyde", "retrieve_books")
workflow.add_edge("retrieve_books", "generate_answer")
workflow.add_edge("generate_answer", END)

workflow.set_entry_point("analyze_context")

agent_app = workflow.compile()


# =====================================================================
# 4. FastAPI 호출용 메인 서비스 함수
# =====================================================================

async def stream_book_recommendation_service(
    query: str, 
    current_user: User, 
    db: AsyncSession
) -> AsyncGenerator[str, None]:
    
    initial_state: AgentState = {
        "query": query,
        "domain_levels": current_user.domain_levels, 
    }
    
    # 🌟 핵심: 실행 시점에 DB 세션을 config로 포장해서 주입합니다.
    config: RunnableConfig = {"configurable": {"db_session": db}}
    
    async for event in agent_app.astream_events(initial_state, config=config, version="v1"):
        kind = event.get("event")
        metadata = event.get("metadata", {})
        node_name = metadata.get("langgraph_node")
        event_data = event.get("data", {})
        
        if kind == "on_chain_end" and node_name == "retrieve_books":
            output_data = event_data.get("output", {})
            retrieved_books = output_data.get("recommended_books",[])
            books_json = json.dumps(retrieved_books, ensure_ascii=False)
            yield f"event: books\ndata: {books_json}\n\n"

        elif kind == "on_chat_model_stream" and node_name == "generate_answer":
            chunk = event_data.get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                text = chunk.content
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
    }
    
    # 🌟 테스트용 함수에도 동일하게 config 주입
    config: RunnableConfig = {"configurable": {"db_session": db}}
    
    final_state = await agent_app.ainvoke(initial_state, config=config)
    
    return {
        "hyde_target_category": final_state.get("hyde_target_category", ""),
        "hyde_difficulty_level": final_state.get("hyde_difficulty_level", 0),
        "hyde_summary": final_state.get("hyde_summary", "가상 도서 생성 실패"),
        "hyde_keyword": final_state.get("hyde_keyword",[]),
        "recommended_books": final_state.get("recommended_books",[]),
        "final_answer": final_state.get("final_answer", "답변 생성 실패")
    }
    


