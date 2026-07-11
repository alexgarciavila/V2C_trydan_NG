# Changelog

Todas las versiones de este proyecto y sus cambios notables se documentan en este archivo.

## [4.0.3] - 2026-07-11

Ronda de revisión y correcciones de robustez sobre el estado inicial del código tras
la reactivación del proyecto como V2C Trydan NG. Todos los cambios son correcciones
de comportamiento; no se ha modificado ningún nombre de entidad, servicio ni evento.

### Corregido

- **Servicio `set_dynamic_power_mode` roto por recursión.** La función de módulo que
  escribía `DynamicPowerMode` al dispositivo tenía el mismo nombre que el handler de
  servicio, provocando que se llamase a sí misma en vez de hacer la petición HTTP real.
  Renombrada a `async_write_dynamic_power_mode`.
- **Manejo de errores insuficiente en los servicios.** Los 7 handlers de servicio
  (`set_min_intensity`, `set_max_intensity`, `set_intensity`, `set_dynamic_power_mode`
  y sus variantes slider) solo capturaban `ValueError`; un parámetro ausente o
  inválido podía lanzar `KeyError`/`TypeError` sin controlar. Ahora se capturan y se
  registra un error legible.
- **Carga marcada como completa de forma espuria.** Si `number.v2c_km_to_charge`
  quedaba en `unknown`/`unavailable` (por ejemplo justo tras un reinicio), el ciclo de
  comprobación de carga completa lo interpretaba como "0 km restantes" y pausaba y
  bloqueaba el cargador, además de disparar `v2c_trydan.charging_complete`, de forma
  repetida cada 10 segundos.
- **`sensor.v2c_precio_luz` quedaba `unavailable` tras reiniciar Home Assistant.** La
  entidad no se creaba si el sensor PVPC de origen aún no había publicado su estado en
  el instante del arranque. Ahora se crea siempre que está configurada, y el ciclo de
  refresco periódico la actualiza en cuanto la entidad de origen está lista.
- **Pérdida de valores tras reiniciar Home Assistant.** `number.v2c_max_price`,
  `number.v2c_km_to_charge` y el switch `carga_pvpc` no conservaban su último valor
  o estado tras un reinicio, volviendo siempre a los valores por defecto. Ahora usan
  `RestoreEntity` para recordarlos.
- **Umbral de fallos consecutivos no respetado en el coordinator.** El log de error
  por problemas de conexión con el dispositivo salía en el primer fallo en vez de
  esperar a 5 fallos consecutivos como indica la convención del proyecto; además, el
  `except Exception` interno de cada intento individual de `tenacity` logueaba en
  `ERROR` en vez de `DEBUG`, generando ruido en cada reintento. Ambos puntos corregidos
  y validados contra hardware real (corte de red simulado con firewall).
- **Reparación de JSON del firmware duplicada y divergente.** `coordinator.py` y
  `select.py` tenían cada uno su propia lógica para reparar el JSON malformado que
  devuelve el firmware, y no aplicaban exactamente los mismos apaños. Se extrajo a un
  módulo compartido nuevo, `json_repair.py`, usado por ambos.
- **Fuga de listeners en cada recarga de la integración.** `ChargeKmSensor` registraba
  varios listeners (temporizador de 10s, cambio de estado del switch de pausa) sin
  cancelarlos al desmontar la entidad, acumulándose en cada `reload`. Ahora se cancelan
  automáticamente vía `async_on_remove`. Se eliminó además un listener global sobre
  `state_changed` que no tenía ninguna lógica real (código muerto).
- **Hora actual excluida del cálculo de horas válidas de PVPC.** El cálculo de
  `ValidHours` comparaba con `i > current_hour` en vez de `i >= current_hour`,
  dejando fuera la hora en curso aunque su precio cumpliera el máximo configurado.
  Se corrige además el uso de hora local naive de Python por la hora de Home
  Assistant (`dt_util.now()`), respetando la zona horaria configurada.
- **Excepciones no controladas si el sensor PVPC o `MaxPrice` estaban
  `unavailable`/`unknown`.** El ciclo de control de carga PVPC hacía `float()`
  directamente sobre esos estados sin capturar errores de parseo, abortando el ciclo
  completo (por ejemplo durante un mantenimiento nocturno del proveedor de datos
  PVPC). Ahora se omite el ciclo de forma controlada con log en `debug`.
- **Registro frágil del flujo de opciones en `config_flow.py`.** Se eliminó el
  decorador `@config_entries.HANDLERS.register(DOMAIN)` sobre `async_get_options_flow`,
  redundante con el registro que ya hace la clase vía `domain=DOMAIN`.

### Documentación

- Corregido el contexto sobre disponibilidad de hardware de pruebas en `AGENTS.md`:
  el proyecto original se archivó porque su mantenedor anterior se quedó sin máquina
  de pruebas, no porque este fork carezca de acceso a un dispositivo real. El
  mantenedor actual sí dispone de un V2C Trydan real, usado para validar todos los
  cambios de esta versión.

### Pendiente (no incluido en esta versión)

- Rango de `DynamicPowerMode` limitado a 0-5 en el selector en vez de 0-7 (cambio de
  contrato, se evaluará aparte).
- Varios hallazgos de severidad baja (código muerto menor, `services.yaml` sin
  selectores, `select.py` con polling propio fuera del patrón coordinator, entre
  otros) quedan registrados como backlog para una futura ronda.

## [4.0.2] y anteriores

Sin changelog detallado previo a esta versión. Ver historial de commits del
repositorio para el detalle de cambios anteriores a la reactivación del proyecto
como V2C Trydan NG.
