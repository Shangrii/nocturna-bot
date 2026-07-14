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

**Valores confirmados** (los rellena la Tarea 2 de 10-03):

| Campo | Valor |
|-------|-------|
| Client ID | `TODO — pegar tras la Tarea 2` |
| Redirect URI registrada | `TODO — pegar tras la Tarea 2 (debe terminar en /auth/callback)` |
| Client Secret | **NO se escribe aquí** — vive solo en el `.env` de cinema (§4) |

---

## 2. Subdominio DNS → host cinema

La app es pública (los editores entran desde cualquier sitio), así que necesita un
subdominio resoluble apuntando a cinema.

- Subdominio propuesto: **`editors.nocturna-avatars.site`**.
- Crea un registro **A/AAAA** en el proveedor de DNS de `nocturna-avatars.site`
  apuntando a la IP del host **cinema**.

**Valores confirmados** (los rellena la Tarea 3 de 10-03):

| Campo | Valor |
|-------|-------|
| Subdominio elegido | `TODO — confirmar (default propuesto: editors.nocturna-avatars.site)` |
| Registro DNS creado / apunta a cinema | `TODO — Sí/No` |

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

**Valores confirmados** (los rellena la Tarea 3 de 10-03):

| Campo | Valor |
|-------|-------|
| Reverse proxy en uso | `TODO — Caddy / nginx+certbot / aún-no` |
| HTTPS automático confirmado | `TODO — Sí/No` |
| uvicorn ligado a 127.0.0.1 tras el proxy | `TODO — Sí/No` |

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

**Valor confirmado** (lo rellena la Tarea 3 de 10-03):

| Campo | Valor |
|-------|-------|
| Intent `members` habilitado | `TODO — Sí/No` |
| Mecanismo D-10 resultante | `TODO — on_member_update (si Sí) / barrido de polling (si No)` |

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

*Fase 10 — Editor Profile Pages. Admin app: FastAPI + uvicorn (unidad systemd hermana
en cinema), login Discord OAuth2 + comprobación server-side de rol con el bot token,
commit cross-repo de `editors.json` vía `core/github_publish.py`. La configuración de
la unidad systemd + el snippet del reverse proxy se cierran en 10-11.*
