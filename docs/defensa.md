# Guía breve de defensa del Extractor

## Qué hace este microservicio

Recibe `POST /extract` con bytes PDF (`application/pdf`, hasta 20 MiB en el
Compose local) y devuelve HTTP 200 con `content` en Markdown y `page_count`.
Trabaja en memoria. No guarda documentos ni se conecta a MongoDB: el API
Service coordina el flujo y Document Service persiste el resultado.

Postman sirve como cliente para mostrar la petición y las respuestas. Vegeta
genera carga y mide latencia; no forma parte de la aplicación. No hay una Saga
implementada en este servicio.

## Recorrido real de la petición

1. `app/main.py` crea y conecta FastAPI; `app/lifecycle.py` inicia el worker y
   gestiona el cierre. `app/routes.py` recibe HTTP, valida tipo, longitud y firma
   `%PDF`, y devuelve errores públicos con `application/problem+json`.
2. `app/admission.py` limita cuerpos simultáneos y espera; si no hay cupo,
   devuelve 429 con `Retry-After` antes de hacer una conversión.
3. `app/cache.py` calcula la clave SHA-256 del PDF. Un `HIT` reutiliza Markdown;
   `MISS`, `BYPASS` o `ERROR` ejecutan extracción. Un fallo temporal de Redis
   no impide procesar el PDF.
4. `app/service.py` coordina caché, permisos de CPU y solicitudes idénticas
   dentro de la réplica (`singleflight`).
5. `app/worker.py` ejecuta PyMuPDF en un proceso hijo `spawn`; no comparte un
   documento PyMuPDF entre hilos. `app/extractor.py` abre los bytes y
   `app/markdown.py` construye el resultado en orden.

El checksum interno identifica la entrada de caché; la respuesta no expone un
checksum. `X-Cache: HIT` no demuestra rendimiento de extracción real.

## Salud, fallos y contenedores

- `/health` y `/health/live` indican que el proceso HTTP responde.
- `/health/ready` devuelve 503 cuando el worker está irrecuperable o comienza
  el cierre. Un worker ocupado o un 429 no lo vuelven unhealthy.
- Redis caído produce readiness 200 degradada por defecto; se puede exigir
  Redis con `READINESS_REDIS_REQUIRED=true`.
- Ante `BrokenProcessPool`, la implementación marca la réplica como no disponible,
  termina con código 70 y el Compose local la reinicia con
  `restart: on-failure:3`.

`app/middleware.py` agrega IDs de correlación sin almacenar el PDF. El
Dockerfile instala dependencias con `uv` en el builder y usa `pip` sólo para
desinstalarlo durante el build; el runtime Python 3.12 no lo conserva. Usa
usuario no root y dependencias fijadas por `uv.lock`. El Compose local usa un
sistema de archivos de solo lectura, 1 CPU y 768 MiB por extractor; el proxy publica un
puerto dinámico. El Compose común del equipo define Consul Catalog y Traefik;
su configuración pertenece a infraestructura. La red compartida
es `pdf-network`.

