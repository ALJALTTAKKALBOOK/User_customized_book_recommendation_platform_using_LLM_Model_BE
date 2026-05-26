"""
analyze_difficulty.py — enrich 결과 종합 진단 (v2)

v1 변경 사항 반영: short_summary 길이 분포 + 카테고리별 길이 분석 추가.

진단 항목:
  1. 전체 난이도 분포 + 히스토그램
  2. 카테고리별 난이도 통계
  3. short_summary 길이 분포 (v1 신규)
  4. 카테고리별 short_summary 평균 길이 (v1 신규)
  5. 자동 건강도 체크 (난이도 + 길이)

실행:
    cd BE
    python crawler/scripts/analyze_difficulty.py
"""

import json
import os
from collections import Counter, defaultdict

DATA_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'enriched_books.json')


def main():
    if not os.path.exists(DATA_PATH):
        print(f"파일 없음: {DATA_PATH}")
        return

    with open(DATA_PATH, 'r', encoding='utf-8') as f:
        books = json.load(f)

    print(f"\n{'=' * 70}")
    print(f"BookFit enrich 결과 종합 진단  (총 {len(books)}권)")
    print(f"{'=' * 70}\n")

    # ─────────────────────────────────────────
    # 1. 전체 난이도 분포
    # ─────────────────────────────────────────
    diffs = Counter(b['difficulty'] for b in books)
    if not diffs:
        print("난이도 데이터 없음")
        return
    max_count = max(diffs.values())

    print("[1] 전체 난이도 분포")
    print("-" * 70)
    print(f"{'난이도':>5} {'  ':>4} {'권수':>6}  {'비율':>7}  {'분포':<42}")
    print("-" * 70)
    label_map = {
        0: "입문", 1: "입문", 2: "입문",
        3: "초급", 4: "초급",
        5: "중급", 6: "중급",
        7: "고급", 8: "고급",
        9: "전문가", 10: "전문가",
    }
    for level in range(11):
        count = diffs.get(level, 0)
        if count == 0:
            continue
        label = label_map.get(level, "")
        bar = "█" * int(count / max_count * 40)
        pct = count / len(books) * 100
        print(f"  {level:2d}  {label:>4} {count:>5}권  {pct:>5.1f}%  {bar}")

    # 통계 요약
    sorted_diffs = sorted(b['difficulty'] for b in books)
    avg = sum(sorted_diffs) / len(sorted_diffs)
    median = sorted_diffs[len(sorted_diffs) // 2]
    print(
        f"\n  평균: {avg:.2f}   중앙값: {median}   "
        f"최저: {min(sorted_diffs)}   최고: {max(sorted_diffs)}"
    )

    # ─────────────────────────────────────────
    # 2. 카테고리별 난이도 통계
    # ─────────────────────────────────────────
    cat_diffs = defaultdict(list)
    for b in books:
        cat_diffs[b['sub_category']].append(b['difficulty'])

    print(f"\n\n[2] 카테고리별 난이도 통계")
    print("-" * 70)
    print(f"{'카테고리':<18} {'권수':>5}  {'평균':>5}  {'min':>3}  {'max':>3}  {'분포':<11}")
    print("-" * 70)

    for cat, vals in sorted(cat_diffs.items(), key=lambda x: -sum(x[1]) / len(x[1])):
        cat_avg = sum(vals) / len(vals)
        # 미니 히스토그램
        cat_counter = Counter(vals)
        mini_max = max(cat_counter.values()) if cat_counter else 1
        mini_bars = ""
        for lv in range(11):
            c = cat_counter.get(lv, 0)
            if c == 0:
                mini_bars += "·"
            elif c / mini_max > 0.66:
                mini_bars += "█"
            elif c / mini_max > 0.33:
                mini_bars += "▓"
            else:
                mini_bars += "░"
        print(
            f"  {cat:<16} {len(vals):>5}권  {cat_avg:>5.2f}  "
            f"{min(vals):>3}  {max(vals):>3}  {mini_bars}"
        )

    # ─────────────────────────────────────────
    # 3. short_summary 길이 분포  [v1 신규]
    # ─────────────────────────────────────────
    print(f"\n\n[3] short_summary 길이 분포  (v1 신규)")
    print("-" * 70)
    short_lengths = [len(b.get('short_summary', '')) for b in books]
    missing = sum(1 for l in short_lengths if l == 0)
    valid_lengths = [l for l in short_lengths if l > 0]

    if not valid_lengths:
        print("  ⚠️  short_summary가 모든 책에 누락됨!")
    else:
        avg_len = sum(valid_lengths) / len(valid_lengths)
        print(f"  평균: {avg_len:.1f}자")
        print(f"  최소: {min(valid_lengths)}자  /  최대: {max(valid_lengths)}자")
        print(f"  100자 초과: {sum(1 for l in valid_lengths if l > 100)}권")
        print(f"  120자 초과: {sum(1 for l in valid_lengths if l > 120)}권 (절단 대상)")
        print(f"  누락 (0자): {missing}권")

        # 길이 히스토그램 (10자 단위)
        print(f"\n  [길이 히스토그램 (10자 단위)]")
        bins = Counter()
        for l in valid_lengths:
            bins[l // 10 * 10] += 1
        max_bin = max(bins.values())
        for bin_start in sorted(bins.keys()):
            count = bins[bin_start]
            bar = "█" * int(count / max_bin * 30)
            print(f"    {bin_start:3d}~{bin_start+9:3d}자: {count:>4}권  {bar}")

    # ─────────────────────────────────────────
    # 4. 카테고리별 short_summary 평균 길이  [v1 신규]
    # ─────────────────────────────────────────
    print(f"\n\n[4] 카테고리별 short_summary 평균 길이  (v1 신규)")
    print("-" * 70)
    cat_lengths = defaultdict(list)
    for b in books:
        cat = b['sub_category']
        sl = len(b.get('short_summary', ''))
        if sl > 0:
            cat_lengths[cat].append(sl)

    print(f"{'카테고리':<18} {'권수':>5}  {'평균':>6}  {'min':>4}  {'max':>4}")
    print("-" * 70)
    for cat, lens in sorted(cat_lengths.items(), key=lambda x: -sum(x[1]) / len(x[1])):
        cat_avg_len = sum(lens) / len(lens)
        print(
            f"  {cat:<16} {len(lens):>5}권  {cat_avg_len:>5.1f}자  "
            f"{min(lens):>4}  {max(lens):>4}"
        )

    # ─────────────────────────────────────────
    # 5. 건강도 체크 (자동 진단)
    # ─────────────────────────────────────────
    print(f"\n\n[5] 자동 건강도 체크")
    print("-" * 70)

    # 5-1. 난이도 — 중간값 편중
    mid_count = sum(diffs.get(l, 0) for l in [4, 5, 6])
    mid_pct = mid_count / len(books) * 100
    print(f"\n[난이도]")
    if mid_pct > 70:
        print(f"  ⚠️  중간값(4~6) 편중: {mid_pct:.1f}% — 프롬프트 앵커 강화 필요")
    else:
        print(f"  ✓ 중간값(4~6) 비율: {mid_pct:.1f}% — 정상")

    # 5-2. 난이도 — 극단값 사용
    extreme_count = diffs.get(0, 0) + diffs.get(10, 0)
    extreme_pct = extreme_count / len(books) * 100
    if extreme_pct < 1.0:
        print(f"  ⚠️  극단값(0, 10) 거의 없음: {extreme_count}권 ({extreme_pct:.1f}%) — 모델이 안전하게만 판정 중")
    else:
        print(f"  ✓ 극단값(0, 10): {extreme_count}권 ({extreme_pct:.1f}%) — 모델이 극단 판정도 함")

    # 5-3. 난이도 — 사용되지 않은 점수
    unused = [l for l in range(11) if diffs.get(l, 0) == 0]
    if unused:
        print(f"  ⚠️  사용되지 않은 난이도: {unused}")
    else:
        print(f"  ✓ 모든 난이도(0~10) 사용됨")

    # 5-4. short_summary — 누락
    print(f"\n[short_summary]")
    if missing > 0:
        print(f"  ⚠️  short_summary 누락: {missing}권 — 재처리 필요")
    else:
        print(f"  ✓ 모든 책에 short_summary 존재")

    # 5-5. short_summary — 길이 적정성
    if valid_lengths:
        over_100 = sum(1 for l in valid_lengths if l > 100)
        over_100_pct = over_100 / len(valid_lengths) * 100
        if over_100_pct > 5:
            print(f"  ⚠️  100자 초과 비율 높음: {over_100_pct:.1f}% — 프롬프트 강화 필요")
        else:
            print(f"  ✓ 100자 초과: {over_100_pct:.1f}% — 정상")

        # 너무 짧은 것 검출 (30자 미만)
        too_short = sum(1 for l in valid_lengths if l < 30)
        too_short_pct = too_short / len(valid_lengths) * 100
        if too_short_pct > 5:
            print(f"  ⚠️  30자 미만(정보 부족 의심): {too_short}권 ({too_short_pct:.1f}%)")
        else:
            print(f"  ✓ 30자 미만: {too_short_pct:.1f}% — 정상")

    print(f"\n{'=' * 70}\n")


if __name__ == "__main__":
    main()