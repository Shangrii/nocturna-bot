# Sketch Manifest

## Design Direction

Dashboard de administración profesional para Nocturna Bot, estilo "bot famoso de Discord"
(referencia principal: MEE6). Estética SaaS neutro oscuro: fondo gris-azulado profundo,
tipografía sans limpia (Inter), acentos de color por sección; la marca Nocturna (rojo
graffiti) queda reservada al logo. Sidebar por módulo con las 7 secciones (Overview,
Galería, Reseñas, Recordatorios, Tienda Jinxxy, Reuniones, Ajustes). Debe cubrir no solo
settings sino gestión real: CRUD de recordatorios, cola de aprobación de galería/reseñas,
sync manual de tienda — paridad con lo que hoy se hace por comandos/reacciones en Discord.
Target de implementación: FastAPI + Jinja + Alpine.js (server-rendered, sin build step).

## Reference Points

- MEE6 (sidebar por plugin, toggles de módulo, páginas espaciosas)
- Dyno / Carl-bot (densidad utilitaria, como contrapunto en variante B)

## Sketches

| # | Name | Design Question | Winner | Tags |
|---|------|----------------|--------|------|
| 001 | dashboard-shell | ¿Cómo se organiza y se siente el dashboard completo? | A: MEE6 puro | layout, dashboard, navigation, admin-panel |
