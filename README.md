# PDF Extractor Service

Microservicio independiente de PDF-Extractext que recibe un PDF binario y devuelve
su texto como Markdown. Su responsabilidad termina en la extracción: no guarda
documentos, no usa MongoDB y no implementa las funciones del API Service ni del
Document Service.

Los comandos de esta guía se ejecutan desde la raíz de
`pdf-extractor-service/`. El historial de experimentos y sus condiciones de
medición están en [Rendimiento](docs/performance.md).

## Tecnologías

- **Python 3.12, FastAPI y Uvicorn:** API HTTP y proceso servidor.
- **PyMuPDF:** apertura del PDF y extracción de bloques de texto.
- **Redis:** caché compartida y descartable entre réplicas.
- **Docker Compose y Traefik:** despliegue, healthchecks y balanceo.
- **uv, pytest y Ruff:** dependencias bloqueadas, pruebas y análisis estático.
- **k6 y Vegeta:** perfiles de carga reproducibles, ejecutados por separado.
- **Prometheus y OpenTelemetry:** observabilidad opcional, desactivada por defecto.

PyMuPDF4LLM está fijado para reproducir experimentos anteriores; la ruta de
producción no lo utiliza.

## Características principales

- PDF a Markdown en memoria, sin archivos temporales ni OCR.
- API REST con límite de **20 MiB** por PDF y errores `application/problem+json`.
- Caché Redis por SHA-256 de los bytes del PDF, con respuesta fail-open.
- Despliegue recomendado con dos réplicas detrás de Traefik; balanceo
  verificado hasta cinco.
- Admisión y cola acotadas, con `429` y `Retry-After` cuando se saturan.
- Una extracción por proceso hijo y réplica por defecto; peticiones idénticas
  comparten trabajo dentro de la misma réplica.
- Readiness del worker y reinicio acotado ante `BrokenProcessPool`.
- IDs de correlación, métricas Prometheus y trazas OTLP opcionales.

## Arquitectura

```text
Cliente / API Service → Traefik → extractor (réplicas) → Redis
                                  ↓
                         proceso PyMuPDF
Document Service → persistencia propia
```

El extractor valida el cuerpo, consulta Redis y, si no hay un resultado válido,
convierte el PDF en un proceso `spawn`. Redis conserva sólo resultados exitosos
con TTL; no es fuente de verdad. El contrato permite que el API Service envíe
bytes `application/pdf` y consuma `content` y `page_count`; esa integración
entre repositorios aún debe verificarse. El Document Service es
responsable de persistir documentos y de su MongoDB; este repositorio no lo
configura.

Cada réplica aplica sus propios límites de concurrencia. El trabajo compartido
por SHA (`singleflight`) es local a una réplica: dos réplicas pueden convertir el
mismo PDF al mismo tiempo. Cancelar una petición HTTP no detiene una
conversión activa; el cupo de CPU se libera cuando termina. La caché evita
la conversión únicamente cuando hay `X-Cache: HIT`; HIT no equivale a
extracción real.

La conversión conserva el orden nativo de los bloques textuales de PyMuPDF.
Cada página, incluso vacía, empieza con `## Página N`. No interpreta imágenes,
tablas ni estilos de forma semántica; un PDF escaneado no recibe OCR.

## Endpoints

| Método | Ruta | Función |
| --- | --- | --- |
| `GET` | `/health` | Vida básica: `{"status":"ok","service":"extractor"}`. |
| `GET` | `/health/live` | Vida del proceso, sin consultar Redis. |
| `GET` | `/health/ready` | Estado del worker y comprobación breve de Redis. |
| `POST` | `/extract` | PDF binario → JSON con Markdown y páginas. |
| `GET` | `/docs`, `/redoc`, `/openapi.json` | Documentación, si `DOCS_ENABLED=true`. |
| `GET` | `/metrics` | Métricas, sólo si `METRICS_ENABLED=true`. |

### POST /extract

Enviar los **bytes del PDF como cuerpo**, con `Content-Type: application/pdf`.
No se recibe multipart ni una ruta a un archivo. La respuesta exitosa es HTTP
200, `application/json`:

```json
{
  "content": "## Página 1\n\nTexto extraído...\n",
  "page_count": 1
}
```

Ejemplo en PowerShell, con el stack de Compose levantado:

```powershell
$port = ((docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80).Trim()).Split(':')[-1]
$pdf = (Resolve-Path 'C:\ruta\documento.pdf').Path
curl.exe -i "http://localhost:$port/extract" -H "Content-Type: application/pdf" --data-binary "@$pdf"
```

