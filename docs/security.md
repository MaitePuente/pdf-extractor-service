# Arquitectura, límites y seguridad

## Cambios locales de contrato (2026-10-10)

Las fallas públicas de extracción se serializan como RFC 9457
`application/problem+json`; se conserva `detail` para clientes existentes y
se agrega `request_id`. El texto de excepciones inesperadas y los valores de
entrada rechazados por FastAPI no se devuelven. `X-Request-ID` o el legado
`X-Audit-Id` se validan como ASCII imprimible de hasta 128 bytes y se reflejan
en ambos headers. Las métricas sólo etiquetan método, ruta fija, status, estado
de caché y razón de rechazo; no usan nombre, SHA ni request ID como labels.
Las trazas son opcionales y no reciben bytes de PDF ni Markdown. El shutdown
marca no-ready, rechaza nuevas conversiones y espera como máximo el plazo
configurado antes de terminar los procesos propios del pool. Las pruebas
unitarias de estos contratos pasaron; el stop real del contenedor y un escaneo
de la imagen nueva están pendientes porque Docker Desktop no está disponible.

## Recorrido de una petición

1. Validar `Content-Type` y `Content-Length`: tipo incorrecto 415; tamaño
   declarado mayor que `MAX_UPLOAD_MB` 413, antes de solicitar bytes al ASGI.
2. Admisión global de solicitudes: como máximo `MAX_IN_FLIGHT + QUEUE_SIZE`.
   Si se agota, 429 con `Retry-After`, sin leer el cuerpo.
3. Reservar capacidad para un cuerpo residente. La espera tiene cola y plazo
   limitados. Leer por streaming y controlar también los bytes reales; un
   cliente sin `Content-Length` no puede evadir el límite.
4. Validar cuerpo y firma, calcular SHA-256 y consultar Redis.
5. **HIT: responder sin adquirir el gate CPU ni un worker.** Sí necesita pasar
   por el límite de cuerpos: no se conoce su SHA antes de recibir el archivo.
6. Sin HIT, unir por SHA en singleflight. Los seguidores liberan inmediatamente
   su copia y permiso de cuerpo; el líder conserva ambos hasta finalizar.
7. Sólo el líder espera un permiso CPU y convierte en un proceso `spawn`.
   Se vuelve a consultar Redis antes de CPU en un MISS, por si el trabajo anterior
   terminó entre la primera consulta y la creación del nuevo flight.
8. Guardar un resultado exitoso si correspondía MISS; compartir resultado o
   excepción con los seguidores y limpiar el flight. Un seguidor de MISS sigue
   indicando MISS: no se contabiliza falsamente como HIT de Redis.

El lock de singleflight protege sólo el diccionario, nunca la conversión.
`asyncio.shield` separa la cancelación de un cliente de la tarea compartida.
Cerrar la aplicación espera los trabajos pendientes hasta el plazo configurado
antes de cerrar procesos y Redis; si vence, termina los hijos del pool. Una
falla de worker devuelve 503; no hay reinicio automático del pool.
Los límites pertenecen a cada réplica, no al conjunto de réplicas.

## Por qué estos defaults

| Variable | Default | Criterio |
|---|---:|---|
| `MAX_UPLOAD_MB` | 20 MiB | Conserva el margen del PDF real de 17.749.468 bytes. |
| `MAX_IN_FLIGHT` | 4 | Hasta 80 MiB de entradas finales; el ensamblado puede duplicar temporalmente ese presupuesto. Deja margen dentro de 768 MiB para Python, worker, IPC y Markdown. |
| `QUEUE_SIZE` | 16 | Junto con cuatro cuerpos permite admitir el ejemplo de 20 clientes, sin almacenar 20 PDFs a la vez. No es un óptimo de rendimiento medido. |
| `EXTRACTION_CONCURRENCY` | 1 | Una CPU por réplica; no aumentar procesos sin comparación estable. Se probó funcionalmente la opción 2, no su rendimiento. |
| `ADMISSION_TIMEOUT_SECONDS` | 2 s | Espera finita, del orden de cuatro conversiones históricas de ~414 ms; no garantiza esa latencia bajo presión. Aplica por gate, no a todo HTTP. |
| `DOCS_ENABLED` | true | Facilita la defensa; false despublica las tres rutas de documentación. |

Los 768 MiB son el límite del contenedor. El cálculo anterior **no demuestra
ausencia de OOM para todo PDF**: el tamaño comprimido no limita el número de
páginas, el coste nativo, el Markdown de salida ni las copias IPC. Estos gates
limitan entradas de la aplicación, no toda la memoria de Traefik/Uvicorn/kernel.
No se agregó timeout de subida ni aislamiento frente a PDFs patológicos en esta
fase. Los clientes lentos pueden ocupar permisos hasta desconectarse.

