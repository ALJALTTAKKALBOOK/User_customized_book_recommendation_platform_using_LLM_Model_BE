import requests

URL = "http://localhost:8000/api/books/"

# 🌟 파이썬의 리스트 곱하기 문법으로 [0.01, 0.01, ... ] 1536개짜리 꽉 찬 리스트를 만듦!
fake_embedding = [0.01] * 1536 

payload : dict[str, object] = {
  "isbn": "9788960773417",
  "title": "토비의 스프링 3.1",
  "author": "이일민",
  "genre": "IT",
  "sub_category": "웹/백엔드",
  "difficulty": "3",  
  "language": "KOR",
  "grade_point": 95,
  "page_count": 800,
  "cover_url": "https://image.yes24.com/goods/12345/L",
  "total_readers": 15000,
  "published_at": "2012-09-25T00:00:00Z", 
  "summary": "자바 엔터프라이즈 개발의 표준 스프링 프레임워크의 바이블",
  "keywords": ["Spring", "Java", "Backend"],
  "embedding": fake_embedding  # 1536개짜리 배열 투입!
}

response = requests.post(URL, json=payload)
print(response.status_code)
print(response.json())