"""Minimal sequential client for Linux/Docker; no app imports or PDF copies on disk."""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import re
from time import perf_counter_ns
from urllib.parse import urlsplit


def stats(values):
    values = sorted(values)
    def q(f):
        p=(len(values)-1)*f
        i=int(p)
        return values[i]+(values[min(i+1,len(values)-1)]-values[i])*(p-i)
    return dict(n=len(values),min=values[0],p50=q(.5),p90=q(.9),p95=q(.95),max=values[-1])


def main(args):
    body=args.pdf.read_bytes()
    url=urlsplit(args.url)
    client=http.client.HTTPConnection(url.hostname,url.port,timeout=60)
    rows=[]
    warmup=[]
    try:
        for n in range(args.repeat+args.warmup):
            audit=f'{args.name}-{n:03d}'
            started=perf_counter_ns()
            client.request('POST','/extract',body,{'Content-Type':'application/pdf','Host':'localhost','X-Audit-Id':audit})
            sent=perf_counter_ns()
            response=client.getresponse()
            headers=perf_counter_ns()
            raw=response.read()
            done=perf_counter_ns()
            result=json.loads(raw)
            digest=hashlib.sha256(result['content'].encode()).hexdigest()
            assert response.status==200 and response.getheader('X-Cache')==args.cache
            assert result['page_count']==279 and len(result['content'])==427008
            assert digest=='c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc'
            assert re.findall(r'^## Página (\d+)$',result['content'],re.M)==list(map(str,range(1,280)))
            row=dict(audit_id=audit,total_ms=(done-started)/1e6,client_send_ms=(sent-started)/1e6,
                     wait_headers_ms=(headers-sent)/1e6,response_read_ms=(done-headers)/1e6,
                     status=response.status,cache=response.getheader('X-Cache'),page_count=279,
                     characters=427008,sha256=digest)
            (warmup if n<args.warmup else rows).append(row)
    finally:
        client.close()
    print(json.dumps(dict(url=args.url,client='Docker Python http.client; sequential keep-alive',
                         pdf_bytes=len(body),pdf_sha256=hashlib.sha256(body).hexdigest(),
                         warmup=warmup,measured=rows,
                         summary={k:stats([r[k] for r in rows]) for k in
                                  ['total_ms','client_send_ms','wait_headers_ms','response_read_ms']})),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf',type=Path,required=True)
    parser.add_argument('--url',required=True)
    parser.add_argument('--name',required=True)
    parser.add_argument('--cache',choices=['HIT','BYPASS','MISS'],required=True)
    parser.add_argument('--repeat',type=int,default=20)
    parser.add_argument('--warmup',type=int,default=4)
    main(parser.parse_args())
