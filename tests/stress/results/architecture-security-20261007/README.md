# Evidencia de arquitectura y seguridad — 2026-10-07

Repositorio standalone, rama `main`, HEAD inicial
`0e100e7d4f58934e6ccced413e7a622d1e7a73db`. Sin commit ni push.
No se alteraron resultados históricos ni los cuatro scripts de profiling.
`initial.json` contiene SHA-256 de los archivos preexistentes para comprobarlo.

## Pruebas

- `baseline.log`: `uv run --locked pytest -v`: 40 passed, 1 skipped.
- `baseline-redis.log`: integración Redis real: 1 passed.
- `tests-final.log`, `tests-final-recheck.log`, `pytest-release.log`: suites de
  la implementación nueva. Consultar el último para el estado final.
- `integration-final.log`: primer intento posterior; ERROR en vez de MISS.
- `integration-recheck.log`: segundo intento; MISS y TTL correctos, ERROR en
  vez de HIT. No se eliminan ni se presentan como pasados.
- `integration-release.log`: último intento, contra la imagen final después
  del build completo y arranque: 1 passed, 60 deselected en 14,83 s. Verifica
  MISS→HIT, contenido y TTL; no prueba estabilidad de latencia.
- `redis-diagnostic.json`: conectividad PING desde cada réplica, con tiempos.
  No reemplaza la prueba funcional MISS→HIT.

Las suites se ejecutaron con el entorno virtual existente y `UV_NO_SYNC=true`;
no cambiaron dependencias del host. La integración utilizó
`EXTRACTOR_BASE_URL=http://localhost:53701`, pasando por Traefik y DB 0. El test
crea un PDF único y elimina sólo su propia clave en `finally`, nunca una DB.

### TDD observado en consola

| Paso | RED | GREEN |
|---|---|---|
| `pytest tests/test_singleflight.py -v` | 1 failed, 1 passed: diez llamadas para bytes idénticos | 2 passed: mismo SHA una llamada, distintos SHA diez |
| `pytest tests/test_admission.py -v -x` | 1 failed: Content-Length excesivo recibía 400, no 413 | 4 passed: límites y admisión |
| `pytest tests/test_openapi.py -v -x` | 1 failed: no existía create_app | 2 passed: docs configurables y contrato |

Esta tabla resume salidas reales de consola, no archivos de log completos
conservados del RED. Se añadieron pruebas de cancelación, errores, CPU ocupada,
configuración y liberación de permisos. El contador 10→1 corresponde a un mock
explícito del límite de conversión, no a un benchmark de CPU.

## Docker y plataforma

- `Dockerfile.distroless-probe`, `distroless-build.log`, `distroless-run.log`:
  prueba real de la imagen Python 3.13 distroless con dependencias CPython 3.12.
  PyMuPDF importó; pydantic_core impidió importar FastAPI.
- `build-no-cache.log`: primer build fallido; se intentó quitar pip usando el
  Python de `.venv`, que ya no tiene pip. Se corrigió usando `/usr/local/bin/python`.
- `build-no-cache-final.log`: build completo sin caché aprobado después de esa
  corrección. Los logs posteriores corresponden a verificaciones finales.
- `build-release.log`: build `--no-cache` de todo el código final; exit 0.
- `start-release.log`: arranque con los scripts finales; exit 0.
- `start-windows.log`, `start-windows-final.log`: arranque Windows real.
- `validate_start_linux.sh`: sintaxis y cuatro flujos del bootstrap Linux,
  ejecutado en Linux con Docker simulado. No prueba Docker en otro host.
- `runtime.json`: identidad, capabilities, no-new-privileges, filesystem,
  shell/pip/uv y PDF real (hash de archivo y contenido; no se guarda el PDF).
- `docs-disabled.json`, `docs-toggle.log`: docs false → tres 404; restauración true.
- `quick-checks.json`: validaciones Compose, diff y estado.

El primer intento de `verify_runtime.py` no guardó su informe porque falló el
diagnóstico de Content-Length sin cuerpo: timeout de 10 s vía Traefik. La versión
guardada usa `Expect: 100-continue`, obtiene 413 y conserva el informe. Los PDF
funcionales devolvieron contenido correcto pero X-Cache ERROR, no HIT.

## Rendimiento

`host-before.json` y `singleflight-deferred/host.json` muestran RAM insuficiente
y paginación. `singleflight-guard.log` demuestra que el benchmark terminó antes
de enviar solicitudes o cambiar Redis. No hay nuevas distribuciones de latencia,
comparación 2/5 réplicas ni cargas k6/Vegeta de esta fase.

No interpretar los tiempos de verificaciones funcionales como benchmark. Los
resultados y pendientes se explican en `docs/performance.md` y `docs/security.md`.
