# AGENTS.md

Fuente de verdad operativa para agentes de IA en este repositorio.

---

## 1. Contexto del proyecto

- Nombre: `V2C Trydan NG`
- Tipo: `integración custom de Home Assistant (custom component, distribuida vía HACS)`
- Estado: `activo; continuación (fork) del proyecto original archivado por su autor (Rain1971/V2C_trydant) tras un fallo de hardware (el mantenedor anterior se quedó sin máquina de pruebas). Este repo (V2C Trydan NG) es mantenido activamente por Àlex Garcia Vilà (@alexgarciavila), quien sí dispone de una máquina V2C Trydan real para pruebas`
- Dominio funcional: `carga de vehículo eléctrico (cargador V2C Trydan) y control de carga por precio de la luz (PVPC)`
- Plataforma objetivo: `Home Assistant (instancia del usuario), comunicación HTTP local con el dispositivo`
- Idioma del proyecto/producto: `español (entidades y estados en español; README en inglés y español; traducciones en 7 idiomas)`

Objetivo breve:

Exponer en Home Assistant los datos y funciones del cargador V2C Trydan vía su
interfaz HTTP local (sensores, switches, numbers, select), incluyendo control de
carga basado en el precio PVPC de la electricidad y carga inteligente.

Fuera de alcance por defecto:

- Soporte de otros cargadores o modelos distintos de V2C Trydan.
- Comunicación cloud con V2C (la integración es exclusivamente local, `iot_class: local_polling`).
- Cambios en el firmware del dispositivo.

---

## 2. Jerarquia de instrucciones

En caso de conflicto, aplicar este orden (mayor a menor prioridad):

1. Instrucciones del sistema/plataforma del agente.
2. Este `AGENTS.md`.
3. Instrucciones del entorno de ejecución (developer).
4. Reglas de skills individuales.
5. Solicitud explícita del usuario para la tarea actual.

Si dos reglas del mismo nivel conflictúan, aplicar la más restrictiva.

---

## 3. Orquestacion obligatoria

`orchestrator-agent` es la puerta de entrada obligatoria del flujo: toda solicitud pasa primero por él, y el primary agent nunca ejecuta en directo una tarea que tenga agente especializado asignado.

Reglas de delegación:

- Delegar siempre en el agente especializado correspondiente; la ejecución directa solo está permitida cuando no existe agente para esa tarea.
- `orchestrator-agent` no bloquea el inicio de la delegación pidiendo validación global; solo exige validación explícita en hitos críticos (ej. spec aprobada).
- Si la delegación falla, reportar el bloqueo y reintentar con más contexto; nunca ejecutar la tarea especializada como fallback.
- Cada agente especializado rechaza explícitamente solicitudes fuera de su rol, deriva al agente correcto y bloquea esa parte de la ejecución.
- Si una solicitud mezcla tareas de varios dominios, cada agente ejecuta solo su tramo y lista las derivaciones pendientes.

### 3.1 Especificacion persistente por feature

- Toda especificación aprobada se persiste en `specs/<feature-slug>/` (`feature-slug` en kebab-case).
- Artefactos mínimos: `spec.md`, `user-stories.md`, `tasks.md`. Opcionales: `decisions.md`, `ux-ui.md`.
- Artefactos de coordinación (propiedad exclusiva de `orchestrator-agent`): `state.md` (foto del estado actual del flujo) y `journal.md` (historial append-only: una entrada por handover con agente, fecha, resumen, veredicto y decisiones del usuario con cita textual).
- Bloqueo: no se implementa código productivo sin `Validacion del usuario: Aprobada`.
- Excepción: las solicitudes clasificadas como `trivial` por el triaje de `orchestrator-agent` (cambio mínimo sin efecto en comportamiento ni API) no requieren spec ni validación previa; van directas al agente especializado y a `git-agent`. En caso de duda sobre el tamaño, aplica el bloqueo.
- Si cambian requisitos durante la ejecución, se vuelve a `spec-agent` y se versiona el alcance.
- Flujo mínimo: `orchestrator-agent` -> `spec-agent` -> validación explícita del usuario -> `git-agent` -> `ux-ui-agent` (si aplica) -> `architect-agent` (si aplica) -> `dev-agent`. Sin validación explícita, el flujo se detiene en especificación.
- El triaje de tamaño (`trivial`/`acotada`/`feature completa`) y sus rutas cortas se definen en `agents/orchestrator-agent.md`; el bloqueo de spec aplica siempre a la ruta `feature completa` y, cuando haya ambigüedad de alcance, también a la `acotada`.

