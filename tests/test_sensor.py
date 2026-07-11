"""Tests para custom_components/v2c_trydan/sensor.py.

Foco: logica de negocio (parseo, guards, calculo de PVPC, disparo de eventos),
no getters triviales de ``device_info``/``icon``/``name``.

Notas de diseno importantes (leer antes de tocar este fichero):

- ``PrecioLuzEntity`` define ``extract_price_attrs``, ``pause_or_resume_charging``,
  ``find_entities`` y ``update_state`` como funciones ANIDADAS dentro de
  ``async_added_to_hass`` (closures), no como metodos de instancia. Por tanto
  NO se pueden invocar directamente como ``entity.extract_price_attrs(...)``:
  no existen fuera de la ejecucion de ``async_added_to_hass``. Se testean aqui
  de forma indirecta ejecutando ``await entity.async_added_to_hass()``, que
  internamente llama a ``await update_state(None)`` una vez de forma sincrona
  antes de programar el intervalo periodico. Esto es una limitacion de
  testabilidad del codigo de produccion (funciones de negocio no extraibles
  sin cambiar sensor.py); se reporta como hallazgo y NO se modifica
  ``sensor.py`` para solucionarlo (fuera del rol de test-agent).
- En esa misma clase, la programacion periodica
  ``async_track_time_interval(self.hass, update_state, timedelta(seconds=30))``
  ya se envuelve en ``self.async_on_remove(...)`` (igual que ``ChargeKmSensor``),
  de modo que HA cancela el listener al desmontar la entidad. Aun asi, para no
  programar el timer real de 30s ni dejar timers colgando entre tests (logs de
  "lingering timer" de pytest-homeassistant-custom-component) se parchea
  ``async_track_time_interval`` a un no-op que devuelve un callback vacio en los
  tests de ``PrecioLuzEntity``; esto no afecta la logica bajo prueba, que se
  ejecuta en la llamada directa ``await update_state(None)`` dentro de
  ``async_added_to_hass``.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_mock_service,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.v2c_trydan.sensor import (
    ChargeKmSensor,
    NumericalStatus,
    PrecioLuzEntity,
    V2CtrydanSensor,
)
from custom_components.v2c_trydan.const import CONF_PRECIO_LUZ

from tests.conftest import FAKE_IP_ADDRESS


def _register_entity_state(
    hass: HomeAssistant,
    domain: str,
    unique_id: str,
    object_id: str,
    state: str,
    attributes: dict | None = None,
) -> str:
    """Da de alta una entidad en el entity_registry y le fija un estado.

    ``PrecioLuzEntity`` localiza sus entidades colaboradoras (switch de
    pausa, switch carga_pvpc, number MaxPrice) buscando por ``unique_id`` en
    el entity_registry, no por ``entity_id`` fijo, asi que hace falta
    registrarlas igual que lo haria la plataforma real antes de fijar su
    estado en ``hass.states``.
    """
    registry = er.async_get(hass)
    entry = registry.async_get_or_create(
        domain, "v2c_trydan", unique_id, suggested_object_id=object_id
    )
    hass.states.async_set(entry.entity_id, state, attributes or {})
    return entry.entity_id


# ---------------------------------------------------------------------------
# ChargeKmSensor
# ---------------------------------------------------------------------------


def test_charge_km_native_value_returns_zero_when_coordinator_data_is_none(
    mock_coordinator,
):
    """Guard: si el coordinator aun no tiene datos (arranque), 0 km sin error."""
    mock_coordinator.data = None
    sensor = ChargeKmSensor(mock_coordinator, FAKE_IP_ADDRESS, 20.8)

    assert sensor.native_value == 0


def test_charge_km_native_value_computes_km_from_charge_energy(mock_coordinator):
    """Calculo de negocio: km recorribles a partir de ChargeEnergy y consumo."""
    mock_coordinator.data["ChargeEnergy"] = 12.5
    sensor = ChargeKmSensor(mock_coordinator, FAKE_IP_ADDRESS, 20.8)

    # (12.5 / (20.8 / 100)) * 0.92 = 55.288... -> redondeado a 2 decimales.
    assert sensor.native_value == pytest.approx(55.29, abs=0.01)


async def test_check_and_pause_charging_returns_early_when_paused_switch_already_on(
    hass: HomeAssistant, mock_coordinator
):
    """Si ya esta pausado, no vuelve a comprobar km ni a llamar servicios."""
    hass.states.async_set("switch.v2c_trydan_switch_paused", "on")
    switch_calls = async_mock_service(hass, "switch", "turn_on")
    number_calls = async_mock_service(hass, "number", "set_value")

    sensor = ChargeKmSensor(mock_coordinator, FAKE_IP_ADDRESS, 20.8)
    sensor.hass = hass

    await sensor.check_and_pause_charging(None)
    await hass.async_block_till_done()

    assert switch_calls == []
    assert number_calls == []


async def test_check_and_pause_charging_returns_early_when_km_to_charge_entity_missing(
    hass: HomeAssistant, mock_coordinator
):
    """Guard: si `number.v2c_km_to_charge` no existe todavia, no hace nada."""
    switch_calls = async_mock_service(hass, "switch", "turn_on")

    sensor = ChargeKmSensor(mock_coordinator, FAKE_IP_ADDRESS, 20.8)
    sensor.hass = hass

    await sensor.check_and_pause_charging(None)
    await hass.async_block_till_done()

    assert switch_calls == []


@pytest.mark.parametrize("bad_state", ["unknown", "unavailable", "no-es-un-numero"])
async def test_check_and_pause_charging_skips_when_km_to_charge_not_parseable(
    hass: HomeAssistant, mock_coordinator, bad_state
):
    """km_to_charge en estado unknown/unavailable/no numerico no rompe el ciclo."""
    hass.states.async_set("number.v2c_km_to_charge", bad_state)
    switch_calls = async_mock_service(hass, "switch", "turn_on")

    sensor = ChargeKmSensor(mock_coordinator, FAKE_IP_ADDRESS, 20.8)
    sensor.hass = hass

    await sensor.check_and_pause_charging(None)
    await hass.async_block_till_done()

    assert switch_calls == []


async def test_check_and_pause_charging_ignores_target_of_zero_km(
    hass: HomeAssistant, mock_coordinator
):
    """km_to_charge == 0 se interpreta como "sin objetivo", nunca pausa."""
    hass.states.async_set("number.v2c_km_to_charge", "0")
    switch_calls = async_mock_service(hass, "switch", "turn_on")

    sensor = ChargeKmSensor(mock_coordinator, FAKE_IP_ADDRESS, 20.8)
    sensor.hass = hass

    await sensor.check_and_pause_charging(None)
    await hass.async_block_till_done()

    assert switch_calls == []


async def test_check_and_pause_charging_does_nothing_when_target_not_reached(
    hass: HomeAssistant, mock_coordinator
):
    """Si los km cargados aun no alcanzan el objetivo, no se pausa nada."""
    # ChargeEnergy=12.5 kWh, 20.8 kWh/100km -> ~55.29 km recorribles.
    hass.states.async_set("number.v2c_km_to_charge", "500")
    switch_calls = async_mock_service(hass, "switch", "turn_on")

    sensor = ChargeKmSensor(mock_coordinator, FAKE_IP_ADDRESS, 20.8)
    sensor.hass = hass

    await sensor.check_and_pause_charging(None)
    await hass.async_block_till_done()

    assert switch_calls == []


async def test_check_and_pause_charging_pauses_and_fires_event_when_target_reached(
    hass: HomeAssistant, mock_coordinator
):
    """Caso principal: km objetivo alcanzado -> pausa, bloquea, resetea y evento."""
    # ChargeEnergy=12.5 kWh, 20.8 kWh/100km -> ~55.29 km recorribles >= 50.
    hass.states.async_set("number.v2c_km_to_charge", "50")
    turn_on_calls = async_mock_service(hass, "switch", "turn_on")
    number_calls = async_mock_service(hass, "number", "set_value")

    events = []
    hass.bus.async_listen(
        "v2c_trydan.charging_complete", lambda event: events.append(event)
    )

    sensor = ChargeKmSensor(mock_coordinator, FAKE_IP_ADDRESS, 20.8)
    sensor.hass = hass

    await sensor.check_and_pause_charging(None)
    await hass.async_block_till_done()

    called_entities = {call.data["entity_id"] for call in turn_on_calls}
    assert called_entities == {
        "switch.v2c_trydan_switch_paused",
        "switch.v2c_trydan_switch_locked",
    }
    assert len(number_calls) == 1
    assert number_calls[0].data == {
        "entity_id": "number.v2c_km_to_charge",
        "value": 0,
    }
    assert len(events) == 1


# ---------------------------------------------------------------------------
# NumericalStatus
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("charge_state", "expected"),
    [
        ("Manguera no conectada", 0),
        ("Manguera conectada (NO CARGA)", 1),
        ("Manguera conectada (CARGANDO)", 2),
        ("algun-otro-valor-no-mapeado", "algun-otro-valor-no-mapeado"),
    ],
)
def test_numerical_status_maps_spanish_charge_state_to_number(
    mock_coordinator, charge_state, expected
):
    """Traduce los estados en espanol de ChargeState a un codigo numerico."""
    mock_coordinator.data["ChargeState"] = charge_state
    sensor = NumericalStatus(mock_coordinator, FAKE_IP_ADDRESS)

    assert sensor.native_value == expected


def test_numerical_status_defaults_to_string_zero_when_charge_state_key_missing(
    mock_coordinator,
):
    """Si el firmware no envia ChargeState, usa el valor por defecto "0" (string),
    que no coincide con ninguno de los tres estados mapeados y se devuelve tal cual
    (no se normaliza a `int`)."""
    del mock_coordinator.data["ChargeState"]
    sensor = NumericalStatus(mock_coordinator, FAKE_IP_ADDRESS)

    assert sensor.native_value == "0"


def test_numerical_status_returns_none_when_coordinator_data_is_none(mock_coordinator):
    """Guard homogeneo con ChargeKmSensor/V2CtrydanSensor: si el coordinator aun
    no tiene datos (p.ej. justo tras el arranque, antes del primer refresh),
    ``NumericalStatus.native_value`` devuelve ``None`` en vez de lanzar
    ``AttributeError`` al llamar a ``.get(...)`` sobre ``None``. Se devuelve
    ``None`` (y no ``"0"``) porque "0" no es un estado real del dispositivo.
    """
    mock_coordinator.data = None
    sensor = NumericalStatus(mock_coordinator, FAKE_IP_ADDRESS)

    assert sensor.native_value is None


# ---------------------------------------------------------------------------
# V2CtrydanSensor
# ---------------------------------------------------------------------------


def test_v2ctrydan_sensor_native_value_returns_none_when_coordinator_data_is_none(
    mock_coordinator,
):
    mock_coordinator.data = None
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "ChargeState", 20.8, "entry1")

    assert sensor.native_value is None


@pytest.mark.parametrize(
    ("raw_state", "expected"),
    [
        (0, "Manguera no conectada"),
        (1, "Manguera conectada (NO CARGA)"),
        (2, "Manguera conectada (CARGANDO)"),
        (99, 99),
    ],
)
def test_v2ctrydan_sensor_maps_charge_state_codes_to_spanish_labels(
    mock_coordinator, raw_state, expected
):
    mock_coordinator.data["ChargeState"] = raw_state
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "ChargeState", 20.8, "entry1")

    assert sensor.native_value == expected


def test_v2ctrydan_sensor_charge_state_returns_none_when_key_missing(mock_coordinator):
    del mock_coordinator.data["ChargeState"]
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "ChargeState", 20.8, "entry1")

    assert sensor.native_value is None


def test_v2ctrydan_sensor_formats_charge_time_as_hh_mm_ss(mock_coordinator):
    mock_coordinator.data["ChargeTime"] = 3725  # 1h 02m 05s
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "ChargeTime", 20.8, "entry1")

    assert sensor.native_value == "01:02:05"


def test_v2ctrydan_sensor_charge_time_defaults_to_zero_when_missing(mock_coordinator):
    del mock_coordinator.data["ChargeTime"]
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "ChargeTime", 20.8, "entry1")

    assert sensor.native_value == "00:00:00"


@pytest.mark.parametrize("data_key", ["MinIntensity", "MaxIntensity", "Intensity"])
def test_v2ctrydan_sensor_intensity_keys_pass_through_raw_value(
    mock_coordinator, data_key
):
    mock_coordinator.data[data_key] = 16
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, data_key, 20.8, "entry1")

    assert sensor.native_value == 16


@pytest.mark.parametrize(
    "data_key", ["HousePower", "ChargePower", "FVPower", "BatteryPower"]
)
def test_v2ctrydan_sensor_power_keys_are_rounded_to_int(mock_coordinator, data_key):
    mock_coordinator.data[data_key] = 1234.6
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, data_key, 20.8, "entry1")

    assert sensor.native_value == 1235
    assert isinstance(sensor.native_value, int)


@pytest.mark.parametrize(
    "data_key", ["HousePower", "ChargePower", "FVPower", "BatteryPower"]
)
def test_v2ctrydan_sensor_power_keys_return_none_when_not_numeric(
    mock_coordinator, data_key
):
    """Guard try/except: un valor no numerico (p.ej. "unknown") no rompe la entidad."""
    mock_coordinator.data[data_key] = "unknown"
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, data_key, 20.8, "entry1")

    assert sensor.native_value is None


def test_v2ctrydan_sensor_generic_key_returns_raw_value(mock_coordinator):
    mock_coordinator.data["FirmwareVersion"] = "1.6.13"
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "FirmwareVersion", 20.8, "entry1")

    assert sensor.native_value == "1.6.13"


def test_v2ctrydan_sensor_generic_key_returns_none_when_value_missing(mock_coordinator):
    del mock_coordinator.data["FirmwareVersion"]
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "FirmwareVersion", 20.8, "entry1")

    assert sensor.native_value is None


def test_v2ctrydan_sensor_available_false_when_last_update_failed(mock_coordinator):
    mock_coordinator.last_update_success = False
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "ChargePower", 20.8, "entry1")

    assert sensor.available is False


def test_v2ctrydan_sensor_available_false_when_data_is_none(mock_coordinator):
    mock_coordinator.last_update_success = True
    mock_coordinator.data = None
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "ChargePower", 20.8, "entry1")

    assert sensor.available is False


def test_v2ctrydan_sensor_available_true_when_update_ok_and_data_present(
    mock_coordinator,
):
    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "ChargePower", 20.8, "entry1")

    assert sensor.available is True


async def test_update_min_intensity_calls_service_only_when_value_changes_and_entity_exists(
    hass: HomeAssistant, mock_coordinator
):
    """Logica de dedup: solo llama al servicio si el valor cambia y la entidad existe."""
    hass.states.async_set("number.v2c_min_intensity", "6")
    calls = async_mock_service(hass, "number", "set_value")

    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "MinIntensity", 20.8, "entry1")
    sensor.hass = hass

    await sensor.update_min_intensity(8)
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0].data == {"entity_id": "number.v2c_min_intensity", "value": 8.0}

    # Mismo valor otra vez: no debe repetir la llamada (imin_old ya == 8).
    await sensor.update_min_intensity(8)
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_update_min_intensity_noop_when_number_entity_not_created_yet(
    hass: HomeAssistant, mock_coordinator
):
    """Si `number.v2c_min_intensity` aun no existe, no intenta llamar al servicio."""
    calls = async_mock_service(hass, "number", "set_value")

    sensor = V2CtrydanSensor(mock_coordinator, FAKE_IP_ADDRESS, "MinIntensity", 20.8, "entry1")
    sensor.hass = hass

    await sensor.update_min_intensity(10)
    await hass.async_block_till_done()

    assert calls == []


# ---------------------------------------------------------------------------
# PrecioLuzEntity
# ---------------------------------------------------------------------------


@pytest.fixture
def precio_luz_config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain="v2c_trydan",
        options={CONF_PRECIO_LUZ: "sensor.pvpc"},
    )


@pytest.fixture(autouse=True)
def _no_op_periodic_tracker(monkeypatch):
    """Evita programar el `async_track_time_interval` real de 30s de PrecioLuzEntity.

    El listener periodico ya se registra via `self.async_on_remove(...)` en el
    codigo de produccion (mismo patron que `ChargeKmSensor`), asi que se
    devuelve un callback de remocion vacio (callable) para que
    `async_on_remove` reciba algo valido que almacenar. Se neutraliza el timer
    real para no dejar timers colgando entre tests. La logica bajo prueba
    (`update_state`, `extract_price_attrs`, `pause_or_resume_charging`) se
    ejecuta de forma sincrona una vez dentro de `async_added_to_hass`, antes de
    programar el intervalo, asi que este parche no oculta ningun comportamiento
    probado.
    """
    monkeypatch.setattr(
        "custom_components.v2c_trydan.sensor.async_track_time_interval",
        lambda *args, **kwargs: (lambda: None),
    )


def _setup_precio_luz_collaborators(
    hass: HomeAssistant,
    *,
    paused_state: str = "off",
    carga_pvpc_state: str = "on",
    max_price_state: str = "0.20",
    pvpc_state: str = "0.10",
    pvpc_attributes: dict | None = None,
):
    _register_entity_state(
        hass, "switch", f"{FAKE_IP_ADDRESS}_Paused", "paused_test", paused_state
    )
    _register_entity_state(
        hass, "switch", "v2c_carga_pvpc", "carga_pvpc_test", carga_pvpc_state
    )
    _register_entity_state(
        hass, "number", "v2c_MaxPrice", "max_price_test", max_price_state
    )
    hass.states.async_set("sensor.pvpc", pvpc_state, pvpc_attributes or {})

    # `update_state` (closure de PrecioLuzEntity.async_added_to_hass) llama
    # incondicionalmente a `homeassistant.update_entity` para refrescar la
    # entidad PVPC de origen antes de leerla. El hass de test no trae ese
    # servicio registrado por defecto (no se carga la integracion
    # `homeassistant`), asi que se mockea aqui para poder ejercitar el resto
    # de la logica de negocio; no se toca el estado real de `sensor.pvpc`,
    # que ya se fija explicitamente arriba.
    async_mock_service(hass, "homeassistant", "update_entity")


async def test_pause_or_resume_charging_resumes_when_price_within_budget(
    hass: HomeAssistant, mock_coordinator, precio_luz_config_entry
):
    """Precio actual <= MaxPrice y carga_pvpc activado -> reanuda (turn_off pausa)."""
    _setup_precio_luz_collaborators(
        hass, carga_pvpc_state="on", max_price_state="0.20", pvpc_state="0.10"
    )
    turn_off_calls = async_mock_service(hass, "switch", "turn_off")
    turn_on_calls = async_mock_service(hass, "switch", "turn_on")

    entity = PrecioLuzEntity(mock_coordinator, None, FAKE_IP_ADDRESS, precio_luz_config_entry)
    entity.hass = hass
    entity.entity_id = "sensor.v2c_precio_luz_test"

    await entity.async_added_to_hass()
    await hass.async_block_till_done()

    assert len(turn_off_calls) == 1
    assert turn_off_calls[0].data["entity_id"].startswith("switch.paused_test")
    assert turn_on_calls == []


async def test_pause_or_resume_charging_pauses_when_price_exceeds_budget(
    hass: HomeAssistant, mock_coordinator, precio_luz_config_entry
):
    """Precio actual > MaxPrice y carga_pvpc activado -> pausa (turn_on pausa)."""
    _setup_precio_luz_collaborators(
        hass, carga_pvpc_state="on", max_price_state="0.20", pvpc_state="0.30"
    )
    turn_off_calls = async_mock_service(hass, "switch", "turn_off")
    turn_on_calls = async_mock_service(hass, "switch", "turn_on")

    entity = PrecioLuzEntity(mock_coordinator, None, FAKE_IP_ADDRESS, precio_luz_config_entry)
    entity.hass = hass
    entity.entity_id = "sensor.v2c_precio_luz_test"

    await entity.async_added_to_hass()
    await hass.async_block_till_done()

    assert len(turn_on_calls) == 1
    assert turn_on_calls[0].data["entity_id"].startswith("switch.paused_test")
    assert turn_off_calls == []


async def test_pause_or_resume_charging_noop_when_carga_pvpc_switch_is_off(
    hass: HomeAssistant, mock_coordinator, precio_luz_config_entry
):
    """Si el switch `carga_pvpc` esta apagado, no se toca el switch de pausa."""
    _setup_precio_luz_collaborators(
        hass, carga_pvpc_state="off", max_price_state="0.20", pvpc_state="0.30"
    )
    turn_off_calls = async_mock_service(hass, "switch", "turn_off")
    turn_on_calls = async_mock_service(hass, "switch", "turn_on")

    entity = PrecioLuzEntity(mock_coordinator, None, FAKE_IP_ADDRESS, precio_luz_config_entry)
    entity.hass = hass
    entity.entity_id = "sensor.v2c_precio_luz_test"

    await entity.async_added_to_hass()
    await hass.async_block_till_done()

    assert turn_off_calls == []
    assert turn_on_calls == []


async def test_pause_or_resume_charging_skips_when_current_price_unavailable(
    hass: HomeAssistant, mock_coordinator, precio_luz_config_entry
):
    """Precio PVPC en estado `unavailable`: la entidad degrada con gracia.

    ``pause_or_resume_charging`` en si misma no rompe (el
    ``try/except (ValueError, TypeError)`` alrededor de ``float(current_state)``
    la hace volver sin tocar el switch de pausa).

    Tras el fix de ``PrecioLuzEntity`` (property ``available``), el ciclo
    completo (``update_state`` -> ``self.async_write_ha_state()``) ya NO revienta
    con ``ValueError``: la entidad hereda ``state_class="measurement"`` y una
    unidad (``€/kWh``) del sensor PVPC de origen, pero cuando la fuente esta en
    ``unavailable``/``unknown`` (valor no numerico) ``available`` devuelve
    ``False`` y Home Assistant escribe el estado como no disponible sin exigir
    un valor numerico. Antes esto propagaba una excepcion no controlada cada
    vez que el sensor PVPC pasaba a ``unavailable``/``unknown`` mientras
    `v2c_carga_pvpc` seguia activo; ahora degrada a "no disponible".
    """
    _setup_precio_luz_collaborators(
        hass, carga_pvpc_state="on", max_price_state="0.20", pvpc_state="unavailable"
    )
    turn_off_calls = async_mock_service(hass, "switch", "turn_off")
    turn_on_calls = async_mock_service(hass, "switch", "turn_on")

    entity = PrecioLuzEntity(mock_coordinator, None, FAKE_IP_ADDRESS, precio_luz_config_entry)
    entity.hass = hass
    entity.entity_id = "sensor.v2c_precio_luz_test"

    # No debe propagarse ninguna excepcion al pasar la fuente a unavailable.
    await entity.async_added_to_hass()
    await hass.async_block_till_done()

    # La entidad queda no disponible (fuente PVPC no numerica), en vez de
    # reventar en async_write_ha_state.
    assert entity.available is False

    # pause_or_resume_charging por si sola no actua sobre el switch de pausa
    # (precio no parseable).
    assert turn_off_calls == []
    assert turn_on_calls == []


async def test_update_state_skips_full_cycle_when_max_price_unavailable(
    hass: HomeAssistant, mock_coordinator, precio_luz_config_entry
):
    """MaxPrice en unknown/unavailable descarta el ciclo completo (sin tocar nada)."""
    _setup_precio_luz_collaborators(
        hass, carga_pvpc_state="on", max_price_state="unknown", pvpc_state="0.10"
    )
    turn_off_calls = async_mock_service(hass, "switch", "turn_off")
    turn_on_calls = async_mock_service(hass, "switch", "turn_on")

    entity = PrecioLuzEntity(mock_coordinator, None, FAKE_IP_ADDRESS, precio_luz_config_entry)
    entity.hass = hass
    entity.entity_id = "sensor.v2c_precio_luz_test"

    await entity.async_added_to_hass()
    await hass.async_block_till_done()

    assert turn_off_calls == []
    assert turn_on_calls == []
    # El ciclo se descarto antes de reasignar la fuente PVPC: sigue en el
    # estado inicial (None -> native_value None) y `valid_hours` conserva la
    # lista vacia por defecto fijada en __init__ (no se ha reasignado a la
    # lista que devuelve extract_price_attrs).
    assert entity.native_value is None
    assert entity.valid_hours == []


async def test_periodic_listener_registered_via_async_on_remove(
    hass: HomeAssistant, mock_coordinator, precio_luz_config_entry, monkeypatch
):
    """P2-A: el `async_track_time_interval` de 30s se registra via
    `self.async_on_remove(...)`, de modo que HA cancela el listener al
    desmontar la entidad y no se acumulan timers duplicados en cada reload.
    """
    _setup_precio_luz_collaborators(hass, carga_pvpc_state="off")

    def sentinel_cancel() -> None:
        return None

    monkeypatch.setattr(
        "custom_components.v2c_trydan.sensor.async_track_time_interval",
        lambda *args, **kwargs: sentinel_cancel,
    )

    entity = PrecioLuzEntity(
        mock_coordinator, None, FAKE_IP_ADDRESS, precio_luz_config_entry
    )
    entity.hass = hass
    entity.entity_id = "sensor.v2c_precio_luz_test"

    registered = []
    original_on_remove = entity.async_on_remove

    def _spy(func):
        registered.append(func)
        return original_on_remove(func)

    monkeypatch.setattr(entity, "async_on_remove", _spy)

    await entity.async_added_to_hass()
    await hass.async_block_till_done()

    # El callback de cancelacion del timer periodico quedo registrado para
    # limpieza automatica al desmontar la entidad.
    assert sentinel_cancel in registered


async def test_extract_price_attrs_includes_current_hour_and_excludes_past_hour(
    hass: HomeAssistant, mock_coordinator, precio_luz_config_entry, monkeypatch
):
    """`extract_price_attrs`: incluye la hora actual si es valida, excluye horas pasadas
    de hoy, e incluye siempre las horas validas del dia siguiente."""
    fixed_now = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        "custom_components.v2c_trydan.sensor.dt_util.now", lambda: fixed_now
    )

    pvpc_attributes = {
        "price_10h": 0.10,  # hora actual, precio valido -> incluida
        "price_09h": 0.05,  # precio valido pero hora ya pasada -> excluida
        "price_11h": 0.50,  # precio no valido -> excluida
        "price_next_day_05h": 0.05,  # dia siguiente, precio valido -> incluida
        "price_next_day_06h": 0.50,  # dia siguiente, precio no valido -> excluida
    }
    _setup_precio_luz_collaborators(
        hass,
        carga_pvpc_state="off",  # evita ruido de pause_or_resume en este test
        max_price_state="0.20",
        pvpc_state="0.10",
        pvpc_attributes=pvpc_attributes,
    )

    entity = PrecioLuzEntity(mock_coordinator, None, FAKE_IP_ADDRESS, precio_luz_config_entry)
    entity.hass = hass
    entity.entity_id = "sensor.v2c_precio_luz_test"

    await entity.async_added_to_hass()
    await hass.async_block_till_done()

    assert entity.valid_hours == [10]
    assert entity.valid_hours_next_day == [5]
    assert entity.total_hours == 2
    assert entity.extra_state_attributes["ValidHours"] == [10]
    assert entity.extra_state_attributes["ValidHoursNextDay"] == [5]
    assert entity.extra_state_attributes["TotalHours"] == 2


def test_precio_luz_native_value_returns_none_when_no_source_entity(mock_coordinator):
    entity = PrecioLuzEntity(mock_coordinator, None, FAKE_IP_ADDRESS, MockConfigEntry())

    assert entity.native_value is None
    assert entity.extra_state_attributes is None
