# Despliegue del Admin App de páginas de editor (Fase 10)

Guía de despliegue **manual** en el host de producción **cinema** para la nueva
app web autenticada que edita las páginas de perfil de editor (Discord OAuth2 +
FastAPI/uvicorn, repo `nocturna-bot`). Este documento es la **fuente de verdad de
infraestructura** para el plan de deploy final (10-11): recoge los prerequisitos
humanos (app OAuth2, DNS + reverse proxy/TLS, intent `members`) y los valores
confirmados.

> El bot en vivo corre en el host Linux **cinema** vía `systemd`. La carpeta
> "Discord Bot" en Windows **no** es el bot en vivo. La app admin es una **unidad
> systemd hermana** que comparte el mismo venv, `core/` y `.env` que el bot, pero
> corre en su propio proceso (uvicorn).

> **PLAT-02 intacto:** la app admin vive **fuera** del sitio público. El sitio sigue
> siendo 100% estático en GitHub Pages; la app admin solo *commitea* `editors.json`
> + imágenes al repo del sitio, igual que hace el bot hoy.

---

## 1. Aplicación Discord OAuth2 (login del admin app — D-07)

Acción **exclusiva del Developer Portal** — no hay CLI/API para registrar la
redirect URI. Reutiliza la **misma aplicación de bot existente** (mismo app/guild,
D-15) — no crees una app nueva.

Pasos:

1. Abre tu aplicación de bot en el **Discord Developer Portal**
   (`https://discord.com/developers/applications`).
