# Despliegue del JinxxyCog (Fase 9 — sync de la tienda)

Guía de despliegue **manual** en el host de producción **cinema** para el cog de
auto-sync de la tienda Jinxxy (`cogs/jinxxy.py`). El código ya está en el repo; este
documento cubre el paso humano: variables de entorno, `git pull` + reinicio del
servicio, y la **rotación obligatoria de la API key**.

> El bot en vivo corre en el host Linux **cinema** vía `systemd`. La carpeta
> "Discord Bot" en Windows **no** es el bot en vivo.

---

## 1. Variables de entorno (`.env` en cinema)

Añade las siguientes claves al `.env` del repo `nocturna-bot` en cinema (ver la
sección "Jinxxy (Fase 9)" de `.env.example` para el formato exacto):

| Variable | Requerida | Valor / notas |
|----------|-----------|---------------|
| `JINXXY_API_KEY` | **Sí** | Clave **fine-grained** de la Creator API de Jinxxy con el scope **`products_read`**. Créala en `https://dashboard.jinxxy.com/api-keys`. El bot **fail-fasts** (`sys.exit(1)`) si falta. **Solo va en el `.env` de cinema — nunca se commitea.** |
| `JINXXY_ANNOUNCE_CHANNEL_ID` | Sí (default D-18) | `1525202600738295818` — canal donde el cog anuncia altas/cambios/bajas de la tienda. |
| `JINXXY_POLL_HOURS` | Opcional | Cadencia del poll en horas; banda recomendada **6–12** (D-03). Default `6`. |
| `JINXXY_STAFF_ROLE_IDS` | Opcional | IDs de rol separados por comas que pueden usar `/tienda sync` y `/tienda medios`. Vacío → **cae a `GALLERY_STAFF_ROLE_IDS`**. |
| `WEBSITE_STORE_JSON` | Sí (default en `.env.example`) | `src/data/store.json` — ruta del JSON de la tienda en el repo del sitio. |
| `WEBSITE_STORE_IMAGE_DIR` | Sí (default en `.env.example`) | `public/store` — directorio de imágenes de la tienda; servido como `/store/<archivo>`. |

### Reutilizadas de la Fase 5 (ya en vivo — **no** re-commitear ni recrear)

`GITHUB_PAT`, `WEBSITE_REPO` y `WEBSITE_BRANCH` **ya están vivos** en el `.env` de
cinema desde el despliegue de la galería (Fase 5). El JinxxyCog los **reutiliza sin
cambios** (mismo repo destino, mismo transporte cross-repo). No los toques, no los
vuelvas a pegar en ningún archivo versionado.

---

## 2. Pasos de despliegue (host cinema)

Mismo procedimiento que la Fase 5 (precedente confirmado en STATE.md):

```bash
# 1. En el repo nocturna-bot de cinema:
git pull

# 2. Reinicia la unidad systemd del bot:
sudo systemctl restart <unidad-del-bot>   # p. ej. nocturna-bot.service

# 3. Verifica que arrancó (si falta JINXXY_API_KEY, el proceso hace sys.exit(1)):
systemctl status <unidad-del-bot>
journalctl -u <unidad-del-bot> -n 50 --no-pager
```

Tras el reinicio, el `on_ready` corre **una** reconciliación de arranque y el poll
programado toma la cadencia `JINXXY_POLL_HOURS`.

---

## 3. ⚠️ SEGURIDAD — rotación de la API key (API key rotation, obligatoria)

> La Creator API key **pegada durante la planificación de esta fase DEBE rotarse**
> una vez que la fase se despliega. **Trata la clave pegada como comprometida.**

- Genera una **clave nueva** en `https://dashboard.jinxxy.com/api-keys` (scope
  `products_read`), ponla en el `.env` de cinema y **revoca la anterior**.
- La `JINXXY_API_KEY` vive **ÚNICAMENTE** en el `.env` de cinema — **jamás** en el
  repo, en `.env.example`, ni en logs. El cliente la envía solo en la cabecera de
  autenticación (T-09-21).
- Mismo régimen de mínimo privilegio + expiración/rotación que el `GITHUB_PAT`
  fine-grained de la Fase 5 (T-05-13).

---

## 4. Primer arranque y flujo de medios

- El **primer sync importa toda la storefront** de Jinxxy a `store.json` (D-13),
  enlazando por `checkoutUrl` los productos que ya existan para no duplicar.
- La Creator API **no** expone imágenes ni descripción (D-14, probe en vivo): por
  cada producto nuevo, el staff corre **`/tienda medios`** para adjuntar hasta 4
  imágenes + una descripción bilingüe (es/en). El bot las optimiza a WebP, las
  commitea bajo `public/store` y escribe las rutas `/store/<archivo>` + la
  descripción en `store.json` (imágenes/descripción son **100% del staff** — el
  sync nunca las sobrescribe, D-15).
- Hasta que el staff las suministre, la tarjeta del producto muestra el
  **placeholder de marca** + una descripción vacía (fallbacks del sitio verificados)
  — nunca se rompe.

---

*Fase 9 — Jinxxy store auto-sync. Comandos: `/tienda sync` (fuerza sync),
`/tienda medios` (adjunta imágenes + descripción). Ambos staff-only.*
