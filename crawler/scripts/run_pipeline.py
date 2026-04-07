"""
run_pipeline.py — 데이터 파이프라인 통합 실행 스크립트

crawl_detail → clean_data → enrich_data → embedder 순서로 실행한다.
load_to_db.py는 DB 적재이므로 별도 수동 실행.

실행 방법:
    cd BE/crawler

    # 전체 실행 (urls.json 전체 대상)
    python scripts/run_pipeline.py

    # 테스트 실행 (카테고리당 N권만 크롤링)
    python scripts/run_pipeline.py --limit 10

    # 특정 단계부터 실행 (crawl_detail 이미 끝난 경우)
    python scripts/run_pipeline.py --start clean

입력: data/urls.json (crawl_list.py 산출물)
최종 출력: data/embedded_books.json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# 경로
SCRIPTS_DIR = Path(__file__).resolve().parent
CRAWLER_DIR = SCRIPTS_DIR.parent
DATA_DIR = CRAWLER_DIR / "data"
URLS_PATH = DATA_DIR / "urls.json"
URLS_BACKUP_PATH = DATA_DIR / "urls_full.json"

# 파이프라인 단계 정의 (순서대로)
STEPS = [
    {
        "name": "crawl_detail",
        "script": "scripts/crawl_detail.py",
        "desc": "Step 2: 도서 상세 정보 수집",
        "output": "data/raw_books.json",
    },
    {
        "name": "clean",
        "script": "scripts/clean_data.py",
        "desc": "Step 3: 데이터 정제",
        "output": "data/cleaned_books.json",
    },
    {
        "name": "enrich",
        "script": "scripts/enrich_data.py",
        "desc": "Step 3.5: 난이도/키워드 생성",
        "output": "data/enriched_books.json",
    },
    {
        "name": "embed",
        "script": "scripts/embedder.py",
        "desc": "Step 4: 임베딩 벡터 생성",
        "output": "data/embedded_books.json",
    },
]

STEP_NAMES = [s["name"] for s in STEPS]


def create_limited_urls(limit_per_category):
    """테스트용으로 카테고리당 N권만 포함하는 urls.json을 생성한다."""
    if not URLS_PATH.exists():
        print(f"urls.json이 없습니다. crawl_list.py를 먼저 실행하세요.")
        sys.exit(1)

    with open(URLS_PATH, 'r', encoding='utf-8') as f:
        full_data = json.load(f)

    # 원본 백업
    if not URLS_BACKUP_PATH.exists():
        with open(URLS_BACKUP_PATH, 'w', encoding='utf-8') as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2)
        print(f"  원본 urls.json 백업 → urls_full.json")

    # 카테고리당 N권으로 제한
    limited = {}
    for cat, urls in full_data.items():
        limited[cat] = urls[:limit_per_category]

    with open(URLS_PATH, 'w', encoding='utf-8') as f:
        json.dump(limited, f, ensure_ascii=False, indent=2)

    total = sum(len(u) for u in limited.values())
    print(f"  테스트 모드: 카테고리당 {limit_per_category}권 → 총 {total}권")
    return total


def restore_full_urls():
    """테스트 후 원본 urls.json을 복구한다."""
    if URLS_BACKUP_PATH.exists():
        with open(URLS_BACKUP_PATH, 'r', encoding='utf-8') as f:
            full_data = json.load(f)
        with open(URLS_PATH, 'w', encoding='utf-8') as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2)
        URLS_BACKUP_PATH.unlink()
        print("  urls.json 원본 복구 완료")


def run_step(step):
    """한 단계를 subprocess로 실행한다."""
    script_path = CRAWLER_DIR / step["script"]

    print(f"\n{'=' * 60}")
    print(f"▶ {step['desc']}")
    print(f"  실행: python {step['script']}")
    print(f"{'=' * 60}\n")

    start = time.time()

    result = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=str(CRAWLER_DIR),
    )

    elapsed = time.time() - start
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    if result.returncode != 0:
        print(f"\n{step['name']} 실패 (exit code: {result.returncode})")
        print(f"   소요 시간: {minutes}분 {seconds}초")
        return False

    print(f"\n✅ {step['name']} 완료 (소요: {minutes}분 {seconds}초)")

    # 출력 파일 확인
    output_path = CRAWLER_DIR / step["output"]
    if output_path.exists():
        size = output_path.stat().st_size / 1024
        print(f"   출력: {step['output']} ({size:.1f} KB)")
    return True


def main():
    parser = argparse.ArgumentParser(description="BookFit 데이터 파이프라인")
    parser.add_argument(
        "--limit", type=int, default=None,
        help="테스트용: 카테고리당 수집할 최대 권수 (예: --limit 10)"
    )
    parser.add_argument(
        "--start", type=str, default=None, choices=STEP_NAMES,
        help="특정 단계부터 시작 (예: --start clean)"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("BookFit 데이터 파이프라인")
    print("crawl_detail → clean → enrich → embedder")
    print("=" * 60)

    # 테스트 모드: urls.json 제한
    is_test = args.limit is not None
    if is_test:
        create_limited_urls(args.limit)

    # 시작 단계 결정
    if args.start:
        start_idx = STEP_NAMES.index(args.start)
        print(f"\n  '{args.start}' 단계부터 시작")
    else:
        start_idx = 0

    steps_to_run = STEPS[start_idx:]

    # 파이프라인 실행
    pipeline_start = time.time()

    for step in steps_to_run:
        success = run_step(step)
        if not success:
            print(f"\n파이프라인 중단: {step['name']}에서 실패")
            if is_test:
                restore_full_urls()
            sys.exit(1)

    pipeline_elapsed = time.time() - pipeline_start
    minutes = int(pipeline_elapsed // 60)
    seconds = int(pipeline_elapsed % 60)

    # 테스트 모드: urls.json 원복
    if is_test:
        restore_full_urls()

    # 최종 결과
    print(f"\n{'=' * 60}")
    print(f"파이프라인 완료 총 소요: {minutes}분 {seconds}초")
    print(f"최종 출력: data/embedded_books.json")
    print(f"\nDB 적재는 별도 실행:")
    print(f"  python scripts/load_to_db.py")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()