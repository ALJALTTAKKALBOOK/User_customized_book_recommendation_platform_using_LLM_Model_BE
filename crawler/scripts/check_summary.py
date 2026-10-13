# scripts/check_summary.py
import json

with open('data/raw_books.json', encoding='utf-8') as f:
    books = json.load(f)

empty = [b for b in books if len((b.get('summary') or '').strip()) < 20]
print(f'summary 20자 미만: {len(empty)}권\n')
for b in empty[:5]:
    s = (b.get('summary') or '').strip()
    print(f'제목: {b["title"][:40]}')
    print(f'  summary: "{s}"')
    print(f'  url: {b["url"]}')
    print()