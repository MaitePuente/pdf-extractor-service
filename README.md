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
- `POST /extract`: recibe los bytes del PDF como cuerpo `application/pdf`,
  sin formulario multipart. Devuelve HTTP 200 y `application/json`:
  `{"content": "<Markdown>", "page_count": 2}`.
- HTTP 415 si falta `Content-Type` o no es `application/pdf`.
- HTTP 400 si el cuerpo está vacío, no comienza con `%PDF`, no puede abrirse
  como PDF o requiere contraseña. Los errores tienen el campo JSON `detail`.

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

La conversión se ejecuta en un proceso separado (`spawn`) con un solo trabajador
por réplica. `/health` continúa disponible. Si otra conversión ya ocupa ese
trabajador, una nueva extracción que necesita CPU recibe HTTP 503 con `detail`;
un HIT puede responder sin ocuparlo. No hay una cola ilimitada de conversiones.
Cancelar una petición no mata el proceso: la capacidad se libera al terminar
el trabajo pendiente. El apagado espera su finalización. La muerte inesperada
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

Se validan booleanos, TTL y timeout al iniciar. Valores inválidos de estas
opciones producen un error de configuración. Una URL Redis inválida se registra
como error de caché y permite iniciar en modo fail open.

El plazo limita cada operación de caché, **no** el tiempo total de `/extract`.
Un MISS puede efectuar una lectura y una escritura. No se afirma ningún objetivo
de rendimiento ni se evita que dos MISS simultáneos conviertan el mismo PDF.

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

Por defecto se ejecutan los 38 tests unitarios y se omite la integración real.
No necesitan Docker ni Redis. La integración se habilita explícitamente con
`--run-integration`; ver los comandos de Compose más abajo.

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
existente instala el lockfile actualizado y no necesita cambios. Dentro del
contenedor, `localhost` apunta al propio contenedor: pasar `-e REDIS_URL=...`
con la dirección accesible del Redis elegido, o `-e CACHE_ENABLED=false`.

## Extractor + Redis real con Docker Compose

Todos los comandos siguientes se ejecutan desde la raíz de `pdf-extractor-service/`.
El proyecto Compose se llama `pdf-extractor`, independiente del monolito.

### Red externa y arranque

```powershell
docker network inspect pdf-network
# Solo si no existe:
docker network create pdf-network

docker compose up --build -d
docker compose ps
```

El archivo `compose.yaml` declara `pdf-network` como `external: true`. Ambos
servicios pertenecen a esa red. Compose no la crea ni la elimina. Redis es
accesible por el nombre de servicio `redis`, sin publicar su puerto en Windows.
El extractor recibe `REDIS_URL=redis://redis:6379/0` y `CACHE_ENABLED=true`.

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
128 MiB, y comparte `pdf-network`. El socket Docker se monta en modo de lectura.

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
El perfil oficial de spike está preparado, pero requiere comprobar previamente
la estabilidad de las pruebas pequeñas. No ejecutarlo automáticamente.

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
