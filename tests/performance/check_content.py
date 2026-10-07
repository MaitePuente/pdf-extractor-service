"""Audit text preservation/order independently of the timed conversion.

This verifies selectable text against geometrically sorted PyMuPDF spans.
It does not verify semantic reading order for complex columns or image text.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

import pymupdf


def plain_markdown(markdown):
    escaped = []

    def protect(match):
        escaped.append(match[1])
        return '\ue000' + str(len(escaped) - 1) + '\ue001'

    text = re.sub(r'\\([\\`*_[\]<>#|])', protect, markdown)
    text = re.sub(r'<!--.*?-->', '', text, flags=re.S)
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'</?(?:sup|sub|u|b|em|strong)(?:\s[^>]*)?>', '', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.M).replace('*', '')
    text = re.sub(r'(?<!\w)_+|_+(?!\w)', '', text)
    return re.sub(r'\ue000(\d+)\ue001', lambda m: escaped[int(m[1])], text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', required=True, type=Path)
    parser.add_argument('--markdown', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to overwrite prior evidence')
    body = args.pdf.read_bytes()
    content = args.markdown.read_text(encoding='utf-8')
    compact = lambda s: re.sub(r'\s+', '', s)
    actual = compact(plain_markdown(content))
    expected_pages = []
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    with pymupdf.open(stream=body, filetype='pdf') as doc:
        for page in doc:
            data = page.get_text('dict', flags=flags, sort=True)
            expected_pages.append(compact(''.join(
                span['text'] for block in data['blocks']
                for line in block.get('lines', []) for span in line['spans']
            )))
        source_pages = doc.page_count
    cursor = 0
    page_checks = []
    for number, text in enumerate(expected_pages, 1):
        found = actual.find(text, cursor) if text else cursor
        page_checks.append({'page': number, 'text_chars': len(text), 'found_at': found})
        if found >= 0:
            cursor = found + len(text)
    exact = actual == ''.join(expected_pages)
    report = dict(
        source_pages=source_pages, pdf_bytes=len(body),
        input_sha256=hashlib.sha256(body).hexdigest(),
        content_sha256=hashlib.sha256(content.encode()).hexdigest(), chars=len(content),
        all_selectable_characters_in_geometric_order=exact,
        pages_with_selectable_text=sum(bool(p) for p in expected_pages),
        pages_found_in_order=all(p['found_at'] >= 0 for p in page_checks),
        page_checks=page_checks,
        missing_characters=dict(Counter(''.join(expected_pages)) - Counter(actual)),
    )
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'page_checks'}))
    if not exact:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
