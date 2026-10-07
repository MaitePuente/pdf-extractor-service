"""Basic page Markdown, plus the previous spans converter for offline comparison.

Production joins only textual blocks in their native order, under one page heading.
The previous get_text("text") path remains available for offline comparison.
The retained offline spans converter uses geometric sorting and font styles.
Neither converter reconstructs a semantic multi-column reading order.
"""
from collections import Counter
import re
from time import perf_counter

import pymupdf


def to_spans_markdown(document, *, pages=None, **kwargs):
    selected = range(document.page_count) if pages is None else pages
    flags = pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES
    page_data = [document[number].get_text('dict', flags=flags, sort=True)
                 for number in selected]
    sizes = Counter()
    for page in page_data:
        for block in page['blocks']:
            for line in block.get('lines', []):
                for span in line['spans']:
                    sizes[round(span['size'], 1)] += len(span['text'].strip())
    body_size = sizes.most_common(1)[0][0] if sizes else 0
    heading_sizes = sorted((s for s in sizes if s > body_size * 1.2), reverse=True)
    levels = {size: min(i + 1, 6) for i, size in enumerate(heading_sizes)}
    output = []
    for page in page_data:
        blocks = []
        for block in page['blocks']:
            lines = []
            for line in block.get('lines', []):
                parts = []
                for span in line['spans']:
                    text = span['text']
                    # Escape source syntax before adding Markdown formatting.
                    text = re.sub(r'([\\`*_[\]<>#|])', r'\\\1', text)
                    if text.strip():
                        leading = text[:len(text) - len(text.lstrip())]
                        trailing = text[len(text.rstrip()):]
                        value = text.strip()
                        if span['flags'] & 16:
                            value = '**' + value + '**'
                        if span['flags'] & 2:
                            value = '*' + value + '*'
                        text = leading + value + trailing
                    parts.append(text)
                text = ''.join(parts).strip()
                if not text:
                    continue
                size = max(round(s['size'], 1) for s in line['spans'])
                if size in levels:
                    text = '#' * levels[size] + ' ' + text
                lines.append(text)
            if lines:
                blocks.append('\n'.join(lines))
        output.append('\n\n'.join(blocks))
    return '\n\n'.join(output) + ('\n' if any(output) else '')


def to_text_markdown(document, *, pages=None, timings=None):
    selected = range(document.page_count) if pages is None else pages
    get_text_ms = 0.0
    build_ms = 0.0
    parts = []
    for number in selected:
        page = document[number]
        started = perf_counter()
        text = page.get_text("text")
        get_text_ms += (perf_counter() - started) * 1000
        started = perf_counter()
        parts.append(f"## Página {number + 1}\n\n{text}")
        build_ms += (perf_counter() - started) * 1000
    started = perf_counter()
    content = "\n\n".join(parts)
    build_ms += (perf_counter() - started) * 1000
    if timings is not None:
        timings.update(get_text_ms=get_text_ms, markdown_build_ms=build_ms)
    return content


def to_markdown(document, *, pages=None, timings=None):
    selected = range(document.page_count) if pages is None else pages
    get_text_ms = build_ms = 0.0
    parts = []
    for number in selected:
        page = document[number]
        started = perf_counter()
        blocks = page.get_text("blocks", sort=False)
        get_text_ms += (perf_counter() - started) * 1000
        started = perf_counter()
        text = ''.join(block[4] for block in blocks if block[6] == 0)
        parts.append(f"## Página {number + 1}\n\n{text}")
        build_ms += (perf_counter() - started) * 1000
    started = perf_counter()
    content = "\n\n".join(parts)
    build_ms += (perf_counter() - started) * 1000
    if timings is not None:
        timings.update(get_text_ms=get_text_ms, markdown_build_ms=build_ms)
    return content