`X-Cache` en una respuesta 200 indica:

| Valor | Significado |
| --- | --- |
| `HIT` | Resultado obtenido de Redis; no se ejecuta PyMuPDF. |
| `MISS` | Se extrajo y se guardó el resultado. |
| `BYPASS` | Caché desactivada; se extrajo el documento. |
| `ERROR` | Redis falló o devolvió un valor inválido; se extrajo igualmente. |

La clave es `extract:v4:<SHA-256 del PDF>` y el TTL predeterminado es una hora.
No se usa el checksum del Markdown como clave. Los encabezados
`X-Request-ID` y `X-Audit-Id` permiten correlacionar respuesta y logs.

| Código | Causa principal |
| --- | --- |
| 400 | Cuerpo vacío, firma inválida, PDF corrupto o protegido. |
| 413 | PDF mayor que `MAX_UPLOAD_MB`, incluso sin `Content-Length`. |
| 415 | Falta `Content-Type: application/pdf`. |
| 429 | Límite de admisión o espera agotado; consultar `Retry-After`. |
| 503 | Worker irrecuperable o servicio en cierre. |
| 500 | Fallo interno inesperado. |

Los errores públicos usan RFC 9457 (`application/problem+json`), con
`type`, `title`, `status`, `detail`, `instance` y `request_id`.
La validación de parámetros puede devolver 422.

`/health/ready` responde 503 con `worker: broken` si falla definitivamente el
pool. Si Redis cae, la política predeterminada es fail-open: responde 200 con
`status: degraded` y la extracción continúa. Con
`READINESS_REDIS_REQUIRED=true`, Redis caído produce readiness 503. Un worker
ocupado o una cola llena no indican que el pool esté roto.

Al iniciar, se comprueba una vez que el proceso hijo puede arrancar. Un
`BrokenProcessPool` irreversible retira la réplica, termina el servidor con
código 70 tras un cierre acotado y Compose aplica `restart: on-failure:3`.
Tras agotar los reintentos se requiere diagnóstico; pueden aparecer 502/503
durante la transición: Traefik no tiene reintentos configurados. Compose
consulta `/health/ready` cada 10 segundos. Un 429, PDF inválido o fallo
temporal de Redis no disparan este reinicio.

## Instalación y ejecución

**Requisitos:** Python 3.12 y uv para ejecución local; Docker Engine y Docker
Compose 2.24 o posterior para el despliegue. Compose necesita la red externa
`pdf-network`. Los PDFs de prueba pueden permanecer fuera del repositorio.

### Ejecución local sin Redis

```powershell
uv sync --locked
$env:CACHE_ENABLED = "false"
uv run --locked python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

La recuperación con salida 70 y reinicio Docker corresponde al entrypoint del
contenedor (`python -m app.server`), no a este comando de desarrollo. Para usar
Redis local, iniciarlo por separado y fijar `CACHE_ENABLED=true` y
`REDIS_URL=redis://localhost:6379/0` antes de arrancar.

### Docker Compose: dos réplicas y Traefik

El inicio más corto crea `pdf-network` si falta, espera los healthchecks y
muestra el puerto dinámico de Traefik:

```powershell
.\scripts\start.ps1
```

Si PowerShell bloquea el script, usar sólo para esa invocación
`powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1`.

En Linux: `./scripts/start.sh`. Para hacerlo manualmente desde una máquina
limpia, crear **una sola vez** la red si no existe:

```powershell
docker network inspect pdf-network *> $null
if ($LASTEXITCODE -ne 0) { docker network create pdf-network }
docker compose -f compose.yaml -f compose.traefik.yaml up --build -d --scale extractor=2 --wait --wait-timeout 150
docker compose -f compose.yaml -f compose.traefik.yaml ps
docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80
```

La condición crea la red únicamente si falta. `pdf-network` es externa
intencionalmente para
compartirla entre microservicios: Compose no la crea ni la elimina. El proxy de
desarrollo publica un puerto libre en `127.0.0.1`; las réplicas no publican
puertos directos en este modo.

