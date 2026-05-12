import json
import logging
import numpy as np
from typing import Dict, TypedDict, List, AsyncGenerator, Any, cast
from typing_extensions import NotRequired 
from pydantic import BaseModel, Field     
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from langgraph.graph import StateGraph, END
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig 

from app.domains.users.model import User
from app.domains.books.model import Book
from app.core.constants import GENRES, ALL_SUB_CATEGORIES
from app.core.llm_helper import llm_analyzer, llm_creator, embeddings_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 0. 시맨틱 라우팅 유틸리티 작성(최초 1회만 메모리에 캐싱)
# ---------------------------------------------------------
CATEGORY_EMBEDDING_CACHE = {}

def calculate_cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """두 벡터 간의 코사인 유사도를 계산합니다."""
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

async def get_or_embed_categories():
    """앱 실행 후 최초 1회만 카테고리를 임베딩하고 캐싱합니다."""
    global CATEGORY_EMBEDDING_CACHE
    
    if not CATEGORY_EMBEDDING_CACHE:
        for category in ALL_SUB_CATEGORIES:
            text_to_embed = f"IT 기술 및 프로그래밍 도서 카테고리: {category}"
            vector = await embeddings_client.aembed_query(text_to_embed)
            CATEGORY_EMBEDDING_CACHE[category] = np.array(vector)
            
    return CATEGORY_EMBEDDING_CACHE

# ---------------------------------------------------------
# 1. State 및 Pydantic 정의 (기존과 동일, db_session 없음)
# ---------------------------------------------------------
class AgentState(TypedDict):
    query: str
    domain_levels: dict[str, int]
    user: User
    
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
    target_genre: str = Field(description="IT와 같은 대분류 장르")
    calculated_difficulty: int = Field(description="1~10 사이의 난이도")
    category_description: str = Field(
        description="유저의 질문과 숙련도를 바탕으로, 찾고자 하는 도서의 구체적인 기술 스택, 언어, 또는 분야를 상세하게 묘사하세요. (예: 'React와 Next.js를 활용한 프론트엔드 상태 관리 및 UI 개발')"
    )
class HydeOutput(BaseModel):
    summary: str = Field(description="가상 도서 줄거리")
    keywords: list[str] = Field(description="키워드")


# ---------------------------------------------------------
# 3. 전역 Node 함수들 
# ---------------------------------------------------------

# node1
async def analyze_context_node(state: AgentState) -> dict[str, Any]:
    # 1. 카테고리 제한(ALL_SUB_CATEGORIES)을 없애고 자유로운 묘사를 요구
    prompt = ChatPromptTemplate.from_messages([
<<<<<<< HEAD
        ("system",
         f"너는 도서 추천을 위한 컨텍스트 분석기야.\n"
         f"[허용된 장르(대분류)]: {', '.join(GENRES)}\n"
         f"유저의 질문과 숙련도를 분석해서, 유저가 필요로 하는 도서의 구체적인 주제나 기술 분야를 상세하게 묘사해."
        ),
        ("user", "내 숙련도: {domain_levels}\n내 질문: {query}")
=======
    ("system",
        f"너는 도서 추천을 위한 컨텍스트 분석기야. 아래 규칙을 엄격히 따라 분석해.\n"
        f"[허용된 장르(대분류)]: {', '.join(GENRES)}\n"
        f"[허용된 카테고리(소분류)]: {', '.join(ALL_SUB_CATEGORIES)}\n\n"
        "1. 유저의 질문을 보고 [허용된 카테고리] 중에서 가장 적합한 것을 찾아.\n"
        "2. 만약 [허용된 카테고리] 중에 적합한 것이 아예 없다면, 카테고리는 null로 비워두고 [허용된 장르]만 선택해.\n"
        "3. 질문에 '기초, 처음, 쉬운' 등이 있으면 소분류(장르)에 대응되는 숙련도를 유지하거나 -1 하향해.\n"
        "4. '심화, 실전, 어려운' 등이 있으면 난이도 +2 상향해.\n"
        "5. 만약 질문한 분야가 유저 숙련도(domain_levels)에 아예 없다면 기본 난이도를 1로 설정해."
    ),
    ("user", "내 숙련도: {domain_levels}\n내 질문: {query}")
>>>>>>> d9d993e08463eadabdf6b159eb0fbc42f42015d1
    ])
    
    structured_llm = llm_analyzer.with_structured_output(ContextAnalysisOutput)
    chain = prompt | structured_llm
    
    raw_result = await chain.ainvoke({"domain_levels": state["domain_levels"], "query": state["query"]})
    result = cast(ContextAnalysisOutput, raw_result)

    # 2. LLM이 생성한 '카테고리 묘사문'을 임베딩 (벡터화)
    description_vector = np.array(
        await embeddings_client.aembed_query(result.category_description)
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

    logger.info(f"LLM이 파악한 주제: {result.category_description}")
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
        
    prompt = ChatPromptTemplate.from_messages([
        ("system", "너는 최고의 도서 큐레이터야..."),
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
    if not hyde_target_category:
        hyde_target_category = hyde_target_genre
    
    hyde_difficulty_level = state.get("hyde_difficulty_level")
    hyde_summary = state.get("hyde_summary")
    hyde_keyword = state.get("hyde_keyword",[])
    
    if not hyde_summary:
        return {"recommended_books":[]}

    keyword_str = ", ".join(hyde_keyword)
    hyde_text_to_embed = f"카테고리: {hyde_target_category}\n난이도: {hyde_difficulty_level}\n키워드: {keyword_str}\n줄거리: {hyde_summary}"
    
    query_vector = await embeddings_client.aembed_query(hyde_text_to_embed)

    stmt = select(Book)
    if hyde_target_category:
        stmt = stmt.where(Book.sub_category == hyde_target_category)
    else:
        stmt = stmt.where(Book.genre == hyde_target_genre)
        
    stmt = stmt.order_by(Book.embedding.cosine_distance(query_vector)).limit(3)

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
        "user": current_user,
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
    current_user: User, 
    db: AsyncSession
) -> Dict[str, Any]:
    
    initial_state: AgentState = {
        "query": query,
        "domain_levels": current_user.domain_levels, 
        "user": current_user,
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
    


