import json
import httpx
import pandas as pd
import asyncio
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()

# ⚙️ 설정값
API_URL = "http://127.0.0.1:8000/api/recommendations/eval"
TEST_FILE = BASE_DIR / "test_cases.json"
OUTPUT_FILE = BASE_DIR / "runner_results_v3.csv"

# DB 커넥션 풀(보통 5~10)과 OpenAI API Rate Limit을 고려하여 5개로 제한합니다.
MAX_CONCURRENT_REQUESTS = 5

async def fetch_case(case: dict, http_client: httpx.AsyncClient, semaphore: asyncio.Semaphore):
    """단일 테스트 케이스를 서버에 요청하는 워커(Worker) 함수"""
    
    # 세마포어(티켓)를 획득할 때까지 대기 (최대 5개만 동시 실행됨)
    async with semaphore:
        print(f"⏳ 요청 시작 [ID: {case['id']}] - {case['scenario']}")
        payload = {
            "query": case["query"],
            "domain_levels": case["domain_levels"]
        }
        
        try:
            # 타임아웃을 60초로 넉넉하게! (병렬 처리 시 서버 로드가 걸려 응답이 길어질 수 있음)
            res = await http_client.post(API_URL, json=payload, timeout=60.0)
            res.raise_for_status()
            data = res.json()
            print(f"✅ 응답 완료 [ID: {case['id']}]")
            
            # 원본 케이스와 서버 응답 데이터를 묶어서 반환
            return case, data
        
        except Exception as e:
            print(f"❌ API 에러 (ID {case['id']}): {e}")
            return case, None


async def run_inference():
    print("🚀 [Runner] 병렬 테스트 파이프라인 가동 시작...")
    
    try:
        with open(TEST_FILE, "r", encoding="utf-8") as f:
            test_cases = json.load(f)
    except FileNotFoundError:
        print(f"❌ {TEST_FILE} 파일을 찾을 수 없습니다.")
        return

    # 세마포어 생성
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
    
    # 🌟 [병렬 처리 핵심 파트]
    async with httpx.AsyncClient() as http_client:
        # 1. 30개의 작업(Task) 리스트를 미리 만듭니다. (아직 실행 안 됨)
        tasks = [fetch_case(case, http_client, semaphore) for case in test_cases]
        
        # 2. asyncio.gather로 한꺼번에 실행! (세마포어 덕분에 알아서 5개씩 돌아감)
        # gather는 끝나는 순서와 상관없이, 처음 넣은 tasks 배열 순서대로 결과를 반환해 줍니다!
        raw_results = await asyncio.gather(*tasks)

    print("\n📦 모든 API 요청 완료! 데이터 평탄화 및 CSV 저장 시작...\n")

    results = []
    
    # 3. 받아온 결과들을 순회하며 CSV용으로 평탄화 (기존 로직 동일)
    for case, data in raw_results:
        if not data:
            continue # 에러 난 케이스는 건너뜀
            
        books = data.get("recommended_books", [])
        
        row = {
            "Test ID": case["id"],
            "Scenario": case["scenario"],
            "Query": case["query"],
            "Expected Category": case.get("expected_sub_category", ""),
            "Expected Topic": case.get("expected_topic", ""),
            "Expected Level": case.get("expected_target_level", 0),
            
            "HyDE Category": data.get("hyde_target_category", ""),
            "HyDE Level": data.get("hyde_difficulty_level", 0),
            "HyDE Keywords": ", ".join(data.get("hyde_keyword", [])),
            "HyDE Summary": data.get("hyde_summary", ""),
            
            "Book 1 Title": books[0]["title"] if len(books) > 0 else "None",
            "Book 1 Level": books[0]["difficulty"] if len(books) > 0 else 0,
            "Book 1 Summary": books[0]["summary"] if len(books) > 0 else "None",
            
            "Book 2 Title": books[1]["title"] if len(books) > 1 else "None",
            "Book 2 Level": books[1]["difficulty"] if len(books) > 1 else 0,
            "Book 2 Summary": books[1]["summary"] if len(books) > 1 else "None",
            
            "Book 3 Title": books[2]["title"] if len(books) > 2 else "None",
            "Book 3 Level": books[2]["difficulty"] if len(books) > 2 else 0,
            "Book 3 Summary": books[2]["summary"] if len(books) > 2 else "None",
        }
        results.append(row)
            
    # 4. CSV 저장
    if not results:
        print("❌ 저장할 테스트 결과가 없습니다.")
        return

    df = pd.DataFrame(results)
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig") 
    
    print("🎉 [Runner] 병렬 데이터 수집 완벽하게 종료! 🎉")
    print(f"📁 총 {len(results)}개의 결과가 '{OUTPUT_FILE}' 파일에 저장되었습니다.")

if __name__ == "__main__":
    asyncio.run(run_inference())