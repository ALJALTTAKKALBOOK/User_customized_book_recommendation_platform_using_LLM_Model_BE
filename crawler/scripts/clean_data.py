import json
import os
from datetime import datetime
import pandas as pd

# 파일 경로
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
INPUT_PATH = os.path.join(DATA_DIR, 'raw_books.json')
OUTPUT_PATH = os.path.join(DATA_DIR, 'cleaned_books.json')

# 정제 기준
MIN_SUMMARY_LENGTH = 30   # summary 최소 글자 수
TODAY = datetime.now().strftime("%Y-%m-%d")


def load_raw_data():
    """raw_books.json을 읽어 DataFrame으로 반환한다."""
    with open(INPUT_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    df = pd.DataFrame(data)
    print(f"원본 데이터: {len(df)}권")
    return df


def remove_duplicates(df):
    """ISBN 기준으로 중복 도서를 제거한다."""
    before = len(df)
    df = df.drop_duplicates(subset='isbn', keep='first')
    after = len(df)
    removed = before - after
    if removed > 0:
        print(f"  중복 제거: {removed}권 제거 → {after}권 남음")
    return df


def remove_empty_summary(df):
    """summary가 비어있거나 너무 짧은 도서를 제거한다."""
    before = len(df)
    df = df[df['summary'].str.strip().str.len() >= MIN_SUMMARY_LENGTH]
    after = len(df)
    removed = before - after
    if removed > 0:
        print(f"  summary 부족: {removed}권 제거 → {after}권 남음 (최소 {MIN_SUMMARY_LENGTH}자)")
    return df


def remove_future_books(df):
    """아직 출간되지 않은 도서를 제거한다."""
    before = len(df)
    df = df[df['published_at'] <= TODAY]
    after = len(df)
    removed = before - after
    if removed > 0:
        print(f"  미출간 도서: {removed}권 제거 → {after}권 남음 (기준일: {TODAY})")
    return df


def clean_text(df):
    """텍스트 필드의 불필요한 공백과 줄바꿈을 정리한다."""
    text_columns = ['title', 'author', 'summary']
    for col in text_columns:
        if col in df.columns:
            # 줄바꿈 → 공백, 연속 공백 → 단일 공백, 앞뒤 공백 제거
            df[col] = df[col].str.replace(r'\s+', ' ', regex=True).str.strip()
    print(f"  텍스트 정리 완료")
    return df


def main():
    print("=" * 50)
    print("BookFit 크롤러 - Step 3: 데이터 정제")
    print("=" * 50)

    # 1. 데이터 로드
    if not os.path.exists(INPUT_PATH):
        print(f"raw_books.json이 없습니다. crawl_detail.py를 먼저 실행하세요.")
        return

    df = load_raw_data()

    # 2. 정제 수행
    print("\n[정제 시작]")
    df = clean_text(df)
    df = remove_duplicates(df)
    df = remove_empty_summary(df)
    df = remove_future_books(df)

    # 3. 결과 저장
    df.to_json(OUTPUT_PATH, orient='records', force_ascii=False, indent=2)

    # 4. 최종 통계
    print(f"\n{'=' * 50}")
    print(f"정제 완료! {len(df)}권")
    print(f"저장 위치: {OUTPUT_PATH}")
    print(f"\n[카테고리별 분포]")
    for cat, count in df['sub_category'].value_counts().items():
        print(f"  {cat}: {count}권")
    print(f"\n[필드별 현황]")
    print(f"  summary 있음: {df['summary'].notna().sum()}권")
    print(f"  grade_point 있음: {df['grade_point'].notna().sum()}권")
    print(f"  summary 평균 길이: {df['summary'].str.len().mean():.0f}자")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()