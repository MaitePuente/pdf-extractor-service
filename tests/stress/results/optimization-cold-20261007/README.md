# Perfilado COLD: evidencia nueva, 2026-10-07

HEAD inicial 0e100e7. Ninguna carpeta histórica se reemplaza.

- initial.json: HEAD, hashes locales y contenedores iniciales.
- offline-before.json: diez muestras A-G, JSON y pickle aislados.
- candidates-before.json y candidates-extra-v2.json: variantes y control rotado.
  candidates-extra.stderr conserva un primer intento fallido del harness DisplayList, corregido en v2.
- transport.json: pares pickle/shared en worker persistente; overhead y algoritmo separados.
- http-*-before.json: referencia Windows inicial, n=10.
- http-*-shared.json: ensayo temporal SharedMemory, n=20, después revertido.
- shared-memory-trial.patch, payload-trial.txt, test_payload-trial.txt: fuente descartada.
- tdd-red.log, tdd-green-payload.log, tdd-red-worker-corrected.log, pytest-first-green.log:
  RED/GREEN válidos; suite experimental 43 passed, 1 skipped.
  tdd-red-worker.log es un error inicial del test/import, no el RED válido del comportamiento.
- offline-after.json: veinte repeticiones A-G; algoritmo sin cambios.
- pure-final.json: veinte conversiones exactas, pared/CPU.
- http-direct-final.json, http-traefik-final.json: n=20 BYPASS después del rollback.
- prime-miss.json: un MISS con proceso frío, fuera de distribuciones.
- http-hot-final.json: veinte HIT Windows.
- docker-traefik-*-final.json y *-server.json: diagnóstico Docker y correlación PROFILE.
- *.log: PROFILE/access logs; recursos e inspect también dentro de los JSON HTTP.
- environment-final.json: versiones, hardware, paginación y cgroups después de restauración.
- baseline-code-comparison.json: imagen inicial y código local coinciden, normalizando CRLF.
- pytest-final.log: 40 passed, 1 skipped; redis-integration-final.log: 1 passed, DB 0.
- documentation-preservation.json: contenido histórico de ambos Markdown conservado.
- *-command.json: comandos reales archivados; stdout/stderr separados en diagnósticos.

Muestras individuales intactas; percentiles con interpolación lineal.
El ruido del entorno creció entre fases: las diferencias no prueban causalidad.
El ensayo SharedMemory no está activo. Sin commit/push ni ramas nuevas.