Para detener únicamente este proyecto, conservando la red:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml down
```

`compose.yaml` por sí solo ofrece una instancia directa y Redis, sin Traefik.
Es una alternativa de desarrollo; `docker compose up --build` también requiere
que exista `pdf-network`. La construcción independiente usa
`docker build --tag pdf-extractor-service:0.1.0 .`.

| Servicio | CPU | Memoria | Nota |
| --- | ---: | ---: | --- |
| Extractor, por réplica | 1 | 768 MiB | Sistema de archivos de solo lectura. |
| Redis compartido | 0,5 | 256 MiB | Caché descartable; sin persistencia. |
| Traefik local | 0,5 | 512 MiB | Puerto de host dinámico. |

El límite de 20 MiB del archivo no acota el tamaño del Markdown ni las copias
en memoria; revisar `docker stats` antes de escalar. Los límites son por
réplica, además de Redis y Traefik.

Para integrarse con un Traefik común, éste debe unirse a `pdf-network`,
descubrir las labels del proyecto y acordar con el equipo un host único,
entrypoint y TLS. Las variables del overlay son `EXTRACTOR_HOST`,
`EXTRACTOR_ENTRYPOINT` y `EXTRACTOR_TLS`. El proxy local está restringido al
proyecto `pdf-extractor`; no descubre automáticamente los otros servicios.

### Configuración

Las variables se leen al iniciar. Compose fija `CACHE_ENABLED=true` y
`REDIS_URL=redis://redis:6379/0`; exportarlas en la terminal no reemplaza esos
dos valores. Los demás defaults están en [app/config.py](app/config.py).

| Variable | Predeterminado | Uso |
| --- | --- | --- |
| `CACHE_ENABLED` | `true` | Desactivar la caché en ejecución local. |
| `REDIS_URL` | `redis://localhost:6379/0` | Dirección Redis fuera de Compose. |
| `CACHE_TTL_SECONDS` | `3600` | Caducidad de resultados, en segundos. |
| `CACHE_TIMEOUT_SECONDS` | `0.2` | Plazo por operación Redis, no del HTTP total. |
| `MAX_UPLOAD_MB` | `20` | Tamaño máximo del PDF en MiB. |
| `MAX_IN_FLIGHT` / `QUEUE_SIZE` | `4` / `16` | Cuerpos admitidos y espera acotada por réplica. |
| `EXTRACTION_CONCURRENCY` | `1` | Procesos CPU por réplica; no superar `MAX_IN_FLIGHT`. |
| `ADMISSION_TIMEOUT_SECONDS` | `2` | Espera máxima por gate, en segundos. |
| `READINESS_REDIS_REQUIRED` | `false` | Exigir Redis para readiness. |
| `DOCS_ENABLED` | `true` | Publicar OpenAPI y documentación interactiva. |
| `METRICS_ENABLED` / `OTEL_ENABLED` | `false` / `false` | Instrumentación opcional. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | vacío | Obligatorio al activar OTLP. |
| `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` | `30` | Drenaje; menor que los 35 s de Compose. |

Para medir extracción real sin caché, usar el overlay de benchmark documentado
en [Rendimiento](docs/performance.md); no vaciar Redis ni confundir HIT con
extracción. No aumentar los límites sin medir el consumo.

## Testing

Desde la raíz, después de `uv sync --locked`:

```powershell
uv run --locked python -m pytest -v
uv run --locked python -m ruff check .
```

`python -m pytest` también evita lanzadores antiguos del entorno virtual que
puedan conservar rutas previas al mover el repositorio. La suite habitual usa
PDFs mínimos generados por los tests y omite la integración real si no se
habilita expresamente.

Con el stack de dos réplicas sano, la integración Redis real necesita la URL
publicada por Traefik:

```powershell
$port = ((docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80).Trim()).Split(':')[-1]
$env:EXTRACTOR_BASE_URL = "http://localhost:$port"
uv run --locked python -m pytest --run-integration -m integration -v
uv run --locked python tests/integration/verify_balance.py --replicas 2
Remove-Item Env:EXTRACTOR_BASE_URL
```

El verificador correlaciona respuestas y access logs de Traefik y limpia sólo
la clave Redis de su PDF de prueba.

Las pruebas k6 y Vegeta, los cuatro PDFs oficiales externos, parámetros,
evidencia y resultados históricos están en [Rendimiento](docs/performance.md)
y `tests/performance/`. El Spike k6 usa 0→100→0 VUs en 10/20/10 s;
Vegeta, 50 req/s durante 30 s.

**Los resultados HOT no demuestran el rendimiento de extracción fría ni un
p95 HTTP actual menor que 400 ms.**

## Documentación adicional

- [Rendimiento](docs/performance.md): metodología, k6, Vegeta, evidencia y límites de las mediciones.
- [Seguridad y admisión](docs/security.md): validaciones, memoria, cola y restricciones.
- [Observabilidad](docs/observability.md): métricas, trazas, dashboard y Postman.
- [Twelve-Factor](docs/twelve-factor.md): revisión de operación y despliegue.
- [Colección Postman](tests/postman/pdf-extractor.postman_collection.json): pruebas manuales del contrato.
