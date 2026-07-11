# Changelog

*[Versión en español](CHANGELOG.es.md)*

All notable changes to this project are documented in this file.

## [4.0.4] - 2026-07-11

Low-severity fixes from the initial code audit. All changes are internal
robustness/cleanup fixes; no entity, service, or event name has changed.

### Fixed

- Removed unreachable dead code in `NumericalStatus.native_value` and three
  no-op attribute assignments in `PrecioLuzEntity` (the `extra_state_attributes`
  property already rebuilds the exposed dict from its own tracked values on
  every access, so those writes were discarded immediately).
- Added a `coordinator.data is None` guard in `ChargeKmSensor.native_value` to
  avoid a transient `AttributeError` right after startup, before the first
  coordinator refresh completes.
- `config_flow.py` now uses `async_get_clientsession(hass)` instead of
  creating and closing its own `ClientSession` on every connection attempt.
- `coordinator.py` now treats any HTTP response other than 200 as an explicit
  error (a non-200 2xx/3xx response used to silently return `None`).
- `DynamicPowerModeSelect` (`select.py`) is migrated to `CoordinatorEntity`,
  removing its own periodic HTTP polling of `/RealTimeData` (which duplicated
  the request the coordinator already makes every 5s); writing the mode is
  unchanged.
- `services.yaml` now documents all 7 registered services (name, description,
  fields, selectors), previously blank and offering no UI selectors under
  Developer Tools → Actions.

### Not included in this release

- `DynamicPowerMode` range limited to 0-5 in the selector instead of 0-7
  (contract change, tracked separately, still not addressed).

## [4.0.3] - 2026-07-11

Review and robustness fixes over the initial state of the code after the
project was resumed as V2C Trydan NG. All changes are behavior fixes; no
entity, service, or event name has changed.

### Fixed

- **`set_dynamic_power_mode` service broken by recursion.** The module-level
  function that wrote `DynamicPowerMode` to the device had the same name as the
  service handler, causing it to call itself instead of making the actual HTTP
  request. Renamed to `async_write_dynamic_power_mode`.
- **Insufficient error handling in services.** The 7 service handlers
  (`set_min_intensity`, `set_max_intensity`, `set_intensity`,
  `set_dynamic_power_mode`, and their slider variants) only caught
  `ValueError`; a missing or invalid parameter could raise an uncaught
  `KeyError`/`TypeError`. These are now caught and logged with a readable error.
- **Charging spuriously marked as complete.** If `number.v2c_km_to_charge`
  ended up in an `unknown`/`unavailable` state (for example right after a
  restart), the charging-complete check cycle interpreted it as "0 km left" and
  paused and locked the charger, also firing `v2c_trydan.charging_complete`,
  repeatedly every 10 seconds.
- **`sensor.v2c_precio_luz` stayed `unavailable` after restarting Home
  Assistant.** The entity wasn't created if the source PVPC sensor hadn't
  published its state yet at setup time. It is now always created when
  configured, and the periodic refresh cycle updates it as soon as the source
  entity is ready.
- **Values lost after restarting Home Assistant.** `number.v2c_max_price`,
  `number.v2c_km_to_charge`, and the `carga_pvpc` switch did not persist their
  last value or state across a restart, always resetting to their defaults.
  They now use `RestoreEntity` to remember them.
- **Consecutive-failure threshold not respected in the coordinator.** The
  connectivity error log fired on the very first failure instead of waiting
  for 5 consecutive failures as the project convention requires; in addition,
  the inner `except Exception` of each individual `tenacity` retry attempt
  logged at `ERROR` instead of `DEBUG`, causing noise on every retry. Both
  points fixed and validated against real hardware (network cut simulated via
  firewall).
- **Duplicated and divergent firmware JSON repair logic.** `coordinator.py`
  and `select.py` each had their own logic to fix the malformed JSON returned
  by the firmware, and did not apply exactly the same workarounds. Extracted
  into a new shared module, `json_repair.py`, used by both.
- **Listener leak on every integration reload.** `ChargeKmSensor` registered
  several listeners (10s timer, pause switch state change) without cancelling
  them when the entity was removed, accumulating on every `reload`. They are
  now cancelled automatically via `async_on_remove`. A global `state_changed`
  listener with no real logic (dead code) was also removed.
- **Current hour excluded from the PVPC valid-hours calculation.** The
  `ValidHours` calculation compared with `i > current_hour` instead of
  `i >= current_hour`, leaving out the current hour even when its price met
  the configured maximum. Also fixed the use of Python's naive local time in
  favor of Home Assistant's time (`dt_util.now()`), respecting the configured
  timezone.
- **Uncaught exceptions if the PVPC sensor or `MaxPrice` were
  `unavailable`/`unknown`.** The PVPC charge-control cycle called `float()`
  directly on those states without catching parsing errors, aborting the
  whole cycle (for example during a PVPC data provider's overnight
  maintenance). The cycle is now skipped in a controlled way with a debug log.
- **Fragile options flow registration in `config_flow.py`.** Removed the
  `@config_entries.HANDLERS.register(DOMAIN)` decorator on
  `async_get_options_flow`, redundant with the registration the class already
  performs via `domain=DOMAIN`.

### Documentation

- Fixed the context about test hardware availability: the original project was
  archived because its previous maintainer was left without a test device, not
  because this fork lacks access to a real one. The current maintainer does
  have a real V2C Trydan, used to validate every change in this release.

### Not included in this release

- `DynamicPowerMode` range limited to 0-5 in the selector instead of 0-7
  (contract change, to be evaluated separately).
- Several low-severity findings (minor dead code, `services.yaml` without
  selectors, `select.py` polling on its own outside the coordinator pattern,
  among others) are tracked as backlog for a future round.

## [4.0.2] and earlier

No detailed changelog prior to this version. See the repository's commit
history for changes before the project was resumed as V2C Trydan NG.
