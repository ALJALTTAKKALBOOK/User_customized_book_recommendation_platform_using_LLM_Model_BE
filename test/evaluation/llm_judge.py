import sys
import asyncio
import pandas as pd
from pathlib import Path

# tests 폴더 안에서 실행할 때 'app' 모듈을 찾을 수 있게 최상위 경로를 등록해 줍니다.
BASE_DIR = Path(__file__).resolve().parent.parent.parent # BE 폴더
sys.path.append(str(BASE_DIR))

# 팀장님이 만들어둔 만능 LLM JSON 생성기 임포트!
from app.core.llm_helper import generate_json_with_llm

# ⚙️ 설정값
INPUT_FILE = Path(__file__).parent / "runner_results_v3.csv"
OUTPUT_FILE = Path(__file__).parent / "judged_results_v3.csv"

# 동시 채점 개수 제한 (API Rate Limit 방지)
MAX_CONCURRENT_EVALS = 10

# 혀용 난이도 오차 범위
ALLOWED_LEVEL_DIFF = 2

async def evaluate_row(index: int, row: dict, semaphore: asyncio.Semaphore) -> int:
    """단일 테스트 케이스의 토픽 관련성을 채점하는 워커(Worker) 함수"""
    async with semaphore:
        # 1. 책을 아예 못 찾았으면 가차 없이 1점(최하점) 부여
        if row["Book 1 Title"] == "None" or pd.isna(row["Book 1 Title"]):
            return 1
            
        # 2. 채점을 위한 프롬프트 조립
        expected_topic = row["Expected Topic"]
        
        # System Prompt: 심판의 역할과 채점 기준, 그리고 JSON 형식을 강제!
        system_prompt = """
        너는 도서 검색 엔진의 정확도를 평가하는 심판관이야.
        주어진 [기준 토픽]과 [추천된 도서 3권]을 비교하여 1~5점 척도로 평가해.

        [객관적 채점 기준]
        5점: 3권 모두 기준 토픽과 정확히 일치한다.
        4점: 2권이 정확히 일치하고, 1권은 약간 관련이 있다.
        3점: 1권만 정확히 일치하거나, 3권 모두 넓은 의미에서만 관련이 있다.
        2점: 3권 중 일부만 아주 미약하게 관련이 있고 핀트를 벗어났다.
        1점: 3권 모두 기준 토픽과 완전히 무관한 엉뚱한 책이다.

        반드시 바로 아래 JSON 형식으로만 응답해, "x점"같은 문자열 쓰지마 단순히 integer 숫자만 줘야해!(int는 1~5 사이의 정수):
        {"score": int}
        """

        # User Prompt: 실제 엑셀에 적혀있는 책 데이터 주입
        user_prompt = f"""
            [기준 토픽]: {expected_topic}

            [추천된 도서 3권]
            1. 제목: {row['Book 1 Title']} / 줄거리: {row['Book 1 Summary']}
            2. 제목: {row['Book 2 Title']} / 줄거리: {row['Book 2 Summary']}
            3. 제목: {row['Book 3 Title']} / 줄거리: {row['Book 3 Summary']}
            """

        # 3. 팀장님의 llm_helper 호출 (온도는 냉정하게 0.0)
        print(f"🧐 토픽 관련성 채점 중... [Test ID: {row['Test ID']}]")
        
        result_json = await generate_json_with_llm(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0
        )
        
        # 4. 결과 파싱 (실패 시 빈 딕셔너리가 오므로 기본값 1점 처리)
        score = result_json.get("score", 1)
        
        # 방어 로직: LLM이 "4점" 처럼 문자열을 줄 수도 있으므로 정수 변환
        try:
            return int(score)
        except ValueError:
            return 1


async def run_judge():
    print("⚖️ [LLM Judge] AI 심판관 자동 채점 파이프라인 가동...\n")
    
    # 1. Runner가 만든 CSV 파일 읽기
    if not INPUT_FILE.exists():
        print(f"❌ {INPUT_FILE.name} 파일을 찾을 수 없습니다. 'runner.py'를 먼저 실행하세요!")
        return
    
    # df: DataFrame
    df = pd.read_csv(INPUT_FILE)
    
    # 2. 비동기 병렬 채점 준비 (LLM 토픽 관련성)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_EVALS)
    tasks = []
    
    records = df.to_dict(orient="records")
    
    for i, row in enumerate(records):
        tasks.append(evaluate_row(i, row, semaphore))
        
    # 3. 한방에 싹 채점 돌리기 (LLM 병렬 처리)
    scores = await asyncio.gather(*tasks)
    
    # =========================================================
    # 🛠️ 4. 모든 평가 지표 컬럼 계산 및 추가 (Pandas 활용)
    # =========================================================
    
    # ① LLM 심판 점수 기록
    df["Topic Relevance (1-5)"] = scores

    # ② 카테고리 일치도 채점 (문자열 비교)
    print("🧮 카테고리 및 난이도 일치도 연산 중...")
    df["Category Match"] = df.apply(
        lambda x: "O" if str(x.get("Expected Category", "")) == str(x.get("HyDE Category", "")) else "X", 
        axis=1
    )

    # ③ 난이도 일치도 채점 (절대 오차 1.5 이하 Pass)
    # 결측치(NaN) 방어를 위해 float 변환 시 예외 처리 적용
    def check_level_match(x):
        try:
            expected = float(x.get("Expected Level", 0))
            actual = float(x.get("Book 1 Level", 0) + x.get("Book 2 Level", 0) + x.get("Book 3 Level", 0)) / 3
            return "Pass" if abs(expected - actual) <= ALLOWED_LEVEL_DIFF else "Fail"
        except (ValueError, TypeError):
            return "Fail"
            
    df["Level Match"] = df.apply(check_level_match, axis=1)
    
    # 5. 최종 결과 CSV로 굽기
    df.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")
    
    # =========================================================
    # 📊 대망의 최종 성적표 출력
    # =========================================================
    # 분모가 0이 되는 에러 방지
    total_len = len(df)
    if total_len == 0:
        print("❌ 분석할 데이터가 없습니다.")
        return

    category_acc = (len(df[df["Category Match"] == "O"]) / total_len) * 100
    level_pass_rate = (len(df[df["Level Match"] == "Pass"]) / total_len) * 100
    avg_topic_score = df["Topic Relevance (1-5)"].mean()
    
    print("\n🎉 [최종 리포트] 채점이 모두 완료되었습니다! 🎉")
    print("-" * 40)
    print(f"✅ [지표 1] 카테고리 적중률:  {category_acc:.1f}%")
    print(f"✅ [지표 2] 난이도 일치도:    {level_pass_rate:.1f}%")
    print(f"✅ [지표 3] 토픽 관련성 평균: {avg_topic_score:.2f} / 5.0 점")
    print("-" * 40)
    print(f"📁 모든 결과가 '{OUTPUT_FILE.name}'에 저장되었습니다.")

if __name__ == "__main__":
    asyncio.run(run_judge())