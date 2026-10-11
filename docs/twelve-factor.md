# Auditoría Twelve-Factor del extractor

Estado del repositorio local; las verificaciones Docker de la fase de observabilidad y apagado siguen pendientes mientras Docker Desktop no responde. Redis es caché descartable, no fuente de verdad.

| Factor | Cómo se cumple | Evidencia | Pendiente o límite |
| --- | --- | --- | --- |
| I. Codebase | Servicio en repositorio independiente, una imagen por revisión. | `pyproject.toml`, `Dockerfile` | No hay despliegue CI de una revisión publicada en esta fase. |
| II. Dependencies | Dependencias declaradas y fijadas por `uv.lock`; imagen copia `.venv` del builder. | `pyproject.toml`, `uv.lock`, `Dockerfile` | Reconstruir imagen con Docker operativo. |
| III. Config | Redis, límites, caché, health, métricas, trazas y drain se configuran por entorno. | `app/config.py`, `compose.yaml` | Los secretos de Redis deben entregarse por variables del entorno externo; no versionarlos. |
| IV. Backing services | Redis se conecta por URL y falla en modo abierto. | `app/cache.py`, `app/main.py` | Verificar integración Redis real de esta versión. |
| V. Build, release, run | Docker multi-stage separa builder/runtime. | `Dockerfile` | No hay release automatizada ni imagen publicada; el equipo debe fijar etiqueta y proceso de publicación. |
| VI. Processes | API sin estado de archivo; PyMuPDF trabaja en procesos `spawn`; caché compartida en Redis. | `app/worker.py`, `app/service.py` | Singleflight es local por réplica, no distribuido. |
| VII. Port binding | Uvicorn escucha 8000; Traefik publica puerto dinámico en localhost. | `app/server.py`, `compose.traefik.yaml` | Red externa `pdf-network` debe existir antes del Compose manual. |
| VIII. Concurrency | Réplicas Compose y gates de admisión/cuerpo/CPU. | `compose.yaml`, `app/admission.py` | Comparación de 2/3/5 réplicas y CPU 1/2 pospuesta por host inestable. |
| IX. Disposability | Señal de salida marca no-ready, rechaza nuevas extracciones y espera hasta deadline; cierra worker y Redis. | `app/server.py`, `app/main.py`, `app/worker.py`, `compose.yaml`, `tests/test_shutdown.py` | Parada real con `docker stop`, drain de petición real y ausencia de hijos zombie no verificados sin Docker. |
| X. Dev/prod parity | Mismo Dockerfile y overlays Compose; Redis y Traefik locales reales. | `compose.yaml`, `compose.traefik.yaml` | No hay plataforma de producción ni prueba de paridad de recursos. |
| XI. Logs | Eventos y profiling a stdout; IDs de correlación. | `app/profiling.py`, `app/problems.py` | No existe agregador central; deben protegerse logs y credenciales de infraestructura. |
| XII. Admin processes | `uv run --locked pytest`, scripts de arranque y comandos Compose. | `scripts/start.ps1`, `scripts/start.sh`, `README.md` | No hay migraciones ni tareas administrativas de base de datos, porque no se persiste. |

## Parada manual pendiente con Docker real

1. Levantar dos réplicas con el comando de `README.md`.
2. Iniciar una extracción real con un PDF permitido y registrar el `X-Request-ID`.
3. Mientras esté en curso, ejecutar `docker compose -f compose.yaml -f compose.traefik.yaml stop -t 35 extractor`.
4. Comprobar en otra terminal `/health/ready` durante el drain si el puerto de la réplica sigue accesible; por Traefik podría dejar de enrutarla antes.
5. Inspeccionar logs y `docker inspect` para confirmar cierre dentro de 35 segundos y ausencia de procesos hijos. Registrar si la solicitud original terminó o fue cancelada por el proxy/servidor.

Este procedimiento no se declara aprobado hasta ejecutarlo. `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` debe ser menor que `stop_grace_period`; el valor entregado es 30 s frente a 35 s.
