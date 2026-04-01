import json
from typing import TypedDict, List, AsyncGenerator, Any, cast
from typing_extensions import NotRequired 
from pydantic import BaseModel, Field     
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.graph import StateGraph, END # type: ignore
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
import logging
from typing import Any, List
from sqlalchemy import select

from app.domains.users.model import User
from app.core.constants import GENRES
from app.core.constants import ALL_SUB_CATEGORIES
from app.domains.books.model import Book  # 도서 모델
from app.core.llm_helper import llm_analyzer
from app.core.llm_helper import llm_creator
from app.core.llm_helper import embeddings_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 1. State 정의 (컨베이어 벨트 바구니)
# ---------------------------------------------------------
class AgentState(TypedDict):
    # --- Input (필수) ---
    query: str
    domain_levels: dict[str, int]
    user:User
    db_session: AsyncSession
    
    # --- 노드를 거치면서 바구니에 추가될 데이터  ---
    hyde_target_genre: NotRequired[str]  
    hyde_target_category: NotRequired[str]      
    hyde_difficulty_level: NotRequired[int]
    
    hyde_summary: NotRequired[str]
    hyde_keyword: NotRequired[list[str]]
    
    recommended_books: NotRequired[List[dict[str,Any]]]
    final_answer: NotRequired[str]

# ---------------------------------------------------------
# 2. Nodes (각 단계별 작업장) - 뼈대만 작성
# ---------------------------------------------------------



# -------- Node 1 --------
# Node 1 Output 규격
class ContextAnalysisOutput(BaseModel):
    target_genre: str = Field(description="가장 적합한 장르(대분류)")
    target_sub_category: str | None = Field(description="적합한 카테고리(소분류). 만약 매칭되는 소분류가 없다면 null(None)로 설정해.")
    calculated_difficulty: int = Field(description="계산된 난이도 (0~10)")
    
