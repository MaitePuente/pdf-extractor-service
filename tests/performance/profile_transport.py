"""Isolated Linux transport experiment. Does not modify the live API.

Same persistent spawned worker, one CPU, same conversion and response. The
only alternative is transfer through shared memory rather than input pickle.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
from multiprocessing.shared_memory import SharedMemory
from pathlib import Path
import resource
import sys
from time import perf_counter_ns

sys.path.insert(0, str(Path.cwd()))
from app.worker import convert_in_process


def convert_shared(name, size):
    memory = SharedMemory(name=name)
    try:
        # PyMuPDF requires bytes/bytearray, not a memoryview. This copy is real.
        body = bytes(memory.buf[:size])
    finally:
        memory.close()
    return convert_in_process(body)


def stats(values):
    values = sorted(values)
    def q(f):
        p = (len(values)-1)*f
        i = int(p)
        return values[i] + (values[min(i+1,len(values)-1)]-values[i])*(p-i)
    return dict(n=len(values), min=values[0], p50=q(.5), p90=q(.9), p95=q(.95), max=values[-1])


def main(args):
    body = args.pdf.read_bytes()
    records = {'pickle': [], 'shared': []}
    with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as pool:
        pool.submit(convert_in_process, body).result()  # startup not measured
        for _ in range(args.repeat):
            for method in records:
                began = perf_counter_ns()
                if method == 'pickle':
                    response = pool.submit(convert_in_process, body).result()
                else:
                    memory = SharedMemory(create=True, size=len(body))
                    try:
                        memory.buf[:] = body
                        response = pool.submit(convert_shared, memory.name, len(body)).result()
                    finally:
                        memory.close()
                        memory.unlink()
                total = (perf_counter_ns()-began)/1e6
                data, status, detail, timing = response
                assert status is None, detail
                assert data['page_count']==279 and len(data['content'])==427008
                assert hashlib.sha256(data['content'].encode()).hexdigest()=='c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc'
                records[method].append(dict(total_ms=total, algorithm_ms=timing['algorithm_ms'],
                                            overhead_ms=total-timing['algorithm_ms']))
    print(json.dumps(dict(samples=records, summary={m:{key:stats([r[key] for r in rows])
          for key in ['total_ms','algorithm_ms','overhead_ms']} for m,rows in records.items()},
          peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf',type=Path,required=True)
    parser.add_argument('--repeat',type=int,default=10)
    main(parser.parse_args())
