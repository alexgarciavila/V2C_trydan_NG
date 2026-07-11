"""Tests para custom_components/v2c_trydan/switch.py.

Cubre:
- ``V2CtrydanSwitch``: lectura de estado desde el coordinator y
  turn_on/turn_off contra el endpoint HTTP de escritura del firmware
  (mockeado con ``mock_v2c_http``), incluyendo el camino de error
  (``aiohttp.ClientError``).
- ``V2CCargaPVPCSwitch``: no depende del coordinator (logica propia de
  disponibilidad basada en el estado del sensor PVPC configurado por el
  usuario) y usa ``RestoreEntity`` para recuperar el ultimo estado on/off
  tras un reinicio de Home Assistant.

No se modifica codigo productivo. Los tests documentan el comportamiento
ACTUAL de ``switch.py``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import aiohttp
import pytest

from homeassistant.core import HomeAssistant, State

from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.v2c_trydan.const import DOMAIN
from custom_components.v2c_trydan.switch import V2CCargaPVPCSwitch, V2CtrydanSwitch

from tests.conftest import FAKE_IP_ADDRESS


# --- V2CtrydanSwitch --------------------------------------------------------


def test_unique_id_and_device_info(mock_coordinator):
    switch = V2CtrydanSwitch(mock_coordinator, FAKE_IP_ADDRESS, "Dynamic")

    assert switch.unique_id == f"{FAKE_IP_ADDRESS}_Dynamic"
    assert switch._attr_translation_key == "dynamic"

    info = switch.device_info
    assert info["identifiers"] == {(DOMAIN, FAKE_IP_ADDRESS)}
    assert info["configuration_url"] == f"http://{FAKE_IP_ADDRESS}"


def test_translation_key_is_none_for_unmapped_data_key(mock_coordinator):
    """Si data_key no esta en SWITCH_TRANSLATION_KEY_MAP, translation_key es None."""
    switch = V2CtrydanSwitch(mock_coordinator, FAKE_IP_ADDRESS, "SomethingElse")

    assert switch._attr_translation_key is None


def test_is_on_reads_truthy_and_falsy_values_from_coordinator_data(mock_coordinator):
    switch = V2CtrydanSwitch(mock_coordinator, FAKE_IP_ADDRESS, "Paused")

    mock_coordinator.data["Paused"] = 1
    assert switch.is_on is True

    mock_coordinator.data["Paused"] = 0
    assert switch.is_on is False


def test_is_on_false_when_key_missing_from_coordinator_data(mock_coordinator):
    switch = V2CtrydanSwitch(mock_coordinator, FAKE_IP_ADDRESS, "Locked")
    mock_coordinator.data.pop("Locked", None)

    assert switch.is_on is False


def test_is_on_false_when_coordinator_data_is_none(mock_coordinator):
    mock_coordinator.data = None
    switch = V2CtrydanSwitch(mock_coordinator, FAKE_IP_ADDRESS, "Locked")

    assert switch.is_on is False


async def test_async_turn_on_writes_1_and_refreshes_coordinator(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_coordinator.async_request_refresh = AsyncMock()
    switch = V2CtrydanSwitch(mock_coordinator, FAKE_IP_ADDRESS, "Paused")
    switch.hass = hass
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/Paused=1", status=200)

    await switch.async_turn_on()

    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_async_turn_off_writes_0_and_refreshes_coordinator(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_coordinator.async_request_refresh = AsyncMock()
    switch = V2CtrydanSwitch(mock_coordinator, FAKE_IP_ADDRESS, "Dynamic")
    switch.hass = hass
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/Dynamic=0", status=200)

    await switch.async_turn_off()

    mock_coordinator.async_request_refresh.assert_awaited_once()


async def test_async_turn_on_raises_client_error_and_does_not_refresh(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_coordinator.async_request_refresh = AsyncMock()
    switch = V2CtrydanSwitch(mock_coordinator, FAKE_IP_ADDRESS, "Locked")
    switch.hass = hass
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/Locked=1", status=500)

    with pytest.raises(aiohttp.ClientError):
        await switch.async_turn_on()

    mock_coordinator.async_request_refresh.assert_not_awaited()


async def test_async_turn_off_raises_client_error_and_does_not_refresh(
    hass: HomeAssistant, mock_coordinator, mock_v2c_http
):
    mock_coordinator.async_request_refresh = AsyncMock()
    switch = V2CtrydanSwitch(mock_coordinator, FAKE_IP_ADDRESS, "Paused")
    switch.hass = hass
    mock_v2c_http.get(f"http://{FAKE_IP_ADDRESS}/write/Paused=0", status=500)

    with pytest.raises(aiohttp.ClientError):
        await switch.async_turn_off()

    mock_coordinator.async_request_refresh.assert_not_awaited()


# --- V2CCargaPVPCSwitch ------------------------------------------------------


def test_init_with_entity_sets_entity_id_and_metadata():
    state = State("sensor.pvpc", "0.1234")
    switch = V2CCargaPVPCSwitch(state, FAKE_IP_ADDRESS)

    assert switch._precio_luz_entity_id == "sensor.pvpc"
    assert switch.unique_id == "v2c_carga_pvpc"
    assert switch.name == "V2C trydan Switch v2c_carga_pvpc"
    assert switch.is_on is False

    info = switch.device_info
    assert info["identifiers"] == {(DOMAIN, FAKE_IP_ADDRESS)}


def test_init_without_entity_defaults_entity_id_to_sensor_pvpc():
    switch = V2CCargaPVPCSwitch(None, FAKE_IP_ADDRESS)

    assert switch._precio_luz_entity_id == "sensor.pvpc"
    assert switch.precio_luz_entity is None


async def test_available_true_when_entity_provided_at_init(hass: HomeAssistant):
    state = State("sensor.pvpc", "0.15")
    switch = V2CCargaPVPCSwitch(state, FAKE_IP_ADDRESS)
    switch.hass = hass

    assert switch.available is True


async def test_available_false_when_entity_never_configured(hass: HomeAssistant):
    switch = V2CCargaPVPCSwitch(None, FAKE_IP_ADDRESS)
    switch.hass = hass

    assert switch.available is False


async def test_available_becomes_true_once_pvpc_entity_appears_in_states(
    hass: HomeAssistant,
):
    switch = V2CCargaPVPCSwitch(None, FAKE_IP_ADDRESS)
    switch.hass = hass
    hass.states.async_set("sensor.pvpc", "0.20")

    assert switch.available is True
    assert switch.precio_luz_entity is not None


async def test_async_turn_on_turns_on_when_entity_provided(hass: HomeAssistant):
    state = State("sensor.pvpc", "0.15")
    switch = V2CCargaPVPCSwitch(state, FAKE_IP_ADDRESS)
    switch.hass = hass

    await switch.async_turn_on()

    assert switch.is_on is True


async def test_async_turn_on_finds_entity_dynamically_when_it_appears_later(
    hass: HomeAssistant,
):
    switch = V2CCargaPVPCSwitch(None, FAKE_IP_ADDRESS)
    switch.hass = hass
    hass.states.async_set("sensor.pvpc", "0.20")

    await switch.async_turn_on()

    assert switch.is_on is True


async def test_async_turn_on_stays_off_when_entity_never_appears(
    hass: HomeAssistant,
):
    switch = V2CCargaPVPCSwitch(None, FAKE_IP_ADDRESS)
    switch.hass = hass

    await switch.async_turn_on()

    assert switch.is_on is False


async def test_async_turn_off_always_sets_is_on_false(hass: HomeAssistant):
    state = State("sensor.pvpc", "0.15")
    switch = V2CCargaPVPCSwitch(state, FAKE_IP_ADDRESS)
    switch._is_on = True
    switch.hass = hass

    await switch.async_turn_off()

    assert switch.is_on is False


async def test_async_added_to_hass_restores_last_on_state(hass: HomeAssistant):
    state = State("sensor.pvpc", "0.15")
    mock_restore_cache(hass, [State("switch.v2c_carga_pvpc", "on")])
    switch = V2CCargaPVPCSwitch(state, FAKE_IP_ADDRESS)
    switch.entity_id = "switch.v2c_carga_pvpc"
    switch.hass = hass

    await switch.async_added_to_hass()

    assert switch.is_on is True


async def test_async_added_to_hass_restores_last_off_state(hass: HomeAssistant):
    state = State("sensor.pvpc", "0.15")
    mock_restore_cache(hass, [State("switch.v2c_carga_pvpc", "off")])
    switch = V2CCargaPVPCSwitch(state, FAKE_IP_ADDRESS)
    switch._is_on = True
    switch.entity_id = "switch.v2c_carga_pvpc"
    switch.hass = hass

    await switch.async_added_to_hass()

    assert switch.is_on is False


async def test_async_added_to_hass_without_cache_keeps_default_off(
    hass: HomeAssistant,
):
    switch = V2CCargaPVPCSwitch(None, FAKE_IP_ADDRESS)
    switch.entity_id = "switch.v2c_carga_pvpc"
    switch.hass = hass

    await switch.async_added_to_hass()

    assert switch.is_on is False


async def test_async_added_to_hass_discovers_pvpc_entity_when_available(
    hass: HomeAssistant,
):
    """Si al arrancar el sensor PVPC ya existe en hass.states, se engancha."""
    hass.states.async_set("sensor.pvpc", "0.20")
    switch = V2CCargaPVPCSwitch(None, FAKE_IP_ADDRESS)
    switch.entity_id = "switch.v2c_carga_pvpc"
    switch.hass = hass

    await switch.async_added_to_hass()

    assert switch.precio_luz_entity is not None
    assert switch.precio_luz_entity.entity_id == "sensor.pvpc"
