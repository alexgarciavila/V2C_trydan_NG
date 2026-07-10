# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

`AGENTS.md` es la fuente de verdad única del repo; este archivo la importa y añade
solo reglas exclusivas de Claude Code.

---

## 1. Importacion de AGENTS.md

@AGENTS.md

---

## 2. Instrucciones especificas de Claude Code

Reglas obligatorias de commits y PRs:

- No añadir ninguna atribución o co-autoría de IA en mensajes de commit ni en
  el cuerpo de PRs (ej. no incluir líneas como
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>` o equivalentes).
- Los commits y PRs se firman únicamente como el usuario/equipo del repo.
- El texto de commits y PRs (título y cuerpo) siempre en castellano o catalán,
  según el idioma predominante usado en el repo. No usar inglés salvo que el
  repo ya esté íntegramente en inglés.

Subagentes:

- Los subagentes de Claude Code están en `.claude/agents/` y son stubs que apuntan
  a su definición operativa completa en `agents/<nombre>.md`: cada subagente debe
  leer su archivo de `agents/` al activarse.
- `orchestrator-agent` es el punto de entrada obligatorio para toda solicitud de
  trabajo (ver sección 3 de `AGENTS.md`); no ejecutar en directo tareas que tengan
  agente especializado.
- Los subdirectorios `agents/abogado-animal/` y `agents/academic/` pertenecen al
  kit multiproyecto y no aplican a este repo.

Skills:

- Las skills del repo viven en `skills/` (raíz), no en `.claude/skills/`; el
  catálogo relevante y las reglas de autoinvocación están en la sección 13 de
  `AGENTS.md`.

---

## Notas finales

Este archivo es solo un puente hacia `AGENTS.md`. Si hay conflicto de contenido,
`AGENTS.md` prevalece salvo que aquí se indique explícitamente lo contrario para
una regla exclusiva de Claude Code.