Mapa de delegación:

| Dominio | Agente | Capacidad recomendada |
|---|---|---|
| Entrada y coordinación | `orchestrator-agent` | media |
| Inicialización | `init-agent` | baja |
| Especificaciones | `spec-agent` | alta |
| UX/UI (*) | `ux-ui-agent` | media |
| Arquitectura (*) | `architect-agent` | alta |
| Implementación | `dev-agent` | alta |
| Bugfix | `bugfix-agent` | alta |
| Refactor | `refactor-agent` | alta |
| Seguridad (*) | `security-agent` | alta |
| Testing automatizado | `test-agent` | media |
| QA funcional | `qa-agent` | media |
| Revisión final | `reviewer-agent` | alta |
| Documentación | `doc-agent` | media |
| Git/PR/commit/branch/merge | `git-agent` | baja |

(*) Agentes condicionales: participan solo cuando se cumple su criterio de activación (definido en la sección 2 de su archivo en `agents/`). El resto participa siempre en su tramo de la ruta. Excepción: `security-agent` se incluye siempre que su criterio se cumpla, aunque la ruta de triaje sea corta.

Sobre la columna "Capacidad recomendada":

- Expresa el nivel de razonamiento que el rol necesita (`alta` = decisiones con consecuencias y análisis profundo; `media` = ejecución con criterio; `baja` = trabajo procedimental con gates), NO un modelo concreto.
- El mapeo a modelos/proveedores concretos se hace en la capa específica de la herramienta (frontmatter `model:`/`effort:` en `.claude/agents/*.md`), nunca en estos documentos agnósticos.

Nota: en este repo `ux-ui-agent` rara vez aplica (no hay frontend propio; la UI son
las tarjetas Lovelace de ejemplo en `lovelance/` y los formularios del config flow).

---

## 4. Reglas globales

- No inventar herramientas, comandos o flujos no definidos.
- Respetar convenciones del proyecto y decisiones de arquitectura (patrón coordinator de Home Assistant, entidades por plataforma).
- Priorizar legibilidad, mantenibilidad y seguridad.
- No introducir nuevas dependencias sin confirmación; las dependencias Python se declaran en `custom_components/v2c_trydan/manifest.json` (`requirements`), no en requirements.txt/pyproject.
- No modificar documentación salvo petición del usuario o necesidad contractual explícita.
- Aplicar KISS, SRP y guard clauses cuando mejore claridad.
- Mantener compatibilidad con las APIs actuales de Home Assistant (evitar APIs deprecadas de `homeassistant.*`).
- Cualquier cambio en nombres de entidades, servicios o eventos es un cambio de contrato de cara al usuario final: documentarlo en el README y evitar romper automatizaciones existentes.
- Reutilizar skills disponibles cuando encaje.

---

## 5. Seguridad operativa (confirmacion obligatoria)

Pedir confirmación explícita antes de ejecutar acciones:

- Destructivas o irreversibles (borrado de archivos/ramas, `git push --force`, reescritura de historial).
- Publicación de releases o cambios de versión en `manifest.json` destinados a distribución HACS.
- Cambios en workflows de CI (`.github/workflows/`).
- Cambios que rompan entidades, servicios o eventos existentes usados en automatizaciones de usuarios.

Reglas obligatorias:

