# 팀원(크롤러)이 분류해 줄 대분류(Genre)와 세부 카테고리(Sub-category) 매핑표
IT_BOOK_CATEGORIES = {
    "IT": ["Spring", "FastAPI", "Node.js", "Django", "JPA", "Database"],
}

# 대분류(Genre) 리스트
GENRES = list(IT_BOOK_CATEGORIES.keys())

# 검증(Validation)을 위해 모든 세부 카테고리를 1차원 리스트로 뽑아두는 유틸리티
ALL_SUB_CATEGORIES = [
    sub for sub_list in IT_BOOK_CATEGORIES.values() for sub in sub_list
]