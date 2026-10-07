# Baseline del microservicio extractor con k6

**Registro histórico:** las secciones del baseline se conservan debajo sin
reemplazar sus resultados. La sección final **CONFIGURACIÓN RECOMENDADA PARA
ENTREGA** contiene la validación vigente con dos réplicas. Las fases anteriores,
incluida HOT CACHE desde Docker con cinco réplicas, conservan sus recomendaciones
y cifras como historia; no representan la configuración elegida para entregar.

**Uso como repositorio independiente:** `pdf-extractor-service/` ya es la raíz
del microservicio. Todos los comandos reproducibles de este documento se
ejecutan desde esa raíz, sin entrar en otra subcarpeta. El historial describe
experimentos del repositorio original `pdf-extactext`, anteriores a la migración;
no se presentan como mediciones nuevas del repositorio standalone.
Las rutas de evidencia describen los artefactos históricos y no presuponen que
se hayan incluido en esta copia. Sus menciones a archivos ignorados por Git
corresponden a la configuración original. Las nuevas corridas generan resultados
en carpetas locales de `tests/stress/results/`. El runner principal conserva el directorio
por defecto de la estructura anterior: los ejemplos pasan explícitamente
`--results` para que ninguna ejecución dependa de esa ubicación antigua.

Medición local del 6 al 7 de octubre de 2026 (Argentina). Alcance histórico:
`microservices/extractor/` en el monorepo original, PDF → Markdown, HTTP a través
de Traefik. No se
modificaron el algoritmo, el monolito, sus benchmarks ni la configuración
funcional del balanceador. No se ejecutó Vegeta ni se aumentaron recursos.

## Entorno y documento

- Windows 11 Home Single Language, versión 10.0.26300.
- AMD Ryzen 5 4600H, 6 núcleos / 12 hilos; 7.36 GiB de RAM física visible.
- Docker Desktop: 12 CPU visibles, 3,767,750,656 bytes de memoria (3.509 GiB).
- Docker Engine 29.7.2; Compose 5.5.1; k6 2.2.0, Windows amd64.
- Cinco extractores, cada uno limitado a 1 CPU y 768 MiB; Redis compartido
  (0.5 CPU, 256 MiB, maxmemory 192 MiB) y Traefik v3.6 (0.5 CPU, 128 MiB).
- Red externa `pdf-network`; puerto de Traefik observado: `127.0.0.1:59345`.
  El runner consulta el puerto de Compose en cada ejecución.
- Otros servicios del equipo permanecieron funcionando: dos réplicas del
  monolito, su Traefik y MongoDB. No es un host dedicado al benchmark.
- Documento obligatorio externo, sin copiarlo ni modificarlo:
  `D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf`.
- Tamaño verificado: **17,749,468 bytes**; PyMuPDF confirmó **279 páginas**,
  sin contraseña. SHA-256 del archivo:
  `728c8a522ce24bf0ba3851cd109cdc0e55b200e3cd9b55b8343b39c005713162`.
- Python local 3.12.2; **Python del contenedor 3.12.15**. Dependencias del
  contenedor verificadas con `importlib.metadata`: FastAPI 0.142.2,
  Pydantic 2.13.5, PyMuPDF/PyMuPDF4LLM/pymupdf-layout 1.28.2,
  ONNX Runtime 1.30.0, Uvicorn 0.54.0 y redis-py 8.1.0. OCR desactivado.

## Qué mide k6

El PDF completo se envía en cada POST como `application/pdf`, también en HIT.
Se conservan y verifican HTTP 200, `page_count=279`, contenido Markdown y el
header `X-Cache`. Después de obtener el primer Markdown se puede fijar su
SHA-256 para comprobar identidad en las siguientes peticiones.

`http_req_duration` mide envío + espera + recepción desde Windows. No incluye
el establecimiento de conexión. `sending`, `waiting`, `receiving` y `blocked`
se registran por petición. La espera incluye recepción del cuerpo en la app,
checksum, conversión o Redis y serialización: **no es una medición aislada del
algoritmo ni del GET de Redis**. No hay instrumentación interna de esas fases;
no se atribuyen tiempos internos que no se midieron. Definiciones:
[métricas oficiales de k6](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/).

El runner conserva log, resumen JSON y muestras de `docker stats` cada
aproximadamente 3 segundos, incluyendo los otros contenedores. Comprueba salud,
OOM y estado de los contenedores del proyecto. Los máximos de memoria son
máximos **muestreados**, no picos continuos garantizados. La comparación
`p(95)<400` está en los scripts nuevos; un exit 99 por latencia no significa
que hubo un error HTTP.

## Procedimiento reproducible (PowerShell)

Desde la raíz del repositorio:

```powershell
# Terminal ubicada en la raíz de pdf-extractor-service.
New-Item -ItemType Directory -Force tests/stress/results/extractor-baseline | Out-Null
$results = (Resolve-Path tests/stress/results/extractor-baseline).Path
$pdf = 'D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf'
Get-Item -LiteralPath $pdf | Select-Object FullName,Length
Get-FileHash -LiteralPath $pdf -Algorithm SHA256
$env:PDF_METADATA_PATH = $pdf
uv run --locked python -c "import os,pymupdf; d=pymupdf.open(os.environ['PDF_METADATA_PATH']); print(d.page_count, d.needs_pass); d.close()"
Remove-Item Env:PDF_METADATA_PATH
docker info --format 'CPUs={{.NCPU}} Memory={{.MemTotal}}'
docker stats --no-stream
```

Desactivar caché temporalmente, manteniendo Redis y las cinco réplicas:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.performance.yaml up -d --scale extractor=5 --wait --wait-timeout 150
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name bypass-validation-new --cache BYPASS --results $results
```

Usar nombres de corrida nuevos: el runner no sobreescribe evidencia previa.
Si la validación responde 200/279/BYPASS y el entorno se mantiene saludable,
continuar en orden, vigilando recursos entre cada etapa:

```powershell
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name bypass-sequential-new --cache BYPASS --iterations 5 --results $results
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name bypass-2vu-new --cache BYPASS --vus 2 --iterations 3 --results $results
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name bypass-5vu-new --cache BYPASS --vus 5 --iterations 2 --results $results
```

No continuar esa secuencia si hay saturación, pérdida de salud, OOM o errores.
La opción `--diagnostic` permite solamente **una** petición con **un** VU:
deja finalizar una validación aunque fallen los health checks y conserva esa
advertencia, pero mantiene la protección ante OOM/contenedor detenido. No es
una autorización para ejecutar carga sobre un entorno inestable. El timeout
predeterminado del runner es 1800 s para BYPASS/MISS y **5 s para HIT**;
se puede explicitar con `--timeout`. Esta última condición se agregó tras
observar reconversiones por timeout de Redis: una validación incorrecta aborta
k6 y conserva el resumen, sin enviar más iteraciones. No cambia el timeout
de Redis, que sigue siendo 200 ms, ni el código de la API.
Cancelar k6 no garantiza cancelar la conversión síncrona en el servidor;
esperar a que las réplicas recuperen salud antes del próximo trabajo.

La validación completa usada en esta auditoría, después de detener el trabajo
de la petición inicial abortada y recuperar salud, fue:

```powershell
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name bypass-diagnostic-new --cache BYPASS --diagnostic --timeout 1800s --results $results
```

Restaurar la configuración normal omitiendo el override (también si una corrida
falla). No ejecutar `down`, `FLUSHDB` ni `FLUSHALL`:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=5 --wait --wait-timeout 150
$address = docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80
$baseUrl = 'http://localhost:' + ($address -split ':')[-1]
curl.exe --fail "$baseUrl/health"
# Precarga, si la clave aún no existe. Excluirla de las estadísticas HIT.
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name preload-new --cache MISS --diagnostic --results $results
# Copiar el content_sha256 real de la precarga en esta variable:
$sha = '77b1126026f79bd08559bddfbf2ae1ca082239f003d4a6bd5d90939d3551065f'
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name hit-1vu-new --cache HIT --iterations 10 --sha256 $sha --results $results
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name hit-2vu-new --cache HIT --vus 2 --iterations 5 --sha256 $sha --results $results
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name hit-5vu-new --cache HIT --vus 5 --iterations 2 --sha256 $sha --results $results
```

Si la precarga ya devuelve HIT, no borrar Redis para forzar MISS: comprobar la
clave/header y documentar esa condición. Los scripts requieren el header
esperado y marcan la discrepancia como error lógico. El checksum del Markdown
no es el checksum del texto plano del monolito.

Suite funcional e integración real (esta última con caché habilitada):

```powershell
uv run --locked pytest -v
$env:EXTRACTOR_BASE_URL = $baseUrl
uv run --locked pytest --run-integration -m integration -v -s
Remove-Item Env:EXTRACTOR_BASE_URL
```

## Spike oficial preparado

`tests/performance/spike.js`: 0 → 100 VUs en 10 s, 100 durante 20 s,
100 → 0 en 10 s. La bajada no prolonga artificialmente el perfil: las
iteraciones pendientes pueden interrumpirse. No se ejecuta automáticamente.
Validado con `k6 inspect` pasando las variables mediante `-e`.

Solo en un entorno cuya estabilidad y recursos se hayan comprobado:

```powershell
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name official-spike-new --cache BYPASS --spike --results $results
```

Para conservar la comparación con el set oficial existente, `common.js`
también admite `PDF_PATHS` (rutas separadas por `|`) y `PDF_PAGES` (cantidades
separadas por comas). Rota los documentos por iteración de cada VU. Ejemplo,
desde la raíz del repositorio, sin modificar los scripts originales. El set
oficial es una entrada externa: configurar una carpeta que contenga esos PDFs;
no se presupone su ubicación en el monorepo:

```powershell
$officialPdfDirectory = 'D:\ruta\al\set-oficial'
$env:PDF_PATHS = (Resolve-Path (Join-Path $officialPdfDirectory 'documento_90_paginas.pdf')).Path + '|' + (Resolve-Path (Join-Path $officialPdfDirectory 'documento_279_paginas.pdf')).Path
$env:PDF_PAGES = '90,279'
# Usar solo cuando se autorice la comparación definitiva y haya recursos.
# No fijar un único --sha256 para PDFs diferentes.
Remove-Item Env:PDF_PATHS,Env:PDF_PAGES
```

## Evidencia y resultados

Los artefactos locales se conservan en
`tests/stress/results/extractor-baseline/` (ignorados por Git conforme a la
configuración existente): logs k6, resúmenes JSON y muestras de recursos.

La validación inicial `bypass-first` se abortó a los 39.99 s cuando
`extractor-4` pasó a unhealthy por tres timeouts consecutivos de `/health`.
No hubo respuesta completa ni resumen estadístico: **no se calcula un p95
con esa petición interrumpida**. Traefik registró 499 y 39,162.936 ms: fue la
cancelación del cliente por el monitor, no un HTTP 500 de la aplicación.
El trabajo síncrono siguió consumiendo CPU después de la cancelación.

Después de más de cinco minutos todavía ocupado, se reinició únicamente
`extractor-4` para cancelar ese trabajo abandonado; no se reinició Redis ni
infraestructura ajena. La posterior validación diagnóstica es otra petición
individual, con timeout de 1800 s y sin escalar concurrencia.

Una muestra del trabajo cancelado confirmó 47 hilos en `/proc/1/status`, cuota
`cpu.max = 100000 100000` y `nr_throttled=3413` sobre `nr_periods=3779`
(90.3 % de períodos con throttling). `throttled_usec` no representa por sí
solo el tiempo HTTP: agrega esperas de ejecución. El código instalado de
PyMuPDF4LLM activa Layout por defecto, aunque `use_ocr=False`. Por tanto,
desactivar OCR no elimina la inferencia de layout. Esto apunta a conversión
CPU limitada; no demuestra todavía cuánto del costo corresponde a ONNX.
Como próxima investigación recomiendo perfilar Layout/ONNX y evaluar la
cantidad de hilos frente a la cuota de 1 CPU, preservando y comparando el
Markdown. ONNX permite ajustar hilos y spinning:
[documentación oficial](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).
También debe resolverse el bloqueo del event loop y el trabajo que continúa
tras cancelar el cliente. No se aplicó ninguna de esas optimizaciones.