# Node 1 핵심 로직
async def analyze_context_node(state: AgentState) -> dict[str, str | int]:
    """[Node 1] 유저의 수준과 질문 의도를 분석하여 타겟 카테고리와 난이도를 계산
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         f"너는 도서 추천을 위한 컨텍스트 분석기야. 아래 규칙을 엄격히 따라 분석해.\n"
         f"[허용된 장르(대분류)]: {', '.join(GENRES)}\n"
         f"[허용된 카테고리(소분류)]: {', '.join(ALL_SUB_CATEGORIES)}\n\n"
         "1. 유저의 질문을 보고 [허용된 카테고리] 중에서 가장 적합한 것을 찾아.\n"
         "2. 만약 [허용된 카테고리] 중에 적합한 것이 아예 없다면, 카테고리는 null로 비워두고 [허용된 장르]만 선택해.\n"
         "3. 질문에 '기초, 쉬운' 등이 있으면 현재 숙련도 유지 또는 -1 하향.\n"
         "4. '심화, 실전' 등이 있으면 난이도 +2 상향."
        ),
        ("user", "내 숙련도: {domain_levels}\n내 질문: {query}")
    ])

    # 구조화된 출력(JSON)을 뱉도록 묶어줌
    structured_llm = llm_analyzer.with_structured_output(ContextAnalysisOutput)
    chain = prompt | structured_llm
    
    # LLM 실행
    raw_result = await chain.ainvoke({
        "domain_levels": state["domain_levels"],
        "query": state["query"]
    })
    
    if not isinstance(raw_result, ContextAnalysisOutput):
        raise ValueError("LLM이 ContextAnalysisOutput 규격에 맞지 않는 응답을 반환했습니다!")
    
    result = cast(ContextAnalysisOutput, raw_result)
    
    # 안전장치(Fallback)
    # LLM이 이상한 소분류를 뱉었거나 None일 경우 빈 문자열로 처리
    if not result.target_sub_category or result.target_sub_category not in ALL_SUB_CATEGORIES:
        result.target_sub_category = ""
        

    #  전체 State가 아닌 '업데이트할 조각'만 리턴
    return {
        "hyde_target_genre": result.target_genre,
        "hyde_target_category": result.target_sub_category,
        "hyde_difficulty_level": result.calculated_difficulty
    }


# -------- Node 2 -------- 
# Node 2 Output 규격
class HydeOutput(BaseModel):
    summary: str = Field(
        description="유저의 질문과 수준에 완벽하게 부합하는 가상의 이상적인 책 줄거리 및 소개글 (200~300자 내외)"
    )
    keywords: list[str] = Field(
        description="이 가상의 책을 대표하는 핵심 기술/주제 키워드 3~5개 (예: ['스프링부트', '실무', '백엔드'])"
    )

# Node 2 핵심 로직
async def generate_hyde_node(state: AgentState) -> dict[str, Any]:
    """
    [Node 2] 분석된 컨텍스트를 바탕으로 가상의 이상적인 책(HyDE)의 줄거리와 키워드를 창작
    """
    # 1. 이전 노드(Node 1)에서 채워준 State 꺼내오기
    query = state["query"]
    target_category = state.get("hyde_target_category")
    target_level = state.get("hyde_difficulty_level", 5)
    if not target_category:
        target_category = state.get("hyde_target_genre", "IT")
        
    # 2. 프롬프트 세팅 (베스트셀러 편집자 페르소나 부여)
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "너는 최고의 도서 큐레이터이자 베스트셀러 편집자야.\n"
         "유저가 원하는 책의 [타겟 카테고리]와 [타겟 난이도(0~10)]에 맞춰서, 유저의 질문에 완벽한 정답이 될 만한 '가상의 책'을 하나 상상해봐.\n"
         "이 가상의 책에 대한 '줄거리(summary)'와 '핵심 키워드(keywords)'를 작성해줘.\n"
         "마케팅 용어(완벽 마스터, 누구나 할 수 있는 등)보다는, 이 책이 다루는 핵심 기술이나 구체적인 내용을 상세히 묘사해야 해."
        ),
        ("user", 
         "유저 질문: {query}\n"
         "타겟 카테고리: {category}\n"
         "타겟 난이도: {level}"
        )
    ])

    # 3. 체인 구성 및 LLM 실행
    structured_llm = llm_creator.with_structured_output(HydeOutput)
    chain = prompt | structured_llm
    
    # 이때 타입은 _DictOrPydantic
    raw_result = await chain.ainvoke({
        "query": query,
        "category": target_category,
        "level": target_level
    })
    
    if not isinstance(raw_result, HydeOutput):
        raise ValueError("LLM이 HydeOutput 규격에 맞지 않는 응답을 반환했습니다!")
    
    result = cast(HydeOutput, raw_result)
    
    # 4. 다음 노드(Node 3)를 위해 State 바구니 업데이트
    return {
        "hyde_summary": result.summary,
        "hyde_keyword": result.keywords
    }
    
    
# -------- Node 3 --------
# Node 3 핵심 로직
async def retrieve_books_node(state: AgentState) -> dict[str, Any]:
    """
    [Node 3] 생성된 가상의 책(HyDE)을 임베딩하고, 
    RDBMS 카테고리 필터링 + 벡터 유사도 검색(하이브리드)을 통해 실제 책 3권을 추출
    """
    # 1. State 바구니에서 필요한 재료 꺼내기
    hyde_target_genre = state.get("hyde_target_genre", "")
    hyde_target_category = state.get("hyde_target_category")
    if not hyde_target_category:
        hyde_target_category = hyde_target_genre  # 카테고리가 없으면 장르로라도 필터링
    hyde_difficulty_level = state.get("hyde_difficulty_level")
    hyde_summary = state.get("hyde_summary")
    hyde_keyword = state.get("hyde_keyword", [])
    
    db_session = state["db_session"]
    
    # 안전장치
    if not hyde_summary:
        logger.error("HyDE summary가 존재하지 않습니다.")
        return {"recommended_books":[]}

    # 2. 가상의 책 줄거리를 벡터(1536개의 숫자)로 변환
    keyword_str = ", ".join(hyde_keyword)
    
    
    hyde_text_to_embed = (
        f"카테고리: {hyde_target_category}\n"
        f"난이도: {hyde_difficulty_level}\n"
        f"키워드: {keyword_str}\n"
        f"줄거리: {hyde_summary}"
    )
    
    # aembed_query는 비동기(async)로 텍스트를 임베딩 리스트로 바꿔줍니다.
    query_vector = await embeddings_client.aembed_query(hyde_text_to_embed)

    # 3. 하이브리드 검색 쿼리 작성 (SQLAlchemy + pgvector)
    # Book.embedding.cosine_distance() 는 pgvector의 <-> 연산자로 번역됩니다.
    stmt = select(Book)
    
    # 카테고리 필터링: 만약 HyDE가 특정 소분류까지 지정했다면 그걸로 필터링, 아니라면 대분류(장르)로라도 필터링
    if hyde_target_category:
        stmt = stmt.where(Book.sub_category == hyde_target_category) #and Book.difficulty >= hyde_difficulty_level - 1 and Book.difficulty <= hyde_difficulty_level + 1)
    else:
        stmt = stmt.where(Book.genre == hyde_target_genre)
        
    # [Vector Search] 가상 책 벡터와 코사인 유사도가 가장 '가까운(작은)' 순서대로 정렬
    stmt = stmt.order_by(Book.embedding.cosine_distance(query_vector)).limit(3)

    # 4. 쿼리 실행 및 결과 추출
    result = await db_session.execute(stmt)
    real_books = result.scalars().all()

    # 5. 다음 노드(LLM 답변 생성)에 넘겨줄 깔끔한 딕셔너리로 포맷팅
    #  주의: 1536개짜리 벡터 데이터를 통째로 LLM 프롬프트에 넘기면 토큰 폭발합니다!
    # 무조건 책 제목, 저자, 줄거리 같은 텍스트만 빼서 넘겨야 합니다.
    recommended_books_list: List[dict[str, Any]] = []
    for book in real_books:
            recommended_books_list.append({
                "book_id": book.id,
                "title": book.title,
                "author": book.author,
                "difficulty": book.difficulty,
                "summary": book.summary,
                "cover_url": book.cover_url
            })
            
    logger.info(f"검색된 책 갯수: {len(recommended_books_list)}권")

    # 6. 다음 노드(Node 4)와 프론트엔드 전송을 위해 State 바구니 업데이트
    return {
        "recommended_books": recommended_books_list
    }


# -------- Node 4 --------
async def generate_answer_node(state: AgentState) -> dict[str, Any]:
    """
    [Node 4] 검색된 실제 도서 3권을 바탕으로, 유저에게 맞춤형 추천 사유를 스트리밍 생성
    """
    query = state["query"]
    domain_levels = state["domain_levels"]
    recommended_books = state.get("recommended_books",[])
    
    # 안전장치: DB에서 조건에 맞는 책을 하나도 못 찾았다면?
    if not recommended_books:
        return {
            "final_answer": "죄송합니다. 현재 회원님의 수준과 조건에 딱 맞는 책을 DB에서 찾지 못했습니다. 질문을 조금 바꿔보시겠어요?"
        }
        
    # 1. 책 정보들을 LLM이 읽기 좋게 하나의 문자열로 쫙 풀어줍니다.
    books_context = ""
    for idx, book in enumerate(recommended_books, 1):
        books_context += (
            f"[{idx}번 책]\n"
            f"제목: {book['title']}\n"
            f"저자: {book['author']}\n"
            f"난이도: {book['difficulty']}/10\n"
            f"줄거리: {book['summary']}\n\n"
        )

    # 2. 프롬프트 세팅
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "너는 친절하고 전문적인 IT 도서 추천 비서(Agent)야.\n"
         "유저의 [질문]과 [현재 숙련도]를 분석해서, 내가 DB에서 찾아온 [추천 도서 목록]이 왜 유저에게 딱 맞는지 추천 사유를 작성해 줘.\n"
         "🚨 절대 규칙:\n"
         "1. 반드시 내가 준[추천 도서 목록] 안에 있는 책만 언급할 것 (지어내기 절대 금지).\n"
         "2. 각 책이 왜 유저의 수준과 상황에 맞는지 1~2줄로 핵심만 짚어줄 것.\n"
         "3. 마크다운(Markdown) 포맷을 적절히 써서 읽기 좋게 작성할 것."
        ),
        ("user", 
         "내 숙련도: {domain_levels}\n"
         "내 질문: {query}\n\n"
         "[추천 도서 목록]\n{books_context}"
        )
    ])

    chain = prompt | llm_creator
    
    # 3. LLM 실행
    #  꿀팁: 여기서 ainvoke를 실행하지만, 라우터의 `astream_events`가 
    # 이 과정에서 생성되는 청크(chunk)들을 낚아채서 프론트로 한 글자씩 쏘게 됩니다!
    response = await chain.ainvoke({
        "domain_levels": domain_levels,
        "query": query,
        "books_context": books_context
    })
    
    # 4. State 바구니 업데이트 (최종 완성된 문자열 전체 저장)
    return {
        "final_answer": str(response.content)
    }



# ---------------------------------------------------------
# 3. LangGraph 조립 (이전과 동일)
# ---------------------------------------------------------
# 1. StateGraph 객체 생성 
workflow = StateGraph(AgentState)

# 2. 작업장(Node) 등록
workflow.add_node("analyze_context", analyze_context_node)
workflow.add_node("generate_hyde", generate_hyde_node)
workflow.add_node("retrieve_books", retrieve_books_node)
workflow.add_node("generate_answer", generate_answer_node)

# 3. 컨베이어 벨트(Edge) 연결 - 순서대로 흘러가게 정의
workflow.add_edge("analyze_context", "generate_hyde")
workflow.add_edge("generate_hyde", "retrieve_books")
workflow.add_edge("retrieve_books", "generate_answer")
workflow.add_edge("generate_answer", END) # 작업 끝!

# 4. 시작점(Entry Point) 설정
workflow.set_entry_point("analyze_context")

# 5. 에이전트 앱 컴파일 (최종 실행 가능한 상태로 만듦)
agent_app = workflow.compile()

# ---------------------------------------------------------
#  4. 메인 실행 함수 (Router에서 호출) - 데이터 & 텍스트 동시 전송
# ---------------------------------------------------------
async def stream_book_recommendation_service(
    query: str, 
    current_user: User, 
    db: AsyncSession
) -> AsyncGenerator[str, None]:
    """
    프론트엔드로 책 목록(JSON)과 설명 텍스트(Streaming)를 SSE 형태로 쏴주는 함수
    """
    
    # 1. 초기 바구니(State) 세팅
    initial_state = {
        "query": query,
        "domain_levels": current_user.domain_levels, # JSONB 데이터
        "user": current_user,
        "db_session": db
    }
    
    # 2. LangGraph astream_events 실행 및 이벤트 감지
    async for event in agent_app.astream_events(initial_state, version="v1"):
        kind = event.get("event")
        metadata = event.get("metadata", {})
        node_name = metadata.get("langgraph_node")
        
        # 안전한 데이터 접근을 위해 .get() 활용
        event_data = event.get("data", {})
        
        # [이벤트 1] DB 검색(Node 3)이 막 끝났을 때!
        if kind == "on_chain_end" and node_name == "retrieve_books":
            # event_data 안의 "output"을 안전하게 꺼냄
            output_data = event_data.get("output", {})
            retrieved_books = output_data.get("recommended_books",[])
            
            books_json = json.dumps(retrieved_books, ensure_ascii=False)
            yield f"event: books\ndata: {books_json}\n\n"

        # [이벤트 2] LLM 답변(Node 4)이 한 글자씩 생성될 때!
        elif kind == "on_chat_model_stream" and node_name == "generate_answer":
            chunk = event_data.get("chunk")
            
            # chunk가 존재하고 내용이 있을 때만 쏘기
            if chunk and hasattr(chunk, "content") and chunk.content:
                yield f"data: {chunk.content}\n\n"