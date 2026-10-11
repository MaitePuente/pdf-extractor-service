# Extractor PDF a Markdown

Microservicio independiente en Python 3.12 y FastAPI. Sus dependencias y tests
son propios; no importa código ni configuración del monolito.

`pdf-extractor-service/` ya es la raíz del microservicio: contiene `app/`,
`tests/`, `Dockerfile` y los archivos Compose. Todos los comandos se ejecutan
desde la raíz del repositorio; si la terminal ya está allí, no hace falta otro
`cd`. Las menciones al monolito y los experimentos registrados corresponden
a la arquitectura original, antes de la migración; no son requisitos para
ejecutar este repositorio independiente.

## Contrato

- `GET /health`: HTTP 200, `{"status": "ok", "service": "extractor"}`.
- `GET /health/live`: vida del proceso, independiente de Redis.
- `GET /health/ready`: prueba breve de Redis; devuelve `ready` o `degraded`.
  Con `READINESS_REDIS_REQUIRED=true`, Redis caído produce HTTP 503.
- `POST /extract`: recibe los bytes del PDF como cuerpo `application/pdf`,
  sin formulario multipart. Devuelve HTTP 200 y `application/json`:
  `{"content": "<Markdown>", "page_count": 2}`.
- HTTP 415 si falta `Content-Type` o no es `application/pdf`.
- HTTP 400 si el cuerpo está vacío, no comienza con `%PDF`, no puede abrirse
  como PDF o requiere contraseña. Los errores públicos usan RFC 9457
  (`application/problem+json`) e incluyen `detail` y `request_id`.

El cuerpo se lee en memoria y se abre con
`pymupdf.open(stream=body, filetype="pdf")`. Se obtiene `page_count` y se pasa el
documento a `app.markdown.to_markdown`, basado en `page.get_text("blocks", sort=False)`.
Sólo se concatenan textos de bloques con `block_type == 0`, en su orden original.
El documento se cierra al
terminar, incluso si ocurre un error. No se guardan PDFs ni imágenes, no se crean
archivos temporales y no hay MongoDB. Redis conserva temporalmente solo el
resultado de conversión, como caché descartable.

No se ejecuta OCR ni se extraen imágenes. Los PDFs escaneados no obtienen
transcripción de sus imágenes en esta etapa. Cada página se emite como
`## Página N`, dos saltos de línea y su texto sin modificar. Se mantienen las
páginas vacías y el orden de páginas; el texto usa el orden nativo de PyMuPDF.
No se infieren estilos, títulos del documento ni énfasis de fuentes.
No reconstruye tablas, imágenes ni columnas mediante análisis semántico.
PyMuPDF4LLM y Layout siguen fijados en las dependencias para reproducir los
experimentos, pero la API actual no los importa ni ejecuta. La comparación
medida y las limitaciones figuran en [performance.md](docs/performance.md).

La conversión se ejecuta en procesos separados (`spawn`), configurables mediante
`EXTRACTION_CONCURRENCY` (por defecto 1 por réplica). `/health` continúa disponible.
Un HIT responde antes del gate de CPU. Los MISS/BYPASS/ERROR concurrentes con
el mismo SHA comparten un trabajo mediante **singleflight por réplica**; dos
réplicas pueden realizar dos conversiones. No es un bloqueo distribuido.
La admisión tiene capacidad y espera limitadas: devuelve **429 + Retry-After**
cuando se llena la cola o vence la espera; 503 indica un trabajador no disponible.
Un cuerpo declarado o efectivamente mayor que `MAX_UPLOAD_MB` recibe **413**.
Cancelar una petición no mata el proceso: la capacidad se libera al terminar
el trabajo pendiente. El apagado espera hasta el plazo configurado y luego
detiene sus trabajadores. La muerte inesperada
del trabajador requiere reiniciar la réplica; no se agregó recuperación automática.

`to_spans_markdown` y `to_text_markdown` conservan los conversores anteriores
únicamente para comparaciones offline; la API no los llama. No se importa ni
ejecuta PyMuPDF4LLM/Layout.

## Cache strategy

`SHA-256(PDF) -> Redis -> HIT/MISS`.

Después de validar el tipo de contenido, cuerpo no vacío y firma `%PDF`, se
calcula SHA-256 sobre **todos los bytes originales del PDF**, no sobre el texto,
nombre de archivo ni Markdown. La clave es `extract:v4:<sha256 hexadecimal>`.
El prefijo `v4` identifica el conversor por bloques textuales. Los resultados
Layout de `v1`, spans de `v2` y texto de `v3` no se reutilizan ni se borran;
expiran con su TTL original. En el PDF de 279 páginas, v3 y v4 conservaron
contenido exactamente igual; la versión identifica el motor elegido.
El prefijo debe cambiar si una futura modificación altera la representación.
Dos archivos con texto igual pero bytes distintos tienen claves distintas.

El valor es JSON con exactamente `content` y `page_count`. Redis recibe el
TTL en la misma operación `SET ... EX`; los HIT no renuevan la caducidad.
Solo se guardan extracciones exitosas. El contrato JSON de `/extract` no cambia:
la observabilidad se agrega mediante el header `X-Cache` y logging estándar
a stdout (`CACHE HIT`, `CACHE MISS`, `CACHE BYPASS`, `CACHE ERROR`).

| X-Cache | Comportamiento |
| --- | --- |
| `HIT` | Devuelve el resultado cacheado sin ejecutar la conversión. |
| `MISS` | No existe resultado; extrae, guarda con TTL y responde. |
| `BYPASS` | Caché desactivada; no crea un cliente Redis y extrae normalmente. |
| `ERROR` | Falla Redis o el valor cacheado es inválido; extrae y responde normalmente. |

Si falla una lectura no se intenta guardar en esa petición. Si falla el guardado,
se devuelve igualmente la extracción recién obtenida con `X-Cache: ERROR`.
Los valores cacheados inválidos se ignoran hasta su caducidad o eliminación
externa. Cada petición posterior vuelve a intentar Redis: no hay circuit breaker
ni reintentos automáticos. Las respuestas de error por PDF inválido mantienen sus
códigos y `detail`; no llevan un estado de caché de extracción exitosa.

Redis no es una dependencia crítica: un PING al iniciar calienta el único
cliente/pool de cada proceso, con el mismo plazo de 200 ms de las operaciones.
Si falla, se registra WARNING y la API igualmente inicia. `/health` indica
que la API está viva, sin consultar Redis. El cliente se comparte durante la vida
de la aplicación y se cierra al apagarla. Los fallos se registran como WARNING
sin incluir credenciales, URL completa ni contenido del documento.

### Variables de entorno

Se leen al iniciar la aplicación; cambiar sus valores requiere reiniciarla.

