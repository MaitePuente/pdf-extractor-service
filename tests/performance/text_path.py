"""Compare current spans Markdown with raw page text, without HTTP or Redis.

One process per candidate; at most three full conversions. No Layout imports.
Uses the API's extract_pdf and substitutes only its converter during comparison.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))
if len(Path(__file__).resolve().parents) > 2:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pymupdf
from app.extractor import extract_pdf
from app.markdown import to_spans_markdown


def text_only(document):
    return '\n\n'.join(
        f'## Página {number + 1}\n\n{page.get_text("text")}'
        for number, page in enumerate(document)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--candidate', choices=['spans', 'text'], required=True)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 3 or args.output.exists() or any(
        args.output.with_suffix(f'.{n}.md').exists() for n in range(args.repeat)
    ):
        parser.error('Use 1..3 repetitions and a new output name')
    body = args.pdf.read_bytes()
    original_get_text = pymupdf.Page.get_text
    converter = to_spans_markdown if args.candidate == 'spans' else text_only
    records = []
    for run in range(args.repeat):
        phases = {'get_text_ms': 0.0}

        def timed_get_text(page, *a, **kw):
            start = perf_counter()
            try:
                return original_get_text(page, *a, **kw)
            finally:
                phases['get_text_ms'] += (perf_counter() - start) * 1000

        start = perf_counter()
        with patch.object(pymupdf.Page, 'get_text', timed_get_text):
            result = extract_pdf(body, converter=converter, timings=phases)
        phases['total_ms'] = (perf_counter() - start) * 1000
        phases['markdown_build_ms'] = phases['convert_ms'] - phases['get_text_ms']
        phases.update(run=run, page_count=result.page_count, chars=len(result.content),
                      sha256=hashlib.sha256(result.content.encode()).hexdigest(), error=None)
        # Quality/reference work is outside the measured conversion.
        with pymupdf.open(stream=body, filetype='pdf') as document:
            page_text = [page.get_text('text') for page in document]
        phases['pages_with_text'] = sum(bool(t.strip()) for t in page_text)
        if args.candidate == 'text':
            expected = '\n\n'.join(f'## Página {n + 1}\n\n{t}' for n, t in enumerate(page_text))
            phases['all_pages_and_text_exact'] = result.content == expected
            assert phases['all_pages_and_text_exact']
        phases['begin'] = result.content[:160]
        phases['end'] = result.content[-160:]
        try:
            import resource
            phases['max_rss_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except ImportError:
            phases['max_rss_mib'] = None
        records.append(phases)
        args.output.with_suffix(f'.{run}.md').write_text(result.content, encoding='utf-8')
        print(json.dumps(phases), flush=True)
    summary = dict(candidate=args.candidate, pdf_bytes=len(body),
                   input_sha256=hashlib.sha256(body).hexdigest(), records=records,
                   medians={k: statistics.median(r[k] for r in records)
                            for k in ['open_ms', 'get_text_ms', 'markdown_build_ms', 'total_ms']})
    args.output.write_text(json.dumps(summary, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
