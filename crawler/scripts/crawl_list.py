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
    TEST_MODE,
    TEST_LIMIT,
)


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
    """한 카테고리의 도서 URL을 수집한다."""
    print(f"\n[{category_name}] 크롤링 시작 (코드: {category_code})")
    
    all_urls = []
    page_num = 1
    
    while True:
        url = f"{CATEGORY_URL}/{category_code}#?page={page_num}&type=all&sort=sel"
        print(f"  페이지 {page_num} 접속 중... {url}")
        
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
        
        # 테스트 모드: 카테고리당 제한된 수만 수집
        if TEST_MODE and len(all_urls) >= TEST_LIMIT:
            all_urls = all_urls[:TEST_LIMIT]
            print(f"  [테스트 모드] {TEST_LIMIT}권 제한 도달. 다음 카테고리로.")
            break
        
        page_num += 1
    
    print(f"[{category_name}] 완료: 총 {len(all_urls)}권")
    return all_urls


async def main():
    """모든 카테고리를 순회하며 도서 URL을 수집한다."""
    print("=" * 50)
    print("BookFit 크롤러 - Step 1: 도서 URL 수집")
    print("=" * 50)
    
    # 결과 저장용 딕셔너리
    result = {}
    
    async with async_playwright() as pw:
        # 브라우저 실행 (headless=False로 하면 브라우저 창이 보임)
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page()
        
        for category_name, category_code in KYOBO_CATEGORY_CODES.items():
            urls = await crawl_category(page, category_name, category_code)
            result[category_name] = urls
        
        await browser.close()
    
    # 결과 저장
    output_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'urls.json')
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # 통계 출력
    total = sum(len(urls) for urls in result.values())
    print(f"\n{'=' * 50}")
    print(f"수집 완료! 총 {total}권")
    print(f"저장 위치: {output_path}")
    for cat, urls in result.items():
        print(f"  {cat}: {len(urls)}권")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())