| Variable | Valor por defecto | Uso |
| --- | --- | --- |
| `REDIS_URL` | `redis://localhost:6379/0` | Conexión Redis de desarrollo; reemplazarla para cada entorno. |
| `CACHE_ENABLED` | `true` | Activa la caché; `false` permite trabajar sin Redis. |
| `CACHE_TTL_SECONDS` | `3600` | TTL entero positivo, en segundos. |
| `CACHE_TIMEOUT_SECONDS` | `0.2` | Plazo positivo por lectura o escritura Redis, en segundos. |
| `QUEUE_SIZE` | `16` | Esperas acotadas; junto con `MAX_IN_FLIGHT` limita a 20 solicitudes admitidas por réplica. |
| `MAX_IN_FLIGHT` | `4` | Máximo de cuerpos residentes por réplica, incluidos los retenidos por conversiones. |
| `EXTRACTION_CONCURRENCY` | `1` | Procesos CPU simultáneos; entero positivo, no mayor que `MAX_IN_FLIGHT`. |
| `ADMISSION_TIMEOUT_SECONDS` | `2` | Plazo de espera en cada gate de cuerpos/CPU; no es un timeout total HTTP. |
| `MAX_UPLOAD_MB` | `20` | Límite del PDF en MiB, tanto declarado como recibido por streaming. |
| `DOCS_ENABLED` | `true` | Habilita `/docs`, `/redoc`, `/openapi.json`; `false` deja las tres rutas en 404. |
| `READINESS_REDIS_REQUIRED` | `false` | Si Redis falla, readiness indica degradación con HTTP 200; `true` devuelve 503. |
| `READINESS_TIMEOUT_SECONDS` | `0.1` | Plazo del PING de readiness; no realiza trabajo pesado. |
| `METRICS_ENABLED` | `false` | Publica `/metrics` cuando está activo. Dejarlo desactivado durante benchmarks de competición. |
| `OTEL_ENABLED` | `false` | Activa instrumentación FastAPI y spans de fases. |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | vacío | URL base OTLP HTTP; obligatoria si se activa tracing. |
| `OTEL_SAMPLE_RATIO` | `0.05` | Muestreo de trazas entre 0 y 1. |
| `GRACEFUL_SHUTDOWN_TIMEOUT_SECONDS` | `30` | Plazo total desde la señal de salida antes de forzar el cierre. Debe ser menor que los 35 s de Compose. |

Los defaults, el presupuesto de memoria y las limitaciones están explicados en
[seguridad y admisión](docs/security.md). Se acepta `X-Request-ID` o el legado
`X-Audit-Id` (hasta 128 caracteres ASCII imprimibles); ambos se devuelven con
el mismo identificador, generado si falta. OpenAPI documenta el body binario y
las respuestas 200/400/413/415/422/429/500/503.

Se validan booleanos, TTL y timeout al iniciar. Valores inválidos de estas
opciones producen un error de configuración. Una URL Redis inválida se registra
como error de caché y permite iniciar en modo fail open.

El plazo limita cada operación de caché, **no** el tiempo total de `/extract`.
Un MISS puede efectuar una lectura y una escritura. Singleflight comparte
extracción entre solicitudes idénticas dentro de una réplica; entre réplicas
puede haber conversiones simultáneas del mismo PDF.

## Ejecución local

Desde la raíz del repositorio, en PowerShell, con Python 3.12 y uv:

```powershell
# Terminal ubicada en la raíz de pdf-extractor-service.
uv sync --locked
$env:CACHE_ENABLED = "true"
$env:REDIS_URL = "redis://localhost:6379/0"
$env:CACHE_TTL_SECONDS = "3600"
$env:CACHE_TIMEOUT_SECONDS = "0.2"
uv run --locked uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Desde otra terminal ubicada en la raíz del repositorio:

```powershell
curl.exe http://127.0.0.1:8001/health
$pdfPath = (Resolve-Path 'C:\ruta\a\documento.pdf').Path
curl.exe -i --fail-with-body -X POST http://127.0.0.1:8001/extract -H "Content-Type: application/pdf" --data-binary "@$pdfPath"
```

Reemplazar `C:\ruta\a\documento.pdf` por un PDF disponible en la máquina;
no se presupone una carpeta de PDFs del monorepo ni es necesario copiarlo al
repositorio. No se usa como fixture: los tests generan sus propios PDFs mínimos
en memoria.

Con Redis disponible, repetir exactamente el mismo pedido permite ver `MISS`
y luego `HIT` antes de que expire el TTL. Sin Redis disponible, la API inicia y
extrae igualmente, con `X-Cache: ERROR` y un WARNING en stdout. Para desactivar
la caché, establecer `$env:CACHE_ENABLED = "false"` antes de iniciar Uvicorn.

## Tests

Ejecutar desde la raíz del repositorio:

```powershell
uv run --locked pytest -v
```

Estado local actual: **suite completa: 79 passed, 1 skipped**. Los 60 casos
de la fase de arquitectura siguen pasando; se agregaron pruebas de readiness,
RFC 9457, correlación, métricas, trazas y apagado. No necesitan
Docker ni Redis; el skip corresponde a la integración real, habilitada
explícitamente con `--run-integration`.

La integración Redis se ejecuta aparte mediante Traefik, comprobando MISS→HIT,
contenido y TTL. La última fase anterior registró **1 passed**; aún no se repitió
contra este estado local porque Docker Desktop no está disponible.
Hubo dos intentos intermedios fallidos por timeout; no se ocultan ni se presenta
el último éxito como estabilidad de latencia. Todos los resultados están en la sección
[arquitectura y seguridad](docs/performance.md#arquitectura-y-seguridad-2026-10-07).

La configuración de pytest corta la búsqueda de `conftest.py` en `tests/` para
evitar importar los fixtures de MongoDB cuando el servicio estaba en el
monorepo original. El comando anterior
ejecuta únicamente la suite de este microservicio.

Se cubren salud, respuesta JSON, Markdown, cantidad y orden de páginas,
cuerpo vacío, firma inválida, PDF corrupto, PDF con contraseña, tipos de contenido
incorrectos o ausentes, parámetros del tipo de contenido y PDF de imagen sin OCR.
Los tests de caché usan un fake pequeño en el límite del cliente Redis: comprueban
HIT/MISS, claves SHA-256 distintas, contenido y páginas, TTL enviado, BYPASS,
fallos de lectura/escritura, timeout, valores inválidos y cierre del cliente.
No requieren un servidor Redis real ni agregan una biblioteca de fakes.
Los tests originales se ejecutan con caché desactivada mediante un fixture de
entorno para que nunca dependan del Redis configurado en la máquina del equipo.

## Docker

Construir desde la raíz del repositorio:

```powershell
docker build --tag pdf-extractor-service:0.1.0 .
```

Para levantarlo de forma independiente:

```powershell
docker run --rm --name pdf-extractor-service -p 127.0.0.1:8001:8000 pdf-extractor-service:0.1.0
```

El contenedor usa un usuario sin privilegios y las dependencias de ejecución
fijadas en `uv.lock`, incluido el cliente `redis` con API asyncio. El Dockerfile
tiene etapas de tooling (`uv`), builder y runtime; sólo el builder instala
dependencias. El runtime recibe el entorno construido y no incluye `pip` ni `uv`.
Conserva shell por compatibilidad de Python 3.12; la prueba distroless y sus
limitaciones están en [security.md](docs/security.md). Dentro del
contenedor, `localhost` apunta al propio contenedor: pasar `-e REDIS_URL=...`
con la dirección accesible del Redis elegido, o `-e CACHE_ENABLED=false`.

## Docker Compose: configuración de entrega y alternativa local

Todos los comandos siguientes se ejecutan desde la raíz de `pdf-extractor-service/`.
El proyecto Compose se llama `pdf-extractor`, independiente del monolito.

### Arranque de la configuración de entrega

Arranque automático desde la raíz del repositorio:

```powershell
.\scripts\start.ps1
```

En Linux, con Docker Engine y Docker Compose disponibles:

```sh
./scripts/start.sh
```

Ambos comprueban Docker, crean `pdf-network` sólo si falta, levantan dos réplicas,
esperan sus healthchecks y muestran las URLs con el puerto dinámico de Traefik.
Swagger: `http://localhost:<puerto>/docs`; ReDoc: `/redoc`; esquema: `/openapi.json`.
En Windows puede ser necesario habilitar la ejecución del script sólo para esa
invocación: `powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1`.
No se cambia la política global del equipo.