2. **OAuth2 → General:** copia el **Client ID**; revela/**resetea** el **Client
   Secret** (el secret solo se pega en el `.env` de cinema — **nunca** en el repo).
3. **OAuth2 → Redirects:** añade **exactamente** la redirect URI de callback fija:

   ```
   ${EDITOR_APP_BASE_URL}/auth/callback
   ```

   Con el subdominio propuesto (§2) esto es:

   ```
   https://editors.nocturna-avatars.site/auth/callback
   ```

   **Ruta fija, sin redirect post-login arbitrario** (Pitfall 4 — evita open
   redirect / CSRF de callback). Authlib genera y verifica el `state`; la única
   redirect URI válida es la registrada aquí, coincidencia exacta.
4. Scope OAuth2 mínimo: **`identify`** (la comprobación de rol se hace server-side
   con el **bot token**, no con un scope de OAuth — D-07).

**Valores confirmados** (Tarea 2 de 10-03, confirmado por el usuario):

| Campo | Valor |
|-------|-------|
| Client ID | `1490114146895794246` |
| Redirect URI registrada | `https://editors.nocturna-avatars.site/auth/callback` — confirmada registrada en el Developer Portal (OAuth2 → Redirects) |
| Client Secret | **NO se escribe aquí** — se genera/rota y se coloca **únicamente** en el `.env` de cinema durante el deploy de 10-11 (§4/§6) |

---

## 2. Subdominio DNS → host cinema

La app es pública (los editores entran desde cualquier sitio), así que necesita un
subdominio resoluble apuntando a cinema.

- Subdominio propuesto: **`editors.nocturna-avatars.site`**.
- Crea un registro **A/AAAA** en el proveedor de DNS de `nocturna-avatars.site`
  apuntando a la IP del host **cinema**.

**Valores confirmados** (Tarea 3 de 10-03, confirmado por el usuario):

| Campo | Valor |
|-------|-------|
| Subdominio elegido | `editors.nocturna-avatars.site` |
| Registro DNS creado / apunta a cinema | Sí — confirmado por el usuario; el registro A/AAAA final se verifica en vivo durante el deploy de 10-11 |

---

## 3. Reverse proxy con HTTPS automático (Pitfall 8)

Sin TLS, la cookie de sesión y el código OAuth viajan en claro. El bot hoy solo
escucha en `127.0.0.1` (puertos de notificación); esta es la **primera superficie
web entrante** del proyecto.

- Front con **Caddy** (preferido — HTTPS automático, config casi nula) o
  **nginx + certbot** (aceptable si cinema ya lo corre).
- El proxy termina TLS en el subdominio de §2 y reenvía a **uvicorn ligado a
  `127.0.0.1`** (nunca `0.0.0.0`).
- Cookies `Secure` + `SameSite=Lax`; sesión con TTL corto (revalidación de rol en
  cada escritura, Pitfall 2).

**Valores confirmados** (Tarea 3 de 10-03, confirmado por el usuario):

| Campo | Valor |
|-------|-------|
| Reverse proxy en uso | **Caddy** (HTTPS automático) |
| HTTPS automático confirmado | Sí — Caddy gestiona el certificado automáticamente para el subdominio §2 |
| uvicorn ligado a 127.0.0.1 tras el proxy | Sí (a confirmar en el Caddyfile final durante 10-11) |

### 3.1 Rate limiting en `/login` + `/auth/callback` + escrituras (10-10, T-10-10-04)

RESEARCH.md señala `slowapi` o límites a nivel de proxy como las dos opciones
válidas (Don't-Hand-Roll). 10-10 elige **proxy-level (Caddy)** en vez de fijar
una nueva dependencia pip a mitad del plan — instalar un paquete nuevo requiere
su propio checkpoint de legitimidad (como el de 10-02) y Caddy ya cubre esto sin
código adicional. Pendiente de aplicar en el `Caddyfile` final de 10-11:

```caddyfile
editors.nocturna-avatars.site {
    @auth path /login /auth/callback
    rate_limit @auth {
        zone auth_zone {
            key {remote_host}
            events 10
            window 1m
        }
    }

    @writes method POST
    @writes_path path /editor/*
    rate_limit @writes {
        zone editor_writes_zone {
            key {remote_host}
            events 30
            window 1m
        }
    }

    reverse_proxy 127.0.0.1:8770
}
```

(Requiere el plugin `caddy-ratelimit` — `xcaddy build --with github.com/mholt/caddy-ratelimit`,
o el equivalente ya empaquetado si cinema usa una build de Caddy con módulos.)
Ajustar `events`/`window` según el tráfico real observado tras el despliegue.

---

## 4. Claves `.env` a rellenar en cinema

Añade estas claves al `.env` del repo `nocturna-bot` en cinema. Las claves nuevas
del admin app se introducen en **10-02** (`config.py` / `.env.example`); aquí solo
se documenta qué debe rellenarse en producción.

| Variable | Requerida | Valor / notas |
|----------|-----------|---------------|
| `DISCORD_OAUTH_CLIENT_ID` | **Sí** | Client ID de la app OAuth2 (§1). |
| `DISCORD_OAUTH_CLIENT_SECRET` | **Sí** | Client Secret de la app OAuth2 (§1). **Solo en el `.env` de cinema — nunca en el repo.** |
| `DISCORD_OAUTH_REDIRECT_URI` | **Sí** | Debe coincidir **exactamente** con la redirect URI registrada en el Portal: `${EDITOR_APP_BASE_URL}/auth/callback`. |
| `SESSION_SECRET` | **Sí** | **32+ bytes aleatorios** para firmar la cookie de sesión (itsdangerous, vía Starlette SessionMiddleware). Genera con `python -c "import secrets; print(secrets.token_urlsafe(32))"`. **Nunca committear.** |
| `EDITOR_APP_BASE_URL` | **Sí** | Origen público del admin app (sin barra final), p. ej. `https://editors.nocturna-avatars.site`. Base para construir la redirect URI y los enlaces absolutos. |

### Reutilizadas (ya en vivo — **no** re-commitear ni recrear)

`GITHUB_PAT`, `WEBSITE_REPO`, `WEBSITE_BRANCH` y `BOT_TOKEN` **ya están vivos** en el
`.env` de cinema (Fase 5 / bot). El admin app los **reutiliza sin cambios**:
`core/github_publish.py` para commitear `editors.json` + imágenes al mismo repo, y el
`BOT_TOKEN` para la comprobación server-side de rol de guild (D-07). No los toques.

---

## 5. Intent privilegiado `members` (impulsa el mecanismo D-10)

La detección de pérdida de rol en tiempo real (D-10 auto-unpublish) usa el evento
gateway `on_member_update`, que **requiere el intent privilegiado `members`**
habilitado en la app del bot (Developer Portal → Bot → Privileged Gateway Intents).

- **Si está habilitado:** D-10 usa `on_member_update` en tiempo real como mecanismo
  primario.
- **Si NO está habilitado:** D-10 cae a un **barrido de polling periódico** como
  mecanismo primario (10-09 lo entrega igualmente, así que el sitio no se bloquea).

**Valor confirmado** (Tarea 3 de 10-03, confirmado por el usuario):

| Campo | Valor |
|-------|-------|
| Intent `members` habilitado (members intent) | **Sí** |
| Mecanismo D-10 resultante | **`on_member_update`** en tiempo real como mecanismo primario, con el barrido de polling periódico (10-09) como respaldo/backstop — el diseño original del plan ya contempla ambos, y con el intent habilitado el camino en tiempo real queda activo desde el arranque |

---

## 6. ⚠️ SEGURIDAD — rotación de secretos (obligatoria)

> Cualquier secreto **pegado durante la planificación de esta fase DEBE rotarse**
> una vez que la fase se despliega. **Trata todo secreto pegado como comprometido.**

- **`DISCORD_OAUTH_CLIENT_SECRET`:** si se reveló/pegó durante la planificación,
  **resetéalo** en el Developer Portal tras el ship y pon el nuevo en el `.env` de
  cinema. Revoca el anterior.
- **`SESSION_SECRET`:** genera uno fresco (32+ bytes) para producción; nunca reutilices
  uno de ejemplo/planificación.
- Todos los secretos (`DISCORD_OAUTH_CLIENT_SECRET`, `SESSION_SECRET`, `GITHUB_PAT`,
  `BOT_TOKEN`) viven **ÚNICAMENTE** en el `.env` de cinema — **jamás** en el repo, en
  `.env.example`, ni en logs. Mismo régimen de mínimo privilegio + rotación que el
  `GITHUB_PAT` fine-grained (Fase 5, T-05-13) y la `JINXXY_API_KEY` (Fase 9).

---

## 7. Despliegue en cinema — pasos concretos (10-11)

Los artefactos de despliegue viven en `deploy/`:

- `deploy/nocturna-editor-admin.service` — unidad systemd hermana (uvicorn `app.main:app`, loopback `127.0.0.1:8770`, `EnvironmentFile` = el `.env` del bot).
- `deploy/Caddyfile.snippet` — bloque del subdominio con HTTPS automático que reenvía a `127.0.0.1:8770`.

> **Antes de empezar**, confirma el registro DNS: `dig +short editors.nocturna-avatars.site`
> debe devolver la IP pública de cinema (§2). Sin DNS, Caddy no puede emitir el certificado.

### 7.1 Traer el código y las dependencias (en el venv del bot)

```bash
# En el repo nocturna-bot de cinema (mismo checkout que corre el bot):
cd ~/nocturna-bot            # ajusta a la ruta real del checkout
git pull

# Instala las nuevas dependencias del admin app EN EL VENV COMPARTIDO del bot
# (fastapi, uvicorn[standard], authlib, python-multipart, jinja2, httpx — 10-02):
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

### 7.2 Rellenar las claves `.env` (ver §4)

Añade al `.env` de cinema (NUNCA al repo) las claves del admin app. Genera el
`SESSION_SECRET` fresco en el propio host:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Claves a rellenar (valores confirmados donde aplica; los secretos se pegan solo aquí):

```dotenv
DISCORD_OAUTH_CLIENT_ID=1490114146895794246
DISCORD_OAUTH_CLIENT_SECRET=<pega-el-client-secret-del-Developer-Portal>
DISCORD_OAUTH_REDIRECT_URI=https://editors.nocturna-avatars.site/auth/callback
SESSION_SECRET=<el-token_urlsafe(32)-generado-arriba>
EDITOR_APP_BASE_URL=https://editors.nocturna-avatars.site
```

`GITHUB_PAT`, `WEBSITE_REPO`, `WEBSITE_BRANCH` y `BOT_TOKEN` ya están vivos — no los toques (§4).

### 7.3 Instalar y arrancar la unidad systemd

```bash
# Copia la unidad y AJUSTA User= + las rutas (WorkingDirectory, venv, EnvironmentFile)
# igual que hiciste con nocturna-bot.service:
sudo cp deploy/nocturna-editor-admin.service /etc/systemd/system/
sudo nano /etc/systemd/system/nocturna-editor-admin.service   # ajusta User + las 3 rutas

sudo systemctl daemon-reload
sudo systemctl enable --now nocturna-editor-admin

# Verifica que arrancó (si falta una clave OAuth/SESSION_SECRET, validate_config
# hace fail-fast y el proceso NO arranca — el error nombra solo las claves que faltan):
systemctl status nocturna-editor-admin --no-pager
journalctl -u nocturna-editor-admin -n 50 --no-pager

# Sanity local (debe responder detrás del loopback, aún sin TLS):
curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8770/login   # espera 200
```

### 7.4 Configurar Caddy (HTTPS automático)

```bash
# Añade el bloque del subdominio al Caddyfile de cinema. Si Caddy hace `import`
# de un directorio de sitios, copia el snippet ahí; si no, pégalo en el Caddyfile:
sudo cp deploy/Caddyfile.snippet /etc/caddy/sites/editors.nocturna-avatars.site.caddy
# (o edita /etc/caddy/Caddyfile y pega el bloque)

sudo caddy validate --config /etc/caddy/Caddyfile     # valida sintaxis
sudo systemctl reload caddy                            # recarga sin downtime

# Caddy emite el certificado ACME al primer request HTTPS. Verifica:
curl -sS -o /dev/null -w "%{http_code}\n" https://editors.nocturna-avatars.site/login  # 200 por HTTPS
```

> **Nota rate-limit:** el snippet usa la directiva `rate_limit` (plugin
> `caddy-ratelimit`, §3.1). Si tu build de Caddy no lo trae, `caddy validate`
> fallará — elimina los dos bloques `rate_limit @...` del snippet (la app sigue
> corriendo; solo pierdes el throttling a nivel de proxy) o reconstruye Caddy con
> `xcaddy build --with github.com/mholt/caddy-ratelimit`.

### 7.5 Reiniciar el bot (cargar `cogs.editors` + intent `members`)

El auto-unpublish por pérdida de rol (D-10) vive en el **proceso del bot**, no en el
admin app. Reinícialo para que cargue `cogs.editors` y reconecte con el intent
`members` habilitado (§5):

```bash
sudo systemctl restart nocturna-bot       # ajusta al nombre real de la unidad del bot
journalctl -u nocturna-bot -n 50 --no-pager   # confirma que cargó cogs.editors sin error
```

### 7.6 Después del ship → **rota los secretos** (§6, obligatorio)

Cierra el deploy ejecutando la rotación de la §6: resetea el Client Secret en el
Developer Portal y confirma que `SESSION_SECRET` es un valor fresco de 32+ bytes que
no aparece en ningún artefacto de planificación. Trata cualquier secreto pegado
durante la planificación como comprometido.

---

## 8. Contador de vistas self-hosted (Fase 10.1, 10.1-12, D-25)

`ViewCounter.astro` (páginas de editor rediseñadas) hace **ping** al descartar el splash a
un contador **propio** en cinema — sin terceros (D-25). Es una app **FastAPI diminuta y
separada** (`app/counter_app.py`), otra **unidad systemd hermana** que comparte el mismo
venv/`core/`/`.env` que el bot y el admin app, pero corre en su **propio proceso** (un crash
aquí no tumba ni el bot ni el admin app).

### Contrato del endpoint

| Método | Ruta | Respuesta |
|--------|------|-----------|
| `GET` | `/api/views/<slug>?hit=1` | `200 {"count": <int>}` — **incrementa** y devuelve |
| `GET` | `/api/views/<slug>` | `200 {"count": <int>}` — **solo lectura**, no incrementa |

- **Puerto (loopback):** `127.0.0.1:8771` (Caddy front, HTTPS en `editors.nocturna-avatars.site`).
- **Slug** validado `[a-z0-9-]+` (si no, `404`); un slug **desconocido** bien formado devuelve
  `{"count": 0}` (nunca 500). El cliente siempre recibe un entero limpio, y `ViewCounter.astro`
  **oculta** el contador si el endpoint es inalcanzable (degradación elegante, UI-SPEC).
- **CORS:** el llamante es el **sitio público** (`WEBSITE_BASE_URL`, un origen DISTINTO de
  `editors.nocturna-avatars.site`) — se permite ese origen (+ su variante www/no-www) solo GET.
- **Anti-inflado:** `rate_limit` por IP a nivel de Caddy (T-10.1-12-01) **más** una ventana de
  dedup por `slug`+`ip_hash` en la DB (un reload no infla el contador). Se guarda **solo un
  HASH** de la IP, nunca la IP cruda (T-10.1-12-02).
- **Sin secretos:** endpoint público de lectura/incremento, sin auth. El `.env` solo aporta
  `WEBSITE_BASE_URL` (el origen CORS) y `DB_PATH` (el sqlite compartido).

> **Nota Lanyard (D-05/A4):** si la instancia pública de Lanyard llega a rate-limitar el fetch
> de presencia en vivo, un self-host de Lanyard podría vivir junto a este contador en cinema
> (mismo patrón de unidad systemd hermana + bloque Caddy). Fuera de alcance de este plan.

### 8.1 Instalar y arrancar la unidad systemd del contador

```bash
# En el repo nocturna-bot de cinema (mismo checkout que corre el bot + admin app):
cd ~/nocturna-bot            # ajusta a la ruta real del checkout
git pull

# Copia la unidad y AJUSTA User= + las rutas (WorkingDirectory, venv, EnvironmentFile,
# ReadWritePaths) igual que hiciste con nocturna-editor-admin.service:
sudo cp deploy/nocturna-view-counter.service /etc/systemd/system/
sudo nano /etc/systemd/system/nocturna-view-counter.service   # ajusta User + las rutas

sudo systemctl daemon-reload
sudo systemctl enable --now nocturna-view-counter

# Verifica que arrancó y que la DB es escribible (ReadWritePaths cubre el checkout):
systemctl status nocturna-view-counter --no-pager
journalctl -u nocturna-view-counter -n 50 --no-pager

# Sanity local (loopback, aún sin TLS) — incrementa y luego lee:
curl -sS "http://127.0.0.1:8771/api/views/aria?hit=1"   # -> {"count":1}
curl -sS "http://127.0.0.1:8771/api/views/aria"         # -> {"count":1} (solo lectura)
```

### 8.2 Añadir la ruta `/api/views/*` a Caddy

El bloque de `editors.nocturna-avatars.site` en `deploy/Caddyfile.snippet` ya incluye un
`handle /api/views/*` que hace `reverse_proxy 127.0.0.1:8771` con un `rate_limit` por IP, y el
resto del tráfico cae al admin app (`handle { reverse_proxy 127.0.0.1:8770 }`). Si ya pegaste
una versión anterior del snippet (solo admin app), re-cópialo o añade a mano el `handle
/api/views/*` + su `rate_limit @views`:

```bash
sudo cp deploy/Caddyfile.snippet /etc/caddy/sites/editors.nocturna-avatars.site.caddy
sudo caddy validate --config /etc/caddy/Caddyfile     # valida sintaxis (incl. rate_limit)
sudo systemctl reload caddy                            # recarga sin downtime

# Verifica el contador por HTTPS a través de Caddy:
curl -sS "https://editors.nocturna-avatars.site/api/views/aria?hit=1"   # -> {"count":N}
```

> **Nota rate-limit:** el `rate_limit @views` usa el mismo plugin `caddy-ratelimit` que los
> bloques del admin app (§3.1). Si tu build de Caddy no lo trae, elimina el bloque
> `rate_limit @views {...}` (el `handle /api/views/*` sigue funcionando; solo pierdes el
> throttling a nivel de proxy) o reconstruye Caddy con el plugin.

> Igual que el resto de esta fase, la **verificación end-to-end en vivo** (splash → ping →
> incremento → render del contador en la página pública) es un paso **humano**; estos son
> artefactos de despliegue.

---

*Fase 10 — Editor Profile Pages. Admin app: FastAPI + uvicorn (unidad systemd hermana
en cinema), login Discord OAuth2 + comprobación server-side de rol con el bot token,
commit cross-repo de `editors.json` vía `core/github_publish.py`. Artefactos de
despliegue: `deploy/nocturna-editor-admin.service` + `deploy/Caddyfile.snippet`; pasos
concretos de instalación/arranque/recarga en §7. La verificación end-to-end en vivo
(login → editar → publicar → render público → auto-unpublish) es humana (10-11 Tarea 2).*
