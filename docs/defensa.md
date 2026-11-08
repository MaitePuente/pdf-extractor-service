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

1. `app/main.py` recibe HTTP, valida tipo, longitud y firma `%PDF`, y devuelve
   errores públicos con `application/problem+json`.
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

El Dockerfile usa un runtime Python 3.12 sin `pip`, usuario no root y
dependencias fijadas por `uv.lock`. El Compose local usa sistema de archivos
de solo lectura, 1 CPU y 768 MiB por extractor; el proxy local publica un
puerto dinámico. El Compose común del equipo usa Consul Catalog y Traefik;
su configuración y Portainer pertenecen a infraestructura. La red compartida
es `pdf-network`.

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

En la revisión local del 7 de noviembre, la suite habitual dio **91 passed,
1 skipped** y `coverage run --branch --source=app -m pytest` informó **80 %**
global. La ejecución del proceso hijo `spawn` no se instrumentó en ese comando:
por eso `app/extractor.py` y `app/markdown.py` figuran con cobertura baja aunque
las pruebas de PDF comprobaron la respuesta final. Para afirmar cobertura de
esas líneas hay que instrumentar también los procesos hijos.

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