- Nunca exponer secretos ni datos personales (IPs reales de dispositivos, tokens) en código, tests, logs ni commits.
- La única configuración sensible es la IP del dispositivo: se gestiona vía config entry de Home Assistant, nunca hardcodeada.
- No añadir llamadas a servicios externos nuevos; las únicas comunicaciones permitidas son el dispositivo local (`http://<ip>/...`) y las ya integradas vía sensor PVPC de Home Assistant.

---

## 6. Stack tecnologico oficial

### 6.1 Base del proyecto

- Lenguaje: `Python (asyncio)` — el que soporte la versión de Home Assistant objetivo (Python 3.11+).
- Framework: `Home Assistant custom component` (config flow, DataUpdateCoordinator, plataformas sensor/switch/number/select).
- Dependencias runtime: `aiohttp>=3.8.0`, `tenacity>=8.0.0` (declaradas en `manifest.json`).
- Distribución: `HACS` (categoría integration, `hacs.json`).
- Base de datos: no aplica (el estado vive en Home Assistant).
- Frontend: no aplica (solo ejemplos Lovelace YAML en `lovelance/`).

Regla:

- No usar alternativas a este stack ni añadir dependencias a `manifest.json` sin confirmación explícita.

### 6.2 Calidad y testing

- Validación oficial: GitHub Actions `hassfest` (validación de integración HA) y `HACS action` (validación HACS). Ver sección 11.1.
- Lint/format local: no hay tooling configurado en el repo.
- Tests: no existe suite de tests actualmente.
- Si se introduce tooling de tests/lint (ej. `pytest` + `pytest-homeassistant-custom-component`, `ruff`), debe proponerse al usuario, configurarse en el repo y actualizarse la sección 10.

---

## 7. Arquitectura y estructura

### 7.1 Arquitectura objetivo

- Estilo: `integración Home Assistant con patrón coordinator` — un `V2CtrydanDataUpdateCoordinator` (en `coordinator.py`) hace polling HTTP cada 5 segundos a `http://<ip>/RealTimeData` y todas las entidades leen de él (`CoordinatorEntity`).
- Escrituras al dispositivo: peticiones GET a `http://<ip>/write/<Parametro>=<valor>` (intensidades, pausa, lock, dynamic power mode), implementadas en `__init__.py` (servicios) y en las plataformas.
- Robustez: reintentos con `tenacity` (3 intentos, espera fija) y reparación de JSON malformado del firmware (`arreglar_json_invalido` en `coordinator.py` — el firmware devuelve campos duplicados y content-type incorrecto).
- Lógica PVPC/carga inteligente: vive en `sensor.py` (sensor `v2c_precio_luz`, cálculo de horas válidas de carga, switches `carga_pvpc` y `smart_charge`); consume el sensor PVPC oficial de HA configurado por el usuario.
- Evento propio: `v2c_trydan.charging_complete` cuando se alcanza el objetivo de km cargados.
- Estados de cara al usuario en español (ej. `Manguera no conectada`); mantener así por compatibilidad.

### 7.2 Estructura base esperada

- `custom_components/v2c_trydan/` -> código de la integración: `__init__.py` (setup, registro de servicios, escrituras HTTP), `coordinator.py` (polling y parsing), `config_flow.py`, `const.py`, plataformas (`sensor.py`, `switch.py`, `number.py`, `select.py`), `services.yaml`, `manifest.json`, `translations/` (ca, en, es, eu, fr, it, pt).
- `lovelance/` -> ejemplos YAML de tarjetas Lovelace referenciados desde el README (nota: el nombre de la carpeta lleva esa grafía; no renombrar sin actualizar el README).
- `images/` -> capturas usadas por el README.
- `agents/`, `skills/`, `.claude/` -> marco operativo de agentes (no es código de producto).
- `specs/` -> especificaciones por feature (se crea al usar el flujo).

Regla:

- Si la estructura real difiere, seguir convenciones existentes del repositorio.

---

## 8. Contrato API

