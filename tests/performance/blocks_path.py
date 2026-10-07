"""At most five alternating, in-memory full-PDF runs per method, without HTTP.

Production remains unchanged. Quality uses captured results from these runs;
it does not perform extra full-document extractions outside the limit.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))
import pymupdf
from app.extractor import extract_pdf
from app.markdown import to_text_markdown


def blocks_markdown(document):
    parts = []
    for number, page in enumerate(document):
        blocks = page.get_text("blocks", sort=False)
        text = ''.join(block[4] for block in blocks if block[6] == 0)
        parts.append(f'## Página {number + 1}\n\n{text}')
    return '\n\n'.join(parts)


def percentile(values, quantile):
    """Linear interpolation, descriptive only for this small sample."""
    values = sorted(values)
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=5)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 5 or any(args.output.parent.glob(args.output.stem + '.*')):
        parser.error('Use 1..5 runs and a new output prefix to preserve evidence')
    body = args.pdf.read_bytes()
    with pymupdf.open(stream=body, filetype='pdf') as document:
        page_count = document.page_count
    original = pymupdf.Page.get_text
    records, outputs, reference_pages = [], {}, None
    for pair in range(args.repeat):
        order = ['text', 'blocks'] if pair % 2 == 0 else ['blocks', 'text']
        for method in order:
            captured = {}
            phases = {'native_get_text_ms': 0.0}

            def timed_get_text(page, *a, **kw):
                start = perf_counter()
                value = original(page, *a, **kw)
                phases['native_get_text_ms'] += (perf_counter() - start) * 1000
                captured[page.number] = value
                return value

            started = perf_counter()
            with patch.object(pymupdf.Page, 'get_text', timed_get_text):
                result = extract_pdf(body, converter=blocks_markdown if method == 'blocks' else
                                     lambda doc: to_text_markdown(doc, timings=phases),
                                     timings=phases)
            phases['total_ms'] = (perf_counter() - started) * 1000
            # All validation, joining captured blocks and hashing are outside timing.
            assert list(captured) == list(range(page_count)), 'Missing/reordered pages'
            pages = [captured[n] if method == 'text' else
                     ''.join(b[4] for b in captured[n] if b[6] == 0)
                     for n in range(page_count)]
            if reference_pages is None:
                assert method == 'text'
                reference_pages = pages
            expected = '\n\n'.join(f'## Página {n + 1}\n\n{t}' for n, t in enumerate(pages))
            assert result.content == expected, 'Markdown differs from captured per-page text'
            different = [n + 1 for n, (actual, reference) in
                         enumerate(zip(pages, reference_pages)) if actual != reference]
            phases.update(method=method, pair=pair, order_in_pair=order.index(method),
                          page_count=result.page_count, chars=len(result.content),
                          raw_text_chars=sum(len(t) for t in pages),
                          pages_with_text=sum(bool(t.strip()) for t in pages),
                          content_sha256=hashlib.sha256(result.content.encode()).hexdigest(),
                          pages_exact_to_text=not different, different_pages=different,
                          first=result.content[:160], last=result.content[-160:], error=None)
            if method == 'blocks':
                phases['ignored_nontext_blocks'] = sum(b[6] != 0 for bs in captured.values() for b in bs)
            import resource
            phases['process_max_rss_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            records.append(phases)
            if method not in outputs:
                outputs[method] = result.content
                args.output.with_suffix('.' + method + '.md').write_text(result.content, encoding='utf-8')
            assert result.page_count == page_count
            print(json.dumps(phases), flush=True)
    stats = {}
    for method in ['text', 'blocks']:
        rows = [r for r in records if r['method'] == method]
        times = [r['total_ms'] for r in rows]
        stats[method] = dict(n=len(rows), min_ms=min(times), median_ms=statistics.median(times),
                             descriptive_p95_ms=percentile(times, 0.95), max_ms=max(times),
                             median_native_get_text_ms=statistics.median(r['native_get_text_ms'] for r in rows))
    assert all(r['pages_with_text'] == 276 and r['page_count'] == 279 for r in records)
    reference_check = dict(all_pages_equal=all(r['pages_exact_to_text'] for r in records),
                           first_outputs_equal=outputs['text'] == outputs['blocks'],
                           paired_blocks_wins=sum(
                               next(r['total_ms'] for r in records if r['pair'] == n and r['method'] == 'blocks') <
                               next(r['total_ms'] for r in records if r['pair'] == n and r['method'] == 'text')
                               for n in range(args.repeat)))
    summary = dict(started_utc=datetime.now(timezone.utc).isoformat(),
                   python=sys.version, pymupdf=pymupdf.__version__,
                   pdf_bytes=len(body), input_sha256=hashlib.sha256(body).hexdigest(),
                   records=records, stats=stats, quality=reference_check)
    args.output.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(dict(stats=stats, quality=reference_check)), flush=True)


if __name__ == '__main__':
    main()
