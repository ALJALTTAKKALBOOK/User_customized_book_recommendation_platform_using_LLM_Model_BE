import asyncio
import json
import os
from playwright.async_api import async_playwright

# 크롤러 설정 가져오기
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from config import (
    CATEGORY_URL,
    KYOBO_CATEGORY_CODES,
    CRAWL_DELAY,
    MAX_PER_CATEGORY,
    HEADLESS,
)

# 파일 경로
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'urls.json')


async def get_book_urls_from_page(page):
    """현재 페이지에서 도서 상세 페이지 URL들을 추출한다."""
    await page.wait_for_selector("a.prod_info", timeout=10000)
    links = await page.query_selector_all('a.prod_info[href*="/detail/S"]')

    urls = []
    for link in links:
        href = await link.get_attribute("href")
        if href:
            urls.append(href)

    return list(set(urls))  # 중복 제거


async def crawl_category(page, category_name, category_code):
    """한 카테고리의 도서 URL을 수집한다. MAX_PER_CATEGORY에 도달하거나 더 이상 없으면 종료."""
    print(f"\n[{category_name}] 크롤링 시작 (코드: {category_code}, 최대: {MAX_PER_CATEGORY}권)")

    all_urls = []
    page_num = 1

    while True:
        url = f"{CATEGORY_URL}/{category_code}#?page={page_num}&type=all&sort=sel"
        print(f"  페이지 {page_num} 접속 중...")

        await page.goto(url)
        await asyncio.sleep(CRAWL_DELAY)

        # 현재 페이지에서 URL 추출
        try:
            urls = await get_book_urls_from_page(page)
        except Exception as e:
            print(f"  페이지 {page_num}에서 도서를 찾을 수 없음. 크롤링 종료. ({e})")
            break

        if not urls:
            print(f"  페이지 {page_num}에 도서가 없음. 크롤링 종료.")
            break

        all_urls.extend(urls)
        print(f"  {len(urls)}권 발견 (누적: {len(all_urls)}권)")

        # 카테고리당 최대 수집 권수 도달
        if len(all_urls) >= MAX_PER_CATEGORY:
            all_urls = all_urls[:MAX_PER_CATEGORY]
            print(f"  최대 {MAX_PER_CATEGORY}권 도달. 다음 카테고리로.")
            break

        page_num += 1

    print(f"[{category_name}] 완료: {len(all_urls)}권 수집")
    return all_urls


def save_result(result):
    """현재까지 수집된 결과를 urls.json에 저장한다."""
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


async def main():
    """모든 카테고리를 순회하며 도서 URL을 수집한다."""
    print("=" * 50)
    print("BookFit 크롤러 - Step 1: 도서 URL 수집")
    print(f"카테고리당 최대 {MAX_PER_CATEGORY}권, {len(KYOBO_CATEGORY_CODES)}개 카테고리")
    print("=" * 50)

    # 결과 저장용 딕셔너리
    result = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page = await browser.new_page()

        for category_name, category_code in KYOBO_CATEGORY_CODES.items():
            urls = await crawl_category(page, category_name, category_code)
            result[category_name] = urls

            # 카테고리 하나 끝날 때마다 누적 저장
            save_result(result)
            total_so_far = sum(len(u) for u in result.values())
            print(f"  → urls.json 저장 완료 (전체 누적: {total_so_far}권)")

        await browser.close()

    # 최종 통계 출력
    total = sum(len(urls) for urls in result.values())
    print(f"\n{'=' * 50}")
    print(f"수집 완료! 총 {total}권")
    print(f"저장 위치: {OUTPUT_PATH}")
    for cat, urls in result.items():
        print(f"  {cat}: {len(urls)}권")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())