- La API HTTP local del firmware V2C Trydan es la fuente de verdad externa: `GET /RealTimeData` (lectura) y `GET /write/<Parametro>=<valor>` (escritura). No es modificable desde este repo; el código debe tolerar sus defectos conocidos (JSON malformado, content-type incorrecto).
- El contrato de cara al usuario final son los IDs de entidades, servicios (`services.yaml`) y el evento `v2c_trydan.charging_complete` documentados en el README: cualquier cambio debe reflejarse en `README.md`/`README.es.md` y evitar breaking changes sin plan de migración.
- Rangos validados: intensidades 6–32 A; `DynamicPowerMode` 0–7.

---

## 9. Observabilidad

- Logging vía `logging.getLogger(__name__)` (`_LOGGER`), siguiendo las convenciones de Home Assistant: `debug` para tráfico/detalles, `info` para recuperación de conexión, `error` solo para fallos accionables.
- El coordinator limita el ruido de log: reporta error persistente solo tras 5 fallos consecutivos y anuncia la recuperación; mantener este patrón al tocar la gestión de errores.
- No registrar datos sensibles; la IP del dispositivo local es aceptable en logs de debug.
- No introducir proveedores externos de observabilidad.

---

## 10. Comandos oficiales (fuente de verdad)

Si un comando no aparece aquí ni en una skill activa, pedir confirmación.

### 10.1 Setup inicial

```bash
git clone <repo>   # sin dependencias locales que instalar; el código corre dentro de Home Assistant
```

### 10.2 Desarrollo / prueba manual

Para probar en real: copiar `custom_components/v2c_trydan/` al directorio
`config/custom_components/` de una instancia de Home Assistant y reiniciarla
(o instalar el repo vía HACS como repositorio custom). No hay entorno de
ejecución local en este repo.

### 10.3 Validación local mínima

```bash
python -m py_compile custom_components/v2c_trydan/*.py   # comprobación de sintaxis
python -m json.tool custom_components/v2c_trydan/manifest.json   # manifest válido
```

### 10.4 Tests

No existe suite de tests. Si `test-agent` añade una, se configurará el tooling y
se actualizará esta sección; hasta entonces, no inventar comandos de test.

### 10.5 Calidad / CI

La validación de calidad oficial corre en GitHub Actions (no ejecutable en local
sin tooling adicional):

- `hassfest` (`.github/workflows/hassfest.yaml`): validación de integración de Home Assistant.
- `HACS action` (`.github/workflows/validate.yml`): validación de requisitos HACS.

---

## 11. Workflow de git y pull requests

- Estrategia: trunk-based sobre `main`.
- Nombre de rama: `<tipo>/<slug-descriptivo>` (ej. `fix/json-firmware-160`, `feature/sensor-bateria`).
- Commits: mensajes descriptivos en castellano o catalán, en imperativo, acotados a un cambio lógico.
- Todo commit debe proponerse primero al usuario y solo ejecutarse tras validación explícita.
- Antes de PR ejecutar como mínimo: la validación local de la sección 10.3 y revisión del diff contra el alcance acordado.

Checklist mínimo PR:

- Cambios acotados al objetivo.
- Validación local en verde y CI (hassfest + HACS) en verde.
- Riesgos y supuestos documentados.
- Si cambian entidades/servicios/eventos, README actualizado y compatibilidad considerada.
- Si cambian dependencias, `manifest.json` actualizado.

### 11.1 CI/CD

- Pipeline: GitHub Actions.
- Checks obligatorios antes de mergear: `Validate with hassfest` y `Validate` (HACS), que corren en cada push y PR (y diariamente por cron).
- El pipeline solo valida; no hay despliegue automático. La "release" es un tag/release de GitHub que HACS consume, siempre con confirmación del usuario.
- No modificar workflows de CI sin confirmación explícita (ver sección 5).

---

## 12. Definition of Done (DoD)

Una tarea se considera terminada solo si:

