"""Controlled offline profiling; external PDF, no writes to existing cache or evidence."""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import pickle
import resource
import sys
from time import perf_counter_ns, process_time_ns
import uuid

import pymupdf
from redis.asyncio import Redis
from starlette.responses import JSONResponse

sys.path.insert(0, str(Path.cwd()))
from app.extractor import extract_pdf


def stats(values):
    values = sorted(values)
    def q(f):
        p = (len(values) - 1) * f
        i = int(p)
        return values[i] + (values[min(i + 1, len(values) - 1)] - values[i]) * (p - i)
    return dict(n=len(values), min=values[0], p50=q(.5), p90=q(.9), p95=q(.95), max=values[-1])


def build(pages):
    return '\n\n'.join(f'## Página {n + 1}\n\n' + ''.join(b[4] for b in blocks if b[6] == 0)
                       for n, blocks in enumerate(pages))


def candidate(body, method):
    if method == 'control':
        return extract_pdf(body).content
    if method == 'low_memory':
        previous = pymupdf.TOOLS.set_low_memory()
        pymupdf.TOOLS.set_low_memory(True)
        try:
            return extract_pdf(body).content
        finally:
            pymupdf.TOOLS.set_low_memory(previous)
    with pymupdf.open(stream=body, filetype='pdf') as document:
        if method == 'text':
            return '\n\n'.join(f'## Página {n + 1}\n\n{page.get_text("text")}' for n, page in enumerate(document))
        flags = pymupdf.TEXTFLAGS_BLOCKS & ~pymupdf.TEXT_PRESERVE_IMAGES
        if method == 'displaylist':
            return build([pymupdf.TextPage(page.get_displaylist(annots=1).get_textpage(flags=flags)).extractBLOCKS() for page in document])
        if method == 'textpage':
            return build([page.get_textpage(flags=flags).extractBLOCKS() for page in document])
        return build([page.get_text('blocks', sort=False, flags=flags) for page in document])


async def main(args):
    body = args.pdf.read_bytes()
    expected = 'c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc'
    with pymupdf.open(stream=body, filetype='pdf') as document:
        pages = document.page_count
        assert pages == 279
    records = {}
    reference = extract_pdf(body)
    assert len(reference.content) == 427008 and hashlib.sha256(reference.content.encode()).hexdigest() == expected
    if args.only_extraction:
        samples, cpu = [], []
        for _ in range(args.repeat):
            started, cpu_start = perf_counter_ns(), process_time_ns()
            result = extract_pdf(body)
            cpu.append((process_time_ns()-cpu_start)/1e6)
            samples.append((perf_counter_ns()-started)/1e6)
            assert result.page_count == 279 and len(result.content) == 427008
            assert result.content == reference.content
            assert hashlib.sha256(result.content.encode()).hexdigest() == expected
        print(json.dumps(dict(samples_ms=samples, summary=stats(samples), cpu_samples_ms=cpu,
                              cpu_summary=stats(cpu), verified=args.repeat, page_count=pages,
                              characters=427008, content_sha256=expected,
                              python=sys.version, pymupdf=pymupdf.VersionBind,
                              cpu_max=Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
                              memory_max=Path('/sys/fs/cgroup/memory.max').read_text().strip(),
                              peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)), flush=True)
        return
    if args.only_candidates:
        names = ['control', 'displaylist', 'low_memory']
        for name in names:
            records[name] = {'samples_ms': [], 'matches': []}
        # Rotate start position to reduce systematic order/thermal bias.
        for run in range(args.repeat):
            order = names[run % len(names):] + names[:run % len(names)]
            for name in order:
                started = perf_counter_ns()
                result = candidate(body, name)
                records[name]['samples_ms'].append((perf_counter_ns()-started)/1e6)
                records[name]['matches'].append(result == reference.content)
        for name, record in records.items():
            record.update(stats(record['samples_ms']))
        print(json.dumps(dict(records=records, page_count=pages, content_sha256=expected,
                              characters=len(reference.content), flags=pymupdf.TEXTFLAGS_BLOCKS)),flush=True)
        return
    blocks = None
    def measured(name, operation):
        samples = []
        for _ in range(args.repeat):
            started = perf_counter_ns()
            result = operation()
            samples.append((perf_counter_ns() - started) / 1e6)
        records[name] = dict(samples_ms=samples, **stats(samples))
        return result
    def read_blocks():
        with pymupdf.open(stream=body, filetype='pdf') as doc:
            return [page.get_text('blocks', sort=False) for page in doc]
    blocks = measured('A_open_traverse_get_text', read_blocks)
    content = measured('B_markdown_only', lambda: build(blocks))
    assert content == reference.content
    measured('C_sha256_pdf', lambda: hashlib.sha256(body).hexdigest())
    measured('D_pydantic_json', reference.model_dump_json)
    measured('D_starlette_json_response', lambda: JSONResponse(reference.model_dump()).body)
    measured('IPC_pickle_dump_pdf', lambda: pickle.dumps(body, protocol=pickle.HIGHEST_PROTOCOL))
    encoded = pickle.dumps(body, protocol=pickle.HIGHEST_PROTOCOL)
    measured('IPC_pickle_load_pdf', lambda: pickle.loads(encoded))
    measured('G_current_extract_pdf', lambda: extract_pdf(body))
    if args.candidates:
        for method in ['no_images', 'textpage', 'text', 'displaylist']:
            result = measured('candidate_' + method, lambda: candidate(body, method))
            records['candidate_' + method]['same_content'] = result == reference.content
            records['candidate_' + method]['sha256'] = hashlib.sha256(result.encode()).hexdigest()
    if args.redis_url:
        client = Redis.from_url(args.redis_url, socket_timeout=.2, socket_connect_timeout=.2)
        key = 'benchmark:optimization:' + uuid.uuid4().hex
        await client.ping()
        payload = reference.model_dump_json()
        try:
            for name, operation in [('E_redis_GET_MISS', lambda: client.get(key + ':absent')),
                                    ('F_redis_SET', lambda: client.set(key, payload, ex=60))]:
                samples = []
                for _ in range(args.repeat):
                    started = perf_counter_ns()
                    value = await operation()
                    samples.append((perf_counter_ns() - started) / 1e6)
                    assert value is None if name.startswith('E_') else value
                records[name] = dict(samples_ms=samples, **stats(samples))
        finally:
            await client.delete(key)
            await client.aclose()
    report = dict(pdf=str(args.pdf), bytes=len(body), pdf_sha256=hashlib.sha256(body).hexdigest(),
                  page_count=pages, characters=len(reference.content), content_sha256=expected,
                  json_response_bytes=len(JSONResponse(reference.model_dump()).body),
                  pymupdf=pymupdf.VersionBind, python=sys.version,
                  cpu_max=Path('/sys/fs/cgroup/cpu.max').read_text().strip(),
                  memory_max=Path('/sys/fs/cgroup/memory.max').read_text().strip(),
                  peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                  records=records)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--repeat', type=int, default=10)
    parser.add_argument('--redis-url')
    parser.add_argument('--candidates', action='store_true')
    parser.add_argument('--only-candidates', action='store_true')
    parser.add_argument('--only-extraction', action='store_true')
    args = parser.parse_args()
    assert args.repeat >= 10
    asyncio.run(main(args))