Para detener únicamente este proyecto, conservando la red externa:

```sh
docker compose -f compose.yaml -f compose.traefik.yaml down
```

Los pasos manuales equivalentes son:

`pdf-network` es **externa intencionalmente**: debe ser compartida por los
microservicios independientes del equipo. `compose.yaml` declara
`external: true`; Compose no crea ni elimina esa red.

1. **Una sola vez, si la red no existe**, crearla. Se puede comprobar antes
   con `docker network inspect pdf-network`:

   ```powershell
   docker network create pdf-network
   ```

2. **Levantar la configuración de entrega**: dos réplicas extractor,
   Traefik y Redis compartido, esperando sus healthchecks:

   ```powershell
   docker compose -f compose.yaml -f compose.traefik.yaml up --build -d --scale extractor=2 --wait --wait-timeout 150
   ```

En una máquina limpia, `docker compose up --build` por sí solo requiere
primero crear la red. Además, el Compose base no incluye Traefik: para la
entrega se usa el comando completo del paso 2. No se debe crear de nuevo una
red que ya exista y sea utilizada por los otros microservicios.

El extractor, Redis y Traefik se conectan a `pdf-network`. Las peticiones de
la configuración de entrega entran por el puerto dinámico de Traefik; las
APIs no publican puertos directos. Los comandos para consultar ese puerto
están en [Traefik y balanceo de carga](#traefik-y-balanceo-de-carga).

### Alternativa local: extractor y Redis sin Traefik

Usar esta alternativa en lugar del despliegue de entrega, con `pdf-network`
ya creada. Los ejemplos de puerto directo e integración de esta sección
corresponden al Compose base. Para cambiar desde el modo balanceado, consultar
[Detener el modo balanceado o volver a una instancia directa](#detener-el-modo-balanceado-o-volver-a-una-instancia-directa).

```powershell
docker compose up --build -d --scale extractor=1
docker compose ps
```

Redis es accesible por el nombre de servicio `redis`, sin publicar su puerto
en Windows. El extractor recibe `REDIS_URL=redis://redis:6379/0` y
`CACHE_ENABLED=true`.

Redis y extractor tienen healthchecks. Esperar a que ambos aparezcan `healthy`
antes de comprobar MISS/HIT. También se puede usar:

```powershell
docker compose up -d --wait --wait-timeout 120
```

No hay dependencia de arranque que exija Redis sano: la API debe poder arrancar
y mantenerse disponible aunque falle la caché. Si se envía un pedido antes de
que Redis esté listo, puede responder `X-Cache: ERROR` mediante fail open.

### Puerto local y demostración MISS/HIT

Docker asigna un puerto libre en `127.0.0.1` para el puerto interno `8000`.
No hay `container_name` ni puerto publicado fijo que impidan escalar.
El Compose base permite ejecutar una sola instancia directamente; el modo
con Traefik se describe más abajo y elimina los puertos directos del extractor.
El puerto puede cambiar al recrear el contenedor; consultarlo nuevamente:

```powershell
$baseUrl = "http://" + (docker compose port extractor 8000).Trim()
curl.exe --fail-with-body "$baseUrl/health"

# Elegir un PDF local; no se requiere una carpeta del monorepo.
$pdfPath = (Resolve-Path 'C:\ruta\a\documento.pdf').Path
$key = "extract:v4:" + (Get-FileHash -LiteralPath $pdfPath -Algorithm SHA256).Hash.ToLowerInvariant()
# Borrar solo el resultado de este PDF para comenzar con MISS, nunca FLUSHDB:
docker compose exec -T redis redis-cli DEL $key

curl.exe -i --fail-with-body "$baseUrl/extract" -H "Content-Type: application/pdf" --data-binary "@$pdfPath"
curl.exe -i --fail-with-body "$baseUrl/extract" -H "Content-Type: application/pdf" --data-binary "@$pdfPath"

docker compose exec -T redis redis-cli TTL $key
docker compose logs extractor
```

Se esperan HTTP 200, `X-Cache: MISS` y luego `X-Cache: HIT`, con exactamente los
mismos `content` y `page_count`. El TTL debe ser positivo y no mayor al configurado;
los logs deben incluir `CACHE MISS` y `CACHE HIT`. No modificar el PDF entre pedidos.

### Integración real separada

Con ambos servicios sanos:

```powershell
uv run --locked pytest --run-integration -m integration -v -s
```

La prueba usa HTTP real contra la API del contenedor y `redis-cli` contra Redis
real mediante `docker compose exec`. No utiliza mocks ni publica Redis al host.
Genera un PDF mínimo con identificador único y dos páginas; limpia únicamente su
clave SHA-256 antes y después del test. Comprueba MISS/HIT, el contrato JSON exacto,
igualdad de resultados, valor almacenado y PTTL positivo que disminuye sin renovarse
en el HIT. Lee el TTL configurado del contenedor, no del entorno de los tests unitarios.
No espera los 3600 segundos completos hasta la caducidad: verifica el plazo efectivo
asignado por Redis. La opción `-s` muestra las respuestas y los PTTL observados.

Si se solicita la integración y Docker o los servicios no están disponibles,
el test falla con el error real; no se omite silenciosamente. Utilizar el TTL
predeterminado para que la clave no caduque entre las comprobaciones.

### Configuración y recursos

Antes de `docker compose up`, se pueden definir en PowerShell:

```powershell
$env:CACHE_TTL_SECONDS = "3600"
$env:CACHE_TIMEOUT_SECONDS = "0.2"
```

Compose aplica esos valores al extractor; no hereda un `REDIS_URL` local ni un
`CACHE_ENABLED=false` de otro uso del servicio.

| Servicio | CPU máxima | Memoria máxima | Configuración adicional |
| --- | --- | --- | --- |
| extractor | 1.0 CPU | 768 MiB | Usuario `extractor` (UID 10001), filesystem de solo lectura. |
| redis | 0.5 CPU | 256 MiB | `maxmemory 192mb`, expulsión `allkeys-lru`, RDB y AOF desactivados. |

Se usan `cpus` y `mem_limit` directamente en el servicio, opciones aplicadas por
Docker Compose local sin requerir Swarm. Referencia:
[servicios de Compose](https://docs.docker.com/reference/compose-file/services/).
Los 64 MiB restantes de Redis dejan margen para estructuras y buffers respecto
del límite de datos. La caché es descartable y no se configura persistencia.
El extractor no tiene volúmenes de datos ni un `/tmp` escribible: procesa el PDF
en memoria y el filesystem de solo lectura impide guardar PDFs en disco.
ONNX Runtime puede registrar que no pudo persistir su identificador de telemetría
y que usará uno en memoria. Se observó ese aviso con `read_only: true`; no impidió
el arranque, la extracción ni la prueba MISS/HIT y no requiere habilitar escrituras.

### Caída de Redis y detención

Para comprobar manualmente fail open, con el extractor iniciado:

```powershell
docker compose stop redis
curl.exe -i --fail-with-body "$baseUrl/extract" -H "Content-Type: application/pdf" --data-binary "@$pdfPath"
docker compose start redis
```

Durante la caída se espera HTTP 200 con `X-Cache: ERROR` y `CACHE ERROR` en logs.
Esperar nuevamente el estado sano de Redis para comprobar MISS/HIT.

Detener ambos servicios conservando los contenedores:

```powershell
docker compose stop
```

Eliminar los contenedores y volúmenes anónimos de **este proyecto** (caché descartable):

```powershell
docker compose down --volumes
```

La red externa `pdf-network` permanece. Estos comandos deben ejecutarse desde
la raíz de este repositorio para utilizar sus propios archivos Compose.

## Traefik y balanceo de carga

`compose.traefik.yaml` se combina con `compose.yaml`. Conserva un solo Redis,
la red externa y los límites de 1 CPU / 768 MiB por extractor. Elimina sus puertos
publicados con `!reset []` (requiere Compose 2.24 o posterior). Las peticiones
externas entran por Traefik; cada réplica expone únicamente el puerto interno 8000.
No hay nombres de contenedor fijos, afinidad de sesión ni reintentos configurados.

Se usan labels con router y servicio `pdf-markdown-extractor`, separados de los
nombres del monolito. `traefik.docker.network=pdf-network` selecciona explícitamente
la red. El provider Docker descubre las réplicas, agrupa sus servidores y excluye
los contenedores detenidos o con healthcheck Docker no saludable. El healthcheck
de cada extractor consulta `/health` cada 10 segundos. Un pedido en curso puede
fallar al detener su servidor: esta etapa no incorpora Retry. La prueba de caída
comprueba nuevas peticiones después de dejar converger los eventos Docker.

Referencia de configuración:
[provider Docker de Traefik](https://doc.traefik.io/traefik/reference/install-configuration/providers/docker/).

### Desarrollo aislado

En el entorno histórico del repositorio original se observó el Traefik del
monolito en `pdf-extactext_default`, sin conexión a `pdf-network`.
No se modifica ese contenedor ni su Compose. El proxy de desarrollo
se ejecuta en el proyecto `pdf-extractor`, publica un puerto libre solo en loopback
y usa la imagen `traefik:v3.6`. Su provider tiene la restricción
`Label(com.docker.compose.project,pdf-extractor)` para descubrir únicamente este
proyecto. No expone dashboard ni ocupa 80/443 del host. Tiene límite de 0.5 CPU y
512 MiB, y comparte `pdf-network`. El socket Docker se monta en modo de lectura.

Desde la raíz del repositorio, con `pdf-network` creada:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml up --build -d --scale extractor=2 --wait --wait-timeout 150
docker compose -f compose.yaml -f compose.traefik.yaml ps
$proxyPort = ((docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80).Trim()).Split(':')[-1]
$baseUrl = "http://localhost:$proxyPort"
curl.exe --fail-with-body "$baseUrl/health"
```

El host local por defecto es `localhost`, con HTTP por el entrypoint `web`.
Traefik registra access logs JSON en stdout. `ServiceAddr` identifica la IP de
la réplica y `request_X-Audit-Id` permite asociar cada pedido con su respuesta.
`docker inspect` permite mapear esa IP al nombre de contenedor.

```powershell
uv run --locked python tests/integration/verify_balance.py --replicas 2
docker compose -f compose.yaml -f compose.traefik.yaml logs traefik

docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=3 --wait --wait-timeout 150
uv run --locked python tests/integration/verify_balance.py --replicas 3
docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=4 --wait --wait-timeout 150
uv run --locked python tests/integration/verify_balance.py --replicas 4
docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=5 --wait --wait-timeout 150
uv run --locked python tests/integration/verify_balance.py --replicas 5 --stop-one
```

El verificador usa un PDF mínimo único, envía dos pedidos por réplica y exige
HTTP 200, un MISS inicial y HIT en los siguientes, con el mismo JSON. Comprueba
en los access logs que **cada réplica** recibió peticiones y tuvo acceso al mismo
resultado de Redis. Verifica también salud, límites y ausencia de puertos directos.
Elimina únicamente su propia clave de caché. `--stop-one` detiene una réplica sana,
espera tres segundos para la actualización del provider y exige respuestas correctas
desde todas las restantes; después restaura la réplica y espera que vuelva a estar sana.
Es una verificación funcional, no un benchmark de rendimiento ni un test de carga.

Verificación local realizada el 2026-10-06 con Docker Engine 29.7.2 y Compose 5.5.1:

| Réplicas sanas | Peticiones iniciales por instancia | Resultado |
| --- | --- | --- |
| 2 | 2, 2 | 4 HTTP 200; MISS inicial y 3 HIT. |
| 3 | 2, 3, 1 | 6 HTTP 200; todas recibieron peticiones. |
| 4 | 2, 2, 2, 2 | 8 HTTP 200; MISS inicial y 7 HIT. |
| 5 | 2, 2, 2, 2, 2 | 10 HTTP 200; MISS inicial y 9 HIT. |

Con cinco instancias se detuvo `pdf-extractor-extractor-1`, previamente sana.
Después de tres segundos de convergencia, diez pedidos nuevos fueron HTTP 200
y HIT, distribuidos entre las otras cuatro instancias (3, 2, 2, 3 pedidos).
La instancia detenida se restauró y volvió a estar sana. No se verificaron
peticiones en curso durante el apagado. Las respuestas y asignaciones se
correlacionaron con los access logs reales de Traefik.

Para ejecutar la integración de Redis existente a través de Traefik:

```powershell
$env:EXTRACTOR_BASE_URL = $baseUrl
uv run --locked pytest --run-integration -m integration -v -s
Remove-Item Env:EXTRACTOR_BASE_URL
```

La suite habitual `uv run --locked pytest -v` continúa funcionando sin Docker.
La cantidad de réplicas no garantiza rendimiento ni que todos los límites de RAM
puedan consumirse simultáneamente: cinco límites de 768 MiB suman 3840 MiB,
además de Redis, Traefik y otros proyectos. Comprobar recursos antes de escalar:

```powershell
docker info --format 'CPUs={{.NCPU}} Memory={{.MemTotal}}'
docker stats --no-stream
```

### Infraestructura común del equipo

El Traefik común debe estar conectado a `pdf-network`, tener el provider Docker
habilitado y permitir este proyecto en sus constraints. Su responsable debe
incorporar la red externa a su propio Compose; no basta con compartir el daemon.
Los providers sin restricciones también pueden descubrir estas labels, pero el
router/servicio tiene nombre propio y no reemplaza los del monolito.

Elegir con el equipo un host único y un entrypoint existente. Ejemplo para HTTPS:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml stop traefik
$env:EXTRACTOR_HOST = "extractor.universidad.localhost"
$env:EXTRACTOR_ENTRYPOINT = "websecure"
$env:EXTRACTOR_TLS = "true"
docker compose -f compose.yaml -f compose.traefik.yaml up -d --scale extractor=5 extractor redis
```

Al nombrar solo `extractor redis`, no se inicia el proxy de desarrollo. El Traefik
común se ocupa de sus puertos, certificado y access logs. La conexión con el
Traefik común debe verificarse en ese entorno; no se afirma que ya esté probada.
Para volver al proxy local, quitar esas tres variables antes de iniciar ambos Compose.

### Detener el modo balanceado o volver a una instancia directa

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml stop
# Volver al modo directo conservando Redis:
docker compose -f compose.yaml -f compose.traefik.yaml stop traefik
docker compose -f compose.yaml up -d --scale extractor=1 --wait --wait-timeout 150
```

Para eliminar únicamente este entorno y su caché descartable:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml down --volumes
```

La red externa y los contenedores del monolito permanecen.

### Baseline de rendimiento con k6

Los scripts independientes están en `tests/performance/`. Envían el PDF como
body binario a través del puerto actual de Traefik; no usan una réplica directa.
La ruta del documento es configurable y no es necesario copiarlo al repositorio.

El procedimiento reproducible, las mediciones y las limitaciones se registran
en [docs/performance.md](docs/performance.md). El override
`compose.performance.yaml` desactiva la caché solamente durante la medición;
omitirlo al ejecutar `up` restaura la configuración habitual sin borrar Redis.
El Spike oficial actual usa cuatro PDFs y k6 nativo de Windows: ejecutar
`run_official_spike.py --k6 <ruta-k6.exe>`. La sección **K6 Spike oficial nativo
en Windows** documenta el comando y el resultado completo. No ejecutarlo
automáticamente; el intento anterior con cliente Docker de 512 MiB es histórico.

### Histórico: text-only, diagnóstico de red y Redis caliente

El conversor de esa fase usó texto nativo por página, sin Layout/ONNX. En el PDF
externo `D:\INGENIERIA\3er\desarrollo de software\pdf279hojas.pdf` se verificaron
279 páginas, 276 con texto, 427,008 caracteres Markdown y SHA-256
`c636e1997422a5a99c45dc6ff9f2d2228f062d1e432b2948b373aa4328c1cdbc`.
Incluye encabezados `## Página N`; no es la representación del monolito.

La sesión anterior midió: candidato offline mediano **435.725 ms** (n=3), BYPASS
Windows directo **2861.464 ms** (n=1), BYPASS Windows por Traefik **2700.867 ms**
(n=1), Docker k6 por Traefik **1215.349 ms** (n=1). Ninguno acredita extracción
<400 ms. Diez HIT secuenciales por Traefik sí dieron **p95 328.654 ms**, máximo
331.286 ms, cero errores y dos HIT por réplica, sin ejecutar extracción.
No acredita estabilidad prolongada ni bajo concurrencia.

Los logs `PROFILE` incluyen recepción del body, SHA, GET Redis, algoritmo,
worker/IPC, creación de modelo, validación/serialización de Response y handler
total, correlacionados por X-Audit-Id. El handler total termina antes de enviar
el cuerpo por socket. Es instrumentación de diagnóstico; no cambia el JSON.

`compose.direct-diagnostic.yaml`, puesto **después** del overlay Traefik,
habilita temporalmente puertos directos dinámicos de localhost por réplica.
Omitirlo al volver a ejecutar `up` los elimina. No usarlo en infraestructura común.
`tests/performance/run_diagnostic.py --mode direct` ejecuta una sola petición
Windows directa; `--mode network` ejecuta una sola petición Docker k6 conectada
a `pdf-network`, **siempre por Traefik**, con la misma versión k6 2.2.0.
El PDF se monta sólo para lectura, no se copia al repositorio.

Ver comandos completos y evidencia en la sección **Fases A–F** de
[performance.md](docs/performance.md). El despliegue final conserva cinco
APIs, caché habilitada, el PING de arranque fail open de 200 ms y acceso externo
exclusivamente por Traefik; no se modificó su configuración funcional.

### Fase anterior: bloques y caché caliente progresiva

Se compararon cinco corridas alternadas por método con 1 CPU / 768 MiB:
`text` mediana **463.282 ms**, `blocks` mediana **414.434 ms**. Se adoptó blocks
por una reducción mediana de 10.5 % y cuatro pares más rápidos de cinco, con
igualdad exacta de todas las páginas y contenido. Conserva 279 páginas, 276
textuales, 427,008 caracteres y el SHA anterior. **La mediana pura no bajó de
400 ms.** El proceso CPU sigue admitiendo una extracción activa por réplica.

Con k6 2.2.0 desde Windows → Traefik → cinco APIs → Redis, todas las respuestas
calientes verificaron HTTP 200, HIT, 279 páginas y SHA. 1 VU / 20 iteraciones:
p95 **384.775 ms**, máximo 426.581 ms, cero errores. 2 VUs / 20 totales:
p95 **544.650 ms**, máximo 551.875 ms, cero errores. Se detuvo la escalada:
**5 VUs no ejecutado**. No se afirma p95<400 bajo concurrencia.

Namespace vigente `v4`, claves `v3` conservadas, timeout Redis sin cambios
(200 ms), cinco réplicas saludables, sin puertos directos. Suite: **38 passed,
1 skipped**; integración Redis real: **1 passed**. El script de experimento es
`tests/performance/blocks_path.py`. Resultados y comandos completos en
[performance.md](docs/performance.md), sección **Blocks y caché caliente**.

### Última fase: HOT CACHE con k6 dentro de Docker

`tests/performance/run_network_k6.py` ejecuta la imagen oficial
`grafana/k6:2.2.0` en `pdf-network`, con 1 CPU / 512 MiB para el cliente.
`network_hot.js` envía el PDF binario **por Traefik**, conservando Host localhost;
el documento externo se monta read-only y no se copia al repositorio.
Cada respuesta verifica HTTP 200, HIT, 279 páginas y el SHA de Markdown anterior.
Conserva logs, summary, recursos, salud/OOM y correlación X-Audit-Id.

Se precargó MISS y se validó HIT usando el mismo Redis compartido, DB 15
previamente vacío, mediante `compose.cache-benchmark.yaml`. No se borró caché
existente. Ese overlay cambia sólo REDIS_URL; omitirlo al ejecutar `up` restaura
DB 0. Para repetir, comprobar un DB vacío; no usar DEL/FLUSH para forzar MISS.

**Resultado 1 VU / 20 iteraciones: p50 89.657 ms, p95 675.247 ms, máximo
1119.765 ms; 20/20 HIT y 100/100 checks, cero errores.** Se detuvo la escalada:
**2 y 5 VUs no ejecutados**, tampoco gzip, Vegeta ni Spike. La mediana de
receive_body bajó a 68.386 ms frente a 199.637 ms desde Windows, pero hubo
picos de hasta 993.093 ms. No se alcanzó p95<400 y no se atribuye toda la demora
a Windows. No hubo OOM ni pérdida de salud observados.

Estado final: cinco extractores healthy, caché habitual DB 0 restaurada,
algoritmo blocks y recursos sin cambios. No se repitió pytest funcional en
esta fase; los resultados de la suite anterior se mantienen como históricos.
Comandos completos, métricas y condiciones de escalada/restauración en la
sección **HOT CACHE desde Docker** de
[performance.md](docs/performance.md).


## Prueba oficial con Vegeta: cuatro PDFs externos

Herramienta: `tests/performance/vegeta/run.py`, Vegeta Windows **v12.13.0** en
`D:\herramientas\vegeta\vegeta.exe`. Configuración fija: **50 req/s × 30 s**,
timeout HTTP **30 s**, 1500 solicitudes teóricas. Recorrido:
**Vegeta Windows → puerto dinámico de Traefik → dos extractores → Redis**.
El runner consulta el puerto; no utiliza endpoints directos de las APIs.

Los cuatro archivos oficiales, confirmados desde el filesystem, son:

- `2020-Scrum-Guide-Spanish-Latin-South-American.pdf` — 16 páginas.
- `scrum_manager_historias_usuario.pdf` — 62 páginas.
- `Essential-Kanban-Condensed-Spanish.pdf` — 90 páginas.
- `Filosofia Lean.pdf` — 42 páginas.

La carpeta externa se configura mediante `--pdf-dir`; no se copian PDFs al
repositorio. `pdf279hojas.pdf` queda reservado al benchmark especial de 279
páginas y **no participa** en Vegeta. Los targets HTTP rotan los cuatro documentos
con `@ruta` a sus bytes originales, sin Base64 ni compresión de entrada.

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

El entorno debe tener dos APIs, Redis y Traefik saludables antes de ejecutar.
El runner usa el overlay **existente** `compose.cache-benchmark.yaml` para apuntar
temporalmente las APIs a una DB vacía. No modifica Redis, Traefik, sus archivos,
el algoritmo ni los límites. No precarga PDFs: el inicio es **COLD CACHE**.
Al terminar restaura DB 0 y dos APIs. La DB de benchmark conserva sus claves
hasta el TTL; si sigue ocupada, elegir otra. No usar FLUSH/DEL para repetir.
La separación de DB aísla claves, pero comparte CPU, memoria y política de
expulsión del mismo Redis.

**Resultado del 7/10/2026: corrida abortada por OOM de Traefik**, no completó
30 s ni 1500 solicitudes. Se registraron **687 resultados**, **0 % success**,
33 HTTP 503 y 654 errores de conexión; p95 **6635.383 ms** y throughput exitoso
**0 req/s**. El proxy terminó con `OOMKilled=true`, exit 137, límite de 128 MiB.
Estas latencias de errores **no representan extracción ni HIT**, y no sustituyen
los resultados históricos de k6.

Se recuperó el mismo contenedor Traefik sin cambiar recursos/configuración;
el puerto dinámico pasó de 59345 a 64097. Estado final: **dos APIs, Redis y
Traefik healthy**, APIs nuevamente en DB 0. `/health` respondió 6/6 HTTP 200.
Bajo carga hay 33 access logs completos repartidos **20/13** entre ambas APIs;
los pedidos interrumpidos por OOM no tienen evidencia de backend completa.

Suite posterior: **40 passed, 1 skipped** (38 existentes + 2 tests del informe);
integración Redis real por Traefik: **1 passed, 40 deselected**. Evidencia local:
`tests/stress/results/official-vegeta-20261007-cold/`, sin PDFs. Detalles, hashes,
comparación con el profesor y limitaciones en la sección **Vegeta oficial** de
[performance.md](docs/performance.md). El perfil oficial completo sigue pendiente
por el OOM; no repetir automáticamente la misma carga sobre estos límites.


## Vegeta oficial repetida: Traefik con 512 MiB

El **7/10/2026** se repitió el perfil completo con un único cambio de
infraestructura: `compose.traefik.yaml`, **Traefik 128 MiB → 512 MiB**.
La primera corrida demostró OOMKilled y 123.3 MiB muestreados sobre 128 MiB;
se conserva íntegra como baseline en `official-vegeta-20261007-cold/`.
Se mantiene 0.5 CPU para Traefik, dos APIs de 1 CPU / 768 MiB, Redis,
el algoritmo, el timeout del cliente y el backpressure existentes.

**Sí se completó Vegeta 50 req/s × 30 s sin OOM: 1500 resultados.**
La ventana primera–última solicitud fue 29.971 s; hubo 29.834 s adicionales
esperando peticiones pendientes, para 59.805 s totales según Vegeta.
Se inició en **COLD CACHE**, DB 14 vacía, sin precargar documentos. Los cuatro
PDFs, sus páginas y hashes coinciden con el baseline; no se usó el PDF de 279
páginas. Cliente Windows → Traefik en puerto dinámico 53701 → dos APIs → Redis.

| Métrica | Resultado con Traefik 512 MiB |
| --- | ---: |
| Solicitudes iniciadas / resultados terminales | 1500 / 1500 |
| Respuestas HTTP completas | 67 |
| Throughput exitoso / success / errores | 0 req/s / 0 % / 100 % |
| HTTP 200 / HTTP 503 | 0 / 67 |
| Timeouts / otras conexiones fallidas | 1282 / 151 |
| Media | 26160.212 ms |
| p50 / p90 | 30005.397 / 30013.531 ms |
| p95 / p99 / máximo | 30015.049 / 30017.559 / 30060.443 ms |
| Bytes de cuerpos enviados / recibidos | 33,278,713 / 3,149 |
| RAM máxima muestreada de Traefik | 309.2 MiB de 512 MiB |
| OOMKilled final | false en los cuatro servicios |

Los percentiles incluyen errores y timeouts: **no miden extracción exitosa ni
CACHE HIT**, y no acreditan 400 ms. X-Cache estuvo ausente en los 1500 resultados;
no se validó contenido HTTP 200 bajo esta carga. Los 107 access logs completos
con X-Audit-Id demuestran tráfico en ambas APIs, **56/51**, incluyendo 40 estados
499 por clientes desconectados; ese reparto no cubre los 1500 intentos.

Al concluir la carga, ambas APIs y Traefik quedaron temporalmente unhealthy;
Redis siguió healthy. El proxy recuperó salud sin reinicio. El runner restauró
las dos APIs a DB 0, conservando imagen y entorno habitual. Estado final:
**dos APIs, Redis y Traefik healthy**, seis `/health` 200, reparto posterior 3/3,
DB 0 vacía. No se borraron datos de Redis.

Verificación posterior, sin instalar dependencias: `uv run --locked pytest -v`
con `UV_NO_SYNC=true` y `UV_OFFLINE=true`: **40 passed, 1 skipped in 39.69s**.
Integración Redis real por Traefik: **1 passed, 40 deselected in 20.23s**,
MISS→HIT y TTL correcto. No se cambió ningún código Python ni test.

Evidencia nueva: `tests/stress/results/official-vegeta-20261007-traefik512-cold/`.
Los comandos de la sección anterior siguen siendo reproducibles con un nombre
nuevo y una DB vacía; para aplicar el nuevo límite al proxy existente:

```powershell
docker compose config --quiet
docker compose -f compose.yaml -f compose.traefik.yaml config --quiet
docker compose -f compose.yaml -f compose.traefik.yaml up -d --no-deps --no-build --wait --wait-timeout 150 traefik
docker inspect pdf-extractor-traefik-1 --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'
# Resultado verificado: 536870912 bytes; 500000000 NanoCPUs.
```

La comparación completa 128/512 MiB, recursos, perfiles internos y comandos
está en **Vegeta oficial repetida: Traefik 512 MiB** de
[performance.md](docs/performance.md). El OOM observado quedó resuelto para
esta corrida; el rendimiento oficial sigue sin ser satisfactorio. No se
aplicaron otras optimizaciones ni se ejecutó k6 Spike.


## Histórico: K6 Spike Docker, inicio frío y OOM del generador

El **7/10/2026** se intentó ejecutar el perfil oficial **0→100 VUs en 10 s,
100 VUs durante 20 s y 100→0 en 10 s**. **NO completó los 40 segundos**:
Docker confirmó **OOMKilled=true, exit 137 del generador k6**, limitado a
1 CPU / 512 MiB. El proxy y los servicios no tuvieron OOM. No se aumentaron
recursos ni se repitió la carga después del OOM.

Configuración conservada: **dos APIs de 1 CPU / 768 MiB, Traefik de 0.5 CPU /
512 MiB, Redis compartido**, algoritmo y backpressure sin cambios. k6
`grafana/k6:2.2.0` corrió en `pdf-network`, con URL `localhost` resuelta a la IP
interna de Traefik y Host `localhost`; no accedió directamente a las APIs.

**COLD CACHE AL INICIO**, DB 13 vacía, sin precargar documentos ni borrar DB 0.
Se montaron individualmente en modo lectura los cuatro archivos externos:

- `2020-Scrum-Guide-Spanish-Latin-South-American.pdf` — 16 páginas.
- `scrum_manager_historias_usuario.pdf` — 62 páginas.
- `Essential-Kanban-Condensed-Spanish.pdf` — 90 páginas.
- `Filosofia Lean.pdf` — 42 páginas.

Los bytes, páginas y SHA coinciden con Vegeta. `pdf279hojas.pdf` no participa.
El Spike rota globalmente los cuatro PDFs y envía cuerpos binarios
`application/pdf`, sin Base64. Sus errores/checks/thresholds no abortan carga.

**Resultados parciales, no resumen final de k6:** 56 respuestas conservadas en
consola, todas HTTP 503; la salida nativa sólo alcanzó a persistir 14 resultados
HTTP. Traefik registró 75 solicitudes diferentes con reparto **37/38**:
63 estados 503, 9 estados 499 y 3 estados 502. Los estados del proxy no se
confunden con respuestas recibidas por k6. El total de requests, iteraciones,
req/s y percentiles finales de 40 s **no quedaron verificados**.

Sobre las **56 respuestas de consola, todas fallidas**, se calcularon p50
**279.918 ms**, p90 **754.030 ms**, p95 **777.199 ms** y máximo **1076.997 ms**.
Son percentiles parciales por interpolación lineal, no el benchmark completo
ni una mejora de extracción. X-Cache ausente en las 56 respuestas; no hubo
HIT/MISS observable en headers ni HTTP 200 para validar contenido bajo carga.

Antes de cargar: cuatro servicios healthy, seis health 200 y reparto 3/3.
Después: **dos APIs, Redis y Traefik healthy**, APIs restauradas a DB 0,
DB 0 vacía, seis health 200 y reparto 3/3. El generador temporal se eliminó
sólo después de guardar su inspección. Memoria máxima muestreada del cliente:
**348.1 MiB / 512 MiB**; el muestreo no capturó el pico que causó OOM.

Receta del cliente Docker de esa etapa, conservada como referencia histórica
(**no repetir el cliente de 512 MiB**; usar el comando nativo de la sección siguiente):

```powershell
$pdfDirectory = 'D:\INGENIERIA\3er\desarrollo de software'
$benchmarkDb = $null
foreach ($candidateDb in 1..15) {
    $keyCount = docker compose -f compose.yaml -f compose.traefik.yaml exec -T redis redis-cli --raw -n $candidateDb DBSIZE
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar Redis' }
    if ([int]$keyCount -eq 0) { $benchmarkDb = $candidateDb; break }
}
if ($null -eq $benchmarkDb) { throw 'No hay DB vacía; no borrar datos' }
$runName = 'official-k6-spike-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '-cold'
uv run --locked --no-sync --offline python tests/performance/run_official_spike.py --pdf-dir $pdfDirectory --name $runName --redis-db $benchmarkDb
```

**Este entorno demostró OOM del cliente: no relanzar automáticamente el Spike
con los mismos recursos.** El runner valida dos APIs y los límites actuales,
espera salud y descubrimiento de ambas por Traefik, monta PDFs read-only,
inspecciona el perfil sin hacer POST y restaura DB 0 al terminar. No ejecuta
Vegeta ni modifica Compose. La DB ocupada y la carpeta existente se rechazan.

Tests finales, usando el entorno existente sin instalar dependencias:
**40 passed, 1 skipped in 35.71s**; integración Redis real por Traefik:
**1 passed, 40 deselected in 16.83s**, MISS→HIT, contenido y TTL correctos.

Evidencia de carga en `tests/stress/results/official-k6-spike-20261007-cold-run2/`:
`partial-report.json`, log k6, métricas nativas, respuestas, inspección OOM,
recursos, access logs, caché, restauración y tests. Se conservaron aparte dos
fallos de preparación que no enviaron POST ni ejecutaron el Spike.
Comparación con el profesor y límites de los registros parciales en la sección
**K6 SPIKE OFICIAL** de [performance.md](docs/performance.md).


## K6 Spike oficial nativo en Windows: corrida completa

El **7/10/2026, 13:30 Argentina**, k6 Windows **v2.2.0** completó el perfil
**0→100 VUs en 10 s, 100 VUs durante 20 s, 100→0 en 10 s**. **SÍ completó los
40 s nominales**, sin aborto ni OOM. Resumen k6: **40.121 s**; ventana del
lanzador hasta recuperar el exit: **44.433 s**, incluyendo init y muestreo.
El exit **99** corresponde a thresholds fallidos, no a interrupción por OOM.

Ruta comprobada: `k6 Windows → 127.0.0.1:53701 (Traefik) → dos extractores → Redis`.
El runner descubre el puerto publicado; no se llama a una API directa. Se
conservaron **1 CPU / 768 MiB por API**, **0.5 CPU / 512 MiB para Traefik**,
Redis compartido, imágenes, algoritmo y backpressure. No hubo cambios en Compose.

Inicio **COLD CACHE**, DB **12** vacía, sin precarga y sin FLUSH. Las APIs
usaron esa DB sólo durante la corrida y volvieron a **DB 0** al terminar.
Los cuatro PDFs oficiales anteriores se leyeron desde su ubicación externa;
`pdf279hojas.pdf` no participó. Rotación de solicitudes iniciadas: **70/70/70/69**.
`spike.js` carga cada binario en init con `open(path, 'b')` y reutiliza su
ArrayBuffer, sin lectura por iteración, strings ni Base64. k6 mantiene copias
por VU: esto no promete memoria compartida entre VUs.

| Métrica | Nuestro resultado Windows | Profesor |
|---|---:|---:|
| Requests en el resumen HTTP | **179** (279 iniciadas) | 1037 |
| Req/s del resumen k6 | **4.462** | 25.35 |
| HTTP 200 | **139** | No desglosado; 0 % errores informado |
| HTTP 503 / otros | **39 / 1 HTTP 502** | 0 errores informado |
| `http_req_failed` | **22.35 %** (40/179) | 0 % |
| p50 | **5.106 s** | 1.88 s |
| p90 | **17.901 s** | 7.83 s |
| p95 | **19.959 s** | 8.80 s |
| Máximo | **33.602 s** | 13.94 s |
| Timeouts / errores de conexión observados | **0 / 0** en 179 resultados | 0 errores informado |

**100 iteraciones fueron interrumpidas por el ramp-down/stop sin gracia**,
conservado en el perfil (`gracefulRampDown=gracefulStop=0s`). No entran en los
179 resultados HTTP ni en sus percentiles/checks. De 279 solicitudes iniciadas,
139 finalizaron correctamente: **49.82 %**; 40 fallaron y 100 se interrumpieron.
No interpretar 0 timeouts como finalización de todas las solicitudes: el
cliente canceló las pendientes antes del timeout de 180 s.

Checks: **695/895 correctos (77.65 %)**. Los 139 HTTP 200 pasaron los cinco
checks, incluidos páginas, longitud y SHA de Markdown para los cuatro PDFs.
Headers recibidos: **134 HIT, 5 MISS, 0 ERROR, 0 BYPASS y 40 ABSENT**. El
resultado empezó frío y luego mezcló MISS/HIT; HIT no es extracción real.

Traefik registró las **279 solicitudes**, reparto **140/139**. Sus logs finales
incluyen resultados tardíos y efectos de restaurar DB 0: 144 estados 200,
39 estados 503, 32 estados 502 y 64 estados 499. No son los mismos estados
recibidos por k6. El snapshot inmediato a la carga tenía 241 registros;
ambos snapshots se conservan.

Sin OOM en APIs, Redis ni Traefik. Memoria máxima muestreada: APIs
**393.4 / 459.8 MiB**, Traefik **257.0 MiB**, Redis **8.07 MiB**. Windows registró
para k6 un pico residente de **1007.95 MiB** y pico de commit de **2461.00 MiB**;
no tuvo el límite de 512 MiB. Hubo presión de memoria en el host (mínimo
muestreado **12.80 MiB** físicos disponibles), por lo que no se atribuye toda
la latencia a un único componente. Recursos y perfiles completos en
[docs/performance.md](docs/performance.md).

### Repetir con k6 nativo

Desde la raíz del repositorio, con los cuatro servicios saludables. La receta
elige una DB ya vacía; no elimina datos ni sobrescribe evidencia:

```powershell
k6 version
where.exe k6
$k6Path = (Get-Command k6 -ErrorAction Stop).Source
$pdfDirectory = 'D:\INGENIERIA\3er\desarrollo de software'
$benchmarkDb = $null
foreach ($candidateDb in 1..15) {
    $keyCount = docker compose -f compose.yaml -f compose.traefik.yaml exec -T redis redis-cli --raw -n $candidateDb DBSIZE
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo consultar Redis' }
    if ([int]$keyCount -eq 0) { $benchmarkDb = $candidateDb; break }
}
if ($null -eq $benchmarkDb) { throw 'No hay DB vacía; no borrar datos' }
$runName = 'official-k6-spike-windows-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff') + '-cold'
uv run --locked --no-sync --offline python tests/performance/run_official_spike.py --k6 $k6Path --pdf-dir $pdfDirectory --name $runName --redis-db $benchmarkDb
```

`--k6` es obligatorio para esta receta: sin él, el runner conserva la opción
Docker histórica. No se instaló k6; se usó `C:\Program Files\k6\k6.exe`.
El runner espera salud y reparto por Traefik, inspecciona el perfil sin POST,
muestrea SUT y proceso Windows, conserva fallos de carga y restaura DB 0 en
`finally`. Su código de salida no reemplaza el de k6: consultar `execution.json`
(exit 99 en esta corrida), `summary.json` y `k6.log`.

Tests posteriores: **40 passed, 1 skipped in 29.35s**;
integración Redis real por Traefik: **1 passed, 40 deselected in 12.03s**,
MISS→HIT y TTL correcto. Estado final: **dos APIs, Redis y Traefik healthy**,
DB 0 restaurada y vacía, seis health 200 con reparto 3/3.

Evidencia nueva: `tests/stress/results/official-k6-spike-windows-20261007-cold/`
(`report.json`, resumen, métricas nativas, logs, estados/OOM, recursos,
validación de PDFs/caché y tests). La evidencia parcial anterior se conserva
intacta. **Se resolvió la interrupción del generador; no se cumplen los
umbrales de errores ni p95 < 400 ms del Spike.**

## Perfilado COLD posterior a la entrega

Los scripts `tests/performance/profile_*.py` investigan CPU, Markdown, SHA,
JSON, Redis, IPC y HTTP con el PDF externo de 279 páginas, sin reejecutar cargas
k6/Vegeta. [Resultados, limitaciones y comandos](docs/performance.md#perfilado-cold-posterior-a-la-entrega-2026-10-07).
No se confirmó p95 < 400 ms en las condiciones actuales. El ensayo SharedMemory
se revirtió: la API conserva el código de `0e100e7`, sus límites y configuración.
Los resultados HOT y oficiales históricos se mantienen como corridas distintas.

## Estado local posterior: salud, observabilidad y cierre

La red `pdf-network` sigue siendo externa para compartirla con otros servicios.
Desde la raíz, crearla una sola vez si falta y levantar la configuración usual
de entrega con dos réplicas:

```powershell
docker network inspect pdf-network 2>$null
if ($LASTEXITCODE -ne 0) { docker network create pdf-network }
docker compose -f compose.yaml -f compose.traefik.yaml up --build -d --scale extractor=2 --wait --wait-timeout 150
docker compose -f compose.yaml -f compose.traefik.yaml port traefik 80
```

Se puede usar `./scripts/start.ps1` en Windows o `./scripts/start.sh` en Linux
para crear la red si falta, iniciar el stack y mostrar el puerto real. No se
publica un puerto fijo de extractor con Traefik. El Compose base mantiene la
alternativa de una instancia sin proxy. Para detener sólo el stack de entrega:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml down
```

`/health/live` comprueba únicamente la vida del proceso; `/health/ready` hace un
PING breve a Redis. La caché sigue fallando en modo abierto: por defecto Redis
caído produce `degraded` con HTTP 200. Si la política operativa exige Redis,
`READINESS_REDIS_REQUIRED=true` produce 503. Durante SIGTERM/SIGINT, readiness
devuelve 503 y nuevas extracciones reciben Problem Details 503; Compose concede
35 s al contenedor para drenar dentro de los 30 s configurados.

`METRICS_ENABLED=true` habilita `/metrics` en formato Prometheus. El overlay
opcional añade Prometheus y Grafana; consume recursos y debe permanecer apagado
durante los benchmarks de competición:

```powershell
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.observability.yaml up --build -d --scale extractor=2 --wait --wait-timeout 150
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.observability.yaml port grafana 3000
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.observability.yaml port prometheus 9090
docker compose -f compose.yaml -f compose.traefik.yaml -f compose.observability.yaml down
```

Las trazas OTLP están desactivadas por defecto. Para activarlas se deben fijar
`OTEL_ENABLED=true` y `OTEL_EXPORTER_OTLP_ENDPOINT` al recolector elegido;
no se incluye Tempo. Ver [observability.md](docs/observability.md) para las
métricas, trazas, Postman y las verificaciones pendientes. La colección
`tests/postman/pdf-extractor.postman_collection.json` requiere elegir el PDF
externo en el cuerpo binary y ajustar `base_url` al puerto dinámico de Traefik.
Los 413 y 429 están automatizados en pytest; la colección permite comprobar
413 con un archivo externo de más de 20 MiB. La auditoría de los 12 factores
está en [twelve-factor.md](docs/twelve-factor.md).
