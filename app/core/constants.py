# 팀원(크롤러)이 분류해 줄 대분류(Genre)와 세부 카테고리(Sub-category) 매핑표
IT_BOOK_CATEGORIES = {
    "IT": [
        "컴퓨터공학", "IT일반", "OS", "네트워크", "보안/해킹",
        "데이터베이스", "개발방법론", "웹프로그래밍", "프로그래밍 언어", "모바일프로그래밍",
    ],
}

# 대분류(Genre) 리스트
GENRES = list(IT_BOOK_CATEGORIES.keys())

# 검증(Validation)을 위해 모든 세부 카테고리를 1차원 리스트로 뽑아두는 유틸리티
ALL_SUB_CATEGORIES = [
    sub for sub_list in IT_BOOK_CATEGORIES.values() for sub in sub_list
]