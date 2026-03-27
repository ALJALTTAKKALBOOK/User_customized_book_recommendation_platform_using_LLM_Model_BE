import asyncio
import json
import os
import re
from playwright.async_api import async_playwright

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from config import CRAWL_DELAY, KYOBO_CATEGORY_CODES

# 파일 경로
DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data')
URLS_PATH = os.path.join(DATA_DIR, 'urls.json')
OUTPUT_PATH = os.path.join(DATA_DIR, 'raw_books.json')


async def extract_book_info(page, url, category_name):
    """상세 페이지에서 도서 정보를 추출한다."""
    try:
        await page.goto(url)
        await page.wait_for_selector(".prod_title", timeout=10000)
        await asyncio.sleep(1)  # 동적 렌더링 대기

        book = {}

        # 제목
        title_el = await page.query_selector(".prod_title")
        book["title"] = await title_el.text_content() if title_el else ""
        book["title"] = book["title"].strip()

        # 저자 (번역자 제외, 공동 저자는 쉼표로 연결)
        author_el = await page.query_selector(".prod_author_box .author")
        if author_el:
            author_text = await author_el.text_content()
            # "저자(글)" 이전 텍스트만 추출 (번역자 제외)
            match = re.match(r"(.+?)저자", author_text, re.DOTALL)
            if match:
                raw = match.group(1)
            else:
                raw = author_text.split("·")[0]
            # 공백/줄바꿈 정리 후 쉼표로 분리된 이름 추출
            names = [name.strip() for name in raw.split(",") if name.strip()]
            book["author"] = ", ".join(names)
        else:
            book["author"] = ""

        # 평점
        rating_el = await page.query_selector(".review_score.feel_lucky")
        if rating_el:
            rating_text = await rating_el.text_content()
            try:
                book["grade_point"] = float(rating_text.strip())
            except ValueError:
                book["grade_point"] = None
        else:
            book["grade_point"] = None

        # 기본정보 테이블 (ISBN, 쪽수)
        book["isbn"] = ""
        book["page_count"] = None

        ths = await page.query_selector_all("table.tbl_row th")
        tds = await page.query_selector_all("table.tbl_row td")

        for i, th in enumerate(ths):
            th_text = await th.text_content()
            th_text = th_text.strip()

            if i < len(tds):
                td_text = await tds[i].text_content()
                td_text = td_text.strip()

                if "ISBN" in th_text:
                    book["isbn"] = td_text

                if "쪽수" in th_text:
                    # "640쪽" → 640
                    num_match = re.search(r"(\d+)", td_text)
                    book["page_count"] = int(num_match.group(1)) if num_match else None

        # 출간일
        pub_el = await page.query_selector(".prod_info_text.publish_date")
        if pub_el:
            pub_text = await pub_el.text_content()
            date_match = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", pub_text)
            if date_match:
                y, m, d = date_match.groups()
                book["published_at"] = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            else:
                book["published_at"] = ""
        else:
            book["published_at"] = ""

        # 표지 이미지
        cover_el = await page.query_selector(".portrait_img_box img")
        if cover_el:
            book["cover_url"] = await cover_el.get_attribute("src") or ""
        else:
            book["cover_url"] = ""

        # 책소개 (summary)
        summary_el = await page.query_selector(".intro_bottom .info_text")
        if summary_el:
            book["summary"] = (await summary_el.text_content()).strip()
        else:
            # 대체 셀렉터 시도
            intro_el = await page.query_selector(".product_detail_area.book_intro")
            if intro_el:
                paragraphs = await intro_el.query_selector_all("p")
                texts = []
                for p in paragraphs:
                    text = await p.text_content()
                    text = text.strip()
                    if len(text) > 20:
                        texts.append(text)
                book["summary"] = " ".join(texts)
            else:
                book["summary"] = ""

        # 목차
        toc_el = await page.query_selector(".product_detail_area.book_contents .auto_overflow_inner")
        if toc_el:
            toc_html = await toc_el.inner_html()
            # <br> → 줄바꿈으로 치환 후 HTML 태그 제거
            toc_text = toc_html.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
            toc_text = re.sub(r"<[^>]+>", "", toc_text)  # HTML 태그 제거
            # 빈 줄 정리
            lines = [line.strip() for line in toc_text.split("\n") if line.strip()]
            book["table_of_contents"] = "\n".join(lines)
        else:
            book["table_of_contents"] = ""

        # 리뷰 (좋아요 순, 최대 30개)
        book["reviews"] = []
        try:
            # 리뷰 섹션으로 스크롤
            review_section = await page.query_selector(".klover_review_wrap")
            if review_section:
                await review_section.scroll_into_view_if_needed()
                await asyncio.sleep(1)

                # 좋아요 순 정렬 (JavaScript로 직접 변경)
                await page.evaluate("""
                    const sel = document.querySelector('.klover_review_wrap select');
                    if (sel) {
                        sel.value = '001';
                        sel.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                """)
                await asyncio.sleep(2)  # 정렬 변경 후 리렌더링 대기

            review_items = await page.query_selector_all(".comment_item .comment_contents")
            for item in review_items[:30]:
                text = (await item.text_content()).strip()
                if text:
                    book["reviews"].append(text)
        except Exception as e:
            print(f"    [리뷰 수집 실패] {e}")

        # config에서 지정하는 값
        book["genre"] = "IT"
        book["sub_category"] = category_name
        book["language"] = "한국어"

        # 이후 단계에서 생성할 필드
        book["difficulty"] = None
        book["keywords"] = None
        book["total_readers"] = None

        # URL 기록 (나중에 디버깅/구매링크용)
        book["url"] = url

        return book

    except Exception as e:
        print(f"    [에러] {url}: {e}")
        return None


async def main():
    print("=" * 50)
    print("BookFit 크롤러 - Step 2: 도서 상세 정보 수집")
    print("=" * 50)

    # urls.json 읽기
    if not os.path.exists(URLS_PATH):
        print(f"urls.json이 없습니다. crawl_list.py를 먼저 실행하세요.")
        return

    with open(URLS_PATH, 'r', encoding='utf-8') as f:
        url_data = json.load(f)

    total_urls = sum(len(urls) for urls in url_data.values())
    print(f"총 {total_urls}개 URL 로드 완료\n")

    all_books = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page()

        for category_name, urls in url_data.items():
            print(f"\n[{category_name}] {len(urls)}권 수집 시작")

            for i, url in enumerate(urls):
                print(f"  ({i+1}/{len(urls)}) {url}")
                book = await extract_book_info(page, url, category_name)

                if book:
                    all_books.append(book)
                    print(f"    → {book['title'][:30]} | {book['author']}")
                else:
                    print(f"    → 수집 실패")

                await asyncio.sleep(CRAWL_DELAY)

        await browser.close()

    # 결과 저장
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(all_books, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 50}")
    print(f"수집 완료! 총 {len(all_books)}권")
    print(f"저장 위치: {OUTPUT_PATH}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())