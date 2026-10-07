# Rendimiento del microservicio extractor: estado final de entrega

Este resumen presenta primero el **estado final de la entrega**, con las
mediciones ya realizadas el 7 de octubre de 2026. Las fases de investigación
y sus resultados históricos se conservan íntegros más abajo. No se mezclan
extracción fría, CACHE HIT, extracción offline y cargas oficiales.

## Configuración final

- **2 réplicas del extractor**, cada una con **1 CPU / 768 MiB**.
- **Redis compartido**, DB 0 en funcionamiento normal; las cargas oficiales
  empezaron con una DB de benchmark vacía y después se restauró DB 0.
- **Traefik: 0.5 CPU / 512 MiB**. Las peticiones pasan por Traefik, no por una
  réplica directa.
- Red externa **`pdf-network`**, compartida intencionalmente por los
  microservicios independientes. Si no existe, se crea una sola vez antes
  de Compose; el arranque reproducible está en [README](../README.md#arranque-de-la-configuración-de-entrega).
- Cuatro PDFs oficiales externos, sin copiarlos al repositorio. Carpeta
  configurable; en estas corridas: `D:\INGENIERIA\3er\desarrollo de software\`:

  1. `2020-Scrum-Guide-Spanish-Latin-South-American.pdf`
  2. `scrum_manager_historias_usuario.pdf`
  3. `Essential-Kanban-Condensed-Spanish.pdf`
  4. `Filosofia Lean.pdf`

`pdf279hojas.pdf` no participa en las cargas oficiales de cuatro PDFs: se
reserva para los experimentos especiales de 279 páginas.

## Resultado final k6 oficial

**Spike completo** desde k6 nativo Windows: **0→100 VUs en 10 s**, **100 VUs
por 20 s**, **100→0 VUs en 10 s**. Inicio **COLD CACHE**, sin precarga.

| Métrica | Resultado final |
|---|---:|
| Duración registrada | **40,121 s** (40 s nominales) |
| Requests iniciadas | **279** |
| Respuestas HTTP completas | **179** |
| Req/s del resumen HTTP | **4,46** |
| HTTP 200 | **139** |
| HTTP 503 | **39** |
| HTTP 502 | **1** |
| `http_req_failed` | **22,35 %** |
| p50 | **5,106 s** |
| p90 | **17,901 s** |
| p95 | **19,959 s** |
| Máximo | **33,602 s** |
| Iteraciones interrumpidas por cierre sin gracia | **100** |

Las 100 interrumpidas no entran en las 179 respuestas ni en sus percentiles
o en el denominador de `http_req_failed`. Se completó el perfil sin OOM del
generador; el exit 99 corresponde a thresholds fallidos. **NO se superó al
profesor ni se cumplió p95 < 400 ms**. El inicio frío dio paso a respuestas
MISS/HIT; el resumen no representa extracción pura sin caché.

Detalle, comparación y comandos: [K6 SPIKE OFICIAL NATIVO WINDOWS](#k6-spike-oficial-nativo-windows-40-s-completos).
Evidencia: `tests/stress/results/official-k6-spike-windows-20261007-cold/`.

## Resultado final Vegeta oficial

Perfil completo **50 req/s × 30 s**, timeout **30 s**, rotando los cuatro
PDFs oficiales. **COLD CACHE al inicio**, con **1500 solicitudes**.

| Métrica | Resultado final |
|---|---:|
| Success | **0 %** |
| Respuestas HTTP 503 completas | **67** |
| Timeouts | **1282** |
| Otros errores de conexión | **151** |
| p50 | **30005,397 ms** |
| p95 | **30015,049 ms** |
| OOM con Traefik 512 MiB | **No** |

**NO se superó al profesor**. Las categorías suman las 1500 solicitudes;
los percentiles incluyen errores y timeouts, no extracción exitosa ni HIT.
El timeout de peticiones pendientes prolongó la ejecución después de la
ventana nominal de 30 s; no se confunde esa espera con el perfil configurado.

Detalle, comparación y comandos: [Vegeta oficial repetida: Traefik 512 MiB](#vegeta-oficial-repetida-traefik-512-mib).
Evidencia: `tests/stress/results/official-vegeta-20261007-traefik512-cold/`.

## CACHE caliente: resultado separado

Mediciones previas HOT CACHE del PDF especial de **279 páginas**, con dos
réplicas y 30 iteraciones por corrida. Se mantienen como resultados de esa
fase, bajo sus condiciones originales; no son nuevas mediciones posteriores
al Spike o a Vegeta.

| VUs | p95 HTTP HOT CACHE |
|---|---:|
| 1, primera corrida | **126,5 ms** |
| 1, segunda corrida | **143,4 ms** |
| 2 | **213,7 ms** |
| 5 | **1197,5 ms** |

**CACHE HIT != extracción fría.** HIT devuelve Markdown desde Redis, aunque
cada POST todavía transmite el PDF y calcula su checksum. Estas corridas
cumplieron p95 < 400 ms con 1 y 2 VUs; no con 5 VUs. No prueban cumplimiento
en frío ni en las cargas oficiales.

Detalle histórico: [CONFIGURACIÓN RECOMENDADA PARA ENTREGA](#configuración-recomendada-para-entrega),
la validación HOT de esa fase; las cifras originales completas se conservan.

## Extracción pura: resultado separado

Para el PDF especial `pdf279hojas.pdf`, PyMuPDF **blocks** obtuvo una mediana
**~414 ms (414,434 ms)** en la comparación offline registrada. Mide el tramo
de extracción offline, no el HTTP completo ni Redis. No demuestra que la
extracción fría por Traefik cumpla 400 ms. Las muestras originales y sus
condiciones permanecen en la fase de comparación text/blocks.

## Tests finales registrados

**Suite completa: 40 passed, 1 skipped** (38 tests funcionales/de aplicación
más 2 de herramientas/reportes). **Integración Redis real, ejecutada aparte:
1 passed**, con MISS→HIT, contenido y TTL verificados. Son los resultados ya
guardados; esta actualización de documentación no ejecuta tests ni cargas.

## Orientación y lectura del historial

Para el estado final, consultar primero las secciones k6 y Vegeta enlazadas
arriba. La sección histórica **CONFIGURACIÓN RECOMENDADA PARA ENTREGA**
corresponde a la validación HOT del PDF de 279 páginas; no reemplaza los
resultados oficiales posteriores. Las fases previas conservan sus cifras,
recomendaciones y afirmaciones sobre lo ejecutado en cada etapa.

**Uso como repositorio independiente:** `pdf-extractor-service/` ya es la raíz
del microservicio. Todos los comandos reproducibles de este documento se
ejecutan desde esa raíz, sin entrar en otra subcarpeta. El historial describe
experimentos del repositorio original `pdf-extactext`, anteriores a la migración;
no se presentan como mediciones nuevas del repositorio standalone.
Las rutas de evidencia describen los artefactos históricos y no presuponen que
se hayan incluido en esta copia. Sus menciones a archivos ignorados por Git
corresponden a la configuración original. Los runners oficiales actuales guardan resultados
en carpetas locales de `tests/stress/results/`. El runner histórico
`run_k6.py` conserva el directorio por defecto de la estructura anterior:
sus ejemplos pasan explícitamente `--results` para que esa ejecución no
dependa de la ubicación antigua.

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

## Spike preparado en la fase inicial (referencia histórica)

El comando con un PDF que sigue se conserva como registro de la preparación
inicial. Para el Spike actual de cuatro PDFs, usar `run_official_spike.py --k6 <ruta-k6.exe>`
y la sección **K6 SPIKE OFICIAL NATIVO WINDOWS** al final de este documento.

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


## Vegeta oficial: cuatro PDFs externos, inicio frío y aborto por OOM

### Alcance y condiciones reales

Corrida local del **7 de octubre de 2026**, nombre
`official-vegeta-20261007-cold`; inicio **11:47:30 Argentina / 14:47:30 UTC**.
Se ejecutó una única carga. No se repitió para obtener un resultado favorable.

- Repositorio standalone `pdf-extractor-service`, rama `main`, HEAD
  `4569ea6983dc771e729f513bce9b84b2b6216340`; comenzó limpio.
- Vegeta **v12.13.0**, commit `507c4f028fbad80168f3b734dab9530d3aabfefa`,
  Go 1.22.12 Windows amd64, binario existente fuera de PATH.
- Windows 11, Ryzen 5 4600H, 6 núcleos / 12 hilos. Docker Engine **29.7.2**,
  Compose **5.5.1**, 12 CPU visibles, **3,767,750,656 bytes / 3.509 GiB** de RAM.
  Los otros servicios del equipo continuaron funcionando; host compartido.
- **Vegeta Windows → Traefik → dos APIs → Redis compartido**, red externa
  `pdf-network`. Puerto de la corrida: **127.0.0.1:59345**, Host `localhost`.
  El generador no corrió dentro de Docker; no tiene un límite cgroup de cliente.
- Recursos sin cambios: API **1 CPU / 768 MiB** cada una, Traefik
  **0.5 CPU / 128 MiB**, Redis **0.5 CPU / 256 MiB**, maxmemory 192 MiB.
- Misma imagen API, algoritmo blocks, namespace v4, TTL **3600 s** y timeout
  de Redis **200 ms**. Sin cambios de código del extractor, Compose ni dependencias.

### Los cuatro PDFs verificados

Ubicación externa de esta corrida: `D:\INGENIERIA\3er\desarrollo de software\`.
El primer nombre se obtuvo desde el filesystem, sin completar visualmente un
nombre truncado. Los **cuatro SHA-256 del archivo son distintos**.

| Nombre exacto | Bytes | page_count | SHA-256 del PDF |
| --- | ---: | ---: | --- |
| `2020-Scrum-Guide-Spanish-Latin-South-American.pdf` | 319,343 | 16 | `6bbff3f361e52016cbb75a72671f1b31b5e043fdc1cc3f022f1b15a32795a256` |
| `scrum_manager_historias_usuario.pdf` | 3,830,899 | 62 | `30efd6fcd0c022665676edcf164feb28e6b43dcce53ab9738550b99d70f5fd84` |
| `Essential-Kanban-Condensed-Spanish.pdf` | 8,901,466 | 90 | `257f73b908420ac5c78852fb8673beb683a8ca0c05d2e6a82b5e9629f6ad7be8` |
| `Filosofia Lean.pdf` | 668,142 | 42 | `c77b55bd68477ecc0d96074ea4606bffe5802a1c8a241a725f6eb358be17ce40` |

Rutas completas comprobadas:

- `D:\INGENIERIA\3er\desarrollo de software\2020-Scrum-Guide-Spanish-Latin-South-American.pdf`
- `D:\INGENIERIA\3er\desarrollo de software\scrum_manager_historias_usuario.pdf`
- `D:\INGENIERIA\3er\desarrollo de software\Essential-Kanban-Condensed-Spanish.pdf`
- `D:\INGENIERIA\3er\desarrollo de software\Filosofia Lean.pdf`

No se copiaron, generaron, recortaron ni comprimieron PDFs. `pdf279hojas.pdf`
**no forma parte de esta prueba oficial**. El Kanban oficial de 90 páginas
es este archivo de 8,901,466 bytes: no se sustituye por el PDF de 90 páginas
utilizado en los experimentos históricos del monorepo.

Referencia offline del conversor vigente, excluida del tiempo HTTP:

| PDF | Caracteres Markdown | SHA-256 del contenido UTF-8 |
| --- | ---: | --- |
| `2020-Scrum-Guide-Spanish-Latin-South-American.pdf` | 35,783 | `74bab3f4235b5b87f72e3cf09e4bc849026049d855002b2b2dde5a29c6d8b4c1` |
| `scrum_manager_historias_usuario.pdf` | 90,183 | `873a7f73e3877ebd0367b9a23fffc95823d0bffd98f3e219e6f0f9ed2e252e35` |
| `Essential-Kanban-Condensed-Spanish.pdf` | 125,909 | `1a9b530049012b86d0777fdfd886b4acc4a1381360ee7553808da728d2d577f5` |
| `Filosofia Lean.pdf` | 59,181 | `ea727a442fdaccc8d8f00b7a34ba5bed6b1f0017e91a41e22eb4657e55d81c6a` |

Los metadatos completos están en `pdfs.json`. El runner verifica firma, ausencia
de contraseña, páginas, unicidad de archivos y hashes; el informe comprueba
contrato JSON, páginas, longitud y SHA de cada respuesta HTTP 200 que haya.
**En esta corrida no hubo respuestas HTTP 200, por lo que no se validó contenido
HTTP del set oficial bajo carga**. Estos hashes son referencias offline.

### Preparación, caché y balanceo

Redis **DB 15** tenía **DBSIZE=0** antes de iniciar. El overlay existente
`compose.cache-benchmark.yaml` se aplicó sólo al servicio extractor con
`--no-deps --no-build --scale extractor=2`, sin recrear Redis ni Traefik.
Las APIs fueron recreadas para cambiar temporalmente REDIS_URL a DB 15; sus
trabajadores también comenzaron nuevos. No hubo precarga ni POST previo.

Las dos APIs, Redis y Traefik estaban healthy. Se enviaron **seis GET /health**
por Traefik, todos 200, excluidos de Vegeta. Los access logs con X-Audit-Id
confirmaron reparto **3/3** antes de cargar. Health no calienta la conversión.

La condición inicial fue **COLD CACHE**, con trabajadores nuevos. Si hubieran
aparecido resultados cacheados, las siguientes peticiones habrían medido HIT;
no se rotula toda una corrida fría como extracción real de cada petición.
Las respuestas observadas no incluyeron X-Cache: **ABSENT=687**. No hubo
MISS/HIT/ERROR **observables en headers**, ni resultados exitosos para asignar
esos estados. No se deducen HIT a partir de la latencia ni de Redis saludable.

Después se encontró una clave en DB 15 correspondiente a Scrum Guide, con
16 páginas, 35,783 caracteres y SHA Markdown coincidente; eso sólo prueba que
un trabajo del servidor dejó un resultado, no que el cliente recibió HTTP 200
ni que hubo HIT. DB 0 estaba vacía al iniciar y siguió vacía al verificar,
antes y después de la integración (que limpia sólo su propia clave UUID).
No se ejecutó FLUSHDB, FLUSHALL ni DEL contra documentos existentes.
La DB lógica comparte límites y política allkeys-lru con las demás DB del mismo
Redis; no es un servidor de recursos aislados.

### Configuración y comandos reproducibles

El runner usa cuatro targets HTTP y el targeter estático de Vegeta rota en
round robin. Se leen los bytes originales mediante `@ruta completa`; no se
codifica el PDF en Base64. `X-Audit-Id` identifica corrida y documento.
Se mantiene HTTP keep-alive, sin limitar los workers/conexiones de Vegeta.

```powershell
# Desde la raíz de pdf-extractor-service, con el entorno de dos APIs ya healthy.
$pdfDirectory = 'D:\INGENIERIA\3er\desarrollo de software'
$vegeta = 'D:\herramientas\vegeta\vegeta.exe'
& $vegeta -version

# Inspeccionar los archivos y su referencia Markdown, sin enviar peticiones.
uv run --locked --no-sync --offline python tests/performance/vegeta/run.py --pdf-dir $pdfDirectory --vegeta $vegeta --name inspect-official --inspect-only

# Seleccionar una DB lógica vacía. Nunca borrar datos para repetir una corrida.
$benchmarkDb = $null
foreach ($candidateDb in 1..15) {
    $keyCount = docker compose -f compose.yaml -f compose.traefik.yaml exec -T redis redis-cli --raw -n $candidateDb DBSIZE
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar Redis' }
    if ([int]$keyCount -eq 0) { $benchmarkDb = $candidateDb; break }
}
if ($null -eq $benchmarkDb) { throw 'No hay una DB de benchmark vacía; no ejecutar carga' }
$runName = 'official-vegeta-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
uv run --locked --no-sync --offline python tests/performance/vegeta/run.py --pdf-dir $pdfDirectory --vegeta $vegeta --name $runName --redis-db $benchmarkDb
```

**El comando anterior reproduce una carga capaz de causar el OOM observado.**
Se documenta para la entrega; no se ejecutó otra vez tras ese fallo ni se
incrementaron recursos. Para una nueva corrida elegir nombre y DB vacía nuevos.
El runner rechaza DB ocupada, PDFs ausentes/duplicados, resultados preexistentes,
réplicas no saludables o recursos distintos; nunca borra caché para preparar carga.

El comando real del ataque, conservado completo en `execution.json`, incluyó:

```text
D:\herramientas\vegeta\vegeta.exe attack -rate=50/s -duration=30s -timeout=30s -format=http -max-body=-1 -name=official-vegeta-20261007-cold -targets=<ruta-de-evidencia>\targets.http -output=<ruta-de-evidencia>\results.bin
```

La captura completa de respuestas permite medir bytes y conservar X-Cache.
La representación Base64 de los **resultados** que produce `vegeta encode`
se decodifica al analizar; el **PDF enviado** permanece binario. El binario de
resultados se comprime **después** del ataque, verificando el SHA de la versión
descomprimida; sólo se elimina su duplicado nuevo sin comprimir. No se comprime
la entrada ni se excluyen resultados del informe.

Referencias primarias de Vegeta v12.13.0:
[target HTTP y round robin](https://github.com/tsenart/vegeta/blob/v12.13.0/lib/targets.go),
[medición de respuestas](https://github.com/tsenart/vegeta/blob/v12.13.0/lib/attack.go),
[métricas y throughput](https://github.com/tsenart/vegeta/blob/v12.13.0/lib/metrics.go).

### Resultado parcial real frente a la referencia del profesor

**No completó 30 segundos.** La configuración fue 50 req/s × 30 s, timeout 30 s,
pero se abortó por **OOM severo de Traefik**, una de las excepciones autorizadas.
No se abortó por 503, mala latencia ni un umbral de rendimiento.

- Ventana entre primera y última solicitud registrada: **13.710010 s**.
  Duración total de resultados: **13.710608 s**; wall del monitor **14.017470 s**.
- Tasa registrada por Vegeta: **50.109374 req/s**. Es la tasa ofrecida sobre la
  ventana observada; no es throughput exitoso ni garantiza exactamente 50.000.
- **687 registros terminales**, secuencias 0..686 sin huecos. Son solicitudes
  iniciadas y registradas; el aborto no permite certificar un contador adicional
  de operaciones todavía en vuelo. No se alcanzaron aproximadamente 1500.
- **33 respuestas HTTP completas**, todas 503; **654 fallos de transporte**,
  código Vegeta 0. **0 éxitos**, **100 % errores**, **0 timeouts registrados**.
  El ataque fue abortado antes de que transcurrieran los 30 s del timeout;
  cero timeouts aquí no demuestra que todas las peticiones hubieran terminado
  dentro de ese plazo si se hubiera mantenido la carga.

Todas las latencias siguientes incluyen errores; **ninguna mide una extracción
exitosa o CACHE HIT**. La comparación es informativa, con distinta duración.

| Métrica | Nuestro resultado | Profesor |
| --- | --- | --- |
| Requests registradas | 687 (corrida parcial) | 1500 |
| Respuestas HTTP completadas | 33 (todas 503) | No desglosadas |
| Throughput exitoso | 0.000 req/s | 16.65 req/s |
| Success | 0.00 % | 66.53 % (998/1500) |
| Errores | 100.00 %; 33 HTTP 503 + 654 errores de conexión | 501 timeouts; otro resultado no clasificado |
| Timeouts HTTP registrados | 0 | 501 |
| Media | 2153.547 ms | No informada |
| p50 | 976.978 ms | 14890 ms |
| p90 | 5965.882 ms | No informado |
| p95 | 6635.383 ms | No informado |
| p99 | 7683.876 ms | No informado |
| Máximo | 8084.340 ms | No informado |

Fuente de los valores del profesor: **Plan_Microservicios_PDF_Extractext.pdf**,
página 7, apartado 8.2, disponible en la misma carpeta externa de la cátedra.
La fuente resume 998 éxitos y 501 timeouts sobre 1500: suma 1499 y no clasifica
la solicitud restante. El porcentaje se calcula como 998/1500. No se inventan
p90/p95/p99/máximo de Vegeta, ni se usan los valores de k6 del profesor para
completar esas columnas. No se presenta este aborto como benchmark oficial completo.

Vegeta reportó **1,551 bytes in** (media 2.258) y **39,653,598 bytes out**
(media 57,719.939). Divididos por su duración total: **113.124 B/s recibidos** y
**2,892,183.838 B/s enviados**. Son contadores de cuerpos informados por Vegeta:
los fallos de transporte pueden registrar cero aunque se hayan enviado bytes
parciales; no representan todo el tráfico TCP ni incluyen headers.

### Balanceo, memoria y recuperación

Se conservaron **33 access logs completos** durante el ataque: **20** apuntan a
extractor-1 y **13** a extractor-2, todos con estado downstream 503. Confirman
que ambas recibieron tráfico, **no extracción correcta ni reparto verificable
sobre las 687 solicitudes**. El OOM interrumpió las demás; no se completan logs
faltantes con una distribución supuesta. Los logs completos identifican PDF 1
(13), PDF 2 (7) y PDF 4 (13). El target PDF 3 estaba configurado, pero no tuvo
respuesta HTTP completa; el cuerpo/instancia de los 654 fallos queda sin verificar.

Cuatro muestras del proyecto, aproximadamente en t=0.11, 3.78, 7.04 y 11.89 s:

| Contenedor | CPU máxima muestreada | RAM máxima muestreada | Límite |
| --- | ---: | ---: | --- |
| extractor-1 | 102.70 % | 297.6 MiB | 1 CPU / 768 MiB |
| extractor-2 | 101.00 % | 307.4 MiB | 1 CPU / 768 MiB |
| Traefik | 57.16 % | **123.3 MiB** | 0.5 CPU / **128 MiB** |
| Redis | 9.08 % | 7.613 MiB | 0.5 CPU / 256 MiB |

No son picos continuos garantizados. Traefik terminó a **14:47:39.066187 UTC**,
unos **8.12 s** después del primer request, con **OOMKilled=true / ExitCode=137**.
La detección del monitor fue posterior por el muestreo. APIs y Redis no tuvieron
OOM observado. Ambas CPUs de API estuvieron cerca de su cuota; los intervalos
de extracción/worker de la corrida no quedaron disponibles para aislar esa CPU.
La primera falla demostrada que impide completar el perfil es la memoria de
Traefik, no un tiempo medido del algoritmo ni Redis GET.

La caída se recuperó iniciando **el mismo ID de contenedor Traefik**, con
la misma imagen y límites. Docker reasignó su puerto dinámico de **59345 a
64097**. Redis conservó ID y StartedAt; no se tocó configuración. Las APIs
se restauraron a DB 0 y dos réplicas, conservando imagen, entorno normal y
1 CPU / 768 MiB. Tras recuperar: **cuatro contenedores healthy**, seis health
200 por Traefik y reparto posterior **3/3**. No se cambió arquitectura ni se
intentó otra corrida de 50 req/s sobre el mismo límite que falló.

### Tests y evidencia

- `uv run --locked --no-sync --offline pytest -v`:
  **40 passed, 1 skipped in 37.71s**, exit 0; incluye los 38 tests existentes
  y 2 nuevos del informe. Se cubren contabilidad de 503/timeouts/headers nulos,
  validación de contenido, unidades ns→ms y diferencia tasa/throughput.
- `uv run --locked --no-sync --offline pytest --run-integration -m integration -v -s`:
  **1 passed, 40 deselected in 19.28s**, exit 0. Redis real por el Traefik
  recuperado, PDF mínimo único de dos páginas, MISS→HIT, TTL 3600 s;
  PTTL **3599442→3595972 ms**. Limpieza limitada a su clave UUID de integración.

Durante el primer análisis, un header `null` de conexión fallida causó un error
sólo en el lector. El ataque ya había sido abortado por OOM. Se corrigió el
lector y se reconstruyó el informe a partir del **mismo binario**, sin repetir
Vegeta. La restauración automática ya había reemplazado las APIs: **sus logs
volátiles de carga no se recuperaron**. Por eso no hay conteo fiable de intentos
MISS/ERROR ni perfiles internos de esa corrida. Los headers, errores y access
logs Traefik sí están conservados. El runner final guarda los logs antes de
analizar y recupera infraestructura caída sin cambiar configuración; esa ruta
completa revisada **no se volvió a probar con carga** después del OOM.

Evidencia en `tests/stress/results/official-vegeta-20261007-cold/`:
`pdfs.json`, `targets.http`, `environment.json`, `hardware.json`, contenedores
antes/durante/después, `execution.json`, `report.json`, `report.txt`,
`records.jsonl` (metadatos, headers, errores y resultados de validación),
`results.bin.gz`, `raw-artifact.json`, `summary.json`, `traefik-access.jsonl`,
`oom-traefik.json`, `cache-after.json`, `restoration.json`, health logs y logs
pytest/integración. No contiene PDFs ni archivos de preparación sobrantes.

**Conclusión:** los cuatro PDFs y el recorrido por Traefik quedaron preparados,
pero el perfil **50 req/s durante 30 s está pendiente** por OOM del proxy bajo
los límites autorizados. No acredita p95<400 ms ni extracción correcta bajo
esta carga. La recomendación de dos réplicas para HOT k6 permanece como resultado
histórico; esta prueba revela otra condición de carga. El próximo trabajo debe
investigar/resolver la memoria de Traefik antes de repetir el perfil completo,
sin deducir una optimización del algoritmo de estas respuestas fallidas.


## Vegeta oficial repetida: Traefik 512 MiB

### Cambio único y conservación del baseline

Corrida del **7 de octubre de 2026**, nombre
`official-vegeta-20261007-traefik512-cold`; inicio **12:18:58 Argentina /
15:18:58.953787 UTC**. Se ejecutó una sola repetición, completa.
La sección anterior y sus 28 archivos de evidencia permanecen como historial
del fallo con 128 MiB; no se sustituyen sus métricas ni sus resultados.

El único cambio de configuración permanente es `mem_limit: 128m` →
`mem_limit: 512m` en `compose.traefik.yaml`. Lo justifica la evidencia anterior:
**Traefik OOMKilled=true, exit 137, 123.3 MiB / 128 MiB muestreados**. El proxy
murió aproximadamente 8.12 s después del primer pedido; el monitor abortó más
tarde y quedaron 13.710 s de ventana registrada. Aumentar memoria permite
comprobar el perfil completo y no elimina ni oculta ese fallo previo.

`docker compose config --quiet` y la configuración combinada con Traefik
pasaron con exit 0. La comparación de configuraciones resueltas arroja una
sola diferencia: `services.traefik.mem_limit`, **134,217,728 → 536,870,912 bytes**.
`docker inspect` confirmó **512 MiB / 500,000,000 NanoCPUs (0.5 CPU)**.
Se recreó únicamente Traefik para aplicar memoria; puerto dinámico **53701**.

Se conservaron: dos APIs de **1 CPU / 768 MiB** cada una, imagen API
`sha256:e1f07e8c52fe4b8c0468cdf6333a3ec1b23ee23733d27d866b0ab8f8eddf2406`,
algoritmo blocks, worker y backpressure, Redis **0.5 CPU / 256 MiB**,
maxmemory 192 MiB, caché v4, TTL 3600 s, timeout Redis 200 ms y timeout cliente
30 s. No hubo instalación de dependencias ni cambios de código, tests,
Dockerfile, Redis o reglas de Traefik. Docker Desktop siguió con **3.509 GiB**;
las versiones y el host Windows son los del baseline, con otros servicios
funcionando. No se aumentaron recursos de las APIs ni del generador.

### Preparación COLD y recorrido verificado

Mismos **cuatro PDFs oficiales externos**, con los nombres, tamaños, páginas,
SHA de archivo y referencia Markdown de la sección anterior. `pdfs.json` de
ambas corridas coincide; no se copiaron ni modificaron PDFs. No participa
`pdf279hojas.pdf`.

Se verificó **DB 14 vacía, DBSIZE=0**, sin borrar nada. El overlay existente
`compose.cache-benchmark.yaml` cambió temporalmente REDIS_URL de las APIs a
DB 14 y recreó sus trabajadores, igual que en el baseline con DB 15. Redis
conservó ID, StartedAt, imagen y configuración. DB 0 tenía cero claves.
No se precargó ninguno de los cuatro documentos.

Antes del ataque: **cuatro contenedores healthy**, seis GET `/health` por
Traefik con HTTP 200 y cuerpo correcto, balance **3/3** comprobado en logs
con X-Audit-Id. Health no realiza conversión ni precarga de caché.
Ruta: **Vegeta Windows → 127.0.0.1:53701, Host localhost → Traefik → dos APIs
→ Redis compartido**, red externa `pdf-network`; sin puertos directos de API.

Se reutilizaron sin modificaciones los scripts existentes. Los cuatro targets
HTTP siguen rotando uniformemente mediante el targeter estático de Vegeta,
con PDF binario, `Content-Type: application/pdf` y `Accept-Encoding: identity`.
No se cambiaron workers, keep-alive, timeout ni perfil; no se comprimió entrada.
El objetivo de 1500 intentos se cumplió, aunque los fallos de transporte no
permiten certificar entrega completa de cada uno de los cuatro cuerpos.

### Resultado: perfil completo, sin OOM, rendimiento fallido

**¿Se completó Vegeta 50 req/s × 30 s? SÍ.** Configuración exacta
`-rate=50/s -duration=30s -timeout=30s`; exit 0, `aborted=null`.
**1500 solicitudes iniciadas y 1500 resultados terminales**, secuencias
0..1499 sin huecos. Se dejó terminar pese a 503, timeouts y pérdida de salud.

La ventana medida entre primera y última solicitud es **29.9712166 s**;
la tasa ofrecida calculada es **50.0480184 req/s**. El generador mantiene el
perfil nominal de 30 s; el intervalo entre dos requests no equivale al tiempo
de proceso. Después esperó **29.8341105 s** a solicitudes pendientes:
**59.8053271 s totales** en resultados, wall del monitor **61.5578343 s**.
La tasa ofrecida no es throughput exitoso.

| Métrica | Antes: Traefik 128 MiB | Después: Traefik 512 MiB |
| --- | ---: | ---: |
| Perfil configurado | 50 req/s × 30 s, timeout 30 s | Igual |
| Ventana primera–última solicitud | 13.710010 s; abortada | 29.971217 s; completa |
| Espera posterior | 0.000598 s | 29.834111 s |
| Duración total Vegeta | 13.710608 s | 59.805327 s |
| Solicitudes iniciadas / resultados | 687 / 687 | **1500 / 1500** |
| Respuestas HTTP completas | 33 | **67** |
| Throughput exitoso | 0.000 req/s | **0.000 req/s** |
| Success / errores | 0 % / 100 % | **0 % / 100 %** |
| HTTP 200 | 0 | **0** |
| HTTP 503 | 33 | **67** |
| Timeouts registrados | 0, aborto anterior al plazo | **1282** |
| Otros fallos de conexión | 654 | **151** |
| Media | 2153.547 ms | **26160.212 ms** |
| p50 | 976.978 ms | **30005.397 ms** |
| p90 | 5965.882 ms | **30013.531 ms** |
| p95 | 6635.383 ms | **30015.049 ms** |
| p99 | 7683.876 ms | **30017.559 ms** |
| Máximo | 8084.340 ms | **30060.443 ms** |
| Bytes de cuerpos enviados | 39,653,598 | **33,278,713** |
| Bytes de cuerpos recibidos | 1,551 | **3,149** |
| RAM máxima muestreada de Traefik | 123.3 MiB / 128 MiB | **309.2 MiB / 512 MiB** |
| OOMKilled observado | true, exit 137 | **false; sin reinicios** |

Las 1433 respuestas de código Vegeta **0** son fallos de transporte:
**1282 deadline exceeded** esperando headers y **151 connection refused**.
Son categorías separadas, no 1433 errores más 1282 timeouts. Las restantes
67 son HTTP 503 con cuerpo recibido. Todos los 1500 intentos fallaron.
El throughput HTTP completo, incluyendo errores, es **1.120302 req/s**
(67 / 59.8053271); el throughput **exitoso es 0**.

Los percentiles nativos incluyen todos los errores; el p95 ~30 s corresponde
principalmente al timeout. No se interpreta como tiempo del algoritmo,
extracción exitosa o CACHE HIT. Tampoco se concluye que memoria adicional
empeore la extracción comparando percentiles de una carga abortada con una
carga completa que esperó los timeouts. No acredita el objetivo p95<400 ms.

Bytes reportados son cuerpos, no tráfico TCP total: media **22,185.809 bytes
out / 2.099 bytes in**; **556,450.648 B/s out / 52.654 B/s in** sobre la duración
total. En errores de transporte Vegeta puede registrar cero bytes enviados
pese a transmisión parcial; no se infiere que sólo se enviaron 33 MB por red.

La referencia oficial del profesor conservada arriba es 1500 requests,
16.65 req/s exitosos, 998 éxitos (66.53 %), 501 timeouts y p50 14890 ms.
Ahora sí se completó el mismo perfil nominal, pero el resultado de éxito es
inferior: 0 % y 1282 timeouts. Las máquinas y condiciones de caché difieren;
no se inventan percentiles de Vegeta que la fuente no publica.

### Caché, contenido y balanceo observable

**X-Cache ABSENT=1500** en los registros del cliente; ningún HIT/MISS/ERROR
observable en headers. Los 503 no incluyen X-Cache y los fallos de conexión
no tienen headers. No hubo HTTP 200 para validar JSON, páginas, longitud o
SHA bajo carga: **content_validated=0**. La suite e integración posteriores
verifican funcionalidad, pero no reemplazan esta validación bajo 50 req/s.

Se conservaron los logs de API antes de restaurar sus contenedores. Hay seis
perfiles de rutas que construyeron resultados con `status=200, cache=ERROR`,
pero **eso no significa que el cliente recibiera HTTP 200**: todas sus
solicitudes habían superado el timeout. Ninguna de esas seis era HIT.
El conteo interno no se suma a los 67 HTTP completados del cliente.

DB 14 terminó con una clave del Scrum Guide: 16 páginas, 35,783 caracteres y
SHA Markdown idéntico a la referencia. No quedaron claves de los otros tres
PDFs. Eso confirma un resultado almacenado en el servidor, no recepción
exitosa ni HIT. DB 0 estuvo vacía antes, después de restaurar y después de la
integración. No se ejecutó FLUSHDB/FLUSHALL ni se borraron documentos.
La DB 14 conserva su clave hasta el TTL; para repetir seleccionar otra vacía.

Los **107 access logs completos** identificados por X-Audit-Id se repartieron
**56 a extractor-1 / 51 a extractor-2**. Sus estados downstream/origin:
**67 HTTP 503 y 40 estados 499** por clientes desconectados. No se cuentan los
499 como respuestas HTTP recibidas por Vegeta. Los cuatro PDFs aparecen en
los access logs: Guide 45, Historias 18, Kanban 1, Lean 43. Esto demuestra
tráfico en ambas APIs y targets presentes; **no prueba reparto completo ni
contenido correcto sobre los 1500 intentos**, porque faltan logs de la mayoría.

### Recursos y recuperación

**14 muestras** de Docker stats / inspect, sin errores de telemetría ni
OOMKilled en ningún servicio. No hubo eventos Docker OOM desde el arranque
del nuevo proxy hasta la comprobación final. Valores máximos muestreados:

| Contenedor | CPU máxima reportada | RAM máxima reportada | Límite verificado |
| --- | ---: | ---: | --- |
| extractor-1 | 146.28 % | 409.1 MiB | 1 CPU / 768 MiB |
| extractor-2 | 136.02 % | 384.5 MiB | 1 CPU / 768 MiB |
| Traefik | 73.17 % | **309.2 MiB** | **0.5 CPU / 512 MiB** |
| Redis | 66.29 % | 11.54 MiB | 0.5 CPU / 256 MiB |

Son muestras discretas, no máximos continuos garantizados. CPU es el valor
reportado por Docker stats sobre intervalos de muestreo y puede mostrar
picos transitorios por encima de la cuota; **los límites no se aumentaron**.
Traefik llegó a usar más que el límite anterior sin OOM en esta corrida.
No se certifica que 512 MiB cubra toda futura carga.

Al terminar: APIs y Traefik estaban **running pero unhealthy**; Redis siguió
healthy. Sus healthchecks registraron demoras/timeouts durante la carga.
El proxy y Redis recuperaron/retuvieron salud sin reinicios ni recreaciones
adicionales. El runner esperó la infraestructura y recreó sólo las APIs para
restaurar REDIS_URL a DB 0. Imagen, entorno habitual y recursos coinciden con
los previos. `restoration.json`: restaurado=true, infraestructura reiniciada=[],
DB 0=0 claves, DB 14=1 clave. Estado final: **los cuatro healthy, OOMKilled=false**.
Se verificaron seis GET `/health` 200 por Traefik y balance posterior **3/3**.

Los seis perfiles conservados muestran `receive_body_ms` entre **97.476 y
57122.732 ms**, Redis GET entre **106.806 y 1001.437 ms** y algoritmo entre
**289.166 y 1120.618 ms**. Los primeros trabajos tuvieron `worker_ms` de
**48717.461 / 53369.127 ms**, mientras su algoritmo fue **573.342 / 1002.574 ms**.
`worker_ms` incluye la espera del proceso y comunicación, no sólo conversión.
Estos seis perfiles supervivientes no son una distribución de los 1500
intentos ni una prueba de extracción fría <400 ms.

La evidencia sugiere presión de CPU/scheduling, recepción de cuerpos y espera
del worker bajo carga fría; el OOM dejó de ser el fallo observado. El 503
proviene del backpressure existente cuando el worker está ocupado, después
de leer el cuerpo. No se aisló cuánto corresponde a Windows/Docker Desktop,
proxy, arranque del worker o aplicación. Los 151 connection refused no se
atribuyen a OOM sin evidencia. Redis respondió salud, pero hubo errores de
caché internos bajo carga. El siguiente diagnóstico debería aislar esos
tramos antes de proponer otro cambio. **No se aplicaron optimizaciones**.

### Comandos, tests y evidencia nueva

Desde la raíz de `pdf-extractor-service`, con `pdf-network` existente:

```powershell
docker compose config --quiet
docker compose -f compose.yaml -f compose.traefik.yaml config --quiet
# Aplicar solamente el nuevo límite al proxy; APIs y Redis ya estaban healthy.
docker compose -f compose.yaml -f compose.traefik.yaml up -d --no-deps --no-build --wait --wait-timeout 150 traefik
docker inspect pdf-extractor-traefik-1 --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'
docker compose -f compose.yaml -f compose.traefik.yaml ps

# Comando efectivamente ejecutado; esa carpeta y DB ya no deben reutilizarse.
uv run --locked --no-sync --offline python tests/performance/vegeta/run.py --pdf-dir 'D:\INGENIERIA\3er\desarrollo de software' --vegeta 'D:\herramientas\vegeta\vegeta.exe' --name official-vegeta-20261007-traefik512-cold --redis-db 14
```

Para repetir, usar el bloque anterior de selección de DB vacía, un nombre
nuevo como `official-vegeta-<fecha>-traefik512-cold`, y el mismo runner.
Nunca limpiar la DB 0 o una DB ocupada para preparar el benchmark.
`execution.json` conserva el ataque nativo exacto: **50/s, 30s, timeout 30s**.
No se impuso un límite a workers/conexiones ni un abort por percentiles/503.

Pruebas ejecutadas después de restaurar y esperar healthy:

```powershell
# Evitar sincronización/instalación: usar el entorno virtual ya existente.
$env:UV_NO_SYNC = 'true'
$env:UV_OFFLINE = 'true'
uv run --locked pytest -v
$proxyPort = ((docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80).Trim()).Split(':')[-1]
$env:EXTRACTOR_BASE_URL = "http://localhost:$proxyPort"
uv run --locked pytest --run-integration -m integration -v -s
docker compose -f compose.yaml -f compose.traefik.yaml ps
```

- Pytest: **40 passed, 1 skipped in 39.69s**, exit 0; mismos tests existentes.
- Integración Redis real por Traefik: **1 passed, 40 deselected in 20.23s**,
  exit 0; PDF único de dos páginas, HTTP 200, MISS→HIT, contenido idéntico,
  TTL 3600 s; PTTL **3599612→3596614 ms**. Limpia sólo su propia clave UUID.
- Configuración combinada válida y cuatro contenedores finales healthy;
  `docker inspect` conserva 512 MiB para proxy, 768 MiB para cada API.

Evidencia nueva en
`tests/stress/results/official-vegeta-20261007-traefik512-cold/`:
`preflight.json`, metadatos de PDFs/entorno, contenedores iniciales/de benchmark/
tras carga/restaurados/tras tests, targets y comandos, `execution.json`,
`report.json`, `report.txt`, `records.jsonl`, `summary.json`, `results.bin.gz`
(con SHA de su contenido descomprimido), logs completos de Traefik y ambas
APIs, `traefik-access.jsonl`, `profiles.json`, análisis de recursos/caché,
health antes/después, eventos OOM, restauración y logs pytest/integración.
No incluye PDFs. La compresión del binario de resultados ocurrió después de
medir, sin alterar la entrada ni la carga.

**Conclusión:** el criterio inmediato quedó cumplido: **perfil oficial completo,
1500 intentos y sin OOM con Traefik 512 MiB**. El benchmark funcional de carga
sigue fallando (**0 éxitos**), por lo que no acredita mejora de latencia ni
400 ms. Se conservan íntegros los resultados anteriores y los cambios locales.
No se ejecutó k6 Spike ni se cambió otra configuración; no hubo commit ni push.


## Histórico: K6 SPIKE OFICIAL Docker, cuatro PDFs y OOM del generador

### Condiciones y cambios limitados a la prueba

Intento del **7 de octubre de 2026**, resultado de carga
`official-k6-spike-20261007-cold-run2`. El comando del runner comenzó a lanzar
Docker a **13:01:17 Argentina / 16:01:17.240409 UTC**; el evento setup de k6
se registró a **16:01:20 UTC**. Se ejecutó una sola carga con POST. No se
volvió a ejecutar Vegeta ni se aplicó otra optimización.

Se mantuvieron **dos APIs, 1 CPU / 768 MiB cada una**, imagen y algoritmo
vigentes, worker/backpressure, Redis **0.5 CPU / 256 MiB**, caché v4, TTL
3600 s y timeout Redis 200 ms. Traefik siguió con **0.5 CPU / 512 MiB**,
mismo ID/StartedAt, imagen, reglas y puerto dinámico **53701**. Red externa
`pdf-network`. Docker Desktop: 12 CPU visibles y **3.509 GiB**; otros servicios
seguían presentes. No se modificó ningún Compose, Dockerfile, dependencia ni
código del extractor.

Generador: imagen oficial existente **grafana/k6:2.2.0**, commit `00a9a1b7f5`,
Go 1.26.5 Linux amd64, **1 CPU / 512 MiB**, los límites del cliente Docker ya
utilizado. Recorrido **k6 Docker → Traefik → dos extractores → Redis**. La URL
configurable fue `http://localhost/extract`, con `hosts.localhost=172.19.0.5`
(IP interna comprobada de Traefik) y Host localhost. Puerto interno 80 del
proxy; el puerto dinámico 53701 se utilizó para las verificaciones desde
Windows. Las APIs no publicaron puertos directos.

`spike.js` ya tenía el perfil requerido. Su import de `common.js` abortaba
ante un 503 y exigía un estado de caché fijo, por lo que se adaptó **sólo el
Spike**, preservando `common.js`, baseline, HOT y Vegeta. Ahora rota cuatro
PDFs por `iterationInTest % 4`, registra estados/cache/errores y valida páginas,
contenido, longitud y SHA en las respuestas; ninguna validación aborta la carga.
Se conservaron los thresholds originales, incluyendo **p(95)<400 ms**, sin
abortOnFail, y `gracefulRampDown=0s`, `gracefulStop=0s`. El timeout HTTP siguió
siendo el default **180 s** del script Spike anterior; no se sustituyó por el
30 s de Vegeta. No se añadieron sleeps, límites de RPS ni cambios de concurrencia.

La lectura de los cuatro mounts binarios se hace con el módulo incorporado
`k6/experimental/fs`, usando handles y un ArrayBuffer del PDF seleccionado;
no se instaló una extensión ni se cambió la extracción del servicio.
Referencia: [File/read de k6](https://grafana.com/docs/k6/latest/javascript-api/k6-experimental/fs/file/read/)
y [POST binario](https://grafana.com/docs/k6/latest/javascript-api/k6-http/post/).

### Cuatro PDFs y COLD CACHE AL INICIO

Carpeta configurable `D:\INGENIERIA\3er\desarrollo de software\`:

| PDF oficial externo | Bytes | Páginas |
| --- | ---: | ---: |
| `2020-Scrum-Guide-Spanish-Latin-South-American.pdf` | 319343 | 16 |
| `scrum_manager_historias_usuario.pdf` | 3830899 | 62 |
| `Essential-Kanban-Condensed-Spanish.pdf` | 8901466 | 90 |
| `Filosofia Lean.pdf` | 668142 | 42 |

Nombres reales, SHA de archivo y referencias Markdown idénticos a `pdfs.json`
de Vegeta; cuatro SHA distintos. El runner releyó, verificó firma/páginas y
calculó la referencia offline, fuera del HTTP y sin poblar Redis. Se montó cada
PDF read-only como `/pdfs/1.pdf`…`/pdfs/4.pdf`; no se copiaron archivos al repo,
no Base64, no multipart y **no pdf279hojas.pdf**. El cuerpo fue application/pdf.

**DB 13 empezó con DBSIZE=0**, sin precarga. El overlay existente cambió
REDIS_URL temporalmente, recreando dos APIs/trabajadores nuevos. Redis siguió
compartido y no se recreó. DB 0 estaba vacía y no se borró. Cuatro contenedores
healthy y seis health 200 por Traefik, reparto **3/3**, antes del POST.

La preparación registró dos fallos, ambos conservados y sin carga de PDF:

1. `official-k6-spike-20261007-cold/`: seis health llegaron a una sola API
   inmediatamente después de recrear las APIs. El provider todavía no había
   incorporado ambas. El runner frenó antes de iniciar k6 y restauró DB 0.
   Se corrigió la espera hasta observar tráfico en las dos, sin tocar Traefik.
2. `official-k6-spike-20261007-cold-run1/`: k6 exit **107** por un mensaje de
   setup que consultaba `options.scenarios` normalizado por k6. El error fue
   previo a las iteraciones: cero POST, testRunDurationMs **3.586041 ms**.
   Se corrigió sólo ese mensaje; no fue una corrida fallida por rendimiento.

`k6 inspect --include-system-env-vars` confirmó **startVUs=0**, etapas exactas
**10s/100, 20s/100, 10s/0** y grace 0. Inspect no envía HTTP ni calienta caché.
El intento con carga fue `cold-run2`, desde DB 13 todavía vacía.

### Resultado real: OOM del generador, Spike incompleto

**¿SE COMPLETÓ EL K6 SPIKE OFICIAL 0→100→0? NO.**
No fue abortado por 503, checks, latencia ni thresholds. **El proceso k6 murió
por OOM**, una de las excepciones autorizadas. Docker inspect:
`OOMKilled=true`, `ExitCode=137`, memoria limitada a **536870912 bytes**.
El estado del cliente quedó guardado antes de eliminar sólo ese contenedor
nuevo. Los cuatro servicios no tuvieron OOM y permanecieron healthy.

Vida del contenedor, incluyendo init/setup: **5.396393 s**,
`StartedAt=16:01:18.864595403Z`, `FinishedAt=16:01:24.260988235Z`.
Wall del runner/monitor: **9.4465459 s**, que incluye inicio Docker y detección.
**La duración exacta de la fase de carga no está verificada**: no se generó
`summary.json` ni evento teardown. El log alcanza a mostrar **2.0 s / 40.0 s,
19/100 VUs y 31 iteraciones completas**; los últimos instantes no se conservaron
como agregado. No se alcanzó la meseta de 100 VUs ni la bajada 100→0.
No se informa 5.396 s como duración del Spike: incluye preparación del proceso.

La salida nativa alcanzó a persistir **14 http_reqs**, **13 iterations**,
**21 requests_started** y **22 iterations_started**. El log de consola
conservó **56 respuestas**, mientras Traefik conservó **75 access logs**.
Son ventanas/capturas diferentes, debido a muerte abrupta y buffers sin vaciar.
**El total de requests/iteraciones y el throughput final de k6 no se verificaron**.
No se divide un conteo parcial por 40 s, la vida del contenedor o el wall para
presentarlo como req/s del benchmark. Los 75 IDs de Traefik son solicitudes
observadas por el proxy, no 75 respuestas recibidas por k6.

### Comparación con el profesor: muestras parciales, no benchmark completo

Las latencias de nuestra columna se calculan **sólo sobre las 56 respuestas
HTTP conservadas en consola, todas 503**, mediante interpolación lineal
`posición=(n−1)×p`. No son percentiles finales emitidos por k6 ni latencias de
extracción exitosa. La media de esa muestra es **323.002 ms**; la salida
nativa conserva sólo 14 tiempos y tiene una media diferente (**95.632 ms**).
Se mantienen ambos conjuntos y se declara cuál se utiliza.

| Métrica | Nuestro resultado | Profesor k6 Spike |
| --- | --- | --- |
| Perfil | Interrumpido por OOM antes de 40 s | 0→100→0, 40 s |
| Requests totales | No verificadas; 56 respuestas de consola, 14 registros HTTP nativos y 75 access logs | 1037 |
| Iteraciones totales | No verificadas; 13 nativas persistidas, log muestra 31 a t=2 s | No informadas |
| Throughput req/s | **No verificado: sin resumen final** | 25.35 |
| http_req_failed | 100 % de las 14 muestras nativas; agregado completo no disponible | 0 % |
| Error en respuestas de consola | 100 % de 56 | 0 % |
| Checks | 0/70 puntos nativos conservados; agregado completo no disponible | No informados |
| HTTP 200 | 0 observados por cliente | No desglosado |
| HTTP 503 | 56 observados por cliente | No desglosado |
| Otros status del cliente | Ninguno en los 56 registros; total no verificado | No desglosado |
| Timeouts / errores de conexión | 0 observados en los 56 registros; total no verificado | Sin desglose adicional al 0 % de errores |
| p50 parcial | **279.918 ms**, sólo errores | 1880 ms |
| p90 parcial | **754.030 ms**, sólo errores | 7830 ms |
| p95 parcial | **777.199 ms**, sólo errores | 8800 ms |
| Máximo parcial | **1076.997 ms**, sólo errores | 13940 ms |

La referencia del profesor es la provista para esta fase: **1037 requests /
40 s, 25.35 req/s, 0 % errores, p50 1.88 s, p90 7.83 s, p95 8.80 s,
max 13.94 s**. Se conservan exactamente esos valores, sin recalcular 25.35
como 1037/40 ni suponer una duración precisa no publicada.
**Nuestros errores rápidos no acreditan superar al profesor ni cumplir 400 ms.**

### Caché, contenido y balanceo

En las 56 respuestas de consola: **X-Cache ABSENT=56**;
**HIT=0, MISS=0, ERROR=0, BYPASS=0 observados en headers**. Las respuestas
fueron 503 sin X-Cache. Esos ceros no son un agregado de todas las operaciones
internas del servidor. No hubo HTTP 200 observado, por lo que el contrato y
SHA bajo carga del set oficial no quedaron verificados por el cliente.

Los logs de API conservaron **dos perfiles internos MISS**. Redis DB 13
terminó con dos resultados: Scrum Guide **16 páginas/35783 caracteres** y
Historias **62 páginas/90183 caracteres**, ambos con SHA Markdown idéntico a
la referencia. Kanban y Lean no quedaron cacheados. Estos resultados internos
**no se cuentan como dos HTTP 200 ni como dos MISS recibidos por k6**.
No se verificó un HIT de carga antes del OOM. Se conserva la distinción entre
inicio frío, conversión interna y respuestas cacheadas.

Rotación observada en las respuestas: Guide **16**, Historias **14**, Kanban
**12**, Lean **14**. La asignación global rota cuatro archivos; el aborto y las
latencias diferentes hacen que el subconjunto completado no sea uniforme.

Traefik: **75 access logs**, reparto **37/38** entre ambas APIs; estados
**63×503, 9×499, 3×502**. Es evidencia de balanceo, no de éxito. Los 499
corresponden a clientes desconectados; 502/499 del proxy no se suman a los
56 HTTP 503 de consola como si fueran respuestas recibidas por k6.

### Recursos, restauración y tests

Tres muestras del monitor, incluyendo su estado inicial. Máximos reportados
por Docker stats; no picos continuos garantizados:

| Contenedor | CPU máxima muestreada | RAM máxima muestreada | Límite conservado |
| --- | ---: | ---: | --- |
| extractor-1 | 99.16 % | 302.7 MiB | 1 CPU / 768 MiB |
| extractor-2 | 102.53 % | 297.6 MiB | 1 CPU / 768 MiB |
| Traefik | 51.56 % | 75.66 MiB | 0.5 CPU / 512 MiB |
| Redis | 6.24 % | 7.32 MiB | 0.5 CPU / 256 MiB |
| k6 | 99.10 % | **348.1 MiB** | **1 CPU / 512 MiB** |

La muerte ocurrió entre muestras: **348.1 MiB no es el pico de OOM**.
No se inventa un máximo efectivo de 512 MiB. `client-inspect.json` sí confirma
OOMKilled=true y exit 137; no hubo OOMKilled en APIs, Redis o proxy. La consulta
posterior de Docker events no recuperó el evento; no reemplaza ni contradice
la inspección capturada. La CPU es lo reportado por Docker sobre intervalos y
puede exceder transitoriamente la cuota; los límites no se cambiaron.

El generador fue la limitación física demostrada que impidió terminar el
perfil. No se aisló el reparto de su memoria entre buffers de PDF, runtimes
VU, métricas, HTTP y GC. No se atribuye este OOM a Traefik ni se deduce de él
una optimización del algoritmo. **No se cambió la implementación ni la configuración, ni se ejecutó otra carga después del OOM.**

Se restauraron dos APIs a DB 0 con imagen, entorno y recursos originales;
Redis y Traefik conservaron ID y StartedAt. DB 0=0 claves antes y después de
la integración; DB 13 conserva sus dos claves con TTL. No se ejecutó FLUSH ni
DEL contra documentos existentes. Estado final: **dos APIs, Redis y Traefik
healthy**, seis health HTTP 200 por Traefik y reparto **3/3**.

- `uv run --locked pytest -v`: **40 passed, 1 skipped in 35.71s**, exit 0.
- `uv run --locked pytest --run-integration -m integration -v -s`:
  **1 passed, 40 deselected in 16.83s**, exit 0; Redis real por Traefik,
  MISS→HIT, contenido idéntico y TTL 3600 s. PTTL **3599557→3595968 ms**.
- Se usaron `UV_NO_SYNC=true` y `UV_OFFLINE=true`, evitando instalaciones.
  La integración sólo limpia su propia clave PDF/UUID.

### Comandos reproducibles y evidencia

Comando real, desde la raíz del repositorio, antes del OOM:

```powershell
uv run --locked --no-sync --offline python tests/performance/run_official_spike.py --pdf-dir 'D:\INGENIERIA\3er\desarrollo de software' --name official-k6-spike-20261007-cold-run2 --redis-db 13
```

**No volver a lanzar automáticamente con estos recursos:** se ha probado OOM
del cliente. Para una futura ejecución autorizada usar un nombre nuevo y una
DB vacía, seleccionados con el bloque de README. No reutilizar DB 13 ocupada
ni borrar DB 0; el runner rechaza DB o carpeta existentes. El comando antiguo
`run_k6.py --pdf ... --spike` quedó como referencia histórica de preparación
con un PDF; **no corresponde al nuevo Spike oficial de cuatro PDFs**.

El runner conserva el comando Docker completo y mounts read-only en
`k6-settings.json`, el perfil validado en `k6-inspect.json`, ejecución en
`execution.json`, estado del generador y los servicios, logs volátiles antes
de restaurar, métricas JSON y balance. Un fallo de thresholds, incluido exit
99, no activa abort. La salida del runner documenta estado y restauración;
para juzgar k6 se usa su exit_code en `execution.json`, **137 en esta carga**.

Pruebas finales y consulta de estado:

```powershell
$env:UV_NO_SYNC = 'true'
$env:UV_OFFLINE = 'true'
uv run --locked pytest -v
$proxyPort = ((docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80).Trim()).Split(':')[-1]
$env:EXTRACTOR_BASE_URL = "http://localhost:$proxyPort"
uv run --locked pytest --run-integration -m integration -v -s
docker compose -f compose.yaml -f compose.traefik.yaml ps
```

Evidencia de carga en
`tests/stress/results/official-k6-spike-20261007-cold-run2/`:
`partial-report.json`, `metrics.jsonl` original, `k6.log`, respuestas de consola,
`client-inspect.json`, entorno/PDFs/mounts, estados/recursos, logs de ambas APIs
y Traefik, balance, perfiles internos, caché, restauración, health y tests.
Dos carpetas aparte conservan la preparación fallida, claramente sin POST.
No se sobrescribieron Vegeta ni benchmarks anteriores; todos los PDFs siguen
externos e intactos.

**Conclusión:** el perfil oficial quedó implementado y se intentó ejecutarlo,
pero **NO se completó 0→100→0 durante 40 s por OOM del generador**. El resultado
es parcial y no sustituye el benchmark oficial completo. Los servicios quedaron
restaurados y los tests pasan. No se optimizó, no se modificaron recursos ni
se repitió carga después del OOM. No hubo ramas, commit ni push.


## K6 SPIKE OFICIAL NATIVO WINDOWS: 40 s completos

### Alcance y configuración conservada

Corrida **official-k6-spike-windows-20261007-cold**, **7/10/2026 a las
13:30 Argentina (16:30 UTC)**. Se continuó el intento Docker anterior con un
generador **nativo de Windows**, sin ejecutar Vegeta ni modificar el SUT.
La sección anterior describe el intento histórico; su OOM y sus cifras
parciales se conservan y no se mezclan con esta nueva corrida completa.

- k6 existente: **v2.2.0, commit 00a9a1b7f5, Go 1.26.5, windows/amd64**;
  ruta `C:\Program Files\k6\k6.exe`, comprobada con `k6 version` y `where.exe k6`.
  No se instaló ninguna herramienta o dependencia.
- Windows 11, AMD Ryzen 5 4600H, 6 núcleos / 12 hilos; RAM física visible
  **7,907,151,872 bytes (7.364 GiB)**. Docker dispone de 12 CPU lógicas y
  **3,767,750,656 bytes (3.509 GiB)**. El equipo conservó sus otros procesos
  y contenedores; no es un host dedicado de carga.
- **Dos APIs: 1 CPU / 768 MiB cada una**. Traefik **v3.6: 0.5 CPU / 512 MiB**.
  Redis compartido **8.2.10-alpine: 0.5 CPU / 256 MiB**. Se verificaron estos
  límites antes, durante la preparación y después. No se reconstruyeron imágenes.
- Ruta **k6 Windows → puerto publicado de Traefik → dos APIs → Redis**.
  En esta corrida `http://127.0.0.1:53701/extract`, con `Host: localhost`.
  El runner consulta el puerto real; las APIs no publican puertos al host.
- **COLD CACHE AL INICIO**: DB **12**, con **0 claves** tanto antes de la
  preparación como justo antes de la carga. No hubo precarga de PDFs ni FLUSH.
  Sólo se cambió transitoriamente el REDIS_URL de las APIs mediante el override
  de benchmark ya existente. El servidor Redis y sus datos normales no se alteraron.
  TTL conservado **3600 s**, timeout Redis **200 ms**.
- Antes de k6, los cuatro servicios estaban healthy y seis health HTTP 200 por
  Traefik demostraron descubrimiento de ambas APIs, reparto **3/3**.

### Cuatro PDFs e input del generador

Ubicación externa: `D:\INGENIERIA\3er\desarrollo de software\`.
Ningún PDF se copió al repositorio y `pdf279hojas.pdf` **no participó**.

| PDF exacto | Bytes | Páginas | Caracteres Markdown |
|---|---:|---:|---:|
| `2020-Scrum-Guide-Spanish-Latin-South-American.pdf` | 319343 | 16 | 35783 |
| `scrum_manager_historias_usuario.pdf` | 3830899 | 62 | 90183 |
| `Essential-Kanban-Condensed-Spanish.pdf` | 8901466 | 90 | 125909 |
| `Filosofia Lean.pdf` | 668142 | 42 | 59181 |

Se recalcularon firma, páginas, SHA-256 del PDF y referencia de Markdown con
el algoritmo actual, sin enviar solicitudes al SUT para precargarlo. Los
cuatro SHA de archivo son distintos y coinciden con los manifiestos previos.
`pdfs.json` conserva nombres, rutas y ambos hashes completos; `cache-after.json`
y los checks validan contenido/páginas. Los archivos externos mantienen su SHA
antes y después de la corrida.

La única modificación de `spike.js` respecto del estado local anterior fue
la carga de los binarios: **`open(path, 'b')` en init**, ArrayBuffer reutilizado
en `http.post`, sin `seek/read` ni `new Uint8Array` por iteración, sin Base64
ni conversión del PDF a string. No se cambiaron stages, checks, thresholds,
timeout de 180 s ni tiempos de cierre. k6 mantiene copias por VU: cargar en
init elimina lecturas repetidas, pero **no establece un buffer compartido
entre VUs**. Esta limitación está descrita en la
[documentación oficial de open](https://grafana.com/docs/k6/latest/javascript-api/init-context/open/).

La rotación usa el índice global `iterationInTest % 4`. Hubo **279 solicitudes
iniciadas**, repartidas **70/70/70/69**; la distribución de respuestas completas
varía porque los tamaños y tiempos difieren y se cancelan iteraciones en la bajada.

### Perfil y finalización real

`k6 inspect --include-system-env-vars` verificó, sin HTTP ni cambios de caché:

```text
startVUs: 0
10s -> 100 VUs
20s -> 100 VUs
10s -> 0 VUs
gracefulRampDown: 0s
gracefulStop: 0s
```

**¿SE COMPLETÓ EL SPIKE 0→100→0 DURANTE 40 s? SÍ.** Se observaron 100 VUs
activos, la meseta y la bajada final a 0 en `k6.log`. El perfil tiene **40 s
nominales**; `summary.json` informa **40,120.8811 ms** de test. La ventana del
lanzador hasta recuperar el exit fue **44.433 s**, incluyendo init, cierre y
muestreo; no se la presenta como duración de los stages. No hubo aborto.

Exit nativo k6 **99**: fallaron los thresholds de checks, errores y p95, con
`abortOnFail` ausente. Se dejaron terminar todos los stages a pesar de los
503 y los malos tiempos. La salida exit 0 del wrapper indica que guardó la
corrida/restauración; el resultado de carga es el **99** de `execution.json`.

### Resultado completo vs profesor

Las latencias son `http_req_duration` de k6, **en milisegundos**, sobre todos
los **179 resultados HTTP completos** (incluidos 40 errores HTTP). No incluyen
init ni las 100 iteraciones interrumpidas. Profesor: referencia suministrada,
1037 requests / 25.35 req/s / 0 % errores; sus tiempos se convirtieron de s a ms.

| Métrica | Nuestro resultado Windows | Profesor |
|---|---:|---:|
| Requests del resumen HTTP | **179** | 1037 |
| Solicitudes iniciadas | **279** | No desglosado |
| Req/s del resumen | **4.4615** | 25.35 |
| HTTP 200 correctos | **139 (77.65 % de los resultados HTTP)** | 0 % errores informado |
| HTTP 503 | **39** | 0 errores informado |
| Otros HTTP | **1 HTTP 502** | 0 errores informado |
| `http_req_failed` | **22.3464 % (40/179)** | 0 % |
| Timeouts observados | **0** | 0 errores informado |
| Errores de conexión observados | **0** | 0 errores informado |
| Iteraciones interrumpidas | **100** | No desglosado |
| Latencia mínima | **490.027 ms** | No informado |
| Latencia media | **7495.256 ms** | No informado |
| p50 | **5105.832 ms** | 1880 ms |
| p90 | **17900.786 ms** | 7830 ms |
| p95 | **19958.908 ms** | 8800 ms |
| Máximo | **33601.796 ms** | 13940 ms |
| Checks | **695/895 (77.6536 %)** | No informado |
| Bytes enviados / recibidos (k6) | **879747150 / 9277646** | No informado |

Sólo los 139 HTTP 200: p50 **4688.004 ms**, p90 **18374.587 ms**,
p95 **20981.704 ms**, máximo **33601.796 ms**. El throughput de respuestas
válidas fue **3.4645/s**. Estos son resultados secundarios; no sustituyen el
resumen global ni excluyen errores para presentar una aprobación artificial.

**No se cumple p95 < 400 ms ni la tasa de errores de 0 %.** El Spike es un
modelo de VUs, no un perfil de llegada de 50 req/s. La cantidad de requests
no fue fijada a 1037 ni a 1500; emerge de los tiempos del sistema y del cliente.

### Cierre sin gracia: 100 iteraciones interrumpidas

Se conservó el cierre inmediato del script anterior, sin modificar el perfil.
k6 inició **279** solicitudes y terminó **179** iteraciones: **100 quedaron
interrumpidas durante el ramp-down o el stop**. No se registran como resultados
HTTP ni ejecutan los cinco checks de respuesta. Se verificó la diferencia de
IDs entre `spike_requests_started` y las respuestas, y el total coincide con
la consola final: **179 complete / 100 interrupted**.

Sobre las 279 iniciadas: **139 correctas (49.82 %)**, **40 fallos HTTP** y
**100 interrumpidas**; fallidas o interrumpidas juntas: **50.18 %**. Es una
contabilidad distinta de `http_req_failed`, que usa 179 como denominador.
No se ocultan las cancelaciones bajo el 0 de timeouts/conexiones.

No se observaron códigos de timeout/DNS/TCP/TLS en los resultados terminados.
El timeout sigue en **180 s**, mayor que el perfil; las pendientes se
interrumpieron antes de agotar ese tiempo. Un **HTTP 502 recibido** es un
error del proxy y se cuenta por separado de un error de conexión del cliente.

### Caché, texto correcto y balanceo

Headers recibidos: **134 HIT, 5 MISS, 0 ERROR, 0 BYPASS, 40 ABSENT**. ABSENT
corresponde a los errores HTTP y no demuestra el estado de la caché de esas
solicitudes. Las 100 interrumpidas tampoco tienen header registrado. Los
HIT **no representan extracción real**; éste es un Spike que empieza frío y
luego incluye respuestas calientes, no un benchmark íntegramente sin caché.

Las **139 respuestas HTTP 200** pasaron los cinco checks: 47 de Scrum Guide,
40 de Historias, 3 de Kanban y 49 de Lean. Página, longitud y SHA de Markdown
correctos en todas. Los cinco MISS recibidos fueron uno por cada documento
y un segundo MISS de Lean; no se presume que un archivo se convierta una sola
vez cuando llegan solicitudes frías concurrentes. La DB 12 terminó con las
cuatro claves; su contenido y TTL fueron comprobados sin borrarlas.

Balanceo observado por X-Audit-Id y ServiceAddr:

| Captura de logs de Traefik | Registros únicos | API 1 / API 2 | Estados del proxy |
|---|---:|---:|---|
| Inmediata al terminar la carga | 241 | 124 / 117 | 144×200, 39×503, 17×502, 41×499 |
| Después de completar registros tardíos y restaurar DB 0 | **279** | **140 / 139** | 144×200, 39×503, 32×502, 64×499 |

Los 279 IDs del generador aparecen en la captura final del proxy. Entre los
100 sin respuesta registrada por k6 hay **5 estados proxy 200, 31 estados
502 y 64 estados 499**. Un estado del proxy no significa que el cliente haya
recibido/checkeado esa respuesta. La captura final incluye completaciones y
cancelaciones tardías, así como el efecto de recrear las APIs para volver a
DB 0; no se atribuyen esos 32 estados 502 íntegramente a la ventana de carga.
Se conservaron ambas capturas para distinguirlas.

### CPU, memoria y perfiles internos

**12 muestras** de Docker y proceso Windows, aproximadamente cada 3–4.5 s.
Las 48 observaciones de health del SUT fueron healthy. Máximos **muestreados**:

| Servicio | CPU Docker máxima | RAM máxima muestreada | Límite conservado |
|---|---:|---:|---|
| API 1 | 107.64 % | 393.4 MiB | 1 CPU / 768 MiB |
| API 2 | 106.63 % | 459.8 MiB | 1 CPU / 768 MiB |
| Traefik | 58.46 % | 257.0 MiB | 0.5 CPU / 512 MiB |
| Redis | 10.24 % | 8.07 MiB | 0.5 CPU / 256 MiB |

Docker expresa 100 % como una CPU lógica; su intervalo de medición puede
mostrar picos mayores que el límite nominal. Los límites efectivos de
`docker inspect` se mantuvieron. No se inventan máximos entre muestras.

k6 nativo no tuvo límite Docker ni afinidad/CPU impuesta por el runner:

- Pico residente según el contador Windows: **1,056,911,360 bytes /
  1007.95 MiB**; pico de commit del proceso: **2,580,541,440 bytes /
  2461.00 MiB**. Son contadores de pico del proceso, no sólo el máximo de muestras.
- CPU acumulada **9.734 s**; máximo calculado por intervalo **75.22 % de una
  CPU lógica** (incluye init; no es porcentaje de las 12 CPU juntas).
- Host físico disponible antes de iniciar: **533.68 MiB**; mínimo muestreado
  **12.80 MiB**. Commit disponible mínimo **668.40 MiB**. El archivo de paginación
  ya existente era de **19545 MiB**. No se cambió su configuración.
- **904489 page faults** del proceso; el contador incluye fallos blandos,
  por lo que no se interpreta como 904489 lecturas de disco. Hay presión de
  memoria demostrada, pero no una cuantificación aislada del costo de paging.

Ninguna API, Redis o Traefik tuvo OOM (`OOMKilled=false` después de carga), y
los IDs/StartedAt de Redis/Traefik se conservaron. k6 completó el escenario,
guardó resumen, ejecutó teardown y salió 99 sin error fatal de memoria.

Los **181 perfiles de servidor** guardados antes de recrear APIs tienen
176 HIT y 5 MISS; incluyen trabajo cuyo cliente ya canceló. No son la misma
población de 179 resultados k6, ni sumandos independientes del tiempo HTTP:

| Tramo (perfiles de servidor) | n | p50 | p95 | Máximo |
|---|---:|---:|---:|---:|
| `receive_body_ms` | 181 | 3712.630 ms | 26454.011 ms | 38797.208 ms |
| `redis_get_ms` | 181 | 7.236 ms | 53.597 ms | 292.817 ms |
| Algoritmo sólo en MISS | 5 | 272.850 ms | 953.345 ms | 1079.701 ms |
| `worker_ms` sólo en MISS | 5 | 1661.806 ms | 12766.809 ms | 12929.396 ms |

Los 176 HIT tienen `extraction_ms=0`. El tiempo observado por el cliente
muestra envío p50 **15.669 ms** / p95 **8323.012 ms**, espera p50
**4613.334 ms** / p95 **15075.666 ms** y recepción p50 **1.035 ms** /
p95 **608.768 ms**. Los p95 de distintos tramos no se suman ni corresponden
necesariamente a la misma petición.

El OOM que impedía finalizar el intento anterior quedó resuelto al sacar
el generador del contenedor de 512 MiB. La nueva prueba demuestra **presión
de memoria del host**, CPU cercana a los cupos en APIs/proxy y un costo alto
de recepción/espera. Los 503 son coherentes con la protección existente ante
conversión ocupada. Estas mediciones no aíslan una única causa de los malos
tiempos ni justifican cambiar algoritmo, Redis, límites o backpressure en
esta fase. No se aplicó ninguna optimización al SUT.

### Reproducir y comprobar el estado final

Comando real de la corrida, desde la raíz del repositorio:

```powershell
uv run --locked --no-sync --offline python tests/performance/run_official_spike.py --k6 'C:\Program Files\k6\k6.exe' --pdf-dir 'D:\INGENIERIA\3er\desarrollo de software' --name official-k6-spike-windows-20261007-cold --redis-db 12
```

Para una nueva corrida, elegir **otra carpeta** y **una DB actualmente vacía**
con la receta nativa de README. No reutilizar esta DB 12 ocupada, ni borrar
DB 0 u otros resultados. El runner rechaza DB/carpeta ocupada, inspecciona
el perfil, espera salud/reparto por Traefik y restaura el REDIS_URL original
en `finally`. El parámetro **`--k6`** selecciona Windows; omitirlo conserva
el cliente Docker histórico y **no corresponde a esta receta**.

Comandos finales ejecutados (dependencias ya disponibles):

```powershell
$env:UV_NO_SYNC = 'true'
$env:UV_OFFLINE = 'true'
uv run --locked pytest -v
$proxyPort = ((docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80).Trim()).Split(':')[-1]
$env:EXTRACTOR_BASE_URL = "http://localhost:$proxyPort"
uv run --locked pytest --run-integration -m integration -v -s
docker compose -f compose.yaml -f compose.traefik.yaml ps
```

- Pytest: **40 passed, 1 skipped in 29.35s**, exit 0. La integración opt-in se
  omite en la suite común; incluye también los dos tests existentes de reporte.
- Integración Redis real por Traefik: **1 passed, 40 deselected in 12.03s**,
  exit 0, MISS→HIT, contenido correcto, TTL 3600 s y PTTL
  **3599742→3597108 ms**. Sólo limpia su propia clave UUID.
- Final: **dos APIs, Redis y Traefik healthy**, seis health 200 y reparto **3/3**,
  APIs en **DB 0**, DB 0 con **0 claves**, igual que al inicio. Sin FLUSH.
  Mismas imágenes, recursos y variables de entorno originales tras restaurar.
- No hubo ramas, commit, push, instalación ni cambios de Compose/API/Redis.
  El cambio local previo de Traefik 512 MiB y toda la evidencia anterior se
  conservaron; esta fase modifica sólo el input/ejecución del generador y documentación.

Evidencia nueva, completa y separada:
`tests/stress/results/official-k6-spike-windows-20261007-cold/`:

- `summary.json`, `metrics.jsonl`, `k6.log`: resultados nativos originales.
- `k6-inspect.json`, `k6-settings.json`, `environment.json`, `host-tools.json`,
  `pdfs.json`, `commands.json`: perfil, ejecutable, puerto, versiones y fuentes.
- `execution.json`, `generator-before.json`, `generator-after.json`, estados
  iniciales/de carga/restaurados/finales: CPU/RAM, exit y OOM.
- Logs de ambas APIs y Traefik antes de recrear, snapshots finales de access
  logs, `balance.json` y `balance-final.json`: reparto y completaciones tardías.
- `responses.jsonl`, `server-profiles.jsonl`, `vus.json`, `cache-after.json`,
  health y logs pytest/integración: integridad y validación final.
- `report.json` y `analyze.py`: análisis recomputable desde archivos, sin carga
  ni red: `python tests/stress/results/official-k6-spike-windows-20261007-cold/analyze.py`.
- `preflight-files.json` y `final-verification.json`: preservación de archivos
  previos, main/HEAD, configs y PDFs. La evidencia parcial Docker quedó intacta.

**Conclusión:** **SÍ se completó 0→100→0 durante los 40 s nominales sin OOM del
generador**. El benchmark tuvo 22.35 % de errores HTTP, 100 interrupciones y
p95 **19.959 s**; **no cumple 400 ms ni el resultado del profesor**. La fase
resuelve la terminación del generador y deja el SUT original restaurado y
los tests aprobados; no certifica buen rendimiento del servicio.
