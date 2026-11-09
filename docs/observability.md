# Observabilidad y contratos operativos

Las métricas y trazas descriptas aquí son opciones **del extractor**. No hay
en este repositorio una plataforma de observabilidad central del equipo. El
Compose común publicado identifica `api`, `documents` y `extractor`; un cuarto
microservicio queda a confirmar. El factor XI de Twelve-Factor pide **logs
emitidos como flujo de eventos** a stdout/stderr, que el entorno puede capturar.
No equivale a disponer de Prometheus, Grafana ni trazas distribuidas.

## Señales de cada servicio

Esta comparación usa los `main` publicados de [API Service](https://github.com/Lourdesrizza/pdf-api-service/tree/e191097bba601efffe729b811ccbf872b483318b),
[Document Service](https://github.com/angelina-magallanes/pdf-document-service/tree/b4fd3dfc5c2c98e0c8a6a227e04aea18892982db) y
[la infraestructura](https://github.com/JeremiasRoda/pdf-infrastructure/tree/79370968d5e826b22c05198e53f2fccb9ccf893a),
además del código local actual del extractor. Describe capacidades de código;
el Compose común no estaba levantado en esta revisión.

| Servicio | Logs y salud | IDs y señales adicionales |
| --- | --- | --- |
| API Service | Configura logs a stdout y Uvicorn; `/health` responde por el proceso, `/ready` consulta Extractor y Documents. | Genera o acepta `X-Request-ID`, lo devuelve y lo envía a ambos servicios. No se encontró endpoint de métricas ni instrumentación de trazas en su código publicado. |
| Document Service | Logs de cada petición a stdout con duración; `/health/live` no consulta MongoDB y `/health` y `/health/ready` hacen `ping` a MongoDB. | Devuelve y registra `X-Request-ID`; acepta también `X-Audit-Id`. No se encontró endpoint de métricas ni instrumentación de trazas en su código publicado. |
| Extractor | Uvicorn, eventos de caché, errores y perfilado a stdout; `/health`, `/health/live` y `/health/ready` distinguen vida, worker y estado degradado de Redis. | Devuelve `X-Request-ID` y `X-Audit-Id`. `/metrics` sólo existe con `METRICS_ENABLED=true`; los spans OTLP requieren `OTEL_ENABLED=true` y un colector externo. |

Fuentes: [API: logs](https://github.com/Lourdesrizza/pdf-api-service/blob/e191097bba601efffe729b811ccbf872b483318b/app/main.py),
[salud](https://github.com/Lourdesrizza/pdf-api-service/blob/e191097bba601efffe729b811ccbf872b483318b/app/routes.py),
[correlación](https://github.com/Lourdesrizza/pdf-api-service/blob/e191097bba601efffe729b811ccbf872b483318b/app/clients/base.py);
[Documents: logs e IDs](https://github.com/angelina-magallanes/pdf-document-service/blob/b4fd3dfc5c2c98e0c8a6a227e04aea18892982db/app/middleware.py),
[salud](https://github.com/angelina-magallanes/pdf-document-service/blob/b4fd3dfc5c2c98e0c8a6a227e04aea18892982db/app/routes.py);
extractor: `app/profiling.py`, `app/middleware.py`, `app/routes.py`,
`app/metrics.py`, `app/tracing.py` y `compose.yaml`.

Desde el Compose común se consultarían `docker compose -f
docker-compose.integration.yml logs api documents extractor traefik registrator`,
el dashboard de Traefik en `127.0.0.1:8080` y los checks de Consul en
`127.0.0.1:8500`. Traefik escribe access logs, pero el Compose común no define
un agregador de logs, un Prometheus para los tres servicios ni un colector de
trazas. En el despliegue local del extractor, consultar `docker compose -f
compose.yaml -f compose.traefik.yaml logs extractor redis traefik` y los health
checks por el puerto publicado del proxy. El overlay opcional de esta guía
consulta **sólo al extractor**. La correlación por ID entre API y servicios
está implementada en los clientes, pero no equivale a tracing distribuido
comprobado de punta a punta.

El [Compose de integración común](https://github.com/JeremiasRoda/pdf-infrastructure/blob/79370968d5e826b22c05198e53f2fccb9ccf893a/docker-compose.integration.yml)
fija `METRICS_ENABLED=true` **sólo para el extractor**, pero no define allí
Prometheus, Grafana ni un colector OTLP. Exponer `/metrics` no demuestra que
alguien lo esté consultando. En el Compose local del extractor, métricas y
trazas están desactivadas por defecto; la observabilidad adicional se habilita
de forma optativa y no cubre automáticamente al API ni a Documents.

## Prometheus y Grafana

`METRICS_ENABLED=false` es el valor inicial: no se registra middleware de
métricas ni existe `/metrics`. Al activarlo, cada réplica publica su propio
registro Prometheus. La configuración opcional `compose.observability.yaml`
activa métricas y levanta Prometheus/Grafana sobre `pdf-network`. Prometheus
descubre las direcciones A de `extractor` y consulta cada réplica. Grafana trae
un datasource y un dashboard provisionados; los puertos se asignan dinámicamente
en localhost. Consultar los puertos con `docker compose ... port prometheus 9090`
y `docker compose ... port grafana 3000`.

| Métrica | Significado |
| --- | --- |
| `pdf_http_requests_total{method,route,status}` | Respuestas HTTP; ruta limitada a nombres estáticos. |
| `pdf_http_request_duration_seconds` | Duración ASGI por petición; incluye recepción del cuerpo y serialización. |
| `pdf_extraction_duration_seconds` | `algorithm_ms` reportado por PyMuPDF para líderes exitosos. |
| `pdf_request_body_receive_seconds` | Tiempo de lectura del body completo. |
| `pdf_cache_requests_total{result}` | Resultado de la primera consulta Redis por solicitud: hit/miss/error/bypass. |
| `pdf_inflight_requests` | Solicitudes HTTP activas, sin contar el scrape. |
| `pdf_extraction_inflight` | Conversiones del worker activas. |
| `pdf_admission_queue_size` | Esperas en los gates de body y CPU. |
| `pdf_rejected_requests_total{reason}` | Rechazo por cola llena, espera vencida o cuerpo mayor al límite. |
| `pdf_singleflight_shared_total` | Solicitudes seguidoras que comparten una tarea por SHA en la misma réplica. |
| `pdf_extractions_total` | Intentos reales de llamar al worker, incluidos los que terminan en error. |

Un test controlado con caché desactivada comprobó 10 requests iguales,
`pdf_extractions_total=1` y `pdf_singleflight_shared_total=9` usando un worker
simulado. **No demuestra 10 PDFs reales ni un reparto entre réplicas.** Las
series no contienen nombre de archivo, SHA ni request ID. El dashboard muestra
requests/s, cuantiles HTTP, errores, 429/503, tiempos de extracción y body,
cache hit ratio, inflight, cola y singleflight. CPU/RAM no se incluyen porque
no hay exportador de contenedor; consultar `docker stats` separadamente.

En la fase de octubre el daemon Docker no estaba activo, por lo que el overlay
no se ejecutó entonces. Después se construyó y probó la imagen del extractor;
el overlay Prometheus/Grafana sigue sin una verificación de arranque propia.
`docker compose config --quiet` validó la combinación.
Durante pruebas de competición dejar el overlay apagado y
`METRICS_ENABLED=false` para evitar costo y alterar la comparación.

## Tracing

`OTEL_ENABLED=false` por defecto no construye proveedor ni exportador.
Si se habilita, `OTEL_EXPORTER_OTLP_ENDPOINT` es obligatorio; puede ser la URL
base OTLP HTTP o terminar en `/v1/traces`. `OTEL_SAMPLE_RATIO=0.05` aplica
muestreo ParentBased. La instrumentación de FastAPI crea un span de request y
propaga el contexto HTTP. Se agregan spans `admission_wait`, `receive_body`,
`sha256`, `redis_get`, `singleflight_wait`, `pdf_extract`, `redis_set` y
`serialize_response`. Este último mide codificación JSON, sin incluir la
validación del modelo.
El span puede contener el `request.id`, pero nunca PDF, Markdown, nombre privado
ni SHA. El costo con tracing activado frente al desactivado **no fue medido**:
el host no superó el guard de memoria. No hay Tempo en el Compose opcional;
usar un colector OTLP externo si se desea visualizar trazas.

El profiling de stdout registra `serialization_ms` como tiempo de validación,
JSON y construcción de respuesta; ese tramo es más amplio que el span de JSON.

## Health, errores y correlación

`/health` conserva el contrato anterior; `/health/live` no toca Redis;
`/health/ready` realiza un PING con plazo de 100 ms por defecto. Redis caído
devuelve `degraded` y HTTP 200 salvo que `READINESS_REDIS_REQUIRED=true`,
cuando devuelve 503. Durante shutdown devuelve 503. Esta respuesta de health
mantiene su JSON de estado, mientras que los errores HTTP de `/extract` y los
de validación del framework usan RFC 9457 `application/problem+json`.

Se acepta `X-Request-ID` o `X-Audit-Id`, con máximo 128 ASCII imprimibles;
si no viene uno válido se genera un UUID. Ambos headers de respuesta contienen
el mismo valor, también incluido en el problema y los logs. Las fallas 500
no exponen el texto de la excepción. La `instance` usa ruta estática o patrón
de ruta, evitando filtrar valores de parámetros en la respuesta.

## Postman

Importar la colección y el environment de `tests/postman/`. Obtener el puerto
publicado con `docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80`
y cambiar `base_url` a `http://localhost:<puerto>`. En la petición válida elegir
Body → binary → un PDF oficial externo o el PDF especial; ajustar
`expected_page_count` al archivo elegido. Postman no guarda rutas personales
ni copias del PDF. La colección comprueba health, live, ready, Swagger habilitado,
200, JSON, page_count, contenido, X-Cache, X-Request-ID, PDF inválido y 415.
El caso 413 requiere seleccionar manualmente un archivo de más de 20 MiB;
429 se reproduce en pytest con gates controlados porque no es determinista
pedirlo desde una colección secuencial. La colección no fue ejecutada contra
Traefik en este estado local.

## Finalización

`app.server` marca `shutting_down` inmediatamente al recibir SIGTERM/SIGINT.
Las extracciones nuevas reciben 503, `/health/ready` pasa a 503 y `/health/live`
permanece 200 mientras el proceso atienda. El lifespan espera trabajos en curso
hasta un deadline de 30 s desde la señal, cierra worker y Redis, y fuerza la
terminación de procesos propios del pool al vencer el plazo. Compose da 35 s.
El test de señal/contrato pasó; el drenaje y cierre de procesos con una petición
real durante `docker stop` queda pendiente de verificación. Ver el procedimiento
en [twelve-factor.md](twelve-factor.md).