- El código compila (`py_compile` limpio) y la integración carga en Home Assistant sin errores.
- La validación de CI (hassfest + HACS) pasa o no se ve afectada.
- Si cambia lógica y existe suite de tests, hay tests nuevos o actualizados.
- Si cambian entidades, servicios, eventos o configuración, el README (en y es) está alineado.
- Si cambian dependencias, `manifest.json` las refleja.
- Se reportan riesgos, límites y supuestos en la respuesta final (en particular: si un cambio concreto no se ha llegado a probar contra el dispositivo real, decirlo explícitamente; ver sección 14).

---

## 13. Catalogo de skills

Las skills viven en `skills/` (raíz del repo). Es un catálogo genérico multiproyecto;
para este repo son relevantes sobre todo las de Python.

### 13.1 Skills core

- Skill: `async-python-patterns`
  - Ruta: `skills/async-python-patterns/SKILL.md`
  - Usar cuando: se toque código asyncio/aiohttp (coordinator, escrituras HTTP, listeners).

- Skill: `python-code-style`
  - Ruta: `skills/python-code-style/SKILL.md`
  - Usar cuando: se escriba o refactorice cualquier código Python del componente.

- Skill: `python-error-handling`
  - Ruta: `skills/python-error-handling/SKILL.md`
  - Usar cuando: se modifique gestión de errores/reintentos (coordinator, tenacity, UpdateFailed).

### 13.2 Skills por dominio

- Robustez y resiliencia:
  - Skill: `python-resilience` -> `skills/python-resilience/SKILL.md`
  - Skill: `python-anti-patterns` -> `skills/python-anti-patterns/SKILL.md`
- Testing (si se introduce suite):
  - Skill: `python-testing-patterns` -> `skills/python-testing-patterns/SKILL.md`
- Tipado:
  - Skill: `python-type-safety` -> `skills/python-type-safety/SKILL.md`

Las demás skills del catálogo (django, vercel, supabase, docker, etc.) no aplican
a este proyecto; ignorarlas salvo petición explícita.

### 13.3 Reglas de autoinvocacion

- Cambios en `coordinator.py` o llamadas HTTP -> activar `async-python-patterns` + `python-error-handling` + `python-resilience`.
- Cualquier cambio de código Python -> activar `python-code-style`.
- Creación de tests -> activar `python-testing-patterns`.

---

## 14. Limitaciones y advertencias

- El mantenedor actual (Àlex Garcia Vilà) sí dispone de un dispositivo V2C Trydan real para pruebas (el upstream original se archivó porque su autor anterior se quedó sin máquina de pruebas tras un fallo de hardware, no por falta de acceso en este repo). Aun así, los cambios no se consideran validados end-to-end contra el cargador real hasta que se pruebe explícitamente en la instancia del usuario; QA y revisiones deben declarar si un cambio concreto se ha probado o no contra el hardware real.
- La lógica de reparación de JSON (`arreglar_json_invalido`) contiene apaños específicos de versiones de firmware (ej. `"1.6.13"`); tocarla con extremo cuidado y sin eliminar compatibilidad.
- `sensor.py` concentra mucha lógica (precio PVPC, carga inteligente, eventos); evitar cambios masivos sin plan incremental.
- No asumir credenciales ni acceso externo; la integración es 100% local.
- Si falta contexto crítico (ej. comportamiento real del firmware), pedir solo el dato bloqueante.

---

## 15. Estilo de respuesta

- Idioma de respuesta del agente: castellano (o catalán si el usuario lo usa).
- Formato: resultado principal primero, luego detalles accionables.
- Tono: claro, directo y colaborativo.
- Proponer siguientes pasos solo cuando aporten valor.

---

## 16. Notas finales

Este archivo es la fuente de verdad operativa para agentes en este repo.
Si hay conflicto con una skill, prevalece `AGENTS.md`.

Fecha de última actualización: `2026-07-09`
Responsable: `Àlex Garcia Vilà (Infordisa)`