En la prueba ASGI, 413 por `Content-Length` y 429 por admisión no invocaron
`receive`. Vía Traefik, 413 fue comprobado enviando sólo encabezados con
`Expect: 100-continue` y `Connection: close`. El primer diagnóstico, que anunció
un cuerpo grande pero no lo envió ni usó `Expect`, agotó 10 s de espera en el
cliente. El rechazo temprano de la aplicación no garantiza respuesta inmediata
en todos los comportamientos de transporte del proxy/cliente. No se cambió Traefik.

## Imagen y ejecución

`Dockerfile` tiene tres etapas: uv 0.11.6, builder Python 3.12 y runtime Python
3.12 slim. Sólo el builder ejecuta `uv sync --locked --no-dev --no-install-project`.
El runtime copia `.venv`; no instala dependencias. En la construcción se elimina
el pip global y `ensurepip`; uv no se copia. En la fase de arquitectura original
`pyproject.toml` y `uv.lock` no cambiaron. En la fase local posterior se añadieron
dependencias fijadas de Prometheus, OpenTelemetry y Ruff; el algoritmo y los
límites del contenedor no cambiaron.

En Compose, cada extractor conserva 1 CPU / 768 MiB y agrega:

```yaml
read_only: true
security_opt:
  - no-new-privileges:true
cap_drop:
  - ALL
```

Verificado mediante `whoami`, `id`, `docker inspect` y `/proc/1/status`:
usuario `extractor`, UID/GID 10001, `CapEff=0`, `CapBnd=0`, `NoNewPrivs=1`.
No hizo falta `tmpfs /tmp` para extracción. No se guardan PDFs ni archivos
temporales. El runtime mantiene shell y las herramientas del sistema base slim;
no se presenta como distroless ni como una imagen sin gestor de paquetes del SO.
Ni el Python de `.venv` ni el global pueden importar pip; no hay ejecutable uv.

### Prueba distroless

Se construyó una imagen de diagnóstico con
`gcr.io/distroless/python3-debian13:nonroot` (Python 3.13.5) y las dependencias
actuales construidas para Python 3.12. PyMuPDF importó, pero FastAPI falló con
`ModuleNotFoundError: pydantic_core._pydantic_core` por la extensión CPython 3.12.
El proyecto exige `>=3.12,<3.13`. Por eso esta imagen **no fue adoptada**.
No se demuestra incompatibilidad universal de PyMuPDF con distroless; migrar
intérprete/lock o construir un runtime distroless Python 3.12 propio es otro cambio.
La [documentación oficial de distroless](https://github.com/GoogleContainerTools/distroless)
explica las imágenes disponibles y los entrypoints sin shell. Dockerfile de
diagnóstico y salida quedan en `tests/stress/results/architecture-security-20261007/`.

## Bootstrap y documentación de API

Windows: `.\scripts\start.ps1`; Linux: `./scripts/start.sh`, desde la raíz.
Crean la red externa sólo si falta. No eliminan la red ni contenedores de otros
proyectos. Mantienen dos réplicas y publican sólo Traefik. `start.sh` usa LF y
permiso ejecutable en Git. Requieren Docker y Compose ya instalados.
El arranque Windows se ejecutó realmente; Linux se validó en un contenedor
Linux con `sh -n` y Docker simulado para red existente/ausente y fallos. No se
afirma haber desplegado en un segundo host Linux independiente.

`DOCS_ENABLED=true`: `/docs`, `/redoc`, `/openapi.json` por el puerto de Traefik.
Con false, las tres responden 404; se comprobó también en el despliegue y luego
se restauró true. El esquema anuncia PDF binario, JSON `content/page_count`,
estados de error, `X-Cache`, `X-Audit-Id` y `Retry-After` para 429.
`/health` es liveness de API: no certifica disponibilidad ni latencia de Redis.

## Referencias conceptuales

- [AsterMaybe/microservicio-extract-go](https://github.com/AsterMaybe/microservicio-extract-go): separación de admisión, cuerpos residentes y trabajo CPU; coalescing. Se eligieron límites propios para 768 MiB.
- [marcos-velez-20/pdf-extractext-repositorios](https://github.com/marcos-velez-20/pdf-extractext-repositorios): organización de servicios y configuración. El repositorio observado corresponde a persistencia; no se usó como evidencia de velocidad del extractor.
- [CNBRAVOCUENCA/extraccion-service](https://github.com/CNBRAVOCUENCA/extraccion-service): separación del procesamiento y la gestión de capacidad.

Se tomaron conceptos, sin copiar código. No se modificó el algoritmo PyMuPDF,
no se volvió a probar SharedMemory y no se agregaron Retry, Circuit Breaker ni Consul.