El extractor expone `/metrics` si `METRICS_ENABLED=true` y permite trazas OTLP
por separado. [Infraestructura en `d854b12`](https://github.com/JeremiasRoda/pdf-infrastructure/tree/d854b12ec29206ae969dfc36dd9a36a433f3c1a4)
configura Prometheus, el scrape del extractor y Grafana bajo el perfil
`monitoring`; su ejecución conjunta no se comprobó aquí. El factor XI de
Twelve-Factor trata de **logs**, no de métricas ni trazas. Este repositorio no
implementa Consul, Saga, circuit breaker, reintentos de Traefik ni el
recolector central.

## Patrones para explicar en el oral

La referencia para el despliegue común es el `main` publicado de
`pdf-infrastructure` (`79370968`), `pdf-api-service` (`e191097b`) y
`pdf-document-service` (`b4fd3df`). En el Compose común figuran **tres
microservicios de aplicación**: `api`, `documents` y `extractor`. Traefik,
Consul, el registrador y las bases de datos son infraestructura. Un cuarto
microservicio queda **a confirmar con el equipo**; no aparece en ese Compose
ni en el registro de servicios.

| Patrón | Evidencia de implementación | Estado del despliegue común |
| --- | --- | --- |
| Proxy inverso e ingreso | Traefik recibe HTTP; el API Service expone `/process` y coordina el negocio. | Definido en el Compose común; no se levantó ese stack en esta revisión. |
| Balanceo | Traefik usa `consulCatalog` para instancias registradas; el Compose local del extractor balancea dos réplicas por Docker labels. | Probado antes en el despliegue local; el reparto del stack Consul queda a verificar en vivo. |
| Descubrimiento | El registrador publica `api`, `documents` y `extractor` con IP y health en Consul; Traefik filtra instancias `passing`. | Configurado, sin consulta en vivo al catálogo común en esta revisión. Las llamadas internas del API usan DNS de Docker. |
| Caché | El extractor usa Redis por SHA-256 y tolera su caída. | Activa en el Compose local; el Compose común fija `CACHE_ENABLED=false` y deja Dragonfly en un perfil opcional. |
| Capacidad o bulkhead | Traefik define rate limits de ingreso; Extractor: gates de cuerpo/CPU y worker; API: límite de `/process`; Documents: semáforo y pool MongoDB acotado. | Configurado en los tres; no se midió el comportamiento conjunto en esta revisión. |
| Reintentos | Traefik define un middleware de ingress. El API reintenta una vez el `GET` de checksum ante fallos elegidos; no reintenta los `POST` a extractor ni a Documents. | Middleware enlazado en la configuración común; su activación ante fallos reales no se verificó aquí. |
| Circuit breaker | Traefik define middlewares para ingress de API y extractor; los clientes del API tienen circuitos por dependencia y tests de estados. | Configurado y probado en tests del API; no se provocó su apertura en el stack común aquí. |
| Saga | El API consulta duplicados, extrae y solicita guardar; no hay pasos de compensación ni transacción distribuida. | **No implementada.** k6 y Vegeta son generadores de carga, no patrones de coordinación. |

Fuentes precisas: [Compose y servicios comunes](https://github.com/JeremiasRoda/pdf-infrastructure/blob/79370968d5e826b22c05198e53f2fccb9ccf893a/docker-compose.integration.yml),
[proveedores de Traefik](https://github.com/JeremiasRoda/pdf-infrastructure/blob/79370968d5e826b22c05198e53f2fccb9ccf893a/traefik/traefik.yml),
[middlewares](https://github.com/JeremiasRoda/pdf-infrastructure/blob/79370968d5e826b22c05198e53f2fccb9ccf893a/traefik/dynamic/middlewares.yml),
[registro en Consul](https://github.com/JeremiasRoda/pdf-infrastructure/blob/79370968d5e826b22c05198e53f2fccb9ccf893a/registrator/registrator.py),
[clientes y circuitos del API](https://github.com/Lourdesrizza/pdf-api-service/blob/e191097bba601efffe729b811ccbf872b483318b/app/clients/circuit.py),
[tests de circuitos](https://github.com/Lourdesrizza/pdf-api-service/blob/e191097bba601efffe729b811ccbf872b483318b/tests/test_client_resilience.py),
[reintento del GET de checksum](https://github.com/Lourdesrizza/pdf-api-service/blob/e191097bba601efffe729b811ccbf872b483318b/app/clients/documents.py),
[flujo del orquestador](https://github.com/Lourdesrizza/pdf-api-service/blob/e191097bba601efffe729b811ccbf872b483318b/app/services/orchestrator.py),
[admisión de Documents](https://github.com/angelina-magallanes/pdf-document-service/blob/b4fd3dfc5c2c98e0c8a6a227e04aea18892982db/app/middleware.py).

### Un PDF nuevo, paso a paso

1. El cliente envía el PDF a Traefik y éste lo dirige al API Service. Consul
   informa qué instancias están disponibles para ese ingreso; no extrae PDFs.
2. El API calcula el checksum y consulta a Documents. Si ya existe, devuelve
   el documento guardado sin llamar al extractor.
3. Si es nuevo, el API envía los bytes `application/pdf` a `extractor:8000`
   por DNS de Docker. Esa llamada interna no pasa por los middlewares de
   Traefik ni por Consul.
4. Mi extractor valida el PDF, consulta Redis si está habilitado y convierte
   en memoria cuando no hay HIT. Devuelve `content` Markdown y `page_count`.
5. El API solicita a Documents guardar el resultado. Documents resuelve
   duplicados y persiste en MongoDB 7; el extractor no guarda documentos.

**Respuesta corta — patrones:** «Usamos Traefik como ingreso y balanceador;
el stack común configura descubrimiento con Consul. Mi extractor aplica caché
Redis y límites de capacidad. El API tiene circuit breakers por dependencia y
un reintento acotado para consultar checksum. No implementamos una Saga. La
configuración común existe, pero su ejecución completa requiere una prueba
conjunta antes de decir que todos esos patrones funcionaron en vivo».

**Respuesta corta — observabilidad:** «Los tres microservicios confirmados
emiten logs y tienen health checks. Los IDs permiten relacionar peticiones. El
extractor expone `/metrics` y ofrece trazas OTLP sólo si se habilitan.
Infraestructura publicó Prometheus y Grafana con un scrape del extractor, pero
no comprobamos ese perfil en ejecución ni una recolección completa de métricas,
logs y trazas de todos. El factor XI pide logs como flujo de eventos; no exige
Grafana». Ver [observability.md](observability.md) para consultar cada señal.

## Pruebas y cobertura

`tests/` cubre contrato HTTP, PDFs válidos e inválidos, caché, admisión,
cancelaciones, salud, cierre y recuperación. `tests/integration/` incluye
Redis real y verificación de balance, que requieren servicios Docker.
La suite normal omite la integración real si no se habilita expresamente.

Hay registros RED → GREEN para cambios puntuales en
`tests/stress/results/optimization-cold-20261007/`. Eso demuestra una
secuencia TDD para esos cambios; la existencia de tests no demuestra que
todo el proyecto se haya desarrollado con TDD.

Para medir cobertura de código Python, usar `coverage.py` con `--branch` y
`--source app`, ejecutar pytest y luego `coverage report -m`. No se afirma
100 % de cobertura; el porcentaje depende de la suite ejecutada y debe
registrarse junto al comando y la revisión del código.

En la revisión del 7 de noviembre, la suite habitual dio **91 passed,
1 skipped** y `coverage run --branch --source=app -m pytest` informó **80 %**
global. La ejecución del proceso hijo `spawn` no se instrumentó en ese comando:
por eso `app/extractor.py` y `app/markdown.py` figuran con cobertura baja aunque
las pruebas de PDF comprobaron la respuesta final. Para afirmar cobertura de
esas líneas hay que instrumentar también los procesos hijos.
Tras ordenar los módulos el 9 de noviembre, la suite dio **92 passed,
1 skipped**; no se volvió a medir cobertura, por lo que el 80 % anterior no
debe presentarse como cifra de la revisión actual.

## Qué mostrar en clase

1. Arrancar el stack local con `scripts/start.ps1` y comprobar ambas réplicas
   healthy. El despliegue común se inicia desde infraestructura, no con el
   Traefik local de este repositorio.
2. Consultar `/health/ready` y enviar un PDF pequeño a `/extract` con Postman
   o `scripts/verify.ps1`; mostrar HTTP 200, Markdown y páginas.
3. Repetir el mismo PDF y explicar `MISS`/`HIT`. Mostrar un PDF inválido y
   explicar el 400, sin ejecutar pruebas de carga en vivo.
4. Consultar `docs/performance.md` para k6, Vegeta y sus condiciones. Los
   resultados históricos no prueban que el HTTP frío actual tenga p95 <400 ms.

Antes de afirmar una versión final, acordar el identificador de imagen y
commit con el equipo: `pyproject.toml` declara `0.1.0`, mientras OpenAPI
todavía anuncia `1.0.0`.
