"""Tests para custom_components/v2c_trydan/number.py.

Cubre las 5 entidades definidas en el modulo:
- ``KmToChargeNumber`` y ``MaxPrice`` (``RestoreEntity``): restauracion de
  estado tras un reinicio de Home Assistant, caso de valor previo no
  parseable y guardado de un nuevo valor.
- ``MaxIntensityNumber``, ``MinIntensityNumber`` e ``IntensityNumber``
  (``CoordinatorEntity``): validacion de rango 6-32 A, guard cuando
  ``coordinator.data`` es ``None`` y escritura HTTP del nuevo valor
  (mockeada con ``mock_v2c_http``/``aioresponses``).

Patron de restauracion: se usa el helper oficial ``mock_restore_cache`` de
``pytest_homeassistant_custom_component.common`` para poblar la cache de
``RestoreStateData`` y despues se asignan manualmente ``entity.hass`` y
``entity.entity_id`` (en produccion los asigna la plataforma de entidades al
anadir la entidad; aqui se simula el minimo necesario para que
``RestoreEntity.async_get_last_state`` pueda resolver el estado guardado,
sin levantar el ciclo completo de ``async_setup_entry``).

``async_write_ha_state`` se mockea en los tests de ``KmToChargeNumber`` y
``MaxPrice`` porque estas entidades nunca se anaden a una plataforma real de
entidades en estos tests (no hace falta para validar la logica de
validacion de rango / guardado del atributo interno ``_state``, que es lo
que pide la tarea).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.v2c_trydan import DOMAIN
from custom_components.v2c_trydan.number import (
    IntensityNumber,
    KmToChargeNumber,
    MaxIntensityNumber,
    MaxPrice,
    MinIntensityNumber,
    async_setup_entry,
)

from tests.conftest import FAKE_IP_ADDRESS


# ---------------------------------------------------------------------------
# KmToChargeNumber (RestoreEntity)
# ---------------------------------------------------------------------------

KM_ENTITY_ID = "number.v2c_km_to_charge"


async def test_km_to_charge_default_state_before_restore(hass: HomeAssistant):
    """Sin estado previo restaurado, el valor por defecto es 0."""
    entity = KmToChargeNumber(hass, FAKE_IP_ADDRESS)

    assert entity.native_value == 0


async def test_km_to_charge_restores_previous_valid_state(hass: HomeAssistant):
    """Un estado previo numerico valido se restaura como float."""
    mock_restore_cache(hass, (State(KM_ENTITY_ID, "45.5"),))
    entity = KmToChargeNumber(hass, FAKE_IP_ADDRESS)
    entity.hass = hass
    entity.entity_id = KM_ENTITY_ID

    await entity.async_added_to_hass()

    assert entity.native_value == 45.5


async def test_km_to_charge_restore_invalid_value_falls_back_to_default(
    hass: HomeAssistant,
):
    """Un estado previo no parseable como float no rompe la entidad y se
    mantiene el default (0), tal y como hace el codigo real (try/except
    ValueError/TypeError con log de warning)."""
    mock_restore_cache(hass, (State(KM_ENTITY_ID, "no-es-un-numero"),))
    entity = KmToChargeNumber(hass, FAKE_IP_ADDRESS)
    entity.hass = hass
    entity.entity_id = KM_ENTITY_ID

    await entity.async_added_to_hass()

    assert entity.native_value == 0


@pytest.mark.parametrize("previous_state", ["unknown", "unavailable"])
async def test_km_to_charge_restore_ignores_unknown_and_unavailable(
    hass: HomeAssistant, previous_state: str
):
    """Los estados especiales ``unknown``/``unavailable`` de HA no se
    intentan parsear y se mantiene el default."""
    mock_restore_cache(hass, (State(KM_ENTITY_ID, previous_state),))
    entity = KmToChargeNumber(hass, FAKE_IP_ADDRESS)
    entity.hass = hass
    entity.entity_id = KM_ENTITY_ID

    await entity.async_added_to_hass()

    assert entity.native_value == 0


async def test_km_to_charge_set_native_value_within_range_updates_state(
    hass: HomeAssistant,
):
    """Un valor dentro de [0, 1000] se guarda y se escribe el estado."""
    entity = KmToChargeNumber(hass, FAKE_IP_ADDRESS)
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_native_value(120)

    assert entity.native_value == 120
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.parametrize("out_of_range_value", [-1, 1000.5, 5000])
async def test_km_to_charge_set_native_value_out_of_range_is_rejected(
    hass: HomeAssistant, out_of_range_value: float
):
    """Un valor fuera de [0, 1000] no se guarda (guard clause + log error)."""
    entity = KmToChargeNumber(hass, FAKE_IP_ADDRESS)
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_native_value(out_of_range_value)

    assert entity.native_value == 0
    entity.async_write_ha_state.assert_not_called()


def test_km_to_charge_bounds_and_unit():
    """Limites y unidad expuestos por la entidad (metadatos)."""
    entity = KmToChargeNumber(None, FAKE_IP_ADDRESS)

    assert entity.native_min_value == 0
    assert entity.native_max_value == 1000
    assert entity.native_unit_of_measurement == "km"
    assert entity.unique_id == "v2c_km_to_charge"


# ---------------------------------------------------------------------------
# MaxPrice (RestoreEntity)
# ---------------------------------------------------------------------------

MAX_PRICE_ENTITY_ID = "number.v2c_maxprice"


async def test_max_price_default_state_before_restore(hass: HomeAssistant):
    entity = MaxPrice(hass, FAKE_IP_ADDRESS)

    assert entity.native_value == 0


async def test_max_price_restores_previous_valid_state(hass: HomeAssistant):
    mock_restore_cache(hass, (State(MAX_PRICE_ENTITY_ID, "0.25"),))
    entity = MaxPrice(hass, FAKE_IP_ADDRESS)
    entity.hass = hass
    entity.entity_id = MAX_PRICE_ENTITY_ID

    await entity.async_added_to_hass()

    assert entity.native_value == 0.25


async def test_max_price_restore_invalid_value_falls_back_to_default(
    hass: HomeAssistant,
):
    mock_restore_cache(hass, (State(MAX_PRICE_ENTITY_ID, "carisimo"),))
    entity = MaxPrice(hass, FAKE_IP_ADDRESS)
    entity.hass = hass
    entity.entity_id = MAX_PRICE_ENTITY_ID

    await entity.async_added_to_hass()

    assert entity.native_value == 0


async def test_max_price_set_native_value_within_range_updates_state(
    hass: HomeAssistant,
):
    entity = MaxPrice(hass, FAKE_IP_ADDRESS)
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_native_value(0.123)

    assert entity.native_value == 0.123
    entity.async_write_ha_state.assert_called_once()


@pytest.mark.parametrize("out_of_range_value", [-0.01, 1.01, 5])
async def test_max_price_set_native_value_out_of_range_is_rejected(
    hass: HomeAssistant, out_of_range_value: float
):
    entity = MaxPrice(hass, FAKE_IP_ADDRESS)
    entity.async_write_ha_state = MagicMock()

    await entity.async_set_native_value(out_of_range_value)

    assert entity.native_value == 0
    entity.async_write_ha_state.assert_not_called()


def test_max_price_bounds_and_step():
    entity = MaxPrice(None, FAKE_IP_ADDRESS)

    assert entity.native_min_value == 0.0
    assert entity.native_max_value == 1.0
    assert entity.native_step == 0.001
    assert entity.unique_id == "v2c_MaxPrice"


# ---------------------------------------------------------------------------
# MaxIntensityNumber / MinIntensityNumber / IntensityNumber (CoordinatorEntity)
# ---------------------------------------------------------------------------


def test_max_intensity_native_value_and_bounds_from_coordinator_data(
    mock_coordinator,
):
    entity = MaxIntensityNumber(mock_coordinator)

    assert entity.native_value == 32
    assert entity.native_max_value == 32
    assert entity.native_min_value == 6
    assert entity.unique_id == "v2c_max_intensity"
    assert entity.native_unit_of_measurement == "A"


def test_max_intensity_guard_when_coordinator_data_is_none(mock_coordinator):
    """Si ``coordinator.data`` es ``None`` (aun sin primer refresh o tras un
    fallo de polling), las propiedades caen a los defaults documentados
    (32/6) en vez de lanzar excepcion."""
    mock_coordinator.data = None
    entity = MaxIntensityNumber(mock_coordinator)

    assert entity.native_value == 32
    assert entity.native_max_value == 32
    assert entity.native_min_value == 6


async def test_max_intensity_set_native_value_within_range_writes_http_and_refreshes(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=20", status=200, body="OK"
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MaxIntensityNumber(mock_coordinator)
    entity.hass = hass

    await entity.async_set_native_value(20)

    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_max_intensity_set_native_value_out_of_range_does_not_write_http(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    """Fuera de [6, 32] no debe llamarse a la API (no se registra mock de
    respuesta a proposito: si se intentase, aioresponses fallaria)."""
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MaxIntensityNumber(mock_coordinator)
    entity.hass = hass

    await entity.async_set_native_value(33)

    mock_coordinator.async_request_refresh.assert_not_awaited()


async def test_max_intensity_set_native_value_device_returns_error(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    """Si el firmware responde con el literal ``ERROR``, se propaga un
    ``ValueError`` (comportamiento actual documentado en el codigo)."""
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=20", status=200, body="ERROR"
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MaxIntensityNumber(mock_coordinator)
    entity.hass = hass

    with pytest.raises(ValueError):
        await entity.async_set_native_value(20)

    mock_coordinator.async_request_refresh.assert_not_awaited()


async def test_max_intensity_set_native_value_client_error_propagates(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=20",
        exception=aiohttp.ClientConnectionError("boom"),
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MaxIntensityNumber(mock_coordinator)
    entity.hass = hass

    with pytest.raises(aiohttp.ClientError):
        await entity.async_set_native_value(20)


async def test_max_intensity_set_native_value_without_ip_address_logs_and_returns(
    hass: HomeAssistant, mock_coordinator
):
    """Sin IP configurada, la escritura no se realiza (guard clause) y no
    lanza excepcion."""
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MaxIntensityNumber(mock_coordinator)
    entity.hass = hass
    entity._ip_address = None

    await entity.async_set_native_value(20)

    mock_coordinator.async_request_refresh.assert_awaited_once()


def test_min_intensity_native_value_and_bounds_from_coordinator_data(
    mock_coordinator,
):
    entity = MinIntensityNumber(mock_coordinator)

    assert entity.native_value == 6
    assert entity.native_max_value == 32
    assert entity.native_min_value == 6
    assert entity.unique_id == "v2c_min_intensity"


def test_min_intensity_guard_when_coordinator_data_is_none(mock_coordinator):
    mock_coordinator.data = None
    entity = MinIntensityNumber(mock_coordinator)

    assert entity.native_value == 6
    assert entity.native_max_value == 32
    assert entity.native_min_value == 6


async def test_min_intensity_set_native_value_within_range_writes_http_and_refreshes(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10", status=200, body="OK"
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MinIntensityNumber(mock_coordinator)
    entity.hass = hass

    await entity.async_set_native_value(10)

    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_min_intensity_set_native_value_below_range_does_not_write_http(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MinIntensityNumber(mock_coordinator)
    entity.hass = hass

    await entity.async_set_native_value(5)

    mock_coordinator.async_request_refresh.assert_not_awaited()


def test_intensity_native_value_and_bounds_from_coordinator_data(mock_coordinator):
    entity = IntensityNumber(mock_coordinator)

    assert entity.native_value == 16
    assert entity.native_max_value == 32
    assert entity.native_min_value == 6
    assert entity.unique_id == "v2c_intensity"


def test_intensity_guard_when_coordinator_data_is_none(mock_coordinator):
    mock_coordinator.data = None
    entity = IntensityNumber(mock_coordinator)

    assert entity.native_value == 6
    assert entity.native_max_value == 32
    assert entity.native_min_value == 6


async def test_intensity_set_native_value_within_range_writes_http_and_refreshes(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/Intensity=25", status=200, body="OK"
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = IntensityNumber(mock_coordinator)
    entity.hass = hass

    await entity.async_set_native_value(25)

    mock_coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.parametrize("out_of_range_value", [5, 33])
async def test_intensity_set_native_value_out_of_range_does_not_write_http(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http, out_of_range_value: int
):
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = IntensityNumber(mock_coordinator)
    entity.hass = hass

    await entity.async_set_native_value(out_of_range_value)

    mock_coordinator.async_request_refresh.assert_not_awaited()


async def test_intensity_set_native_value_without_ip_address_logs_and_returns(
    hass: HomeAssistant, mock_coordinator
):
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = IntensityNumber(mock_coordinator)
    entity.hass = hass
    entity._ip_address = None

    await entity.async_set_native_value(20)

    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_intensity_set_native_value_client_error_propagates(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/Intensity=25",
        exception=aiohttp.ClientConnectionError("boom"),
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = IntensityNumber(mock_coordinator)
    entity.hass = hass

    with pytest.raises(aiohttp.ClientError):
        await entity.async_set_native_value(25)


async def test_max_intensity_set_native_value_timeout_propagates(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MaxIntensity=20",
        exception=asyncio.TimeoutError("timed out"),
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MaxIntensityNumber(mock_coordinator)
    entity.hass = hass

    with pytest.raises(asyncio.TimeoutError):
        await entity.async_set_native_value(20)


async def test_min_intensity_set_native_value_device_returns_error(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10", status=200, body="ERROR"
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MinIntensityNumber(mock_coordinator)
    entity.hass = hass

    with pytest.raises(ValueError):
        await entity.async_set_native_value(10)

    mock_coordinator.async_request_refresh.assert_not_awaited()


async def test_min_intensity_set_native_value_client_error_propagates(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10",
        exception=aiohttp.ClientConnectionError("boom"),
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MinIntensityNumber(mock_coordinator)
    entity.hass = hass

    with pytest.raises(aiohttp.ClientError):
        await entity.async_set_native_value(10)


async def test_min_intensity_set_native_value_timeout_propagates(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_v2c_http.get(
        f"http://{FAKE_IP_ADDRESS}/write/MinIntensity=10",
        exception=asyncio.TimeoutError("timed out"),
    )
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MinIntensityNumber(mock_coordinator)
    entity.hass = hass

    with pytest.raises(asyncio.TimeoutError):
        await entity.async_set_native_value(10)


async def test_min_intensity_set_native_value_without_ip_address_logs_and_returns(
    hass: HomeAssistant, mock_coordinator
):
    mock_coordinator.async_request_refresh = AsyncMock()
    entity = MinIntensityNumber(mock_coordinator)
    entity.hass = hass
    entity._ip_address = None

    await entity.async_set_native_value(10)

    mock_coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# Metadatos de entidad (icon / device_info / state_class): propiedades
# triviales pero forman parte del contrato de UI de Home Assistant.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "entity_factory",
    [
        lambda hass, coordinator: MaxIntensityNumber(coordinator),
        lambda hass, coordinator: MinIntensityNumber(coordinator),
        lambda hass, coordinator: IntensityNumber(coordinator),
    ],
)
def test_coordinator_backed_entities_expose_expected_metadata(
    mock_coordinator, entity_factory
):
    entity = entity_factory(None, mock_coordinator)

    assert entity.icon == "mdi:car"
    assert entity.native_unit_of_measurement == "A"
    device_info = entity.device_info
    assert device_info["name"] == f"V2C Trydan ({FAKE_IP_ADDRESS})"
    from homeassistant.components.sensor import SensorStateClass

    assert entity.state_class == SensorStateClass.MEASUREMENT


def test_km_to_charge_metadata(hass: HomeAssistant):
    entity = KmToChargeNumber(hass, FAKE_IP_ADDRESS)

    assert entity.icon == "mdi:car"
    from homeassistant.components.sensor import SensorStateClass

    assert entity.state_class == SensorStateClass.MEASUREMENT
    device_info = entity.device_info
    assert device_info["name"] == f"V2C Trydan ({FAKE_IP_ADDRESS})"


def test_max_price_metadata(hass: HomeAssistant):
    entity = MaxPrice(hass, FAKE_IP_ADDRESS)

    assert entity.icon == "mdi:currency-eur"
    from homeassistant.components.sensor import SensorStateClass

    assert entity.state_class == SensorStateClass.MEASUREMENT
    device_info = entity.device_info
    assert device_info["name"] == f"V2C Trydan ({FAKE_IP_ADDRESS})"


# ---------------------------------------------------------------------------
# async_setup_entry
# ---------------------------------------------------------------------------


async def test_async_setup_entry_creates_all_five_number_entities(
    hass: HomeAssistant, mock_config_entry, mock_coordinator
):
    """``async_setup_entry`` registra las 5 entidades ``number`` esperadas."""
    mock_config_entry.add_to_hass(hass)
    hass.data.setdefault(DOMAIN, {})[mock_config_entry.entry_id] = mock_coordinator

    added_entities = []

    def _capture(new_entities):
        added_entities.extend(new_entities)

    await async_setup_entry(hass, mock_config_entry, _capture)

    assert len(added_entities) == 5
    assert isinstance(added_entities[0], MaxIntensityNumber)
    assert isinstance(added_entities[1], MinIntensityNumber)
    assert isinstance(added_entities[2], KmToChargeNumber)
    assert isinstance(added_entities[3], IntensityNumber)
    assert isinstance(added_entities[4], MaxPrice)
