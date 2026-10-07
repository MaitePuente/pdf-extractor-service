"""Offline profiling of the endpoint's extract_pdf; never rewrites the input PDF.

Example: uv run --locked python tests/performance/offline.py --pdf PATH
         --layout off --pages 20 --output RESULTS/name.json
The pages filter is injected only in this benchmark, on the original Document.
Imports, disk read, quality checks and output writes are outside algorithm timing.
Run each candidate in a fresh process: use_layout changes module-global state.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from time import perf_counter

sys.path.insert(0, str(Path.cwd()))
if len(Path(__file__).resolve().parents) > 2:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def thread_count():
    task = Path('/proc/self/task')
    return len(list(task.iterdir())) if task.exists() else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', required=True, type=Path)
    parser.add_argument('--layout', choices=['on', 'off', 'direct', 'current'], required=True)
    parser.add_argument('--pages', type=int, help='First N pages; omitted = all')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error('Repeat must be positive')
    if args.output.exists():
        parser.error('Refusing to overwrite an existing result')
    before_import = thread_count()
    import pymupdf
    after_pymupdf = thread_count()
    from app.extractor import extract_pdf
    if args.layout in ('on', 'off'):
        import pymupdf4llm
        pymupdf4llm.use_layout(args.layout == 'on')
        original_convert = pymupdf4llm.to_markdown
    else:
        from app.markdown import to_markdown
        original_convert = to_markdown
    after_llm = thread_count()
    body = args.pdf.read_bytes()
    with pymupdf.open(stream=body, filetype='pdf') as doc:
        page_count = doc.page_count
        selected = page_count if args.pages is None else args.pages
        if not 1 <= selected <= page_count:
            parser.error('Pages must be within the input document')
        reference_pages = [doc[p].get_text() for p in range(selected)]
    records = []
    for run in range(args.repeat):
        phases = {}

        def timed_convert(doc, **kw):
            if args.layout in ('on', 'off'):
                kw.update(use_ocr=False, write_images=False, embed_images=False)
            if args.pages is not None:
                kw['pages'] = list(range(selected))
            start = perf_counter()
            value = original_convert(doc, **kw)
            phases['convert_ms'] = (perf_counter() - start) * 1000
            return value

        try:
            start = perf_counter()
            result = extract_pdf(body, converter=timed_convert, timings=phases)
            phases['total_ms'] = (perf_counter() - start) * 1000
            content = result.content
            tokens = lambda text: Counter(re.findall(r'\w+', text.casefold()))
            reference_tokens = tokens('\n'.join(reference_pages))
            output_tokens = tokens(content)
            retained = sum((reference_tokens & output_tokens).values())
            phases.update(
                run=run, error=None, page_count=result.page_count,
                selected_pages=selected, chars=len(content),
                content_sha256=hashlib.sha256(content.encode()).hexdigest(),
                token_recall=retained / max(1, sum(reference_tokens.values())),
                reference_token_count=sum(reference_tokens.values()),
                heading_lines=sum(bool(re.match(r'^#{1,6} ', line)) for line in content.splitlines()),
                table_lines=sum(line.startswith('|') for line in content.splitlines()),
                threads=thread_count(),
            )
            args.output.with_suffix(f'.{run}.md').write_text(content, encoding='utf-8')
            args.output.with_suffix('.reference.txt').write_text('\n'.join(reference_pages), encoding='utf-8')
        except Exception as exc:
            phases.update(run=run, error=repr(exc))
        try:
            import resource
            phases['max_rss_mib'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        except ImportError:
            phases['max_rss_mib'] = None
        records.append(phases)
        print(json.dumps(phases), flush=True)
    result = dict(
        pdf_bytes=len(body), input_sha256=hashlib.sha256(body).hexdigest(),
        source_page_count=page_count, layout=args.layout, use_ocr=False,
        threads_before_import=before_import, threads_after_pymupdf=after_pymupdf,
        threads_after_engine_init=after_llm, records=records,
        cpu_max=Path('/sys/fs/cgroup/cpu.max').read_text().strip() if os.name == 'posix' else None,
    )
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    if any(r.get('error') for r in records):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
