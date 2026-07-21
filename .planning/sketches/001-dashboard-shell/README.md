---
sketch: 001
name: dashboard-shell
question: "¿Cómo se organiza y se siente el dashboard de admin completo (estilo MEE6, SaaS oscuro)?"
winner: "A"
tags: [layout, dashboard, navigation, admin-panel]
---

# Sketch 001: Dashboard Shell

## Design Question

¿Qué estructura y densidad debe tener el dashboard de admin v2 — sidebar por módulo estilo
MEE6, con las 7 secciones (Overview, Galería, Reseñas, Recordatorios, Tienda Jinxxy,
Reuniones, Ajustes) navegables y con acciones reales (CRUD de recordatorios, cola de
aprobación de galería, sync manual de Jinxxy)?

## How to View

open .planning/sketches/001-dashboard-shell/index.html

## Variants

- **A: MEE6 puro** — cada feature es un "módulo" con header propio, toggle grande on/off, cards espaciosas.
- **B: Consola densa** — estilo Dyno/Carl-bot: sidebar compacto con dots de estado, tablas densas, más datos por pantalla.
- **C: Overview-first** — home rica con estado del bot y acciones rápidas (aprobar galería, nuevo recordatorio, sync tienda); secciones iguales a A.

## What to Look For

- ¿La navegación por sidebar con acentos de color por sección se siente clara?
- ¿El toggle de módulo (estilo MEE6) aporta o estorba? (variante B no lo tiene)
- Recordatorios: prueba crear, editar, pausar y borrar — ¿el patrón tabla + modal funciona?
- Galería: aprueba/quita fotos de la cola — ¿se siente paridad con las reacciones de Discord?
- Ajustes: nombres legibles (#canal, @rol) con el ID debajo — ¿mejor que el ID pelado actual?
- ¿Densidad A/C (cómoda) o B (compacta)?
