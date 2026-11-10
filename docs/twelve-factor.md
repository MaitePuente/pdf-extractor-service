# Twelve-Factor aplicado al extractor

Estado actual del repositorio. La aplicación extrae en memoria; Redis es una
caché descartable y MongoDB pertenece a Document Service. La imagen del
extractor, Redis real y Traefik local se probaron en Docker. La integración
central y las mediciones de rendimiento tienen sus propios límites en
[performance.md](performance.md).

| Factor | Implementado | Probado | Pendiente o límite |
| --- | --- | --- | --- |
| I. Codebase | Servicio en repositorio independiente. | `main` y sus revisiones están en Git. | Acordar con el equipo el commit de cada despliegue. |
| II. Dependencies | `pyproject.toml` y `uv.lock`; el builder instala con `uv` y el runtime copia `.venv`. | Build Docker con lock. | No hay escaneo de vulnerabilidades verificado. |
| III. Config | Redis, caché, límites, health, métricas, trazas y cierre leen variables de entorno. | Tests de configuración y Compose. | Secretos del entorno común fuera del repositorio. |
| IV. Backing services | Redis por URL con política fail-open. | Integración real MISS/HIT y TTL en Compose local. | El perfil Dragonfly del Compose común no arrancó con 256 MiB en la prueba anterior. |
| V. Build, release, run | Docker multi-stage e imagen local etiquetada `pdf-extractor-service:0.1.0`. | Build y ejecución aislada. | No hay publicación de imagen en un registry ni release automatizada comprobada. |
| VI. Processes | API sin archivos persistidos; PyMuPDF en procesos `spawn`. | Extracción y recuperación real ante `BrokenProcessPool`. | `singleflight` es local a cada réplica. |
| VII. Port binding | Uvicorn escucha en 8000; Traefik local publica un puerto dinámico. | Health y extracción por Traefik local. | `pdf-network` debe crearse antes del Compose manual. |
| VIII. Concurrency | Dos réplicas y límites de admisión, cuerpo y CPU. | Reparto entre réplicas con el verificador de balance. | El p95 HTTP frío menor de 400 ms no está demostrado. |
| IX. Disposability | Readiness 503 durante cierre o pool roto; drenaje acotado y salida 70 ante fallo irreversible. | Tests de cierre y reinicio real de una réplica aislada. | Falta medir el drenaje de un PDF real durante `docker stop`. |
| X. Dev/prod parity | Mismo Dockerfile para Compose local e integración. | Build y flujo integrado temporal. | No se demostró paridad con producción; el Compose común usa otros límites y política de reinicio. |
| XI. Logs | Eventos y profiling a stdout con IDs de correlación. | Logs observados en Docker. | No hay agregación central propia; métricas y trazas opcionales son capacidades distintas de este factor. |
| XII. Admin processes | Tests y scripts de arranque, parada y verificación. | Pytest y scripts locales. | No hay migraciones de base de datos en este servicio porque no persiste. |

El Dockerfile usa `pip` **sólo para desinstalarlo** de la imagen final durante
el build; las dependencias se instalaron antes con `uv`. Este repositorio no
implementa Consul, Saga, circuit breaker ni reintentos de Traefik. Esas
capacidades, si existen en el despliegue común, se verifican en
`pdf-infrastructure` y no se atribuyen al extractor. Allí se publicó
Prometheus/Grafana con scrape de `/metrics`
del extractor; su ejecución conjunta sigue sin verificarse en esta revisión.

## Prueba específica de drenaje aún pendiente

1. Levantar dos réplicas con el comando de `README.md`.
2. Iniciar una extracción real con un PDF permitido y registrar el `X-Request-ID`.
3. Mientras esté en curso, ejecutar `docker compose -f compose.yaml -f compose.traefik.yaml stop -t 35 extractor`.
4. Comprobar `/health/ready` durante el drenaje si la réplica sigue accesible; Traefik puede dejar de enrutarla antes.
5. Revisar logs y `docker inspect` para confirmar el cierre dentro de 35 segundos y ausencia de hijos huérfanos. Registrar si la solicitud terminó o fue cancelada.

No se declara aprobada esta prueba hasta ejecutarla. El plazo predeterminado
`GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS=30` es menor que `stop_grace_period=35s`.