Las etapas de carga sin caché con varias iteraciones y 2/5 VUs, y el spike
de 100 VUs, quedan bloqueadas por esa pérdida de salud. Además, cinco límites
de 768 MiB suman 3.75 GiB, más que toda la RAM de Docker antes de contar Redis,
Traefik y otros servicios. Windows mostró solo 787 MiB de RAM física libre;
100 copias de este PDF requieren aproximadamente 1.65 GiB del lado cliente.
La [documentación de open()](https://grafana.com/docs/k6/latest/javascript-api/init-context/open/)
advierte sobre copias por VU. No se afirma que haya ocurrido OOM.

Los 28 tests funcionales pasaron, con 1 integración omitida por defecto
(`uv run --locked pytest -v`, 9.56 s). La integración real pasó por separado
(`--run-integration -m integration -v -s`, 1 passed, 21.10 s).

### Extracción sin caché: validación completa

`bypass-diagnostic` terminó con **HTTP 200 / BYPASS / 279 páginas**, sin
errores HTTP ni lógicos. Markdown: **435,769 caracteres** (conteo de k6),
SHA-256 `77b1126026f79bd08559bddfbf2ae1ca082239f003d4a6bd5d90939d3551065f`.
No es el texto plano del monolito: su longitud y checksum son diferentes.

| Corrida | n | p50 ms | p90 ms | p95 ms | máximo ms | errores | req/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| BYPASS diagnóstico, 1 VU | 1 | 1,176,522.714 | 1,176,522.714 | 1,176,522.714 | 1,176,522.714 | 0 % | 0.000850 |

Mínimo y media también fueron 1,176,522.714 ms. Con **n=1**, los percentiles
son formalmente iguales a esa única muestra; **no estiman una distribución**.
Equivale a **19 min 36.5 s HTTP**, no al arranque del contenedor. La solicitud
fue la primera conversión grande de `extractor-2` después de arrancar; no hay
muestra comparable con inferencia ya caliente ni distribución BYPASS de
varias ejecuciones por la pérdida de salud observada.

Desglose observado por k6: envío **773.590 ms**, espera **1,175,688.181 ms**,
recepción **60.942 ms**, bloqueo/conexión **43.182 ms** (este último no integra
`http_req_duration`). Se confirma el incumplimiento de 400 ms en esta ejecución;
no se conoce el tiempo interno puro de conversión.

343 muestras de recursos durante esta corrida: máximo de `extractor-2`
**644.9 MiB**, CPU máxima muestreada **115.94 %** (aproximadamente un núcleo
ocupado; muestras breves pueden superar 100 % sin cambiar la cuota). Perdió
salud durante el procesamiento. Ningún contenedor del proyecto registró OOM
ni reinicios automáticos. Los otros servicios no estaban aislados: MongoDB
tuvo un pico muestreado de 139.15 % de CPU, otra fuente de variabilidad.

Después se restauró `CACHE_ENABLED=true` mediante Compose: cinco extractores
sanos, Redis y Traefik conservados. Integración real a través de Traefik:
**1 passed, 28 deselected, 21.10 s**, validando MISS, HIT, contenido y TTL de
una clave exclusiva del test. Solo se eliminó esa clave de prueba, como ya
establece la integración existente.

### Precarga y respuesta desde caché

`preload`: **200 / MISS / 279 páginas**, 435,769 caracteres y el mismo SHA-256
de Markdown que BYPASS. Tiempo HTTP **1,184,904.948 ms** (19 min 44.9 s):
envío 336.757 ms, espera 1,184,479.147 ms y recepción 89.044 ms. Es otra
conversión completa; **no es una medición HIT**. Con n=1 sus percentiles son
iguales a esa muestra; throughput k6 0.000844 req/s, sin errores HTTP/lógicos.
Memoria máxima muestreada de la réplica: **645.0 MiB**, CPU máxima 110.12 %.
También perdió salud durante la conversión; no hubo OOM.

Se comprobó la clave real en Redis, TTL positivo y valor JSON de **448,021
bytes**. Aun con la clave existente, `hit-validation` registró
`CACHE ERROR operation=get reason=TimeoutError` en extractor-2 y cayó en
reconversión. Se abortó por unhealthy a los 50.47 s. Una repetición individual
respondió 200/HIT en 867.093 ms. Después `hit-sequential` logró dos HIT y la
tercera petición volvió a fallar en GET, esta vez en extractor-4; se abortó
a los 47.27 s. Estas corridas canceladas externamente no generaron resumen
k6: no se atribuyen percentiles completos ni req/s inexistentes.

La última corrida `hit-bounded` mantuvo **1 VU**, 10 iteraciones previstas,
timeout HTTP explícito de **5 s** y aborto al primer fallo de validación:

| Condición | solicitudes medidas | p50 ms | p90 ms | p95 ms | máximo ms | errores HTTP/lógicos | req/s k6 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Caché habilitada, expectativa HIT; 2 HIT + 1 timeout | 3 | 439.526 | 4,089.937 | 4,546.238 | 5,002.540 | 33.33 % | 0.511 |

Mínimo 353.004 ms, media 1,931.690 ms. Finalizó con exit **108** por aborto
explícito, conservando resumen JSON: dos iteraciones completas y una
interrumpida después de medir el timeout. Las siete iteraciones restantes
**no se ejecutaron**. El tercer POST tuvo status k6 0 / `request timeout`:
no respondió HIT, ni 200, ni Markdown. Su timeout es un tiempo observado por
el cliente, **no el tiempo que tardaría en terminar la reconversión**.

Todos los HIT exitosos registrados, cada uno con HTTP 200, 279 páginas,
435,769 caracteres y el mismo SHA-256:

| X-Audit-Id | réplica | HTTP ms | envío ms | espera ms | recepción ms |
|---|---|---:|---:|---:|---:|
| hit-validation-retry-1-0 | extractor-3 | 867.093 | 189.628 | 672.341 | 5.123 |
| hit-sequential-1-0 | extractor-5 | 2,004.791 | 256.497 | 1,735.906 | 12.389 |
| hit-sequential-1-1 | extractor-1 | 744.759 | 209.228 | 519.027 | 16.504 |
| hit-bounded-1-0 | extractor-4 | 353.004 | 275.596 | 71.155 | 6.252 |
| hit-bounded-1-1 | extractor-1 | 439.526 | 253.376 | 181.012 | 5.138 |

Descriptivamente, **solo entre esos cinco HIT exitosos**, mínimo 353.004 ms,
mediana **744.759 ms**, p90 **1,549.712 ms**, p95 **1,777.252 ms** y máximo
2,004.791 ms. Es una muestra pequeña, agrupada de tres corridas, **seleccionada
por éxito**: excluye tres timeouts de GET que dispararon reconversión y no
sirve como p95 global del servicio. Los dos HIT de la corrida final solos
tienen mediana 396.265 ms y p95 435.200 ms; excluir el tercer timeout tampoco
los convierte en una prueba aprobada.

### Recursos, rutas y limitaciones

- Con extracción real, CPU de la réplica sostenidamente próxima a un núcleo
  completo y máximos de memoria cercanos a 645 MiB. La suma máxima muestreada
  de working sets de todos los contenedores fue 2,344.218 MiB durante BYPASS
  y 2,373.345 MiB durante precarga. Esa suma no incluye toda la memoria del
  kernel/caché de Docker y no equivale a RAM física libre de Windows.
- En la corrida HIT final, dos muestras de recursos (demasiado pocas para
  garantizar picos): extractor-2 llegó a 100.02 % de CPU porque el GET falló
  y empezó a convertir. No fue consumo de una lectura HIT. Extractor-3
  conservaba aproximadamente 516.8 MiB después de la precarga; por sí solo
  ese valor no demuestra una fuga. No se verificó una fuga con carga larga.
- Los tres fallos GET de esta fase fueron en extractor-2 (dos) y extractor-4
  (uno). Los logs de aplicación y Traefik se conservaron. Cada POST auditado
  tenía 17,749,468 bytes y llegó al router `pdf-markdown-extractor@docker`,
  a través de `localhost:59345`. No se midió una réplica directa.
- Los HIT correctos llegaron a **cuatro réplicas distintas**, con Redis
  compartido. Los IP se mapearon contra el snapshot de contenedores de esa
  fase; no se reutiliza ese mapa para BYPASS porque recrear contenedores
  puede reasignar IP. La réplica BYPASS se identificó como extractor-2 en
  sus muestras de recursos y estado de salud.
- Traefik registró **499** en las peticiones canceladas por el monitor o el
  timeout de k6. No son respuestas HTTP 500 de la API. Los tiempos de
  Traefik y k6 tienen distintos límites y relojes; no se restan para inventar
  tiempos internos de recepción o extracción. `Overhead` del access log
  tampoco aísla todo el costo de transportar el PDF por el proxy.
- Los tests de integración se ejecutaron antes de la precarga: usaron Redis
  desde extractor-1 y extractor-5; la precarga usó extractor-3. Los primeros
  GET grandes fallidos ocurrieron en réplicas que aún no habían usado Redis
  después de arrancar. Después de reiniciar extractor-4, un GET grande sí
  produjo HIT. Esto sugiere variabilidad de conexión/planificación y un
  presupuesto de 200 ms demasiado ajustado; **no prueba una causa única**.
- No se ejecutaron **2 VUs, 5 VUs ni el spike de 100 VUs**, tampoco en HIT,
  porque las pruebas de 1 VU ya mostraron fallos y pérdida de salud.
- Los procesos que siguieron convirtiendo después de cancelar k6 se
  detuvieron reiniciando exclusivamente sus réplicas. Los reinicios finales
  fueron manuales: dos en extractor-2 y uno en extractor-4; no fueron OOM ni
  reinicios automáticos. Al finalizar quedaron cinco réplicas saludables,
  `CACHE_ENABLED=true` y `/health` 200. No se borró Redis.

Si una prueba aborta y deja conversión en curso, identificar la réplica con
los access logs/X-Audit-Id y reiniciar únicamente esa instancia del extractor;
después esperar salud antes de otro benchmark. Ejemplo usado en esta fase:

```powershell
docker restart pdf-extractor-extractor-2
docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=5 --wait --wait-timeout 150
```

Evidencia adicional local: `requests.csv` (cada respuesta medida),
`analysis.json`, `traefik-audit.jsonl`, `extractor-cache.log`,
`final-containers.json`, versiones de Docker y resúmenes/recursos por corrida,
todos dentro de `tests/stress/results/extractor-baseline/`.

## Conclusión y siguiente cambio recomendado

**No se alcanza p95 < 400 ms**, ni se demuestra estabilidad del servicio.
BYPASS tardó 19 min 36.5 s en la única muestra completa; MISS volvió a
convertir en 19 min 44.9 s. No se obtuvo una distribución BYPASS repetida,
porque la réplica perdió salud. Redis evitó la conversión en cinco respuestas,
pero sus tiempos HTTP variaron entre 353 y 2,005 ms y otras tres lecturas
dispararon reconversión por timeout. El p95 de la corrida final con caché
habilitada fue 4,546.238 ms, con 33.33 % de errores.

El cuello de botella principal sin caché parece ser la **conversión
Layout/ONNX bajo cuota de 1 CPU**; 47 hilos y throttling respaldan esa
hipótesis, sin demostrar todavía qué operadores consumen ese tiempo. Con
caché, el deadline GET y la variabilidad de recepción/transporte del PDF
completo requieren instrumentación interna para separarlos. Los 17.75 MB
se siguen transmitiendo en cada HIT.

Como próximo cambio de rendimiento recomiendo **perfilar la inferencia y
evaluar su cantidad de hilos/spinning frente a 1 CPU**, manteniendo identidad
de Markdown y recursos. Antes de escalar carga deben corregirse también el
bloqueo de salud/cancelación y la fiabilidad del GET bajo el timeout actual.
No se aplicó ninguna optimización, ni se aumentaron recursos. Estas
mediciones no autorizan prometer que esos cambios lograrán 400 ms.

---

## Fase de perfilado y optimización — 7 de octubre de 2026

### Alcance, controles y reproducción

Se preservó el baseline completo en `tests/stress/results/extractor-baseline/`.
La evidencia nueva está en `tests/stress/results/extractor-profiling/`, ignorada
por Git: JSON de algoritmo, Markdown obtenido, referencias secuenciales, auditoría
por página, logs k6, summaries, recursos, perfiles de servidor y access logs.
No se modificaron monolito, Traefik, Compose funcional, dependencias ni lockfile.
No se hicieron commits/push, no se ejecutaron Vegeta ni el spike de 100 VUs.

Archivos creados en esa fase en el antiguo directorio `microservices/extractor/`
del monorepo original (referencia histórica):
`app/markdown.py`, `app/worker.py`, `app/profiling.py`,
`tests/performance/offline.py`, `tests/performance/check_content.py`,
`tests/test_markdown_content.py`, `tests/test_responsiveness.py`.
Archivos existentes modificados: `app/extractor.py`, `app/main.py`, `app/cache.py`,
`tests/test_cache.py`, `tests/integration/test_redis_compose.py`,
`tests/performance/run_k6.py`, `README.md` y este `docs/performance.md` de la raíz.
El runner k6 solo agrega directorio de evidencia y sondeo de salud opcionales;
los scripts JS y thresholds permanecen idénticos. Hashes al inicio y al final
confirman que los archivos ajenos a esta lista conservaron sus cambios locales.

El PDF externo sigue midiendo **17,749,468 bytes**, con **279 páginas** y el mismo
SHA-256 de archivo `728c8a522ce24bf0ba3851cd109cdc0e55b200e3cd9b55b8343b39c005713162`.
El entorno y versiones son los del baseline: Python del contenedor 3.12.15,
PyMuPDF/PyMuPDF4LLM/Layout 1.28.2, Docker 29.7.2, Compose 5.5.1, k6 2.2.0.
La imagen nueva es `sha256:e8d59e904d0bf40fa8db8942a8ca5d2bcf7bd1e12c06035a26c2fd61f9c46447`.

`tests/performance/offline.py` usa la misma función `extract_pdf` del endpoint.
Mide con `perf_counter` apertura, conversión y total. La selección `pages=range(N)`
se aplica al documento original abierto en memoria; no se generan PDFs recortados.
`page_count` describe el documento fuente (279); `selected_pages` identifica la
muestra. Lectura del archivo, importaciones, checks de calidad y escritura de los
resultados quedan fuera del tiempo del algoritmo. Cada candidato arranca en un
proceso nuevo; repeticiones dentro de ese proceso distinguen primera de posteriores.

Las muestras se ejecutaron offline dentro de un contenedor efímero del mismo
entorno: **1 CPU, 768 MiB, read-only, network=none**, PDF montado como solo lectura.
Ninguna medición del algoritmo incluye HTTP, Redis o Docker networking. El host
conservó sus otros contenedores y no estuvo dedicado exclusivamente al benchmark.
Durante la primera serie OFF de 20 páginas corrieron también tests en Windows;
se repitió esa muestra aisladamente y se usa la repetición en la tabla comparativa.
La muestra de control ON no se repitió completamente por su costo.

### Experimentos y decisiones

Todos los tiempos de esta tabla son **milisegundos de algoritmo puro**, no HTTP.
Para n=3 se indica mediana y rango; para n=1 se muestra la única observación.

| IMPLEMENTACIÓN | 10 PÁGINAS | 20 PÁGINAS | 279 PÁGINAS | CALIDAD |
| --- | ---: | ---: | ---: | --- |
| PyMuPDF4LLM + Layout | 40,508.623 (n=1) | 70,568.490 (n=1) | No repetido offline; baseline HTTP 1,176,522.714 | Markdown más rico; tablas, enlaces y análisis de diseño. |
| PyMuPDF4LLM sin Layout | 975.508 (n=1) | 1,943.423; rango 1,921.868–1,984.011 (n=3) | 28,335.882 (n=1) | Títulos/énfasis/tablas, pero omite algunos textos de figuras; no se adoptó. |
| PyMuPDF directo, texto → Markdown | 22.968; rango 22.314–24.769 (n=3) | 38.363; rango 37.914–61.232 (n=3) | 651.441 (n=1) | Conserva caracteres seleccionables; títulos, negrita, cursiva y párrafos. Sin reconstrucción de tablas/columnas. Adoptado. |

Muestras de **5 páginas**: ON 22,035.415 ms, 6,202 caracteres, RSS máximo
362.43 MiB; OFF 888.956 ms, 6,224 caracteres, RSS máximo 200.97 MiB;
directo 16.159 / 14.453 / 16.382 ms, 6,156 caracteres idénticos entre repeticiones,
RSS máximo 204.34 MiB. No hubo errores de conversión en las muestras offline.

ON 10/20 produjo 14,309/25,753 caracteres; OFF 10/20 produjo 14,272/24,707;
directo 10/20 produjo 14,301/25,458. Los JSON contienen todas las observaciones,
SHA y fases. La primera serie OFF 20 fue 1,795.705 / 2,099.940 / 2,103.457 ms;
la repetición aislada fue 1,921.868 / 1,984.011 / 1,943.423 ms, mismo SHA.
Su RSS máximo acumulado pasó de 241.54 a 320.04 MiB en tres repeticiones; eso
no demuestra por sí solo una fuga. ON 20 alcanzó RSS 417.22 MiB y una muestra
Docker de 98.77 % CPU; la apertura tomó 0.637 ms y la conversión 70,564.942 ms.

OFF fue unas 36 veces más rápido en 20 páginas, por lo que se autorizó una sola
corrida offline completa: apertura 0.512 ms, conversión 28,330.443 ms, total
28,335.882 ms, RSS máximo 462.16 MiB, **428,610 caracteres**, 279 páginas,
SHA `0d1dc9bdef50dec0e2dd48a2c26c2953af3ec9ed5edcb39e3f0010d0b43d939a`.
Sigue lejos de 400 ms y se observó pérdida de etiquetas seleccionables de figuras.
No se desplegó OFF ni se midió HTTP BYPASS de ese candidato: **no verificado**.

Eso justificó el experimento directo. En 20 páginas fue unas 1,839 veces más
rápido que ON según medianas/única observación; se hizo una sola corrida offline
completa: apertura 0.750 ms, conversión 646.582 ms, total **651.441 ms**, RSS
máximo 219.32 MiB. Inicialmente el arnés importaba PyMuPDF4LLM para sustituir su
conversor; la API adoptada no lo importa. Una comprobación posterior de 20 páginas
con la función adoptada dio 105.708 / 49.587 / 45.874 ms, mismo SHA de muestra,
un hilo y RSS máximo 162.16 MiB. Esa comprobación coincidió parcialmente con la
serie HIT y se usa solo para comprobar identidad/ausencia de ONNX, no como control.

No se repitieron las extracciones completas ON de ~20 minutos. Las posteriores
conversiones completas directas fueron las necesarias para validar HTTP BYPASS,
precargar caché y las reconversiones no deseadas causadas por dos errores de GET.

### Qué explicó los ~20 minutos y los hilos

El código original usaba `use_ocr=False`, `write_images=False`, `embed_images=False`.
La inspección de la versión instalada confirmó `_use_layout=True` y activación
automática de Layout al importar PyMuPDF4LLM. Desactivar OCR no desactiva Layout.
Se encontraron tres sesiones ONNX: modelo principal, extractor de características
de imagen y detector de grilla de tablas. Todas usaban CPUExecutionProvider,
ORT_SEQUENTIAL, intra/inter_op_num_threads=0; `common_util.py` solo desactivaba
el arena de memoria. No restringía los pools a la cuota de 1 CPU.

Proceso de diagnóstico fresco: 1 hilo inicial y después de importar PyMuPDF;
12 tras NumPy; 13 tras importar ONNX Runtime; **46 tras activar Layout**;
13 tras `use_layout(False)` y recolección de basura. Se observan 33 hilos adicionales
por las sesiones Layout, además de los hilos NumPy/Runtime. El servidor original
sumaba también su hilo de salud. Se confirmó así el origen, sin atribuir todos los
47 hilos exclusivamente a ONNX. La muestra ON 20 tuvo 712/718 períodos throttled;
`throttled_usec` es agregado entre hilos, no tiempo HTTP adicional.

La intervención medida localiza el costo en **PDF→Markdown con Layout/ONNX bajo
1 CPU**, no en abrir el PDF ni en OCR. No se obtuvo un perfil de operadores ONNX
individuales. [API oficial PyMuPDF4LLM](https://pymupdf.readthedocs.io/en/latest/pymupdf4llm/api.html)
y [configuración de hilos ONNX](https://onnxruntime.ai/docs/performance/tune-performance/threading.html).
Legacy informa que ignora `use_ocr`; su código usa el texto existente y no llama
al OCR. La prueba de PDF de imagen sigue garantizando ausencia de reconocimiento.

### Identidad, contenido y límites de Markdown

El conversor adoptado recorre las páginas, obtiene bloques/spans ordenados
geométricamente con `TEXT_PRESERVE_IMAGES` desactivado, infiere títulos por tamaños
de fuente y aplica negrita/cursiva por flags. Escapa sintaxis Markdown literal.
No descarta letra pequeña, encabezados ni pies para reducir el tiempo. No usa
OCR, imágenes, modelos semánticos ni archivos temporales.

Resultado completo: **430,618 caracteres**, `page_count=279`, SHA-256 UTF-8
`afa0699046f69ae58b86b851b7ab1687defd7f76341e8b8cc402318d3b5f911d`.
Es distinto del baseline de 435,769 caracteres/SHA `77b112...` por los cambios
de formato. Se recuperó el Markdown anterior desde su caché v1 antes de su
caducidad; se conservó como evidencia, sin ejecutar de nuevo Layout completo.

`check_content.py` verificó, quitando exclusivamente formato Markdown y espacios,
**igualdad de todos los caracteres seleccionables en orden geométrico** contra
los spans secuenciales de las 279 páginas. Hay **276 páginas con texto seleccionable
y 3 sin texto**; no se perdieron páginas textuales. La comparación de tokens con
`Page.get_text()` secuencial también dio 100 % tras normalizar Markdown.
Las métricas brutas de tokens de los JSON penalizan escapes y estilos; no son una
medida exacta de texto perdido. Las métricas normalizadas ON/OFF también penalizan
la desguionización y no deben interpretarse como porcentaje de caracteres ausentes.

Se conservaron títulos, párrafos y énfasis; se perdieron estructuras de tablas,
enlaces enriquecidos, clasificación de figuras/superíndices y análisis semántico de
columnas. Los datos seleccionables de esas regiones permanecen como texto.
Markdown básico utilizable: **verificado**. Equivalencia visual/semántica completa
con Layout o lectura natural de cualquier documento multicolumna: **no verificada**.
No se promete OCR de las tres páginas sin texto.

El namespace de Redis pasó a `extract:v2:<SHA del PDF>` para impedir servir
Markdown Layout antiguo como resultado nuevo. Los datos v1 se preservan hasta
su TTL; no hubo FLUSHDB/FLUSHALL ni borrado de claves ajenas.

### Event loop, capacidad y salud

RED: test con PDF generado de cinco páginas falló con
`Conversion blocked the event loop` (1 failed, 5.31 s). La conversión síncrona
se ejecutaba directamente en un endpoint async. GREEN: conversión en
`ProcessPoolExecutor(max_workers=1, spawn)`. Se prefirió un proceso porque
[PyMuPDF no admite uso concurrente en threads](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html).

Por réplica hay como máximo una conversión en curso, sin cola de trabajos CPU.
Una segunda petición que necesita convertir recibe 503; un HIT usa Redis sin
ocupar ese proceso. La cancelación conserva la ocupación hasta que termina el
trabajo; no detiene la CPU por sí sola. El apagado espera la terminación.
No se agregó recuperación de un proceso muerto: requiere reiniciar la réplica.
El límite controla trabajos CPU, no toda la recepción simultánea de cuerpos PDF;
su uso de RAM con varias cargas simultáneas todavía no se verificó.

Con el PDF real y k6 BYPASS se tomaron **41 GET /health** a través de Traefik:
todos 200, rango observado por Windows 6.004–469.031 ms. Los access logs
identificaron **5 consultas al mismo backend extractor-4 durante el POST**,
todas 200 (duraciones Traefik 48.896, 404.297, 2.340, 7.765, 2.549 ms).
Esto demuestra respuesta concurrente de esa réplica; no garantiza health <400 ms.
Los límites de CPU pueden demorar la planificación aunque el loop no esté bloqueado.

### HTTP real y Redis, separados

k6 original `baseline.js/common.js`, por Traefik `localhost:59345`, 1 VU, sin
alterar su threshold p95<400. Antes del BYPASS se calentaron los cinco trabajadores
con diez PDFs mínimos, sin usar el archivo de stress para el calentamiento.
El BYPASS incluyó las consultas de salud de diagnóstico descritas arriba.
Al restaurar caché, Compose recreó extractores y los procesos CPU quedaron fríos.

| Corrida | Estado | HTTP ms | Algoritmo puro ms | Lectura del cuerpo ms | GET Redis ms | Serialización ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| direct-bypass (n=1) | 200 / BYPASS | 2,246.684 | 724.612 | 1,101.083 | No utilizado | 13.748 |
| direct-preload (n=1) | 200 / ERROR | 4,593.633 | 671.718 | 704.863 | 216.471, timeout | 9.849 |
| direct-preload-retry (n=1) | 200 / MISS | 5,212.437 | 779.966 | 1,018.195 | 158.937 | 1.378 |
| direct-hit-isolated (n=1) | 200 / HIT | 306.495 | No ejecutado | 207.671 | 30.903 | 10.072 |
| direct-hit-series, iteración 0 | 200 / HIT | 670.385 | No ejecutado | 469.714 | 81.069 | 13.128 |
| direct-hit-series, iteración 1 | 200 / HIT | 1,533.117 | No ejecutado | 1,263.965 | 51.764 | 7.570 |
| direct-hit-series, iteración 2 | Timeout cliente 5 s | 5,001.643 | 917.536, reconversión | 1,362.801 | 239.824, timeout | 13.780, backend final |

La serie planeaba 5 iteraciones y se abortó en la tercera: dos completadas y una
interrumpida; dos no se ejecutaron. El backend de la tercera terminó después con
200/ERROR, pero el cliente ya había agotado 5 s y Traefik registró 499. No se
presenta ese resultado posterior como HTTP 200 recibido por k6.

- BYPASS n=1: p50/p90/p95/máximo 2,246.684 ms; errores HTTP/lógicos 0;
  0.43584 req/s. Una muestra **no define una distribución p95 reproducible**.
- Preload ERROR: n=1, 4,593.633 ms; error lógico 100 % por no ser MISS, HTTP 0 %;
  0.21536 req/s. Retry MISS: n=1, 5,212.437 ms; errores 0; 0.18980 req/s.
- HIT aislado n=1: p50/p90/p95/máximo 306.495 ms; errores 0; 2.92204 req/s.
  Es lectura cacheada, no extracción real ni prueba de cumplimiento sostenido.
- Serie con caché n=3, **incluye el fallo**: mínimo 670.385, p50 1,533.117,
  p90 4,307.938, p95 **4,654.790**, máximo 5,001.643 ms;
  errores HTTP/lógicos **33.33 %**, throughput 0.41167 req/s.

El HIT aislado separó GET 30.903 ms, decode/model validation 7.320 ms y creación
real de respuesta FastAPI 10.072 ms. `cache_get_ms` también incluye decodificación
(y logging). La serialización incluye validación y construcción de Response;
no incluye envío al socket. `worker_ms` incluye spawn/IPC/retorno del proceso;
**algorithm_ms lo excluye**. En BYPASS worker_ms=836.286 ms; en las dos precargas
frías fue 3,233.317/3,391.847 ms, pese a algoritmos de 672/780 ms. No confundir
arranque de trabajador con arranque del servicio ni con procesamiento del PDF.

Cliente BYPASS: sending 397.837, waiting 1,842.815, receiving 6.032 ms;
blocked/connect 22.434 ms fuera de http_req_duration. HIT aislado: sending
201.007, waiting 101.107, receiving 4.382 ms. La lectura de cuerpo de Uvicorn
se solapa con parte de la transmisión: **no se suma otra vez al tiempo cliente**.
Traefik BYPASS registró Duration 2,013.599 ms, OriginDuration 2,013.519 ms,
Overhead 0.080 ms; HIT aislado 270.451/270.247/0.203 ms. Son ventanas específicas
del proxy y su Overhead no mide todo el costo de transferir 17.75 MB desde Windows.

**Redis aún no está libre de timeouts.** Se mantuvo CACHE_TIMEOUT_SECONDS=0.2,
sin aumentarlo. Dos GET agotaron el plazo y activaron fail open/reconversión,
con el nuevo loop ya desbloqueado. No se puede atribuir toda la inestabilidad del
baseline solo al bloqueo del loop. Ambas fallas fueron la primera operación Redis
de sus réplicas tras recreación; GET incluye conectar, DNS y negociación.

Diagnóstico separado de conexión en un proceso dentro de extractor-4: tres
clientes nuevos, tres GET de clave inexistente por cliente, sin escrituras ni
borrados. Con el mismo código/deadline no hubo timeout: primeros GET
16.299/4.486/4.427 ms, siguientes 0.289–0.625 ms. DNS inicial 13.370 ms;
conexión/negociación explican gran parte del frío de esa prueba. No reprodujo las
fallas del servidor bajo recepción HTTP; no demuestra la causa única. La hipótesis
pendiente es planificación/cuota/page faults y establecimiento frío de conexión.
Antes de ajustar el plazo conviene trazar DNS/TCP/negociación y lag del loop en
esa primera llamada real, y compararla con una conexión ya establecida.

### Recursos, tests y estado final

Los recursos no se aumentaron: 5 réplicas, **1 CPU y 768 MiB cada una**;
Docker conserva ~3.509 GiB globales, Redis compartido y `pdf-network`.
Se muestreó Docker stats durante k6: BYPASS llegó a 100.45 % CPU y 343.8 MiB
muestreados en la réplica activa; las precargas a 99.93/94.61 % CPU;
la serie a 99.45 % CPU por reconversión. HIT aislado: máximo muestreado entre
réplicas 0.24 % CPU, 329.4 MiB (incluye memoria retenida de conversiones anteriores).
Son muestras escasas (1/2/3 según corrida), **no máximos absolutos ni prueba de fuga**.
No hubo OOM ni pérdida de health en esta fase. No se ejecutó carga de 2/5/100 VUs.

Se mantienen los 28 casos anteriores; las expectativas de namespace se
actualizaron a v2 y la prohibición de reconversión en HIT ahora intercepta la
frontera del proceso CPU (un parche en el padre no intercepta un hijo spawn).
Se agregaron cinco tests: health durante extracción real,
rechazo 503 y reutilización de capacidad, cancelación que mantiene ocupación,
texto pequeño/sintaxis Markdown literal y aislamiento frente a caché Layout v1.

- RED health: 1 failed en 5.31 s; GREEN inicial: 1 passed en 6.34 s.
- RED contenido: 1 failed en 6.24 s (Layout descartó letra de 2 pt);
  GREEN: 1 passed en 1.90 s.
- RED namespace: 1 failed en 3.15 s (HIT antiguo); GREEN: 1 passed en 3.93 s.
- Suite antes de actualizar el guard de reconversión: 33 passed, 1 skipped, 25.55 s.
- Suite final con guard actualizado: **33 passed, 1 skipped en 23.43 s**.
- Integración Redis/HTTP por Traefik: **1 passed, 33 deselected en 16.56 s**,
  MISS→HIT, contenido y TTL correctos; borra únicamente su clave UUID de prueba.
- Docker build y Compose `--scale extractor=5 --wait`: aprobados.
- Final: cinco extractores, Redis y Traefik saludables, caché activada,
  timeout 200 ms, límites originales. Contenedores del monolito sin intervención.

### Comandos reproducibles

Desde la raíz del repositorio, PowerShell. Usar nombres nuevos para preservar
la evidencia anterior; los runners se niegan a reemplazar resultados existentes.

```powershell
$pdf = 'D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf'
$stamp = Get-Date -Format yyyyMMdd-HHmmss
New-Item -ItemType Directory -Force tests/stress/results/extractor-profiling | Out-Null
$result = (Resolve-Path tests/stress/results/extractor-profiling).Path
Get-Item -LiteralPath $pdf | Select-Object Length
Get-FileHash -LiteralPath $pdf -Algorithm SHA256
uv run --locked pytest -v

# Offline en Windows: condiciones diferentes de Docker, informar por separado.
uv run --locked python tests/performance/offline.py --pdf $pdf --layout current --pages 20 --repeat 3 --output "$result/current-20-$stamp.json"
# Para cada control/candidato, proceso nuevo y cambiar solo --layout/--pages.
# No quitar --pages para ON: el documento completo vuelve a costar ~20 minutos.

# Reproducir la cuota del experimento sin red ni servicio HTTP:
$service = (Get-Location).Path
docker run --rm --network none --cpus 1 --memory 768m --read-only --mount "type=bind,source=$pdf,target=/input.pdf,readonly" --mount "type=bind,source=$service\tests\performance,target=/bench,readonly" --mount "type=bind,source=$result,target=/results" --entrypoint python pdf-extractor-extractor /bench/offline.py --pdf /input.pdf --layout current --pages 20 --repeat 3 --output "/results/current-docker-20-$stamp.json"
# --layout on / off selecciona los controles PyMuPDF4LLM; --layout current,
# o direct, usa el conversor productivo. Los full requieren confirmar antes
# una mejora grande en 20 páginas y quitar --pages conscientemente.

# Construir y habilitar BYPASS de forma temporal:
docker compose -f compose.yaml -f compose.traefik.yaml build extractor
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.performance.yaml up -d --scale extractor=5 --wait --wait-timeout 150
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name "bypass-$stamp" --cache BYPASS --iterations 1 --sha256 afa0699046f69ae58b86b851b7ab1687defd7f76341e8b8cc402318d3b5f911d --timeout 30s --results $result
# Añadir --probe-health solo para diagnóstico; documentar esa carga adicional.
# La primera conversión de cada proceso puede incluir el costo de spawn.

# Restaurar caché normal (sin destruir Redis ni modificar Traefik):
docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=5 --wait --wait-timeout 150
$port = (docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80).Trim().Split(':')[-1]
$env:EXTRACTOR_BASE_URL = "http://localhost:$port"
uv run --locked pytest --run-integration -m integration -v -s
Remove-Item Env:EXTRACTOR_BASE_URL
# Precargar con una petición normal. Si devuelve ERROR, investigar antes de HIT.
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name "preload-$stamp" --cache MISS --iterations 1 --sha256 afa0699046f69ae58b86b851b7ab1687defd7f76341e8b8cc402318d3b5f911d --timeout 30s --results $result
# Si el documento ya está cacheado, usar --cache HIT; no borrar claves ajenas.
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name "hit-$stamp" --cache HIT --iterations 1 --sha256 afa0699046f69ae58b86b851b7ab1687defd7f76341e8b8cc402318d3b5f911d --timeout 5s --results $result
docker compose -f compose.yaml -f compose.traefik.yaml logs --no-color extractor
docker compose -f compose.yaml -f compose.traefik.yaml logs --no-color traefik
docker stats --no-stream
docker compose -f compose.yaml -f compose.traefik.yaml ps

# Auditar el Markdown escrito por offline.py, fuera de la medición:
uv run --locked python tests/performance/check_content.py --pdf $pdf --markdown "$result/direct-279.0.md" --output "$result/content-$stamp.json"
# check_content audita el PDF completo, no una muestra de 20. En otro equipo,
# después de calificar la mejora de 20 páginas, ejecutar UNA vez el comando
# Docker offline con --layout current, sin --pages, y --output full-$stamp.json;
# luego usar su full-$stamp.0.md en --markdown.
```

No se ofrece `down -v`: terminar pruebas con caché false requiere restaurar el
comando normal de arriba. Los scripts originales del monolito/k6/spike conservan
sus umbrales; no se ejecutaron como sustituto de este benchmark Markdown.

### Qué falta para 400 ms

**La meta de extracción p95 <400 ms no está alcanzada.** El algoritmo puro ya
excede 400 ms (651 ms offline; 672–918 ms en conversiones HTTP observadas).
El BYPASS por Traefik fue 2,247 ms y no se obtuvo una distribución BYPASS repetida.
Un HIT aislado de 306 ms no convierte el PDF, y la serie con caché falló.

Próximas tareas concretas, cada una como cambio independiente:

1. Instrumentar la primera conexión real Redis (DNS, TCP, negociación y lag del
   loop) para reproducir los GET de 216/240 ms; verificar el plazo actual antes
   de proponer un ajuste. Resuelve la inestabilidad que sobrevivió al offload.
2. Perfilar en muestras pequeñas el desglose del conversor directo: get_text
   dict, detección de títulos y render Markdown. Elegir una sola reducción CPU
   demostrada que mantenga la auditoría por página/SHA; no prometer <400 ms.
3. Aislar la variación de recepción de 17.75 MB desde Windows/Traefik/Uvicorn
   (207–1,363 ms observados) bajo condiciones iguales y sin carga de salud.
   No sumar tramos solapados; no aplicar cambios al balanceador sin evidencia.
4. Si el frío es relevante para el perfil oficial, medir/preparar el trabajador
   de forma acotada al arranque, conservando presupuesto RAM y el único proceso.
   Mantener separadas extracción pura y preparación/spawn.
5. Revisar semántica de columnas/tablas con documentos exigidos por la cátedra
   antes de exigir equivalencia estructural a Layout o realizar carga mayor.

No se aplicaron estas tareas adicionales ni se subieron los cambios.

## Fases A–F: text-only, recorridos HTTP y Redis caliente

Medición del 7 de octubre de 2026, aproximadamente 01:56–01:58 ART. Estado local
de `main`, sin commits ni push. Evidencia nueva y separada en
[`extractor-text-profile`](../tests/stress/results/extractor-text-profile/).
No se sobrescribieron las mediciones de `extractor-baseline` ni
`extractor-profiling`. No se modificaron el monolito, sus scripts, el PDF, el
Traefik funcional, sus límites ni las dependencias. No se ejecutaron Spike,
Vegeta, Layout ni PyMuPDF4LLM. Sólo 1 VU, una petición por diagnóstico y una
serie de hasta diez HIT; no hubo carga concurrente.

### Condiciones y alcance

Mismo hardware y cuotas del entorno descrito arriba: Ryzen 5 4600H, Windows 11,
7.36 GiB físicos; Docker Desktop 12 CPU visibles y **3.509 GiB totales**.
Cinco extractores de **1 CPU / 768 MiB**, Redis compartido de 0.5 CPU / 256 MiB
y Traefik v3.6 de 0.5 CPU / 128 MiB, red externa `pdf-network`. Otros proyectos
continuaron funcionando; el equipo no estaba dedicado al benchmark.

Python del contenedor 3.12.15; PyMuPDF 1.28.2, FastAPI 0.142.2, Pydantic 2.13.5,
Uvicorn 0.54.0, redis-py 8.1.0. Docker 29.7.2, Compose 5.5.1, uv 0.11.6.
k6 **2.2.0, commit 00a9a1b7f5, Go 1.26.5** en Windows y Linux: misma versión.
Imagen del cliente `grafana/k6:2.2.0`, digest
`sha256:9bd01d6941fca969cb61bb57d2da5ee9b385fe2aa8881df3798c196564d6ace6`.
El cliente Docker diagnóstico tenía 1 CPU / 256 MiB; muestreo observado
134.9 MiB y 28.85 % CPU. No se aumentaron recursos de la API.

PDF externo obligatorio, sin copiarlo al repositorio ni modificarlo:
`D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf`.
**17,749,468 bytes, 279 páginas, 276 con texto seleccionable y 3 sin texto**.
SHA-256 de archivo
`728c8a522ce24bf0ba3851cd109cdc0e55b200e3cd9b55b8343b39c005713162`.
Puerto dinámico de Traefik observado: `127.0.0.1:59345`.

### A. Medir antes de adoptar el Markdown text-only

Primero se midió el candidato adicional; después se cambió el conversor de la
API. Los procesos offline tenían 1 CPU / 768 MiB, sin red, PDF montado sólo
para lectura y bytes leídos antes de iniciar el reloj.

| Conversor | Corridas completas, ms | Apertura, ms | get_text, ms | Resto de conversión, ms | Total mediano, ms |
| --- | --- | --- | --- | --- | --- |
| Spans previo, control n=1 | 793.869 | 31.104 | 671.871 | 85.765 | 793.869 |
| Texto por página, n=3 | 441.634 / 435.725 / 432.806 | 0.517 | 407.550 | 24.113 | **435.725** |

Para texto se muestran medianas de etapas; no se suman medianas independientes.
El «resto» offline es `convert_ms - get_text_ms`: incluye cargar/recorrer páginas
y formar Markdown, no es una medición exclusiva del join. El perfil HTTP de
producción sí cronometra append/join por separado: **0.888–2.561 ms** en las
extracciones medidas. El coste nativo domina.

El control es una sola ejecución con apertura fría; no se puede afirmar una
aceleración constante de 45 % en cualquier condición. Las tres conversiones
del candidato fueron claramente menores en esta sesión. No hubo más corridas
offline del documento completo. RSS máximo: spans 184.59 MiB, texto 168.09 MiB.

Se adoptó `page.get_text("text")`, sin spans, fuentes, estilos, tablas ni imágenes,
bajo `## Página N`. La referencia se calculó fuera del tiempo medido: igualdad
exacta del texto de cada página, incluidas páginas sin texto y orden 1–279,
en las tres corridas. **427,008 caracteres**, de los cuales 422,375 son texto
nativo y 4,633 son encabezados/separadores. Inicio con portada de Scrum y final
con «Fuente: Elaboración propia.». No se omitieron las 276 páginas textuales.
No se garantiza lectura semántica de columnas ni transcripción de imágenes.

SHA-256 del contenido Markdown nuevo:
`c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc`.
Todos los HTTP medidos lo verificaron, con `page_count=279` y HTTP 200.
El checksum de texto plano del monolito y el SHA anterior de spans corresponden
a representaciones diferentes. No se exige que coincidan con este Markdown.
La clave Redis pasa a `extract:v3:<sha-PDF>`; no se borran v1/v2.

### B–D. Etapas HTTP y recorrido del cuerpo

La instrumentación usa `perf_counter` y logs `PROFILE` con X-Audit-Id.
No altera el JSON público. `receive_body_ms` mide `await request.body()` desde
que comienza el handler; `sha256_ms`, el hash del PDF completo; `redis_get_ms`,
la operación Redis; `extraction_ms`, el algoritmo dentro del trabajador;
`response_build_ms`, validación/serialización y creación de Response en FastAPI;
`total_server_ms`, handler hasta Response lista, **sin envío por socket**.
`worker_ms` incluye IPC, transferencia del PDF, despacho y devolución del modelo,
además del algoritmo. Esos tramos no deben sumarse dos veces.

Se habilitaron puertos directos dinámicos de desarrollo con el overlay
`compose.direct-diagnostic.yaml`, sin editar Traefik. Se calentó el proceso CPU
de cada réplica con un PDF mínimo de una página: primeras peticiones observadas
4517.7–6146.1 ms desde Windows (incluyen spawn y recorrido HTTP). Esto excluye
spawn inicial de los tres diagnósticos BYPASS, pero no iguala el caché interno
de fuentes del PDF grande. Después se retiraron los puertos directos.

| Recorrido; n=1 cada uno | HTTP k6, ms | Envío cliente | Recepción cuerpo app | Extracción | Worker total | SHA PDF | Respuesta FastAPI | Recepción cliente |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Windows → app directa, extractor-1 | **2861.464** | 599.523 | 1318.696 | 814.492 | 1200.397 | 12.022 | 21.556 | 12.804 |
| Windows → Traefik → extractor-2 | **2700.867** | 222.169 | 1071.951 | 750.440 | 1275.745 | 19.662 | 25.102 | 17.341 |
| Docker k6 → Traefik → extractor-1 | **1215.349** | 51.920 | 149.687 | 600.136 | 1026.112 | 8.582 | 7.223 | 7.239 |

Tiempos de handler respectivamente 2556.119 / 2393.136 / 1193.070 ms.
Bloqueo/conexión k6, excluido de `http_req_duration`: 36.336 / 20.843 / 2.491 ms.
HTTP k6 significa
envío + espera + recepción, no tiempo total del proceso cliente.
Los tres diagnósticos pasaron todos los checks funcionales, sin fallos HTTP;
k6 terminó con **99 porque p95<400 no pasó**, y se conservó la evidencia.
Con n=1 los percentiles coinciden con la observación y no describen una distribución.

La recepción desde Windows se reprodujo en ~1.07–1.32 s en BYPASS; desde Docker
fue ~150 ms. La diferencia de recepción Windows-Traefik versus Docker-Traefik
es ~922 ms. **Hipótesis apoyada por estas muestras:** el recorrido Windows /
puerto publicado / Docker Desktop y su planificación contribuyen al coste.
El envío visto por k6 no significa que Uvicorn ya tenga todo el cuerpo: hay
buffering y forwarding entre ambos relojes. Los HIT posteriores leyeron ese
mismo cuerpo en 169–265 ms, por lo que no es un coste fijo por byte.

No se aisló cuál componente de Windows/VM/socket provoca cada demora. Tampoco
es válido restar 2861−2701 ms para declarar un overhead negativo del proxy:
son réplicas/instantes distintos y la segunda conversión de extractor-1 pudo
tener fuentes calientes. Las cuotas y estado sano eran iguales. Traefik registró
overhead propio **0.854 ms** para Windows y **0.686 ms** para Docker, pero ese
campo no mide todos los costes del recorrido de red. No se cambió su configuración.

`network.js` mantiene destino Traefik y HTTP `Host: localhost`; la opción
`hosts` de k6 resuelve `localhost` a la IP de Traefik en `pdf-network`, evitando
apuntar accidentalmente al loopback del cliente o a una réplica. Ver
[opción hosts de k6](https://grafana.com/docs/k6/latest/using-k6/k6-options/reference/).
El runner obtiene la IP real y monta el PDF externo sólo para lectura. Ejecuta
exactamente 1 VU / 1 iteración, con checks de BYPASS, páginas y SHA.

### E. Redis caliente y hasta diez HIT

Ya había un cliente/pool Redis persistente por proceso API. Se añadió un único
PING de arranque, con `asyncio.timeout(0.2)` y los mismos timeouts del socket.
Con error o timeout, startup sigue y las peticiones mantienen fail open.
No se agregaron reintentos ni se amplió el plazo para esconder demoras.

Los cinco PING reales fueron READY: **105.428 / 74.061 / 41.875 / 17.053 /
75.156 ms** para réplicas 1–5. Redis CLIENT LIST mostró las mismas cinco
conexiones, IDs **1724–1728**, antes y después: cambiaron de `ping` a `get`;
se reutilizaron a través de réplicas. No se eliminó el documento ni se vació Redis.

Precarga real: HTTP 200 / MISS, **3939.065 ms**; cuerpo 260.558 ms,
algoritmo 482.662 ms, GET 3.258 ms, SET 9.618 ms, worker 3244.101 ms.
Incluye proceso CPU frío tras restaurar caché y recrear APIs; no es un HIT ni
una extracción pura de 3.9 s. Luego una única serie Windows → Traefik,
1 VU / 10 iteraciones, timeout HTTP 5 s, sin pausa deliberada entre HIT:

| Iteración | Instancia | HTTP, ms |
| --- | --- | --- |
| 0 | extractor-2 | 219.427 |
| 1 | extractor-1 | 220.022 |
| 2 | extractor-4 | 223.930 |
| 3 | extractor-5 | 331.286 |
| 4 | extractor-4 | 325.437 |
| 5 | extractor-5 | 257.897 |
| 6 | extractor-2 | 257.894 |
| 7 | extractor-3 | 285.391 |
| 8 | extractor-1 | 292.751 |
| 9 | extractor-3 | 317.366 |

**10/10 HTTP 200, X-Cache HIT, SHA correcto; cero errores HTTP/lógicos/Redis**.
Mínimo 219.427 ms, **p50 271.644**, **p90 326.022**, **p95 328.654**,
máximo 331.286 ms; **3.487 solicitudes/s** incluyendo trabajo de k6 por iteración.
Son percentiles interpolados de k6 para sólo diez muestras, sin promesa de SLO
bajo concurrencia ni estabilidad prolongada. No se hicieron más HIT del PDF real.

En servidor HIT: lectura del cuerpo mediana **208.449 ms** (169.125–264.913),
SHA **8.903 ms** (8.528–56.294), GET **2.854 ms** (1.237–6.701), decodificar
modelo **1.543 ms**, Response **0.984 ms** (0.844–3.589), handler **227.689 ms**.
La extracción fue cero en todos los HIT. El cuerpo completo sigue cruzando la
red y se vuelve a hashear: la latencia HTTP no es «tiempo Redis» exclusivamente.
La serie corta mejoró respecto a los timeouts de la fase anterior, pero el
warm-up y un entorno variable no bastan para atribuir toda la mejora al PING.

### F. Objeto, JSON y transferencia

Traefik registró **454,366 bytes** de cuerpo JSON tanto en BYPASS como en HIT.
Construir `ExtractionResponse` en CPU costó **0.068 / 0.119 / 2.480 ms** en los
tres diagnósticos y 0.054 ms en precarga. Decodificar JSON Redis y validar el
modelo se informa aparte. Response FastAPI: 7.223–25.102 ms en los diagnósticos,
0.528 ms en precarga y mediana 0.984 ms en HIT. Incluye validación y creación de
Response; no se separó el coste exclusivo del serializador.

Se inspeccionó el código instalado de FastAPI 0.142.2: con `response_model` y
respuesta por defecto, `serialize_response(..., dump_json=True)` usa el JSON
directo de Pydantic, sin pasar por un dict y `json.dumps` de Python. Ya se usa
el serializador de Pydantic/Rust. El envío/recepción final visto por k6 fue
2.805–10.652 ms en HIT y 7.239–17.341 ms en BYPASS. Es tiempo de recibir el
cuerpo completo, incluye red/planificación del cliente; no sólo escribir el socket.
**No se añadió ORJSON ni otra dependencia:** el cuello dominante observado está
en cuerpo, texto nativo y despacho/transferencia al trabajador.

### Recursos, tests y límites de las conclusiones

Máximos **muestreados** de CPU / memoria por extractor:
directo 95.38 % / 323.7 MiB; Windows-Traefik 99.85 % / 323.7 MiB;
Docker-Traefik 79.10 % / 331.2 MiB; precarga 98.71 % / 325.3 MiB;
HIT 75.07 % / 325.3 MiB. Muestreo `docker stats --no-stream`, sólo 1–2
muestras por corrida corta: no garantiza capturar el máximo instantáneo.
100 % corresponde a la cuota de un núcleo, no a toda la máquina.
Se observaron períodos de throttling en cgroup; el intervalo precarga + HIT +
observación añadió **77–608 ms de throttled_usec por réplica**. No es un tramo
exclusivo de HIT y tampoco debe sumarse directamente al reloj HTTP.
Todas continuaron sanas, sin OOMKilled ni eventos `oom/oom_kill/max` de memoria.
Los límites máximos de cinco APIs exceden la RAM total de Docker si se consumen
simultáneamente; no se autorizó ni ensayó esa saturación.

Estado final: se reconstruyó la imagen y recrearon sólo las APIs para incluir
una aclaración del docstring, sin cambios funcionales posteriores al benchmark.
Imagen de los HTTP medidos:
`sha256:023c0ce9d6678154d0f9bdec971025d16ee029a574df360d20acb8469a471147`;
imagen final:
`sha256:c712efd7e51fcad7201ee81bfbc8488d771ed8fe60a108eb6ebd63acc2d1b8b6`.
Las cinco quedaron saludables, CACHE_ENABLED=true, 1 CPU / 768 MiB y sin
puertos directos publicados; `/health` por Traefik volvió a dar 200.
Traefik y Redis conservaron sus IDs. En **este último arranque** hubo cuatro
PING READY (120.510–163.926 ms) y **un timeout de warm-up en extractor-4,
201.732 ms**, con inicio fail open correcto. No se repitieron los diez HIT tras
ese arranque: la serie exitosa corresponde al arranque previo con cinco READY.
No se afirma que el warm-up garantice conexiones listas en todos los arranques.

Se contrastaron hashes de **254 archivos iniciales**: cambios sólo en los once
archivos de esta fase, sin pérdidas. Monolito, Mongo 8.2.11 local, Compose/Traefik
previos, dependencias y evidencia anterior sin cambios; PDF conserva tamaño/SHA.
Rama main y HEAD sin cambios, índice vacío. Los resultados nuevos están guardados
localmente pero `tests/stress/results/*` está ignorado por Git, como antes.
`final-verification.json` enumera archivos y estado final; no hay commit ni push.

TDD: test de texto exacto con encabezados RED (1 fallo) → GREEN (1 aprobado);
PING de startup RED (contador 0) → GREEN. Casos de conexión caída y plazo vencido:
4 aprobados en 4.98 s en la selección de startup, incluido URL Redis inválido.
Suite completa: **37 passed, 1 skipped in 27.61 s**. Integración real por Traefik:
primero falló por decodificar stdout Docker con cp1252 en Windows; se fijó
`encoding="utf-8"` en el helper del test, necesario para `Página`.
Repetición: **1 passed, 37 deselected in 12.69 s**; MISS→HIT, texto idéntico,
TTL 3600 s, PTTL 3599806→3597444 ms. Sólo se limpió su propia clave UUID.
Los tests de disponibilidad, cancelación y ocupado siguieron aprobados.

El runner directo inicialmente terminó con error al imprimir Unicode en consola
cp1252 **después de guardar una medición válida**. Se fijó su stdout a UTF-8;
no se repitió el PDF grande para ocultar el error. Su log, summary y recursos
contienen la única petición real. Los otros runners completaron normalmente.

### Cuatro resultados y próximo paso

1. Algoritmo candidato text-only, 279 páginas: **435.725 ms de mediana (n=3)**.
2. HTTP BYPASS directo desde Windows: **2861.464 ms (n=1)**.
3. HTTP BYPASS Windows → Traefik: **2700.867 ms (n=1)**.
4. Redis HIT Windows → Traefik: **p95 328.654 ms (n=10)**.

**Algoritmo puro <400: no. HTTP BYPASS <400: no**, tampoco la muestra interna
Docker-Traefik de 1215.349 ms. **HIT secuencial <400: sí en esta serie corta**,
sin demostrar una distribución duradera/concurrente. El get_text nativo offline
ya consume ~408 ms; bajo HTTP también hay cuerpo (~1.07 s desde Windows en ese
BYPASS) y overhead de worker/IPC (~426–525 ms en los recorridos por Traefik).

Próximo cambio recomendado: perfilar de forma acotada el traslado de 17.75 MB
al trabajador y su throttling, separándolo de get_text, con igual cuota y
documento. Después elegir una única reducción de copias/IPC respaldada por esa
medición; no quitar el aislamiento que mantiene disponible `/health` ni prometer
que eso reducirá el algoritmo nativo por debajo de 400 ms. No se aplicó esa
optimización. La salida JSON no justifica una nueva dependencia en estas muestras.

### Comandos para repetir A–F sin borrar datos

Desde la raíz del repositorio, elegir nombres NUEVOS para preservar resultados:

```powershell
$pdf = 'D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf'
New-Item -ItemType Directory -Force tests/stress/results/extractor-text-profile | Out-Null
$results = (Resolve-Path tests/stress/results/extractor-text-profile).Path
$sha = 'c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc'
git status --short
Get-Item -LiteralPath $pdf | Select-Object Length
Get-FileHash -LiteralPath $pdf -Algorithm SHA256
uv run --locked pytest -q
docker compose -f compose.yaml -f compose.traefik.yaml build extractor
```

Offline: archivo fuente montado sólo para lectura, sin red, máximo tres corridas
por candidato. No ejecutarlo adicionalmente dentro de esta fase ya medida:

```powershell
$scripts = (Resolve-Path tests/performance).Path
docker run --rm --cpus 1 --memory 768m --network none --read-only --mount "type=bind,source=$pdf,target=/input.pdf,readonly" --mount "type=bind,source=$scripts,target=/diagnostics,readonly" --mount "type=bind,source=$results,target=/results" --entrypoint /service/.venv/bin/python pdf-extractor-extractor:latest /diagnostics/text_path.py --pdf /input.pdf --candidate spans --repeat 1 --output /results/spans-next.json
docker run --rm --cpus 1 --memory 768m --network none --read-only --mount "type=bind,source=$pdf,target=/input.pdf,readonly" --mount "type=bind,source=$scripts,target=/diagnostics,readonly" --mount "type=bind,source=$results,target=/results" --entrypoint /service/.venv/bin/python pdf-extractor-extractor:latest /diagnostics/text_path.py --pdf /input.pdf --candidate text --repeat 3 --output /results/text-next.json
```

Diagnósticos cortos BYPASS. Calentar los trabajadores sólo con PDFs mínimos
generados en memoria antes de comparar; la primera conversión arranca `spawn`:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.performance.yaml -f compose.direct-diagnostic.yaml up -d --scale extractor=5 --wait --wait-timeout 150
docker stats --no-stream
# Una sola página generada en memoria por réplica, NO el PDF de rendimiento:
@'
import json, subprocess, urllib.request
import pymupdf
ids = subprocess.check_output(['docker', 'ps', '-q', '--filter',
    'label=com.docker.compose.project=pdf-extractor', '--filter',
    'label=com.docker.compose.service=extractor'], text=True).split()
replicas = json.loads(subprocess.check_output(['docker', 'inspect', *ids]))
with pymupdf.open() as doc:
    doc.new_page().insert_text((72, 72), 'Warm CPU worker only')
    body = doc.tobytes()
for replica in replicas:
    port = replica['NetworkSettings']['Ports']['8000/tcp'][0]['HostPort']
    req = urllib.request.Request(f'http://localhost:{port}/extract', data=body,
        headers={'Content-Type': 'application/pdf', 'X-Audit-Id': 'warm-worker'})
    with urllib.request.urlopen(req, timeout=30) as response:
        assert response.status == 200 and response.headers['X-Cache'] == 'BYPASS'
        assert json.load(response)['page_count'] == 1
'@ | uv run --locked python -
uv run --locked python tests/performance/run_diagnostic.py --mode direct --pdf $pdf --results $results --name windows-direct-next --sha256 $sha
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name windows-traefik-next --cache BYPASS --vus 1 --iterations 1 --sha256 $sha --timeout 30s --results $results
docker pull grafana/k6:2.2.0
uv run --locked python tests/performance/run_diagnostic.py --mode network --pdf $pdf --results $results --name docker-traefik-next --sha256 $sha
```

Restaurar caché y cerrar puertos directos, sin detener/vaciar Redis. Precarga:
si la clave ya existe, esperar HIT y no borrar su contenido para obtener MISS.
Si falla precarga o no hay SHA/279/X-Cache válidos, detener el procedimiento:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=5 --wait --wait-timeout 150
docker compose -f compose.yaml -f compose.traefik.yaml logs extractor | Select-String 'WARMUP|warmup'
$key = 'extract:v3:' + (Get-FileHash -LiteralPath $pdf -Algorithm SHA256).Hash.ToLowerInvariant()
$exists = docker compose -f compose.yaml exec -T redis redis-cli EXISTS $key
$preload = if ($exists.Trim() -eq '1') { 'HIT' } else { 'MISS' }
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name preload-next --cache $preload --vus 1 --iterations 1 --sha256 $sha --timeout 30s --results $results
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name hits-next --cache HIT --vus 1 --iterations 10 --sha256 $sha --timeout 5s --results $results
$address = docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80
$env:EXTRACTOR_BASE_URL = 'http://localhost:' + ($address -split ':')[-1]
uv run --locked pytest --run-integration -m integration -q -s
Remove-Item Env:EXTRACTOR_BASE_URL
docker compose -f compose.yaml -f compose.traefik.yaml ps
```

No automatizar una repetición tras errores ni ampliar esta serie a carga alta.
`--name` protege resultados anteriores. Los runners conservan los umbrales;
99 por latencia no es éxito de rendimiento aunque los checks funcionales pasen.

## Blocks y caché caliente — 7 de octubre de 2026

Esta fase comparó sólo `get_text("text")` y `get_text("blocks", sort=False)`,
y después ejecutó k6 HOT progresivo por Traefik. No se ejecutaron Layout,
PyMuPDF4LLM, OCR, Vegeta ni Spike. No se modificaron el monolito, los Compose
existentes, Traefik, las dependencias, los recursos ni el timeout Redis de
200 ms. Tampoco se introdujeron threads para extraer: continúa un proceso CPU,
como máximo una extracción activa por réplica. Las pruebas funcionales de
ocupado, salud y cancelación siguieron aprobadas.

Evidencia local nueva, sin sobrescribir las fases anteriores:
[`extractor-blocks-hot-cache`](../tests/stress/results/extractor-blocks-hot-cache/).
Está ignorada por Git, igual que el resto de resultados de estrés.
`algorithm.json`, dos salidas Markdown, summaries k6, logs de cada petición,
recursos, perfiles API y access logs Traefik permiten revisar los resultados.

### Condiciones

Mismo Windows 11 / Ryzen 5 4600H / 7.36 GiB físicos, Docker Desktop 12 CPU
visibles y 3.509 GiB; otros proyectos siguieron ejecutándose. Cinco APIs de
**1 CPU y 768 MiB** cada una; Redis compartido 0.5 CPU / 256 MiB, Traefik v3.6
0.5 CPU / 128 MiB, red externa `pdf-network`. La API sigue recibiendo el PDF
completo en memoria como body binario `application/pdf`.

PyMuPDF 1.28.2, Python contenedor 3.12.15, FastAPI 0.142.2, Pydantic 2.13.5,
redis-py 8.1.0; Docker 29.7.2, Compose 5.5.1, uv 0.11.6. k6 2.2.0,
commit 00a9a1b7f5, **ejecutado desde Windows** para mantener el recorrido de la
serie HOT anterior: `Windows → localhost:59345 → Traefik → API → Redis`.
El runner consulta el puerto dinámico; no se apuntó a una réplica directa ni
se sustituyó esta medición por una hecha desde Docker.

PDF externo **sin modificar**:
`D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf`,
**17,749,468 bytes y 279 páginas**. SHA-256 original confirmado antes/después:
`728c8a522ce24bf0ba3851cd109cdc0e55b200e3cd9b55b8343b39c005713162`.
No se copió al repositorio. No se usó `mi_documento.pdf` para rendimiento.

### A–C. Experimento y elección de extracción

Se creó primero un candidato offline; la API siguió en text-only durante toda
la comparación. Se realizaron **exactamente cinco conversiones por método**,
en un solo proceso Docker de 1 CPU / 768 MiB, sin red y PDF montado sólo para
lectura. Cada conversión abrió un Document nuevo desde bytes ya cargados en RAM.
Orden alternado de pares: text→blocks, blocks→text, text→blocks, blocks→text,
text→blocks. No hubo calentamiento adicional del PDF grande ni extracciones
extra para validar calidad: se capturó cada resultado ya medido. La comprobación
de contenido y el hash se hicieron después de detener el reloj.

| Método | Corridas completas, ms | Mínimo | Mediana | p95 descriptivo | Máximo |
| --- | --- | --- | --- | --- | --- |
| `text` | 480.663 / 463.282 / 460.162 / 470.303 / 415.052 | 415.052 | **463.282** | 478.591 | 480.663 |
| `blocks`, sort=False, sólo type=0 | 376.519 / 448.011 / 471.845 / 404.396 / 414.434 | 376.519 | **414.434** | 467.079 | 471.845 |

`total_ms` incluye apertura, extracción, Markdown, cierre, modelo y el envoltorio
del benchmark; excluye leer el archivo, verificar contenido, escribir evidencia
y cualquier HTTP/Redis/spawn. Mediana de llamada nativa get_text: text
427.633 ms, blocks 385.093 ms. Los cronómetros/capturas del diagnóstico tienen
coste pequeño; el text control conserva el perfilado de producción. No se
presenta el p95 interpolado de cinco muestras como una garantía estadística.
El máximo RSS observado del proceso completo fue 180.00 MiB; es acumulativo,
incluye referencia/capturas y no es memoria exclusiva de un método en la API.

**Blocks ganó 4/5 pares**, con reducción de medianas **48.849 ms / 10.54 %**.
Hay solapamiento y variación entre muestras: en un par fue más lento y en otro
la ganancia fue sólo 0.619 ms. Se adoptó como mejora observada en esta sesión,
sin afirmar aceleración constante para todos los documentos o entornos.
**No logró MEDIANA<400 ms**: sólo una de las cinco observaciones quedó debajo.
La mediana text de 435.725 ms de la fase anterior se conserva como histórica;
la comparación válida de esta sesión usa 463.282 versus 414.434 ms.

El candidato concatena únicamente `block[4]` cuando `block[6] == 0`, en el orden
devuelto, bajo `## Página N`; no usa coordenadas ni sort=True ni analiza estilos.
La documentación describe blocks como extracción rápida y advierte que puede
incluir metadatos de imágenes: esos bloques no se emiten. No promete que sea más
rápido que text en todos los casos. Fuentes:
[textos y bloques de PyMuPDF](https://pymupdf.readthedocs.io/en/latest/app1.html#blocks),
[procesos y restricción de threads](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html).

**Calidad:** en las diez conversiones, `page_count=279`, **276 páginas con texto**,
**427,008 caracteres Markdown**, 422,375 caracteres nativos y 4,633 de
encabezados/separadores. Igualdad exacta página por página y del Markdown
completo; ninguna página distinta, ningún cambio de orden ni pérdida de texto.
Principio/final coinciden con la portada de Scrum y «Fuente: Elaboración propia.».
SHA común:
`c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc`.
El PDF grande no devolvió bloques no textuales en estas llamadas. También se
validó con un PDF mínimo que una página de imagen conserva su encabezado sin
OCR/metadatos, así como letra pequeña, caracteres Markdown literales y orden.
No se afirma equivalencia semántica de tablas/columnas ni de imágenes.

Después de medir se adoptó blocks en `app.markdown.to_markdown`; se conserva
`to_text_markdown` como referencia offline. Se pasó a **`extract:v4:<sha-PDF>`**
para versionar el motor. Antes del cambio se comprobó la clave v3 existente
(PTTL 2321570 ms, valor 454366 bytes); v4 no existía. No se borró ni sobrescribió
v3. Después del ensayo ambas claves seguían presentes con contenido/SHA idéntico.

### Preparación del HOT

Se construyó la imagen y recrearon sólo las APIs; Redis y Traefik conservaron
sus contenedores. Imagen ensayada:
`sha256:e1f07e8c52fe4b8c0468cdf6333a3ec1b23ee23733d27d866b0ab8f8eddf2406`.
Las cinco estaban healthy, caché habilitada y sin puertos directos publicados.
PING READY de réplicas 1–5: **26.728 / 94.195 / 73.254 / 65.467 / 80.312 ms**.
No hubo errores de warm-up en este arranque.

Precarga v4: **HTTP 200 / MISS / 279 / SHA correcto**, 4368.410 ms HTTP.
Algoritmo CPU 910.388 ms, worker total 3665.522 ms, cuerpo 212.017 ms,
GET Redis 3.814 ms. Incluye el primer spawn del trabajador y efectos de arranque;
**no es un HIT ni una estimación de extracción caliente de 4.4 s**.
Se confirmó EXISTS=1, PTTL=3587537 ms y STRLEN=454366 de la clave v4.
Después, una petición de validación independiente dio **HIT 289.542 ms**.
La precarga terminó k6 con 99 por umbral de latencia, con 5/5 checks funcionales
correctos. La validación HIT pasó todos los checks y el umbral.

### K6 HOT CACHE: progresión y detención

Cada respuesta comprueba HTTP 200, **X-Cache==HIT**, `page_count==279`, contenido
string y SHA idéntico. El script aborta ante una respuesta inválida; los runners
comprueban salud/estado/OOM y guardan los recursos. Se usó timeout HTTP de **5 s**
y el mismo deadline Redis de 200 ms. No se agregaron pausas deliberadas entre
iteraciones ni peticiones auxiliares continuas de health.

| Etapa | Iteraciones totales | p50, ms | p90, ms | p95, ms | Máximo, ms | http_req_failed | Checks | Iteraciones/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **1 VU** | 20 | **248.096** | 317.012 | **384.775** | 426.581 | **0 %** | **100/100** | **3.643** |
| **2 VUs** | 20 (10 por VU) | **437.756** | 543.846 | **544.650** | 551.875 | **0 %** | **100/100** | **4.141** |
| **5 VUs** | No ejecutada (previsto 25, 5 por VU) | — | — | — | — | No verificado | No verificado | — |

Mínimos: 1 VU 210.420 ms, 2 VUs 332.895 ms. Cero errores lógicos en ambas
etapas, sin MISS, BYPASS ni ERROR entre las **40 peticiones HOT medidas**.
Todas tenían el mismo SHA/279/427008. Los perfiles confirman extracción **0 ms**
y ausencia de trabajo CPU (`worker_ms` no presente) en cada HIT. No se mezclaron
precarga/validación con estas distribuciones. Percentiles calculados por k6
sobre cada grupo completo de veinte; no se eliminaron muestras lentas.

La etapa 1 pasó p95<400 y cero errores, habilitando la etapa 2. Su máximo
426.581 ms recuerda que p95<400 **no implica todas las peticiones<400**.
La etapa 2 falló el umbral (k6 exit 99), sin errores funcionales. Se detuvo la
escalada por p95>=400 y **no se ejecutaron 5 VUs**, 100 VUs ni una repetición
para buscar una corrida más favorable. No hubo timeout Redis que localizar.

Asignaciones verificadas por X-Audit-Id, profiles y logs Traefik:

| Réplica | HIT en 1 VU | HIT en 2 VUs |
| --- | --- | --- |
| extractor-1 | 5 | 3 |
| extractor-2 | 4 | 4 |
| extractor-3 | 4 | 4 |
| extractor-4 | 3 | 4 |
| extractor-5 | 4 | 5 |

Todas compartieron la misma clave v4 en Redis. No se cambió el balanceo.

### Dónde aumenta el tiempo y recursos

| Mediana de tramo, ms | 1 VU | 2 VUs |
| --- | --- | --- |
| Envío del PDF observado por k6 | 209.817 | 330.610 |
| Lectura del cuerpo en la API | 199.637 | 354.853 |
| SHA-256 PDF | 8.753 | 10.955 |
| GET Redis | 2.088 | 3.591 |
| Decodificación/validación del resultado Redis | 1.700 | 2.159 |
| Response FastAPI | 1.073 | 1.733 |
| Recepción de respuesta observada por k6 | 4.471 | 7.518 |
| Handler total servidor | 214.240 | 373.701 |

No sumar recepción de body al envío k6: se solapan y usan distintos relojes.
GET Redis máximo: 4.149 / 9.787 ms. No hay evidencia para aumentar su timeout:
el aumento de latencia corresponde principalmente al traslado/recepción del
body de 17.75 MB y planificación del recorrido Windows/Docker, no a extracción.
Es una inferencia de estos tramos, sin aislar un componente de red específico.
La serialización sigue siendo pequeña. Throughput creció 3.643→4.141 iter/s al
duplicar concurrencia, mientras la latencia aumentó.

Máximos **muestreados** por extractor: precarga 99.66 % CPU / 317.2 MiB;
HOT 1 VU 34.61 % / 317.2 MiB; HOT 2 VUs 47.07 % / 317.2 MiB.
Sólo dos muestras `docker stats --no-stream` por etapa de veinte; no representan
necesariamente el máximo instantáneo. Todas las APIs, Redis y Traefik siguieron
healthy, sin OOM ni reinicios inesperados. Los límites se mantuvieron y no se
ensayó saturación total de Docker Desktop. No se aplicó ninguna optimización
adicional de red, IPC, JSON ni threads.

### Tests y resultado de esta fase

TDD de migración: añadir namespace anterior v3 dio **RED: 1 failed in 1.61 s**,
pues el motor anterior devolvía HIT de esa clave. Después de blocks/v4, la
migración y el test de páginas/texto/imagen dieron **GREEN: 2 passed in 3.29 s**.
Suite completa **38 passed, 1 skipped in 28.43 s**. Integración Redis real por
Traefik **1 passed, 38 deselected in 12.16 s**, MISS→HIT, contenido idéntico,
TTL 3600 s, PTTL 3599779→3597505 ms. Sólo se limpió su clave UUID de test.
Docker build y despliegue de cinco réplicas completados correctamente.

**A. text: 463.282 ms de mediana. B. blocks: 414.434 ms de mediana.**
**C. Elegido blocks**, por mejora mediana observada de 10.54 %, cuatro pares
ganados y equivalencia exacta del contenido. Su mediana pura todavía no alcanza
400 ms; tampoco la precarga HTTP fría. Una muestra mínima de 376.519 ms no
autoriza declarar cumplida esa meta.

**¿Cache HIT p95<400 con este PDF? NO como objetivo bajo concurrencia:** se
cumplió en 1 VU (**384.775 ms**), falló con 2 (**544.650 ms**) y 5 no se ejecutó.
Es un resultado explícitamente separado de extracción fría. No se agregaron
optimización de threads, nuevo timeout ni más recursos para alterar el resultado.
Estado final local en main, sin commit ni push y con cambios anteriores preservados.

### Repetición controlada desde la raíz del repositorio

Elegir nombres de evidencia nuevos. La comparación actual utiliza el conversor
text anterior explícito; no mide blocks bajo el nombre text tras adoptarlo:

```powershell
$pdf = 'D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf'
New-Item -ItemType Directory -Force tests/stress/results/extractor-blocks-hot-cache | Out-Null
$results = (Resolve-Path tests/stress/results/extractor-blocks-hot-cache).Path
$scripts = (Resolve-Path tests/performance).Path
$sha = 'c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc'
git status --short
Get-Item -LiteralPath $pdf | Select-Object Length
Get-FileHash -LiteralPath $pdf -Algorithm SHA256
uv run --locked pytest -q
docker compose -f compose.yaml -f compose.traefik.yaml build extractor
docker run --rm --cpus 1 --memory 768m --network none --read-only --mount "type=bind,source=$pdf,target=/input.pdf,readonly" --mount "type=bind,source=$scripts,target=/diagnostics,readonly" --mount "type=bind,source=$results,target=/results" --entrypoint /service/.venv/bin/python pdf-extractor-extractor:latest /diagnostics/blocks_path.py --pdf /input.pdf --repeat 5 --output /results/algorithm-next.json
docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=5 --wait --wait-timeout 150
docker compose -f compose.yaml -f compose.traefik.yaml ps
docker stats --no-stream
$key = 'extract:v4:' + (Get-FileHash -LiteralPath $pdf -Algorithm SHA256).Hash.ToLowerInvariant()
$exists = docker compose -f compose.yaml exec -T redis redis-cli EXISTS $key
$expected = if ($exists.Trim() -eq '1') { 'HIT' } else { 'MISS' }
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name hot-preload-next --cache $expected --vus 1 --iterations 1 --sha256 $sha --timeout 30s --results $results
docker compose -f compose.yaml exec -T redis redis-cli EXISTS $key
docker compose -f compose.yaml exec -T redis redis-cli PTTL $key
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name hot-validation-next --cache HIT --vus 1 --iterations 1 --sha256 $sha --timeout 5s --results $results
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name hot-1vu-next --cache HIT --vus 1 --iterations 20 --sha256 $sha --timeout 5s --results $results
```

**Sólo si la etapa anterior pasó p95<400, todos los checks y cero errores:**

```powershell
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name hot-2vu-next --cache HIT --vus 2 --iterations 10 --sha256 $sha --timeout 5s --results $results
# Sólo si 2 VUs también cumple: este comando NO se ejecutó en la fase actual.
uv run --locked python tests/performance/run_k6.py --pdf $pdf --name hot-5vu-next --cache HIT --vus 5 --iterations 5 --sha256 $sha --timeout 5s --results $results
```

`--iterations` es **por VU**: 2×10=20, 5×5=25 totales. Detener ante MISS,
BYPASS, ERROR, errores, OOM/unhealthy, tiempos inesperadamente largos o umbral
fallido; no ejecutar los comandos siguientes automáticamente ni reintentar.
No borrar la clave para forzar MISS: una precarga existente puede ser HIT.
Los summaries incluyen checks, errores e iterations/s; 99 por umbral no es
un HTTP fallido, pero impide avanzar. Integración opcional, sin PDF de estrés:

```powershell
$address = docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80
$env:EXTRACTOR_BASE_URL = 'http://localhost:' + ($address -split ':')[-1]
uv run --locked pytest --run-integration -m integration -q -s
Remove-Item Env:EXTRACTOR_BASE_URL
```

## HOT CACHE desde Docker — 7 de octubre de 2026

Se mantuvo intacto el algoritmo blocks y namespace v4. No se ejecutaron Layout,
PyMuPDF4LLM, Vegeta, Spike ni una optimización del PDF de entrada. La prueba
usa el mismo documento externo **17,749,468 bytes / 279 páginas**:
`D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf`.
SHA del archivo sin cambios:
`728c8a522ce24bf0ba3851cd109cdc0e55b200e3cd9b55b8343b39c005713162`.
Evidencia separada en
[`extractor-docker-hot-cache`](../tests/stress/results/extractor-docker-hot-cache/).
Se conservan las fases anteriores; sus cifras no son ejecuciones nuevas.

### Recorrido, entorno y precarga sin borrar el caché existente

Contenedor oficial **grafana/k6:2.2.0**, misma versión que el k6 Windows de la
comparación. Digest instalado:
`sha256:9bd01d6941fca969cb61bb57d2da5ee9b385fe2aa8881df3798c196564d6ace6`.
Cliente limitado a **1 CPU / 512 MiB**, para admitir hasta cinco VUs sin alterar
los recursos de APIs. Cinco extractores de **1 CPU / 768 MiB**, Redis compartido
0.5 CPU / 256 MiB, Traefik v3.6 0.5 CPU / 128 MiB. Docker Desktop: 12 CPU
visibles, **3.509 GiB**; Ryzen 5 4600H, Windows 11, otros proyectos ejecutándose.
Algoritmo/imagen de las APIs sigue siendo
`sha256:e1f07e8c52fe4b8c0468cdf6333a3ec1b23ee23733d27d866b0ab8f8eddf2406`.

El cliente pertenece a **pdf-network** y monta el PDF original en `/input.pdf`
**read-only**, demostrado por `client_inspect.Mounts[].RW=false`. No se copia al
repositorio. `network_hot.js` conserva `Host: localhost` y resuelve ese host a
la IP real del **Traefik del proyecto**; no llama al extractor directamente.
Los access logs verifican router `pdf-markdown-extractor@docker`, origen cliente
`172.19.0.9` (contenedor k6), backend API y X-Audit-Id. El puerto publicado
Windows (`59345`) no forma parte del recorrido del cuerpo dentro de la red.

La clave v4 del PDF ya existía en Redis DB 0. Para conseguir el MISS solicitado
sin borrar datos se verificó **DB 15 vacía (DBSIZE=0)** y se usó temporalmente
`compose.cache-benchmark.yaml`: sólo cambia REDIS_URL de las cinco APIs a
`redis://redis:6379/15`. Es el **mismo servidor Redis compartido**, distinto DB
lógico de diagnóstico; no se vació ni reinició Redis, ni se modificó su timeout
de 200 ms, algoritmo, etiquetas Traefik o recursos. Al terminar se omitió el
overlay y todas volvieron a DB 0. DB 15 conserva su única clave hasta el TTL;
no se hizo DEL/FLUSHDB/FLUSHALL. Para repetir, elegir otro DB vacío o esperar
caducidad, sin borrar datos existentes.

Las cinco estaban healthy antes de comenzar. PING READY de réplicas 1–5:
**134.067 / 190.321 / 95.482 / 114.232 / 81.097 ms**.
Precarga: **HTTP 200 / MISS / 279 / SHA correcto**, HTTP **5629.214 ms**.
Perfil CPU: algoritmo **488.450 ms**, worker total **3093.872 ms** incluyendo
spawn inicial, cuerpo 145.796 ms, handler 3263.843 ms. La diferencia entre HTTP
y handler no fue aislada; no se atribuye toda la demora a extracción. Esta
petición fría queda fuera del HOT y no modifica la mediana offline anterior.
Redis DB 15 confirmó EXISTS=1, PTTL=3587848 ms y STRLEN=454366.

La siguiente petición dio **HTTP 200 / HIT**, **179.998 ms**, 279 páginas,
427,008 caracteres y SHA esperado:
`c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc`.
El primer k6 salió 99 por umbral HTTP, con todos los checks funcionales correctos;
la validación HIT salió 0. No se confundió la precarga fría con el benchmark HOT.

### Etapa medida y detención de la escalada

Una etapa **1 VU / 20 iteraciones totales**, sin pausas deliberadas. Cada
respuesta comprueba HTTP 200, X-Cache HIT, page_count 279, contenido string y
SHA idéntico. Timeout HTTP 5 s, duración de escenario máxima 30 s. El runner
observa salud/OOM y logs de las APIs, deteniendo el cliente ante CACHE MISS,
BYPASS o ERROR. Conserva inspección del cliente, red, montaje y OOM antes de
eliminar sólo ese contenedor temporal.

| Entorno | VUs | Iteraciones | p50, ms | p90, ms | p95, ms | Máximo, ms | Errores HTTP/lógicos | Checks | Iteraciones/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Windows → Traefik, **fase anterior** | 1 | 20 | 248.096 | 317.012 | **384.775** | 426.581 | 0 % | 100/100 | 3.643 |
| Windows → Traefik, **fase anterior** | 2 | 20 | 437.756 | 543.846 | **544.650** | 551.875 | 0 % | 100/100 | 4.141 |
| Docker k6 → Traefik, **fase actual** | 1 | 20 | **89.657** | 576.379 | **675.247** | **1119.765** | **0 %** | **100/100** | **4.462** |
| Docker k6 → Traefik | 2 | No ejecutada | — | — | — | — | No verificado | — | — |
| Docker k6 → Traefik | 5 | No ejecutada | — | — | — | — | No verificado | — | — |

Mínimo interno **46.774 ms**, promedio 209.523 ms. **20/20 HIT correctos**, sin
MISS/ERROR/BYPASS, sin reconversión: todos los profiles registran extracción
0 ms y ausencia de worker_ms. Ningún timeout Redis, OOM o contenedor unhealthy.
Distribución por réplicas 1–5: **4 / 4 / 4 / 3 / 5**; todas recibieron peticiones
por Traefik y compartieron el resultado de DB 15.

**p95=675.247>=400**: k6 salió 99 por latencia; la escalada se detuvo tras esta
etapa. No se ejecutaron 2/5 VUs, una segunda serie para buscar resultados más
favorables, ni 100 VUs. No se excluyeron los primeros HIT lentos del cálculo.
Los p95 de veinte observaciones describen esta serie corta, no una garantía de
servicio para otros momentos/concurrencia.

### Windows/Docker Desktop: qué parte mejora y qué persiste

Comparación de medianas con **1 VU / 20**, mismas API/representación/cuotas:

| Tramo | Windows anterior, ms | Docker actual, ms | Reducción observada |
| --- | --- | --- | --- |
| Envío del PDF visto por k6 | 209.817 | **28.025** | 181.792 ms / 86.6 % |
| receive_body_ms API | 199.637 | **68.386** | 131.251 ms / 65.7 % |
| HTTP completo | 248.096 | **89.657** | 158.439 ms / 63.9 % |
| Handler servidor | 214.240 | **84.520** | 129.720 ms / 60.5 % |
| GET Redis | 2.088 | **2.230** | Sin mejora relevante |

No sumar esas reducciones: envío y recepción de body se solapan. **Hay evidencia
de un coste habitual importante del recorrido Windows → puerto publicado → VM**;
eliminar ese salto redujo las medianas de transporte. No significa que todo el
problema de p95 anterior fuese Windows: el p95 interno **empeoró**. Son sesiones
distintas, no una comparación aleatoria/intercalada: cambió DB lógico y estado
de procesos por reinicio, y el cliente Linux tiene límites de 1 CPU / 512 MiB
frente al proceso Windows sin esa cuota. No se aisló un overhead constante ni
una causa exacta para todos los picos.

Profiles HOT internos: mediana SHA PDF **8.905 ms**, GET **2.230 ms**,
decodificación Redis **2.152 ms**, Response FastAPI **1.322 ms**. Máximos GET
**64.621 ms**, decodificación 20.218 ms, Response 8.010 ms: sin timeouts.

Distribución de fases internas, correlacionadas con las 20 peticiones HOT
(percentiles interpolados sobre esas muestras, en milisegundos):

| Fase API | p50 | p90 | p95 | Máximo |
| --- | --- | --- | --- | --- |
| receive_body_ms | 68.386 | 481.798 | 558.443 | 993.093 |
| Redis GET | 2.230 | 26.083 | 43.793 | 64.621 |

El máximo receive_body fue **993.093 ms**, en extractor-2, audit
`net-1vu-20-1-1`, HTTP **1119.765 ms**. En ese pedido GET tomó 42.697 ms y
Response 7.564 ms. Traefik registró overhead propio 0.103 ms; ese campo no
mide todo el forwarding/esperas de red. El pico principal sigue en recibir el
cuerpo/planificación, pese a eliminar el salto TCP Windows del body.

Las tres primeras peticiones del benchmark, a réplicas 1, 2 y 5, fueron
**651.851 / 1119.765 / 567.993 ms**; luego hubo otros picos, incluido 333.308 ms.
Los procesos acababan de recrearse y sólo había una validación HIT previa,
además del PING de cada pool. La preparación de cada proceso y planificación
de la VM son hipótesis a investigar; no se demostró esa causa ni se alteró el
baseline con un calentamiento adicional después de fallar el umbral.

Recursos muestreados durante HOT: k6 máximo **30.38 % CPU / 133.5 MiB** de
512 MiB; API máximo **55.72 % / 325.4 MiB** de 768 MiB; Traefik 24.04 % /
81.3 MiB; Redis 1.22 % / 9.711 MiB. Cuatro muestras `docker stats --no-stream`,
no máximos instantáneos. No muestran saturación sostenida ni OOM; no descartan
pausas breves. No se capturó presión de CPU/IO/memoria del kernel en el instante
de los picos, por lo que no se atribuye una causa exacta a estos números.

### Gzip y configuración para la entrega

Traefik confirmó **454,366 bytes de JSON** (427,008 caracteres en content),
sin compresión. Recepción de respuesta k6: mediana **0.965 ms**, máximo
**4.897 ms**. No se activó el experimento opcional de gzip: estaba condicionado
a **2 o 5 VUs cerca de 400 ms**, etapas que no se alcanzaron. Tamaño comprimido,
CPU de gzip y cambio de p95 **no medidos**. No se adoptó compresión ni se
comprimió el PDF de entrada. La transferencia de salida observada no explica
el pico de ~993 ms del body.

Para la entrega funcional se recomienda mantener cinco réplicas, Traefik,
`pdf-network`, Redis compartido **DB 0**, cache_enabled=true, namespace v4,
TTL 3600 s y timeout 200 ms, API 1 CPU / 768 MiB, sin gzip añadido. Usar k6
oficial dentro de la red, PDF read-only y este procedimiento controlado para
verificar rendimiento. **No presentar p95<400 como logrado**: con Docker
falló ya en 1 VU, 2/5 quedaron sin verificar. Antes de ampliar carga conviene
investigar/preparar las primeras peticiones por réplica y las pausas de la VM
sin cambiar algoritmo ni ocultar muestras; esta fase no aplicó esa corrección.
Tampoco se evaluó extracción concurrente fría ni el perfil oficial de Spike.

La conexión habitual DB 0 se restauró y las cinco quedaron healthy. DB 0
conservó su resultado v4 de 279/427008/SHA esperado, mientras DB 15 mantuvo su
resultado de prueba hasta TTL; no se reiniciaron Redis/Traefik ni otros proyectos.
No se repitió pytest funcional: no hubo cambios en app/algoritmo ni tests de
API. La última suite permanece documentada como 38 aprobados y 1 integración
aprobada aparte; la verificación nueva son los checks reales de k6 y Compose.
Sin commit ni push, con resultados/cambios anteriores preservados.

Verificación final registrada en `final-verification.json`: de **369 archivos
iniciales**, 367 conservan el mismo SHA; sólo cambiaron este informe y el README
del extractor. App, algoritmo, configuración previa, dependencias/lockfile,
monolito y resultados anteriores permanecen idénticos. Se agregaron tres archivos
para este benchmark: overlay de DB lógico, script k6 y runner Docker. HEAD y
rama main sin cambios, índice vacío; `/health` por Traefik volvió a dar 200.
Redis, ambos Traefik, MongoDB y réplicas del monolito conservaron ID y StartedAt.

### Comandos reproducibles, desde la raíz del repositorio

Elegir una base lógica **vacía** del Redis de este proyecto y nombres nuevos.
DB 15 ya fue usada; el ejemplo propone 14 pero exige comprobarla antes:

```powershell
git status --short
$pdf = 'D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf'
New-Item -ItemType Directory -Force tests/stress/results/extractor-docker-hot-cache | Out-Null
$results = (Resolve-Path tests/stress/results/extractor-docker-hot-cache).Path
$sha = 'c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc'
Get-Item -LiteralPath $pdf | Select-Object Length
Get-FileHash -LiteralPath $pdf -Algorithm SHA256
$hotRedisDb = 14
$size = docker compose -f compose.yaml exec -T redis redis-cli -n $hotRedisDb DBSIZE
if ($size.Trim() -ne '0') { throw 'Elegir otro DB vacío; no borrar datos' }
$env:EXTRACTOR_BENCHMARK_REDIS_DB = "$hotRedisDb"
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.cache-benchmark.yaml config --quiet
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.cache-benchmark.yaml up -d --scale extractor=5 --wait --wait-timeout 150
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.cache-benchmark.yaml ps
uv run --locked python tests/performance/run_network_k6.py --pdf $pdf --results $results --name net-preload-next --cache MISS --vus 1 --iterations-total 1 --sha256 $sha
uv run --locked python tests/performance/run_network_k6.py --pdf $pdf --results $results --name net-validation-next --cache HIT --vus 1 --iterations-total 1 --sha256 $sha
uv run --locked python tests/performance/run_network_k6.py --pdf $pdf --results $results --name net-1vu-next --cache HIT --vus 1 --iterations-total 20 --sha256 $sha
```

**Sólo tras p95<400, 100 % HIT/checks, cero errores y contenedores sanos**:

```powershell
# Estos dos comandos NO se ejecutaron en esta fase por el fallo de 1 VU.
uv run --locked python tests/performance/run_network_k6.py --pdf $pdf --results $results --name net-2vu-next --cache HIT --vus 2 --iterations-total 20 --sha256 $sha
# Sólo si 2 VUs también cumple:
uv run --locked python tests/performance/run_network_k6.py --pdf $pdf --results $results --name net-5vu-next --cache HIT --vus 5 --iterations-total 25 --sha256 $sha
```

Restaurar siempre al terminar, incluso después de errores; omitir el overlay
reconecta DB 0 sin borrar ninguno de los DB:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=5 --wait --wait-timeout 150
Remove-Item Env:EXTRACTOR_BENCHMARK_REDIS_DB
docker compose -f compose.yaml -f compose.traefik.yaml ps
```

## CONFIGURACIÓN RECOMENDADA PARA ENTREGA

Validación final local del **7 de octubre de 2026**. Configuración elegida:
**2 réplicas del extractor**, **1 CPU / 768 MiB por réplica**, Traefik v3.6,
Redis compartido **DB 0**, red externa **pdf-network**. El acceso externo es
por Traefik; las APIs no publican puertos directos en este modo. Algoritmo
blocks, namespace v4, TTL 3600 s, timeout Redis 200 ms e imagen API sin cambios.
No se modificaron código, scripts existentes, dependencias, límites, Traefik
ni Redis. No se instalaron paquetes, se hizo commit/push ni se ejecutó Vegeta
o Spike. En esta fase sólo se actualiza este informe y se guardan evidencias.

### Por qué dos réplicas

La comparación anterior usó **1 VU / 30 peticiones**, después de 20 peticiones
de calentamiento en cada configuración. Estas cifras pertenecen a esa fase,
no se mezclan con las nuevas corridas:

| Réplicas API | p50 HTTP, ms | p95 HTTP, ms | Máximo, ms | Errores | Reparto medido |
| --- | --- | --- | --- | --- | --- |
| **2** | 85.067 | **138.597** | 158.621 | 0 % | 15 / 15 |
| 3 | 79.452 | 153.578 | 197.946 | 0 % | 10 / 9 / 11 |
| 5 | 62.715 | 206.936 | 267.673 | 0 % | 6 por réplica |

Dos obtuvo el menor p95 y demuestra balanceo real, con menos consumo agregado
de memoria que tres/cinco. Cinco mejoró la mediana, pero empeoró el p95 en esa
serie. El orden fijo y una corrida por cantidad no prueban una causa exclusiva
de esa diferencia. Evidencia de la comparación:
[`extractor-replica-variability`](../tests/stress/results/extractor-replica-variability/).

### Documento, cliente y preparación de las corridas finales

Documento original externo, sin copiarlo ni modificarlo:
`D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf`.
**17,749,468 bytes / 279 páginas** confirmados antes de medir; SHA del PDF:
`728c8a522ce24bf0ba3851cd109cdc0e55b200e3cd9b55b8343b39c005713162`.
Markdown esperado **427,008 caracteres**, SHA:
`c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc`.

Cliente oficial **grafana/k6:2.2.0**, Linux amd64, **1 CPU / 512 MiB** como en
la fase anterior. PDF montado read-only; recorrido **k6 dentro de pdf-network
→ Traefik → API → Redis**. El cliente conserva Host localhost, resuelto a la IP
del Traefik del proyecto. Puerto externo observado: `127.0.0.1:59345`; el body
del benchmark no pasa por ese puerto Windows. Docker Desktop: 12 CPU visibles,
3.509 GiB; Ryzen 5 4600H, Windows 11 y otros servicios del equipo activos.

Las dos APIs, Redis y Traefik estaban healthy antes de iniciar. La clave del
PDF ya existía en DB 0: no hubo precarga MISS del PDF real ni cambios de DB,
DEL/FLUSH o reinicio de servicios para esta medición. Antes de **cada** nueva
corrida de 1 VU se ejecutaron **20 peticiones de calentamiento excluidas del
benchmark**, todas HIT correctos y reparto **10/10**. La primera serie de
calentamiento incluyó un máximo de 2349.018 ms: HIT por sí solo no garantiza
latencia baja sin la preparación requerida. Ninguna petición medida se excluyó.

Los scripts existentes quedan intactos. Una configuración efímera enviada por
stdin a k6 conserva los checks/umbrales de common.js y agrega el check explícito
de longitud. Cada respuesta comprueba **HTTP 200, HIT, page_count 279, content
string, 427008 caracteres y SHA esperado**. Escenario per-vu-iterations:
1×30, 2×15 o 5×6, siempre **30 iteraciones totales por corrida**. Timeout HTTP
5 s, escenario máximo 2 minutos, umbral **p(95)<400**. El runner supervisa
salud, OOM, logs de caché y reconversión; la escalada requiere que la etapa
anterior cumpla todos los checks y el umbral.

### Resultados finales, sin promediar ni mezclar corridas

Tiempos HTTP de k6 en milisegundos: envío + espera + recepción, excluyendo
establecimiento de conexión. Son latencias de POST /extract en **HOT CACHE**,
no tiempo puro del algoritmo de extracción.

| Corrida | VUs | Total | p50 | p90 | p95 | Máximo | Errores HTTP/lógicos | Checks | Reparto API 1/2 | Iteraciones/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| final-1vu-r1 | 1 | 30 | 84.981 | 123.896 | **126.533** | 135.384 | 0 % | 180/180 | 15 / 15 | 8.749 |
| final-1vu-r2 | 1 | 30 | 85.208 | 126.927 | **143.416** | 174.147 | 0 % | 180/180 | 15 / 15 | 7.930 |
| final-2vu | 2 | 30 | 152.420 | 201.752 | **213.672** | 237.345 | 0 % | 180/180 | 15 / 15 | 10.744 |
| final-5vu | 5 | 30 | 376.898 | 910.096 | **1197.476** | 1258.952 | 0 % | 180/180 | 15 / 15 | 8.342 |

**120/120 respuestas medidas HIT correctos**, 720/720 checks; ambas APIs
recibieron tráfico en cada corrida, demostrado por access logs de Traefik y
X-Audit-Id correlacionado con PROFILE de la API. Todas las extracciones fueron
0 ms, sin worker_ms, MISS, ERROR, BYPASS o reconversión durante el benchmark.
Tampoco hubo OOM, reinicios ni pérdida de salud observados.

Las dos repeticiones de 1 VU pasaron, habilitando 2 VUs; esa corrida también
pasó, habilitando 5 VUs. **Con 5 VUs falló el umbral**, exit k6 **99** por
latencia, aunque los checks funcionales fueron correctos. Se detuvo la escalada:
no se repitió esa corrida para buscar un resultado favorable ni se añadió carga.

| Corrida | receive_body p50, ms | receive_body p95, ms | Redis GET p50, ms | Redis GET p95, ms |
| --- | --- | --- | --- | --- |
| final-1vu-r1 | 56.828 | 93.203 | 1.844 | 3.829 |
| final-1vu-r2 | 57.011 | 105.718 | 1.837 | 5.626 |
| final-2vu | 105.136 | 165.036 | 2.139 | 3.933 |
| final-5vu | 267.268 | **1088.487** | 2.354 | **9.894** |

En 5 VUs domina leer el body, no el GET de Redis. Ese intervalo incluye esperas
del cliente, proxy, protocolo HTTP y planificación de la app; no es una medida
aislada de la red ni se suma a sending porque se solapan. No se atribuye una
causa exacta sin medirla por petición.

### Recursos y límites de la conclusión

Tres muestras docker stats por corrida, más contadores cgroup/PSI antes/después.
Los máximos siguientes son muestreados, no picos continuos:

| Corrida | API CPU máxima | API RAM máxima | k6 CPU máxima | k6 RAM máxima | Traefik CPU máxima |
| --- | --- | --- | --- | --- | --- |
| final-1vu-r1 | 69.03 % | 317.6 MiB | 80.56 % | 145.4 MiB | 44.79 % |
| final-1vu-r2 | 36.29 % | 317.5 MiB | 80.20 % | 137.9 MiB | 49.72 % |
| final-2vu | 43.08 % | 317.2 MiB | 82.15 % | 217.0 MiB | 47.74 % |
| final-5vu | 47.19 % | 329.2 MiB | 82.54 % | **436.4 MiB** de 512 | 48.55 % |

PSI CPU some de VM pasó de **4.03/2.82 %** en las repeticiones de 1 VU a
**7.35 %** con 2 y **12.55 %** con 5, en ventanas que abarcan benchmark y
telemetría. Hubo throttling puntual de APIs; no se capturaron contadores de cuota
del cliente/proxy por request, por lo que no se los señala como causa demostrada.
PSI de memoria fue prácticamente cero, sin eventos memory high/max/OOM; hubo
0/2/0/2 páginas swap-in y cero swap-out en esas ventanas globales de VM. No hay
evidencia de presión activa importante de RAM, aunque k6 se acercó a su límite
en 5 VUs. Los recursos se mantuvieron; no se aplicó optimización alguna.

Uvicorn sigue usando **h11 + asyncio**, sin httptools/uvloop instalados. Redis
mantiene la conexión/pool por proceso y almacena el mismo resultado para ambas
APIs. Esta prueba corta no garantiza estabilidad prolongada, otros PDFs, un
generador con otros recursos o concurrencia mayor.

### CACHE HIT frente a CACHE MISS

**HIT:** cada POST todavía sube los **17.75 MB** del PDF, la app recibe el body
y calcula su SHA antes de consultar Redis. Recupera/decodifica el Markdown y
devuelve JSON, sin ejecutar el algoritmo. **HOT CACHE p95<400 ms queda
confirmado en las dos repeticiones de 1 VU y en la corrida controlada de 2 VUs**.
**No se cumple con 5 VUs** en las condiciones medidas.

**MISS:** además de recibir/checksum, ejecuta extracción blocks en el worker y
almacena el resultado con TTL. Este benchmark final no mide esa extracción fría.
**No se afirma que la extracción fría del PDF de 279 páginas cumpla 400 ms**:
la última medición real fría de la fase previa fue 12311.713 ms HTTP (algoritmo
757.249 ms), separada del HOT. La mediana offline de otra fase, 414.434 ms,
tampoco es una garantía HTTP ni queda reemplazada por una latencia HIT.

### Tests finales, estado y comandos

Después del benchmark, desde la raíz del repositorio:

- `uv run --locked pytest -v`: **38 passed, 1 skipped in 37.51s**, exit 0.
  El skip es la integración opt-in, ejecutada inmediatamente después.
- `uv run --locked pytest --run-integration -m integration -v -s`:
  **1 passed, 38 deselected in 17.79s**, exit 0, por Traefik hacia Redis real.
  Validó MISS→HIT, resultado idéntico, PDF generado de dos páginas y TTL 3600 s:
  PTTL **3599601→3596518 ms**. Sólo crea/elimina su clave UUID de test; conserva
  la clave del PDF obligatorio y todos los datos previos.
- Entorno de esos comandos: **UV_NO_SYNC=true, UV_OFFLINE=true** para usar la
  .venv existente sin instalar dependencias; Python local 3.12.2, pytest 9.1.1.

Dejar para entregar **dos réplicas**, Redis compartido DB 0, Traefik y recursos
originales. No ofrecer p95<400 para 5 VUs ni para MISS. El procedimiento incluye
calentamiento explícito y la medición de HIT separada de extracción real.

```powershell
# Desde la raíz del repositorio; no construir ni cambiar recursos.
docker compose -f compose.yaml -f compose.traefik.yaml up -d --no-build --scale extractor=2 --wait --wait-timeout 150
docker compose ps
# Equivalente sin instalar paquetes, usando la .venv ya preparada:
uv run --locked --no-sync --offline pytest -v
$address = docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80
$env:EXTRACTOR_BASE_URL = 'http://localhost:' + ($address -split ':')[-1]
uv run --locked --no-sync --offline pytest --run-integration -m integration -v -s
Remove-Item Env:EXTRACTOR_BASE_URL
```

Las APIs ya estaban levantadas, por lo que durante esta fase no fue necesario
recrearlas ni ejecutar up; ps y la inspección efectiva verifican la cantidad,
salud, límites y configuración. El comando up anterior es para iniciar/repetir.

Evidencia nueva en
[`extractor-final-validation`](../tests/stress/results/extractor-final-validation/):
`validation.json`, logs/summary por corrida, perfiles API, access logs Traefik,
recursos, comandos/variables y script efímero por stdin en `*.execution.json`,
logs completos de pytest e integración. Los resultados previos permanecen
intactos; cada corrida se conserva por separado, sin un promedio combinado.

Verificación final en `final-verification.json` y `compose-ps.log`: **las dos
APIs, Redis y Traefik healthy**, `/health` por Traefik HTTP 200; sus ID,
StartedAt, imágenes y límites sin cambios. Los servicios del monolito y MongoDB
también conservaron ID/StartedAt y recursos. De **482 archivos iniciales**, sólo
cambió `docs/performance.md`; los otros **481** conservan el mismo SHA. Rama
main, HEAD e índice sin cambios; PDF externo intacto. La clave original DB 0
sigue conteniendo 279/427008/SHA esperado, PTTL **2263945 ms** al verificar.
Clientes k6 temporales eliminados después de guardar su inspección.
